"""신호 종목 forward 성과 누적 — reports/signal_tracking.json (2026-10-20 dev: signal-tracking).

무엇을 추적하나 (화면에 '신호'로 노출되는 종목 단위 목록 — SOURCES 표 참고):
  accum      KR 매집 신호 상위 목록 (reports/accum.json top[tag], MARKET 탭 매집 패널) — 태그별(분배 distrib 는 약세 신호)
  us_accum   US 매집 흔적 (reports/us_accum.json hits) — 화면 getter 만 있고 탭 패널 없음(표기)
  sim_kr/us  새로 켜진 추세 신호 (reports/sim_signals_<KR|US>.json rows, 운용회의 '새로 켜진 추세 신호')
  disc_kr/us 추세 탐색 레이어 (reports/trend_discovery_<KR|US>.json — 근접 nm·탐색 통과 x·새 전략 new·국장 추격 chase(약세 방향))
추적하지 않는 것(중복·성격 다름): 운용회의 ideas_top TOP3 = screener/idea_tracking.py(진입 규칙 모의추적) ·
  entry_signals(지수 급락 타점, 종목 아님) · alerts(보유 규정 알림, 종목 신호 아님).

정의 (공통 유틸 screener/fwd_perf.py — idea_tracking 과 같은 KR 가격 원천):
  신호일 = 원천 파일의 기준일(asof / hit.date / entry_date). 진입 = 신호일 종가, h = 5·20·60 거래일 뒤 종가.
  초과 = 종목 − 같은 창 시장 중앙값(KR kr_prices 전종목, US detail/US 전종목). 적중 = 초과 > 0 (약세 신호는 < 0).
  같은 (원천·태그·종목)이 20일 안에 다시 뜨면 '계속'으로 보고 새 신호로 세지 않음(표본 부풀림 방지).
  비용 미반영 · 모의 · 검증전.
복원(--recompute): KR 매집은 data/flows 확정 수급으로 과거 160거래일을 5일 간격 재계산(origin 'recompute', 당시 화면 노출분 아님).
복원: --restore 는 reports/archive/accum/*.json 과 git 이력(accum·us_accum·sim_signals)의 과거 판을 읽어
  당시 기준일로 신호를 되살린다(origin 'archive'/'git:<커밋>' 표기). 그 이전은 기록 없음.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "signal_tracking.json"          # 요약 + 최근 신호 (화면용, 작게)
EV_DIR = REPORT_DIR / "signal_tracking"             # 월별 이벤트 원장 YYYY-MM.json (바뀐 달만 다시 씀 — 저장소 부피)
RECENT_N = 60
REPEAT_DAYS = 20
SOURCES = [
    {"src": "accum", "market": "KR", "file": "reports/accum.json", "screen": "MARKET › KR 매집 패널", "tracked": True},
    {"src": "us_accum", "market": "US", "file": "reports/us_accum.json", "screen": "화면 패널 없음(getUsAccum getter만)", "tracked": True},
    {"src": "sim_kr", "market": "KR", "file": "reports/sim_signals_KR.json", "screen": "DAILY › 운용회의 '새로 켜진 추세 신호'", "tracked": True},
    {"src": "sim_us", "market": "US", "file": "reports/sim_signals_US.json", "screen": "DAILY › 운용회의(미장) '새로 켜진 추세 신호'", "tracked": True},
    {"src": "disc_kr", "market": "KR", "file": "reports/trend_discovery_KR.json", "screen": "화면 패널 없음(탐색 레이어 — 주문표 근거 불가)", "tracked": True},
    {"src": "disc_us", "market": "US", "file": "reports/trend_discovery_US.json", "screen": "화면 패널 없음(탐색 레이어 — 주문표 근거 불가)", "tracked": True},
    {"src": "ideas_top", "market": "KR·US", "file": "reports/idea_tracking.json", "screen": "DAILY › 운용회의 트레이드 아이디어",
     "tracked": False, "why": "screener/idea_tracking.py 가 진입 규칙 모의추적 — 중복 안 함"},
    {"src": "entry_signals", "market": "KR", "file": "reports/studies/entry_signals.json", "screen": "QUANT › 검증 스터디",
     "tracked": False, "why": "지수 급락 타점(종목 아님)"},
    {"src": "alerts", "market": "KR", "file": "reports/alerts_state.json", "screen": "텔레그램 규정 알림",
     "tracked": False, "why": "보유 규정 집행 알림(종목 신호 아님)"},
]
BEAR_TAGS = {"distrib"}
ACCUM_KO = {"accum": "외인+기관 20일 매집", "diverge": "가격 정체 속 매집", "foreign": "외국인 매집", "inst": "기관 매집",
            "pension": "연기금 매집", "streak": "연속 순매수", "dryexp": "거래 마름 뒤 확대", "distrib": "분배(약세)"}


def _j(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def extract(src: str, d: dict) -> list[dict]:
    """원천 파일 한 판 → 신호 [{date, src, tag, code, name, market, side}]."""
    out = []
    if not d or d.get("status") == "fail":
        return out
    if src == "accum":
        day = str(d.get("asof") or "")[:10]
        for tag, rows in (d.get("top") or {}).items():
            for r in rows or []:
                if r.get("code"):
                    out.append({"date": day, "src": src, "tag": tag, "code": str(r["code"]), "name": r.get("name"),
                                "market": "KR", "side": -1 if tag in BEAR_TAGS else 1})
    elif src == "us_accum":
        for h in d.get("hits") or []:
            if h.get("symbol"):
                out.append({"date": str(h.get("date") or d.get("asof") or "")[:10], "src": src,
                            "tag": "combo" if (h.get("n_sig") or 0) >= 2 else "single", "code": h["symbol"],
                            "name": h.get("name"), "market": "US", "side": 1})
    elif src in ("sim_kr", "sim_us"):
        mk = "KR" if src == "sim_kr" else "US"
        for r in d.get("rows") or []:
            if r.get("s"):
                out.append({"date": str(r.get("entry_date") or d.get("asof") or "")[:10], "src": src,
                            "tag": str(r.get("strategy") or "trend"), "code": str(r["s"]), "name": r.get("n"),
                            "market": mk, "side": 1})
    elif src in ("disc_kr", "disc_us"):
        # 추세 탐색 레이어(screener/trend_discovery.py) — 전진 추적으로만 검증(사전등록 전 탐색, 상한 C). 태그: 층:전략
        mk = "KR" if src == "disc_kr" else "US"
        ex = d.get("explore") or {}
        picks = [("nm", r) for r in (d.get("near_miss") or {}).get("rows") or []]
        picks += [("x", r) for r in ex.get("rows") or [] if r.get("pass_wilson") or r.get("pass_exp")]
        picks += [("new", r) for r in (ex.get("fresh_new") or {}).get("rows") or []]
        picks += [("chase", r) for r in (ex.get("chase") or {}).get("rows") or []]
        for layer, r in picks:
            if r.get("s"):
                out.append({"date": str(r.get("entry_date") or d.get("asof") or "")[:10], "src": src,
                            "tag": f"{layer}:{r.get('strategy')}", "code": str(r["s"]), "name": r.get("n"), "market": mk,
                            "side": -1 if layer == "chase" else 1})
    return [x for x in out if len(x["date"]) == 10]


def _file_of(src: str) -> str:
    return next(s["file"] for s in SOURCES if s["src"] == src)


def merge(book: dict, sigs: list[dict], origin: str) -> int:
    """새 신호만 추가 — 같은 (src,tag,code) 가 REPEAT_DAYS 안에 이미 있으면 '계속'(추가 안 함). 반환: 추가 수."""
    ev = book.setdefault("events", [])
    last: dict = {}
    for e in ev:
        k = (e["src"], e["tag"], e["code"])
        last.setdefault(k, []).append(e["date"])
    n = 0
    for s in sorted(sigs, key=lambda x: x["date"]):
        k = (s["src"], s["tag"], s["code"])
        d0 = date.fromisoformat(s["date"])
        if any(abs((d0 - date.fromisoformat(x)).days) < REPEAT_DAYS for x in last.get(k, [])):
            continue
        ev.append({**s, "id": f"{s['date']}:{s['src']}:{s['tag']}:{s['code']}", "origin": origin, "fwd": {}})
        last.setdefault(k, []).append(s["date"])
        n += 1
    ev.sort(key=lambda e: (e["date"], e["src"], e["tag"], e["code"]))
    return n


def collect_live(book: dict) -> int:
    n = 0
    for s in SOURCES:
        if s["tracked"]:
            n += merge(book, extract(s["src"], _j(REPORT_DIR.parent / s["file"], {})), "live")
    return n


def restore(book: dict, repo=None) -> dict:
    """archive/accum + git 이력에서 과거 판 복원. 반환: {원천: 추가 수}."""
    from pathlib import Path
    repo = Path(repo or REPORT_DIR.parent)
    got = {}
    for f in sorted((REPORT_DIR / "archive" / "accum").glob("20*.json")):
        got["archive:accum"] = got.get("archive:accum", 0) + merge(book, extract("accum", _j(f, {})), "archive")
    for s in SOURCES:
        if not s["tracked"]:
            continue
        try:
            hs = subprocess.run(["git", "-C", str(repo), "log", "--format=%h", "--", s["file"]],
                                capture_output=True, text=True, timeout=60).stdout.split()
        except Exception as e:  # noqa: BLE001
            log.warning("git 이력 읽기 실패 %s: %s", s["file"], e)
            continue
        for h in hs:
            try:
                txt = subprocess.run(["git", "-C", str(repo), "show", f"{h}:{s['file']}"], capture_output=True,
                                     text=True, timeout=60).stdout
                d = json.loads(txt) if txt else {}
            except Exception:  # noqa: BLE001
                continue
            got["git:" + s["src"]] = got.get("git:" + s["src"], 0) + merge(book, extract(s["src"], d), "git:" + h)
    return got


def restore_recompute(book: dict, n_days: int = 160, step: int = 5) -> int:
    """KR 매집 신호를 data/flows 확정 수급으로 과거 시점 재계산(accum.scan 을 그날까지 자른 데이터로) — origin 'recompute'.
    그날 이후 데이터는 쓰지 않는다(미래 참조 없음). 단, 당시 화면에 실제로 노출된 목록은 아님(화면은 10/16부터) — 표기."""
    import pandas as pd
    from . import accum as A
    df = A.load_store()
    names = A.load_names()
    days = sorted(df["date"].unique())
    n = 0
    for d in days[-n_days::step]:
        sub = df[df["date"] <= d]
        o = A.scan(sub, names, today=pd.Timestamp(d).date())
        if o.get("status") in ("ok", "partial"):
            n += merge(book, extract("accum", o), "recompute")
    return n


def evaluate(book: dict, now: datetime) -> None:
    from .fwd_perf import HORIZONS, MarketMedian, fwd_excess, kr_bars, us_bars
    todo = [e for e in book.get("events") or [] if any((e.get("fwd") or {}).get(f"h{h}") is None for h in HORIZONS)]
    if not todo:
        return
    uni = {}
    for mk, fn in (("KR", lambda: kr_bars(now)), ("US", lambda: us_bars())):
        if any(e["market"] == mk for e in todo):
            try:
                bars = fn()
                uni[mk] = (bars, MarketMedian(bars))
            except Exception as e:  # noqa: BLE001
                log.warning("신호 추적 가격 실패 %s: %s", mk, e)
                book.setdefault("errors", {})[mk] = f"{type(e).__name__}: 가격 원천 없음"
    for e in todo:
        u = uni.get(e["market"])
        if not u:
            continue
        bars = u[0].get(e["code"]) or []
        e["fwd"] = fwd_excess(bars, e["date"], u[1]) if bars else {}
        if not bars:
            e["note"] = "가격 원천에 종목 없음 — 미평가"


def _summ(evs: list[dict]) -> dict:
    from .fwd_perf import summarize
    # 약세 신호는 부호를 뒤집어 '맞은 방향 초과'로 집계
    flip = [{**e, "fwd": {k: (None if v is None else {**v, "ex": None if v.get("ex") is None else v["ex"] * e.get("side", 1)})
                          for k, v in (e.get("fwd") or {}).items()}} for e in evs]
    return {"n_events": len(evs), **summarize(flip)}


def build(now: datetime | None = None, do_restore: bool = False, write: bool = True) -> dict:
    now = now or datetime.now(KST)
    book = _j(OUT, {}) or {}
    book.pop("recent", None)
    book["events"] = [e for f in sorted(EV_DIR.glob("20*.json")) for e in _j(f, [])] if EV_DIR.exists() else book.get("events", [])
    book.setdefault("version", 1)
    book["schema_version"] = 1
    restored = restore(book) if do_restore else None
    if do_restore and "--recompute" in sys.argv:
        restored["recompute:accum"] = restore_recompute(book)
    added = collect_live(book)
    book.pop("errors", None)
    evaluate(book, now)
    ev = book.get("events") or []
    groups: dict = {}
    for e in ev:
        groups.setdefault((e["src"], e["tag"]), []).append(e)
    by_tag = [{"src": s, "tag": t, "label": ACCUM_KO.get(t, t) if s == "accum" else t, "side": g[0].get("side", 1), **_summ(g)}
              for (s, t), g in sorted(groups.items())]
    by_src = {s["src"]: _summ([e for e in ev if e["src"] == s["src"]]) for s in SOURCES if s["tracked"]}
    first = min((e["date"] for e in ev), default=None)
    book.update(asof=str(now.date()), generated_at=now.strftime("%Y-%m-%d %H:%M KST"), sources=SOURCES,
                by_src=by_src, by_tag=by_tag, first=first, added_today=added,
                origin_counts={o: sum(1 for e in ev if e.get("origin", "").split(":")[0] == o) for o in ("live", "archive", "git", "recompute")},
                policy="신호일 종가 → 5·20·60거래일 뒤 종가, 같은 창 시장 중앙값 대비 초과. 적중 = 초과>0(약세 신호는 <0). "
                       f"같은 원천·태그·종목 {REPEAT_DAYS}일 안 재등장은 '계속'. 비용 미반영 · 모의 · 검증전. "
                       "과거 판 복원분은 origin 'archive'·'git:<커밋>'(당시 게시본), 'recompute'(KR 매집만 data/flows 로 그날까지 재계산, "
                       "5거래일 간격 — 당시 화면 노출분 아님).")
    if restored is not None:
        book["restored"] = {"at": now.strftime("%Y-%m-%d %H:%M"), "added": restored}
    if write:
        EV_DIR.mkdir(parents=True, exist_ok=True)
        months: dict = {}
        for e in ev:
            months.setdefault(e["date"][:7], []).append(e)
        for m, es in months.items():
            f = EV_DIR / f"{m}.json"
            txt = json.dumps(es, ensure_ascii=False, separators=(",", ":"))
            if not f.exists() or f.read_text(encoding="utf-8") != txt:
                f.write_text(txt, encoding="utf-8")
        head = {k: v for k, v in book.items() if k != "events"}
        head["recent"] = [{k: e.get(k) for k in ("date", "src", "tag", "code", "name", "market", "side", "origin", "fwd")} for e in ev[-RECENT_N:]][::-1]
        head["n_events"] = len(ev)
        head["ledger"] = "reports/signal_tracking/<YYYY-MM>.json"
        OUT.write_text(json.dumps(head, ensure_ascii=False, indent=1), encoding="utf-8")
    return book


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    b = build(do_restore="--restore" in sys.argv)
    print(json.dumps({k: b[k] for k in ("asof", "first", "added_today", "origin_counts", "by_src")}, ensure_ascii=False, indent=1))
    print(json.dumps(b.get("restored"), ensure_ascii=False))
