"""대결 누적 성과판 — reports/battle_scoreboard.json (2026-10-20 dev: battle-scoreboard).

원천
  reports/decisions.json        대결 원장(픽·확정 채점 result·승자) — screener/decisions.py 가 채점
  reports/battle_daily*.json    외부 일별 모의 평가 스냅샷(보유 중 평가) — 마킹 이력에 '외부 스냅샷'으로만 합침
  가격(마킹·벤치마크)          screener/fwd_perf.bars_for — KR kr_prices/detail KR, US detail US (네트워크 없음)

정의
  수익률(ret)  확정 = decisions result 의 ret(비용 0.05% 반영). 보유 중 = 진입가(규칙대로 종가/시가) → 최근 확정 종가, 비용 0.05% 차감.
  벤치마크     KR = KODEX 200(069500, duel.NAMES 의 기본 지수 픽) · US = SPY(S&P500, us_committee 채점 기준과 같은 지수).
               같은 창(진입일 진입 방식 → 청산/평가일 종가) 수익. 초과 = ret − 벤치마크.
  누적         참가자별 확정 판의 단순 합(판마다 같은 비중 1단위로 본 수익률 합) · 복리 · 승(=decisions winner) · 평균 초과.
  가격 없음    미제출(pending)·가격 원천에 없는 종목은 '미평가'(사유) — 0 으로 채우지 않는다.
  금액         공개 저장소라 원·달러 금액·notional 은 쓰지 않는다(비율만).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "battle_scoreboard.json"
BENCH = {"KR": ("069500", "KODEX 200"), "US": ("SPY", "SPY (S&P500)")}
COST = 0.0005
MARK_KEEP = 90   # 판당 마킹 이력 최대 일수


def _j(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _bar_on(bars: list[dict], d: str) -> dict | None:
    return next((b for b in bars if b["date"] == d), None)


def _last_upto(bars: list[dict], d: str | None = None) -> dict | None:
    xs = [b for b in bars if (d is None or b["date"] <= d) and b.get("close")]
    return xs[-1] if xs else None


def entry_price(p: dict, date: str, bars: list[dict]) -> tuple[float | None, str | None]:
    """규칙대로 진입가: entry 'open' = 결정일 시가, 그 외 = 결정일 종가."""
    b = _bar_on(bars, date)
    if not b:
        return None, None
    v = b.get("open") if p.get("entry") == "open" else b.get("close")
    return (v, date) if v else (None, None)


def bench_ret(bars: list[dict], start: str, kind: str, end: str, end_kind: str = "close") -> float | None:
    """벤치마크 같은 창: start 의 시가(kind=open) 또는 종가 → end 의 시가(end_kind=open) 또는 end 이하 마지막 종가."""
    b0 = _bar_on(bars, start)
    b1 = _bar_on(bars, end) if end_kind == "open" else _last_upto(bars, end)
    if not b0 or not b1 or b1["date"] < start:
        return None
    a = b0.get("open") if kind == "open" else b0.get("close")
    z = b1.get("open") if end_kind == "open" else b1.get("close")
    if not a or not z:
        return None
    if kind != "open" and b1["date"] == start:
        return None
    return z / a - 1


def _end_date(res: dict) -> tuple[str | None, str]:
    """확정 result.detail '… → YYYY-MM-DD 시가|종가 …' 에서 (청산일, 'open'|'close')."""
    import re
    m = re.search(r"→\s*(\d{4}-\d{2}-\d{2})\s*(시가|종가)?", str(res.get("detail") or ""))
    if not m:
        return None, "close"
    return m.group(1), "open" if m.group(2) == "시가" else "close"


def _row(it: dict, who: str, p: dict, px: dict, bench: dict, today: str) -> dict:
    mk = it.get("market") or "KR"
    res = (it.get("result") or {})
    r = {"who": who, "name": p.get("name") or p.get("ticker") or ("현금" if p.get("cash") else "미제출"),
         "ticker": p.get("ticker"), "entry": p.get("entry"), "exit": p.get("exit")}
    if p.get("pending"):
        return {**r, "status": "미제출", "ret": None, "why": "제출 없음 — 미평가"}
    if res.get("void"):
        return {**r, "status": "제외", "ret": None, "why": res["void"]}
    bb = bench.get(mk) or []
    if p.get("cash"):
        rr = res.get(who) or {}
        return {**r, "status": "확정" if who in res else "현금", "ret": 0.0, "bench": None, "ex": None,
                "why": rr.get("detail") or p.get("label") or "현금 유지"}
    if who in res:   # 확정
        rr = res[who]
        end, ek = _end_date(rr)
        end = end or it["date"]
        b = bench_ret(bb, it["date"], p.get("entry", "close"), end, ek)
        ret = rr.get("ret")
        return {**r, "status": "확정", "ret": ret, "end": end, "bench": None if b is None else round(b - COST, 5),
                "ex": None if b is None or ret is None else round(ret - (b - COST), 5),
                "win": res.get("winner") == who, "why": rr.get("detail")}
    bars = px.get(str(p.get("ticker"))) or []
    if not bars:
        return {**r, "status": "미평가", "ret": None, "why": "가격 원천에 종목 없음(detail·kr_prices) — 평가 보류"}
    e, ed = entry_price(p, it["date"], bars)
    if e is None:
        if it["date"] >= today or it["date"] > bars[-1]["date"]:
            return {**r, "status": "진입 대기", "ret": None, "why": "결정일 확정 봉 대기"}
        return {**r, "status": "미평가", "ret": None, "why": f"{it['date']} 봉 없음 — 진입가 미확인"}
    last = _last_upto(bars)
    if p.get("entry") != "open" and last["date"] <= it["date"]:
        return {**r, "status": "진입 대기", "ret": None, "entry_px_date": ed, "why": "종가 진입 — 다음 거래일부터 평가"}
    ret = last["close"] / e - 1 - COST
    b = bench_ret(bb, it["date"], p.get("entry", "close"), last["date"])
    return {**r, "status": "보유 중", "ret": round(ret, 5), "mark_date": last["date"],
            "bench": None if b is None else round(b - COST, 5), "ex": None if b is None else round(ret - (b - COST), 5),
            "why": "확정 전 평가(최근 확정 종가) — 누적 승패에 합산 안 함"}


def _external_marks() -> dict:
    """battle_daily 스냅샷 → {battle_id: {who: {date: ret}}} (외부 작성, 출처 표기용)."""
    out: dict = {}
    snaps = sorted((REPORT_DIR / "battle_daily").glob("*.json")) + [REPORT_DIR / "battle_daily.json"]
    for f in snaps:
        d = _j(f, {})
        for b in d.get("battles") or []:
            for r in b.get("rows") or []:
                if r.get("ret") is None or not r.get("price_date") or r.get("status") == "cash":
                    continue
                out.setdefault(b.get("id"), {}).setdefault(r.get("who"), {})[r["price_date"]] = round(float(r["ret"]), 5)
    return out


def _tally(rows: list[dict]) -> dict:
    fin = [r for r in rows if r["status"] == "확정" and r.get("ret") is not None]
    trades = [r for r in fin if r.get("ticker")]
    cum, comp = 0.0, 1.0
    for r in fin:
        cum += r["ret"]
        comp *= 1 + r["ret"]
    exs = [r["ex"] for r in trades if r.get("ex") is not None]
    return {"n": len(fin), "win": sum(1 for r in fin if r.get("win")), "trades": len(trades),
            "hit": round(sum(1 for r in trades if r["ret"] > 0) / len(trades), 3) if trades else None,
            "cum_ret": round(cum, 5), "comp_ret": round(comp - 1, 5),
            "avg_ex": round(sum(exs) / len(exs), 5) if exs else None, "n_ex": len(exs),
            "open": sum(1 for r in rows if r["status"] == "보유 중"),
            "unrated": sum(1 for r in rows if r["status"] in ("미평가", "진입 대기"))}


def build(now: datetime | None = None, write: bool = True) -> dict:
    now = now or datetime.now(KST)
    today = str(now.date())
    dec = _j(REPORT_DIR / "decisions.json", {"items": []})
    items = [it for it in dec.get("items") or [] if it.get("kind") not in ("ticket", "exit") and it.get("picks")]
    from .fwd_perf import bars_for
    px: dict = {}
    for mk in ("KR", "US"):
        codes = {str(p["ticker"]) for it in items if (it.get("market") or "KR") == mk
                 for p in it["picks"].values() if p.get("ticker")} | {BENCH[mk][0]}
        try:
            px[mk] = bars_for(mk, codes, now)
        except Exception as e:  # noqa: BLE001
            log.warning("대결 성과판 가격 실패 %s: %s", mk, e)
            px[mk] = {}
    bench = {mk: px[mk].get(BENCH[mk][0]) or [] for mk in px}
    prev = _j(OUT, {})
    pmarks = {b["id"]: {r["who"]: r.get("marks") or {} for r in b.get("rows") or []} for b in prev.get("battles") or []}
    ext = _external_marks()
    battles = []
    for it in sorted(items, key=lambda x: (x["date"], x["id"])):
        mk = it.get("market") or "KR"
        rows = []
        for who, p in it["picks"].items():
            r = _row(it, who, p, px.get(mk) or {}, bench, today)
            m = dict(pmarks.get(it["id"], {}).get(who) or {})
            if r["status"] == "보유 중":
                m[r["mark_date"]] = r["ret"]
            elif r["status"] == "확정" and r.get("ret") is not None:
                m[r.get("end") or it["date"]] = r["ret"]
            r["marks"] = dict(sorted(m.items())[-MARK_KEEP:])
            em = (ext.get(it["id"]) or {}).get(who)
            if em:
                r["marks_ext"] = em
            rows.append(r)
        res = it.get("result") or {}
        battles.append({"id": it["id"], "date": it["date"], "market": mk, "title": it.get("title"),
                        "state": "제외" if res.get("void") else "확정" if res else "진행",
                        "winner": res.get("winner"), "rows": rows})
    whos = sorted({r["who"] for b in battles for r in b["rows"]})
    by_who = {w: _tally([r for b in battles for r in b["rows"] if r["who"] == w]) for w in whos}
    by_mk = {mk: {w: _tally([r for b in battles if b["market"] == mk for r in b["rows"] if r["who"] == w]) for w in whos}
             for mk in ("KR", "US")}
    curve = {}
    for w in whos:
        c, pts = 0.0, []
        for b in battles:
            r = next((x for x in b["rows"] if x["who"] == w and x["status"] == "확정" and x.get("ret") is not None), None)
            if r:
                c += r["ret"]
                pts.append([r.get("end") or b["date"], round(c, 5)])
        curve[w] = pts
    out = {"version": 1, "schema_version": 1, "asof": today, "generated_at": now.strftime("%Y-%m-%d %H:%M KST"),
           "bench": {k: {"ticker": v[0], "name": v[1]} for k, v in BENCH.items()},
           "policy": "확정 = decisions.json 채점(비용 0.05%). 보유 중 = 최근 확정 종가 평가(누적 미합산). 누적 수익률 = 확정 판 수익률 단순 합"
                     "(판마다 같은 비중). 벤치마크 KR KODEX 200·US SPY 같은 창. 미제출·가격 없음 = 미평가. 금액 미표시(비율만). 모의·실거래 아님.",
           "by_who": by_who, "by_market": by_mk, "curve": curve, "battles": battles[::-1]}
    if write:
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    o = build()
    print(json.dumps(o["by_who"], ensure_ascii=False, indent=1))
