"""일본 시장 추적 — 닛케이·TOPIX·JGB 10년·엔 캐리 + 한국 종목과 연결된 일본 피어 그룹 → reports/japan.json

왜: 도쿄는 서울과 같은 09:00 KST 에 열리고, 일본 반도체 장비·메모리·MLCC 종목은 한국 반도체·삼성전기와 같이 움직인다.
엔화 급등(엔 캐리 청산)과 일본은행(BOJ)·JGB 금리는 세계 위험자산을 흔든다 (2024-08-05 닛케이 −12%, 코스피 −8.8%).

그룹별: 종목 1D/5D/20D, 동일가중 바스켓 수익률, 한국(·미국) 피어 바스켓과 60거래일 일간 수익률 상관.
한국 피어 시세는 reports/detail/KR/{code}.json 의 c1y([날짜, 종가]) 를 쓴다 (추가 수집 없음).
실패해도 다른 화면엔 영향 없음. 수집 성공/실패는 sources 에 남긴다.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime, timedelta

from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "japan.json"
CORR_N = 60

INDEX = {"NIKKEI": ["^N225"], "TOPIX": ["^TOPX", "1306.T"]}   # TOPIX 지수가 없으면 TOPIX 추종 ETF(1306.T) 로 대체
GROUPS = [
    {"id": "equip", "name": "반도체 장비",
     "jp": {"8035.T": "도쿄일렉트론", "6857.T": "어드반테스트", "6146.T": "디스코", "6920.T": "레이저텍", "7735.T": "스크린"},
     "kr": {"000660": "SK하이닉스", "005930": "삼성전자"},
     "link": "메모리·파운드리 설비투자가 늘면 장비가 먼저 팔린다 → 일본 장비주는 SK하이닉스·삼성전자 업황의 선행·동행 신호."},
    {"id": "memory", "name": "메모리(Kioxia)",
     "jp": {"285A.T": "키옥시아"},
     "kr": {"000660": "SK하이닉스"}, "us": {"SNDK": "샌디스크"},
     "link": "키옥시아는 낸드 3위(샌디스크와 공동 생산) → 낸드 가격·AI 스토리지 수요를 SK하이닉스(솔리다임)와 같이 탄다."},
    {"id": "mlcc", "name": "MLCC·수동부품",
     "jp": {"6981.T": "무라타", "6762.T": "TDK", "6976.T": "다이요유덴"},
     "kr": {"009150": "삼성전기"},
     "link": "MLCC 1·3위가 무라타·다이요유덴, 2위가 삼성전기 → 같은 제품·같은 고객(스마트폰·AI 서버) 업황을 공유."},
]


# ───────────────────────── 수집 ─────────────────────────
def _yahoo(syms: list[str], days: int = 200) -> dict[str, list[tuple[str, float]]]:
    """{심볼: [(YYYY-MM-DD, 종가), ...]} — 데이터 없는 심볼은 빠짐."""
    import pandas as pd
    import yfinance as yf
    start = (date.today() - timedelta(days=days)).isoformat()
    raw = yf.download(syms, start=start, auto_adjust=True, group_by="ticker", progress=False, threads=True, timeout=60)
    out = {}
    if raw is None or raw.empty:
        return out
    if len(syms) == 1:
        raw = pd.concat({syms[0]: raw}, axis=1)
    lv0 = set(raw.columns.get_level_values(0))
    for s in syms:
        if s not in lv0:
            continue
        c = raw[s]["Close"].dropna()
        if len(c):
            out[s] = [(str(pd.Timestamp(i).date()), float(v)) for i, v in c.items()]
    return out


def _jgb_mof() -> list[tuple[str, float]]:
    """재무성 국채 금리 CSV (영문판). 당월분 + 과거분을 합쳐 [(날짜, 10년물 %)]."""
    import requests
    base = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
    rows: dict[str, float] = {}
    for u in (base + "historical/jgbcme_all.csv", base + "jgbcme.csv"):
        try:
            r = requests.get(u, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            rows.update(_parse_mof(r.content.decode("utf-8", "ignore")))
        except Exception as e:  # noqa: BLE001
            log.info("MOF %s 실패: %s", u.rsplit("/", 1)[-1], e)
    return sorted(rows.items())[-400:]


def _parse_mof(text: str) -> dict[str, float]:
    col, out = None, {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if col is None:
            if "10Y" in cells:
                col = cells.index("10Y")
            continue
        m = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})$", cells[0]) if cells else None
        if m and len(cells) > col:
            try:
                out[f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}"] = float(cells[col])
            except ValueError:
                pass
    return out


def _jgb_naver() -> list[tuple[str, float]]:
    import requests
    r = requests.get("https://api.stock.naver.com/marketindex/bond/JP10YT=RR/prices?page=1&pageSize=60",
                     timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    j = r.json()
    items = j if isinstance(j, list) else (j.get("result") or j.get("items") or [])
    out = []
    for x in items:
        d = str(x.get("localTradedAt") or x.get("date") or "")[:10].replace(".", "-")
        v = x.get("closePrice") or x.get("close")
        if re.match(r"\d{4}-\d{2}-\d{2}$", d) and v is not None:
            out.append((d, float(str(v).replace(",", ""))))
    return sorted(out)


# ───────────────────────── 계산 ─────────────────────────
def _rets(ser: list[tuple[str, float]]) -> dict[str, float]:
    return {ser[i][0]: ser[i][1] / ser[i - 1][1] - 1 for i in range(1, len(ser)) if ser[i - 1][1]}


def _ch(ser: list[tuple[str, float]], n: int) -> float | None:
    return ser[-1][1] / ser[-1 - n][1] - 1 if len(ser) > n and ser[-1 - n][1] else None


def _basket(sers: list[list[tuple[str, float]]]) -> dict[str, float]:
    """동일가중 일간 수익률 (그날 값이 있는 종목 평균)."""
    acc: dict[str, list[float]] = {}
    for s in sers:
        for d, r in _rets(s).items():
            acc.setdefault(d, []).append(r)
    return {d: sum(v) / len(v) for d, v in acc.items()}


def _corr(a: dict[str, float], b: dict[str, float], n: int = CORR_N, lag: bool = False) -> tuple[float | None, int]:
    """공통 날짜 최근 n개 상관. lag=True 면 b(미국)의 '직전 거래일' 수익률을 a(도쿄) 날짜에 붙인다 (밤사이 미장 → 다음 날 도쿄)."""
    if lag:
        bd = sorted(b)
        import bisect
        b = {d: b[bd[i - 1]] for d in a for i in [bisect.bisect_left(bd, d)] if i > 0}
    ds = sorted(set(a) & set(b))[-n:]
    if len(ds) < 20:
        return None, len(ds)
    xs, ys = [a[d] for d in ds], [b[d] for d in ds]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return (round(cov / (vx * vy), 3) if vx and vy else None), len(ds)


def _peer_series(mk: str, code: str) -> list[tuple[str, float]]:
    try:
        d = json.loads((REPORT_DIR / "detail" / mk / f"{code}.json").read_text(encoding="utf-8"))
        return [(str(r[0])[:10], float(r[1])) for r in d.get("c1y") or [] if r and r[1]]
    except Exception:  # noqa: BLE001
        return []


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _r(x, n=4):
    return None if x is None else round(x, n)


def _perf(ser):
    return {"last": _r(ser[-1][1], 2), "date": ser[-1][0], "chg1": _r(_ch(ser, 1)), "chg5": _r(_ch(ser, 5)), "chg20": _r(_ch(ser, 20))}


def build(fetch=None, jgb=None) -> dict:
    """fetch(syms)->{sym:[(date,close)]}, jgb()->[(date,yield)] 는 테스트용 주입."""
    fetch = fetch or _yahoo
    src: dict[str, str] = {}
    syms = [s for v in INDEX.values() for s in v] + [s for g in GROUPS for s in g["jp"]]
    try:
        px = fetch(syms)
    except Exception as e:  # noqa: BLE001
        log.warning("일본 시세 실패: %s", e)
        px = {}
    for s in syms:
        src[s] = f"ok {len(px[s])}일" if px.get(s) else "데이터 없음"

    idx = {}
    for k, cands in INDEX.items():
        for s in cands:
            if len(px.get(s) or []) > 21:
                idx[k] = {**_perf(px[s]), "sym": s, "proxy": s != cands[0]}
                break

    # JGB 10년: 재무성 CSV → 네이버 순
    jser, jsrc = [], None
    for name, fn in ([("test", jgb)] if jgb else [("mof", _jgb_mof), ("naver", _jgb_naver)]):
        try:
            jser = fn()
            if len(jser) >= 2:
                jsrc = name
                break
        except Exception as e:  # noqa: BLE001
            src[f"JGB10Y_{name}"] = f"실패: {type(e).__name__}"
    src["JGB10Y"] = f"{jsrc} {len(jser)}일" if jsrc else "실패 — 무료 소스 없음"
    if jsrc:
        last = jser[-1][1]
        p = lambda n: jser[-1 - n][1] if len(jser) > n else None  # noqa: E731
        idx["JGB10Y"] = {"last": round(last, 3), "date": jser[-1][0], "src": jsrc,
                         "d1bp": _r((last - p(1)) * 100, 1) if p(1) is not None else None,
                         "d20bp": _r((last - p(20)) * 100, 1) if p(20) is not None else None}
        try:   # 매크로 시계열에도 넣어 티커·차트·매크로 해설에서 보이게 (write_macro_series 가 이전 값 유지)
            mp = REPORT_DIR / "macro_series.json"
            m = json.loads(mp.read_text(encoding="utf-8"))
            m.setdefault("series", {})["JGB10Y"] = [[d, v, v, v, v, 0] for d, v in jser[-520:]]
            mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.info("JGB 매크로 시계열 병합 실패: %s", e)

    # 엔/달러 (기존 매크로 시계열) — 5일 −3% 이하면 엔 급등 = 캐리 청산 경계
    try:
        ms = json.loads((REPORT_DIR / "macro_series.json").read_text(encoding="utf-8")).get("series", {})
        u = [(r[0], r[4] if len(r) >= 6 else r[1]) for r in ms.get("USDJPY") or []]
        if len(u) > 21:
            idx["USDJPY"] = _perf(u)
    except Exception:  # noqa: BLE001
        pass
    uj = idx.get("USDJPY") or {}
    carry = {"chg5": uj.get("chg5"), "flag": uj.get("chg5") is not None and uj["chg5"] <= -0.03,
             "rule": "엔/달러 5일 −3% 이하(엔 급등) → 엔 캐리 청산 경계 (2024-08-05 유형)"}

    groups = []
    for g in GROUPS:
        rows = []
        for s, nm in g["jp"].items():
            ser = px.get(s) or []
            if len(ser) > 21:
                rows.append({"sym": s, "name": nm, **_perf(ser)})
        jp_b = _basket([px[r["sym"]] for r in rows])
        kr_sers = {c: _peer_series("KR", c) for c in g["kr"]}
        kr_ok = {c: s for c, s in kr_sers.items() if len(s) > 21}
        kr_b = _basket(list(kr_ok.values()))
        cr, n = _corr(jp_b, kr_b) if rows and kr_ok else (None, 0)
        peers = [{"sym": c, "name": g["kr"][c], "mk": "KR", **_perf(s)} for c, s in kr_ok.items()]
        out = {"id": g["id"], "name": g["name"], "link": g["link"], "rows": rows,
               "jp": {k: _r(_avg([r[k] for r in rows])) for k in ("chg1", "chg5", "chg20")},
               "kr": {k: _r(_avg([p[k] for p in peers])) for k in ("chg1", "chg5", "chg20")},
               "kr_label": "·".join(g["kr"][c] for c in kr_ok) or "·".join(g["kr"].values()),
               "peers": peers, "corr_kr": cr, "corr_n": n,
               "missing": [g["jp"][s] for s in g["jp"] if s not in {r["sym"] for r in rows}]}
        for us_code, us_nm in (g.get("us") or {}).items():
            s = _peer_series("US", us_code)
            if len(s) > 21:
                peers.append({"sym": us_code, "name": us_nm, "mk": "US", **_perf(s)})
                cu, nu = _corr(jp_b, _rets(s), lag=True) if rows else (None, 0)
                out["corr_us"], out["corr_us_n"], out["us_label"] = cu, nu, us_nm
        if rows:
            groups.append(out)
        else:
            src[g["id"]] = "그룹 전체 데이터 없음 — 제외"

    o = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "date": max([r["date"] for g in groups for r in g["rows"]], default=None),
         "index": idx, "carry": carry, "groups": groups, "sources": src,
         "why": "도쿄는 서울과 같은 9시에 열린다. 일본 반도체 장비·메모리·MLCC가 한국 반도체·삼성전기와 같이 움직이고, 엔화 급등(엔 캐리 청산)은 세계 위험자산을 한꺼번에 흔든다."}
    o["line"] = committee_line(o)
    OUT.write_text(json.dumps(o, ensure_ascii=False, default=str), encoding="utf-8")
    log.info("일본: %s", o["line"] or "특이 없음")
    return o


def _p(x, d=1):
    return "—" if x is None else f"{x*100:+.{d}f}%"


def committee_line(o: dict | None = None) -> str | None:
    """운용회의 한 줄 (규칙 기반). 닛케이 1D ±1.5% 이상·그룹 1D ±3% 이상·엔 캐리 경계 중 하나라도 있으면 출력.
    그룹은 1D 움직임이 가장 큰 하나만 언급."""
    if o is None:
        try:
            o = json.loads(OUT.read_text(encoding="utf-8"))
            if (datetime.now(KST).date() - date.fromisoformat(str(o.get("date"))[:10])).days > 4:
                return None
        except Exception:  # noqa: BLE001
            return None
    nk = (o.get("index") or {}).get("NIKKEI") or {}
    gs = [g for g in o.get("groups") or [] if (g.get("jp") or {}).get("chg1") is not None]
    top = max(gs, key=lambda g: abs(g["jp"]["chg1"]), default=None)
    carry = o.get("carry") or {}
    hot_nk = nk.get("chg1") is not None and abs(nk["chg1"]) >= 0.015
    hot_g = top is not None and abs(top["jp"]["chg1"]) >= 0.03
    if not (hot_nk or hot_g or carry.get("flag")):
        return None
    parts = []
    if nk.get("chg1") is not None:
        parts.append(f"닛케이 {_p(nk['chg1'])}")
    if top is not None:
        s = f"日 {top['name']} {_p(top['jp']['chg1'])}"
        if (top.get("kr") or {}).get("chg1") is not None:
            s += f" vs {top['kr_label']} {_p(top['kr']['chg1'])}"
        if top.get("corr_kr") is not None:
            s += f" (60일 상관 {top['corr_kr']:.2f})"
        parts.append(s)
    if carry.get("flag"):
        parts.append(f"엔 캐리 청산 경계: 엔/달러 5일 {_p(carry['chg5'])}")
    return "일본: " + " · ".join(parts) + " (일본 패널)"


def summary(o: dict) -> str:
    L = [f"일본 {o.get('date')} · " + " · ".join(f"{k} {v.get('last')} ({_p(v.get('chg1'))})" for k, v in (o.get("index") or {}).items() if "chg1" in v)]
    for g in o.get("groups") or []:
        L.append(f"- {g['name']}: 1D {_p(g['jp']['chg1'])} 5D {_p(g['jp']['chg5'])} 20D {_p(g['jp']['chg20'])} · 상관(KR) {g.get('corr_kr')} n={g.get('corr_n')}"
                 + (f" · 상관(US 전일) {g.get('corr_us')}" if "corr_us" in g else ""))
    L.append("sources: " + json.dumps(o.get("sources"), ensure_ascii=False))
    L.append("line: " + str(o.get("line")))
    return "\n".join(L)
