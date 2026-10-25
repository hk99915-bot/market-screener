"""수급·파생 일별 이력 → data/deriv/daily.csv (하루 1행, KRX 확정치). 텔레그램·화면 없음.

왜: 수급·파생 신호(외국인 선물, 베이시스, 풋콜비율, 감마, 야간선물, 프로그램)를 검증하려면 일별 이력이 필요한데
    flows.py·derivs.py 는 '오늘'만 본다. 이 모듈은 같은 소스(KRX 정보데이터시스템, pykrx 로그인 세션)로 매일 1행씩 쌓고 과거를 백필한다.

소스 (2026-10-16 Actions 탐침으로 확인 — scripts/probe_deriv_sources.py, reports/logs/deriv_probe.txt)
  | 열                          | 소스                                                         | 과거 깊이        |
  |-----------------------------|--------------------------------------------------------------|------------------|
  | kospi_* · k200_close        | pykrx get_index_ohlcv (1001·1028)                             | 2010~ (기간 1콜) |
  | spot_frgn/inst/indiv/corp   | pykrx get_market_trading_value_by_date(KOSPI) 순매수, 억원     | 2010~ (기간 1콜) |
  | prog_arb · prog_nonarb      | KRX MDCSTAT02601 (프로그램매매, 하루씩 strt=end), 억원         | 2010~ (하루 1콜) |
  | fut_* · basis               | KRX MDCSTAT12501 선물 보드(최근월 주간), 하루 1콜              | 2010~            |
  | basis_theo                  | KRX MDCSTAT13401 베이시스 추이(이론 베이시스, 기간 조회)       | 확인 중          |
  | rep_iv                      | KRX MDCSTAT13501 대표 내재변동성(기간 조회)                    | 확인 중          |
  | pcr_* · walls · gex · flip  | KRX MDCSTAT12501 옵션 보드 → screener.derivs._summ, 하루 1콜   | 2012~            |
  | night_* (유렉스 시절)       | 같은 선물 보드의 '(야간)' 행 — 2025-06-05 이전만 있음           | ~2025-06         |
  | night_vwap · night_vol      | KRX MDCSTAT13001 상품군 합계 '코스피200 선물 (야간)' 대금÷수량  | 2025-06-09~      |
  |                             |  → trdDd=D 행 = D-1 18:00 ~ D 06:00 세션 (T+1 귀속)            |                  |
  | fut_frgn/inst/indiv         | 네이버 모바일 /api/index/FUT/integration dealTrendInfo (당일만) | 2026-10-16~ 적재 |
  |                             |  KRX 파생 투자자별(MDCSTAT13101)은 파라미터를 못 찾아 0만 옴    |                  |
  네이버 PC 일자별 수급·프로그램 페이지는 410(종료). investing·esignal 은 403.

실행
  python -m screener.deriv_hist --task run              # 최근 5영업일 갱신 (평일 16:40 KST)
  python -m screener.deriv_hist --task backfill --days N  # 하루 1콜 소스를 과거 N영업일까지 (빈 칸만 채움)
  python -m screener.main --mode deriv_hist              # = run
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = DATA_DIR / "deriv" / "daily.csv"
STATUS = REPORT_DIR / "deriv_hist_status.json"
MULT = 250_000

COLS = ["date",
        "kospi_open", "kospi_high", "kospi_low", "kospi_close", "k200_close",
        "spot_frgn", "spot_inst", "spot_indiv", "spot_corp",            # 코스피 현물 순매수 (억원)
        "prog_arb", "prog_nonarb",                                        # 코스피 프로그램 순매수 (억원)
        "fut_frgn", "fut_inst", "fut_indiv",                              # 코스피200 선물 순매수 (계약, 네이버 당일값 적재)
        "fut_name", "fut_open", "fut_close", "fut_spot", "fut_oi", "fut_vol", "basis", "basis_pct", "basis_theo",
        "night_close", "night_vol", "night_vwap", "night_src",            # 야간: 유렉스 시절 종가 / KRX 야간 VWAP
        "rep_iv",
        "opt_front", "opt_dte", "pcr_oi", "pcr_vol", "call_wall", "call_wall_oi", "put_wall", "put_wall_oi",
        "gex_bn", "flip", "atm_iv", "skew", "max_pain"]
DAILY_SRC = ("prog", "board")    # 하루 1콜 소스 묶음


def _f(x):
    try:
        s = str(x).replace(",", "").replace("+", "").strip()
        if s in ("", "-"):
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


# ───────────── KRX 호출 (pykrx 로그인 세션 재사용) ─────────────

import threading
_RL = threading.Lock()
_LAST_RELOGIN = [0.0]


def _relogin() -> None:
    """KRX 가 HTML(세션 끊김·과다 요청)을 돌려주면 재로그인 (60초에 한 번까지)."""
    import os
    with _RL:
        if time.time() - _LAST_RELOGIN[0] < 60:
            return
        _LAST_RELOGIN[0] = time.time()
        try:
            from pykrx.website.comm import auth
            if auth._auth_session is not None and os.getenv("KRX_ID"):
                ok = auth._auth_session.refresh(os.getenv("KRX_ID"), os.getenv("KRX_PW"))
                log.info("KRX 재로그인 %s", "성공" if ok else "실패")
        except Exception as e:  # noqa: BLE001
            log.info("KRX 재로그인 오류: %s", e)

def krx_post(bld: str, **params) -> list[dict]:
    import requests
    from pykrx.website.comm.webio import get_session
    params["bld"] = bld
    head = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
            "X-Requested-With": "XMLHttpRequest"}
    url = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    s = get_session()
    for i in range(3):
        try:
            if s is None:
                r = requests.post(url, data=params, headers=head, timeout=30)
            else:
                h = s.get_headers()
                h.update(head)
                r = s.session.post(url, data=params, headers=h, timeout=30)
            if r.text.startswith("{"):
                j = r.json()
                return j.get("output") or j.get("OutBlock_1") or []
            log.info("KRX %s HTML 응답 — 재로그인 후 재시도", bld[-9:])
            time.sleep(5 * (i + 1))
            _relogin()
            s = get_session()
        except Exception as e:  # noqa: BLE001
            log.info("KRX %s 재시도 %d: %s", bld[-9:], i + 1, e)
            time.sleep(2 * (i + 1))
    return []


# ───────────── 기간 소스 ─────────────

def index_range(start: date, end: date) -> dict[str, dict]:
    from pykrx import stock  # type: ignore
    out: dict[str, dict] = {}
    for code, pre in (("1001", "kospi"), ("1028", "k200")):
        df = stock.get_index_ohlcv(_ymd(start), _ymd(end), code)
        if df is None or df.empty:
            continue
        for ts, r in df.iterrows():
            d = str(ts.date())
            row = out.setdefault(d, {"date": d})
            if pre == "kospi":
                row.update({"kospi_open": float(r["시가"]), "kospi_high": float(r["고가"]), "kospi_low": float(r["저가"]),
                            "kospi_close": float(r["종가"])})
            else:
                row["k200_close"] = float(r["종가"])
    return out


def flows_range(start: date, end: date) -> dict[str, dict]:
    from pykrx import stock  # type: ignore
    df = stock.get_market_trading_value_by_date(_ymd(start), _ymd(end), "KOSPI")
    out = {}
    if df is None or df.empty:
        return out
    for ts, r in df.iterrows():
        d = str(ts.date())
        out[d] = {"date": d, "spot_frgn": round(float(r["외국인합계"]) / 1e8, 1), "spot_inst": round(float(r["기관합계"]) / 1e8, 1),
                  "spot_indiv": round(float(r["개인"]) / 1e8, 1), "spot_corp": round(float(r["기타법인"]) / 1e8, 1)}
    return out


def basis_theo_range(start: date, end: date) -> dict[str, dict]:
    """MDCSTAT13401 베이시스 추이: 날짜별 첫 행(최근월) 의 이론 베이시스."""
    out = {}
    s = start
    while s <= end:
        e = min(end, s + timedelta(days=365))
        for x in krx_post("dbms/MDC/STAT/standard/MDCSTAT13401", strtDd=_ymd(s), endDd=_ymd(e), prodId="KRDRVFUK2I", mktTpCd="T"):
            d = (x.get("TRD_DD") or "").replace("/", "-")[:10]
            if d and d not in out and _f(x.get("THRY_BASIS")) is not None:
                out[d] = {"date": d, "basis_theo": _f(x.get("THRY_BASIS"))}
        s = e + timedelta(days=1)
        time.sleep(0.3)
    return out


def rep_iv_range(start: date, end: date) -> dict[str, dict]:
    out = {}
    s = start
    while s <= end:
        e = min(end, s + timedelta(days=365))
        for x in krx_post("dbms/MDC/STAT/standard/MDCSTAT13501", strtDd=_ymd(s), endDd=_ymd(e), prodId="KRDRVOPK2I", mktTpCd="T"):
            d = (x.get("BAS_DD") or "").replace("/", "-")[:10]
            if d and _f(x.get("REP_IMP_VOLT")) is not None:
                out[d] = {"date": d, "rep_iv": _f(x.get("REP_IMP_VOLT"))}
        s = e + timedelta(days=1)
        time.sleep(0.3)
    return out


# ───────────── 하루 1콜 소스 ─────────────

def program_day(d: date) -> dict:
    out = {}
    for x in krx_post("dbms/MDC/STAT/standard/MDCSTAT02601", strtDd=_ymd(d), endDd=_ymd(d), mktId="STK"):
        v = _f(x.get("NETBID_TRDVAL"))
        if v is None:
            continue
        if x.get("ITM_TP_NM") == "차익":
            out["prog_arb"] = round(v / 1e8, 1)
        elif x.get("ITM_TP_NM") == "비차익":
            out["prog_nonarb"] = round(v / 1e8, 1)
    return out


def night_krx(d: date) -> dict:
    """KRX 자체 야간시장(2025-06-09~): trdDd=d 의 '코스피200 선물 (야간)' 상품군 합계 → 평균 체결가(VWAP)·거래량.
    d 행 = d-1 18:00 ~ d 06:00 세션. 종가는 이 화면에 없다(탐침 결과) → VWAP 로 대신하고 night_src='krx_vwap' 로 표시."""
    for x in krx_post("dbms/MDC/STAT/standard/MDCSTAT13001", trdDd=_ymd(d)):
        if (x.get("GRP_PROD_NM") or "").replace(" ", "") == "코스피200선물(야간)":
            vol, val = _f(x.get("TRDVOL")), _f(x.get("TRDVAL"))
            if vol and val:
                return {"night_vol": vol, "night_vwap": round(val / vol / MULT, 2), "night_src": "krx_vwap"}
    return {}


def board_day(d: date) -> dict:
    """옵션·선물 보드 (derivs.py 와 같은 계산). 거래일이 아니면 {}."""
    from . import derivs
    opt = fut = None
    for i in range(4):   # KRX 가 몰아치는 요청에 HTML(차단·세션 만료) 을 돌려줄 때가 있음 → 쉬었다 재시도
        try:
            opt, fut = derivs._day(_ymd(d))
            break
        except Exception as e:  # noqa: BLE001
            if i == 3:
                raise
            log.info("보드 %s 재시도 %d: %s", d, i + 1, e)
            time.sleep(10 * (i + 1))
            _relogin()
    raw = sum(1 for x in opt if re.search(r"코스피200\s+[CP]\s+\d{6}", x.get("ISU_NM") or "") and "야간" not in (x.get("ISU_NM") or ""))
    f = derivs._fut(fut)
    row: dict = {}
    if f:
        row.update({"fut_name": f.get("name"), "fut_open": f.get("open"), "fut_close": f.get("close"), "fut_spot": f.get("spot"),
                    "fut_oi": f.get("oi"), "fut_vol": f.get("vol"), "basis": f.get("basis")})
        if f.get("close") and f.get("spot"):
            row["basis_pct"] = round((f["close"] / f["spot"] - 1) * 100, 4)
        n = f.get("night") or {}
        if n.get("close"):
            row.update({"night_close": n["close"], "night_vol": n.get("vol"), "night_src": "eurex_board"})
    rows = derivs._parse(opt)
    if raw and len(rows) < raw:
        bad = [x.get("ISU_NM") for x in opt if re.search(r"코스피200\s+[CP]\s+\d{6}", x.get("ISU_NM") or "") and not derivs.RX.search(x.get("ISU_NM") or "")][:3]
        log.warning("%s 옵션 이름 파싱 누락 %d/%d 예: %s", d, raw - len(rows), raw, bad)
    S = (f or {}).get("spot") or (f or {}).get("close")
    if rows and S:
        s = derivs._summ(rows, S, d)
        if s:
            row.update({"opt_front": s.get("front"), "opt_dte": s.get("dte"), "pcr_oi": s.get("pcr_oi"), "pcr_vol": s.get("pcr_vol"),
                        "call_wall": (s.get("call_wall") or {}).get("k"), "call_wall_oi": (s.get("call_wall") or {}).get("oi"),
                        "put_wall": (s.get("put_wall") or {}).get("k"), "put_wall_oi": (s.get("put_wall") or {}).get("oi"),
                        "gex_bn": s.get("gex_bn"), "flip": s.get("flip"), "atm_iv": s.get("atm_iv"), "skew": s.get("skew"),
                        "max_pain": s.get("max_pain")})
    return row


def fut_investor_today() -> dict:
    """네이버 모바일 코스피200 선물 투자자별 순매수(계약, 당일). 과거 조회 불가 → 매일 적재해서 이력을 만든다."""
    import requests
    try:
        j = requests.get("https://m.stock.naver.com/api/index/FUT/integration",
                         headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "Referer": "https://m.stock.naver.com/"},
                         timeout=15).json()
        t = j.get("dealTrendInfo") or {}
        d = t.get("bizdate")
        if not d:
            return {}
        return {"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "fut_frgn": _f(t.get("foreignValue")), "fut_inst": _f(t.get("institutionalValue")),
                "fut_indiv": _f(t.get("personalValue"))}
    except Exception as e:  # noqa: BLE001
        log.warning("네이버 선물 투자자 실패: %s", e)
        return {}


# ───────────── 저장 ─────────────

def load() -> list[dict]:
    import csv
    if not OUT.exists():
        return []
    with OUT.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in COLS:
            if k in ("date", "fut_name", "opt_front", "night_src"):
                continue
            r[k] = _f(r.get(k))
    return rows


def save(rows: list[dict]) -> None:
    import csv
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: r["date"])
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in COLS})


def _merge(db: dict[str, dict], part: dict[str, dict] | list[dict], overwrite: bool = True) -> None:
    items = part.values() if isinstance(part, dict) else part
    for x in items:
        d = x.get("date")
        if not d:
            continue
        cur = db.setdefault(d, {"date": d})
        for k, v in x.items():
            if v is None or k == "date":
                continue
            if overwrite or cur.get(k) in (None, ""):
                cur[k] = v


def _trading_days(db: dict[str, dict]) -> list[str]:
    return sorted(d for d, r in db.items() if r.get("kospi_close"))


def run(task: str = "run", days: int = 0, redo: str | None = None) -> dict:
    """redo='YYYY-MM-DD': 그날 이후 옵션·선물 보드 값을 다시 계산 (계산식 수정 뒤 재적재용)."""
    t0 = time.time()
    today = datetime.now(KST).date()
    db = {r["date"]: r for r in load()}
    first = not db
    start = date(2010, 1, 1) if (first or task == "backfill") else today - timedelta(days=40)
    st: dict = {"task": task, "start": str(start), "errors": []}
    for nm, fn in (("index", index_range), ("flows", flows_range), ("basis_theo", basis_theo_range), ("rep_iv", rep_iv_range)):
        try:
            part = fn(start, today)
            _merge(db, part)
            st[nm] = len(part)
            log.info("%s %d일", nm, len(part))
        except Exception as e:  # noqa: BLE001
            log.warning("%s 실패: %s", nm, e)
            st["errors"].append(f"{nm}: {e}")
    # 선물 투자자 (당일만 — 장 마감 후 실행이 전제)
    fi = fut_investor_today()
    if fi.get("date") and fi["date"] in db:
        _merge(db, [fi])
    tds = _trading_days(db)
    # 하루 1콜: run = 최근 5영업일 덮어쓰기, backfill = 최근부터 거꾸로 빈 칸만 days 개
    if redo:
        for d in tds:
            if d >= redo:
                for k in ("pcr_oi", "fut_close"):
                    db[d][k] = None
    if task == "backfill":
        todo = [d for d in reversed(tds) if db[d].get("pcr_oi") is None or db[d].get("prog_nonarb") is None or db[d].get("fut_close") is None][:max(days, 0)]
    else:
        todo = tds[-5:]
    def one(d: str) -> dict:
        dd = date.fromisoformat(d)
        row: dict = {"date": d}
        try:
            if task != "backfill" or db[d].get("prog_nonarb") is None:
                row.update(program_day(dd))
            if task != "backfill" or db[d].get("pcr_oi") is None or db[d].get("fut_close") is None:
                row.update(board_day(dd))
            if dd >= date(2025, 6, 9) and (task != "backfill" or db[d].get("night_vwap") is None):
                row.update(night_krx(dd))
        except Exception as e:  # noqa: BLE001
            log.warning("%s 하루 소스 실패: %s", d, e)
            st["errors"].append(f"{d}: {e}")
        return row

    from concurrent.futures import ThreadPoolExecutor
    done = 0
    fails = 0
    workers = 2 if task == "backfill" else 1
    with ThreadPoolExecutor(workers) as ex:
        for i in range(0, len(todo), 40):
            got = 0
            for row in ex.map(one, todo[i:i + 40]):
                _merge(db, [row])
                done += 1
                got += int(len(row) > 1)
            fails = 0 if got else fails + 1
            if fails:
                log.warning("배치 전부 실패 %d회 — 2분 쉬고 재로그인", fails)
                if fails >= 3:
                    log.warning("연속 실패 — 중단 (다음 실행이 이어서)")
                    break
                time.sleep(120)
                _LAST_RELOGIN[0] = 0
                _relogin()
            save(list(db.values()))
            log.info("하루 소스 %d/%d (%s) %.0fs", done, len(todo), todo[min(i + 39, len(todo) - 1)], time.time() - t0)
            if time.time() - t0 > 80 * 60:   # 워크플로 90분 제한 전에 저장하고 멈춤
                log.warning("시간 제한 — %d/%d 에서 멈춤 (다음 실행이 이어서)", done, len(todo))
                break
    save(list(db.values()))
    rows = sorted(db.values(), key=lambda r: r["date"])
    cover = {}
    for k in COLS[1:]:
        ds = [r["date"] for r in rows if r.get(k) not in (None, "")]
        if ds:
            cover[k] = {"from": ds[0], "to": ds[-1], "n": len(ds)}
    st["n_errors"] = len(st["errors"])
    st["errors"] = st["errors"][:30]
    st.update({"rows": len(rows), "daily_done": done, "daily_todo": len(todo), "secs": round(time.time() - t0),
               "coverage": cover, "asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M")})
    STATUS.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        from . import vkospi   # req-data-4e390b32 — 실패해도 본 적재에 영향 없음
        vkospi.run(days=5 if task == "run" else 30)
    except Exception as e:  # noqa: BLE001
        log.warning("VKOSPI 수집 실패: %s", type(e).__name__)
    log.info("deriv_hist: %d행, 하루소스 %d/%d, %ds", len(rows), done, len(todo), st["secs"])
    return st


# ───────────── 장전 한 줄: 야간선물 ─────────────

def night_futures(today: date | None = None) -> dict:
    """08:50 장전 브리핑용. 직전 야간 세션(전 영업일 18:00 ~ 오늘 06:00) 요약.

    반환 {close, chg_pct, volume, thin, implied_kospi_open, basis_px, src, session}
      close  : 유렉스 시절은 야간 종가, KRX 자체 야간(2025-06~)은 **세션 평균 체결가(VWAP)** — KRX 공개 화면에 야간 종가가 없음
      chg_pct: close ÷ 직전 주간 선물 종가 − 1 (%)
      thin   : 거래량이 최근 20개 야간 세션 중앙값의 50% 미만 또는 2만 계약 미만
      implied_kospi_open: 직전 코스피 종가 × (1 + chg_pct × 기울기). 기울기 = 검증(H8) 회귀값, 없으면 1.0
    없으면 {}.
    """
    today = today or datetime.now(KST).date()
    rows = load()
    past = [r for r in rows if r["date"] < str(today) and r.get("fut_close")]
    if not past:
        return {}
    prev = past[-1]
    n = night_krx(today)
    if not n:
        return {}
    px = n["night_vwap"]
    chg = (px / prev["fut_close"] - 1) * 100
    if abs(chg) > 15:   # 월물 교체·데이터 오류 의심 — 틀린 숫자를 아침에 보내느니 안 보낸다
        log.warning("야간선물 변화율 %.1f%% 비정상 — 생략", chg)
        return {}
    vols = [r["night_vol"] for r in rows[-40:] if r.get("night_vol") and r.get("night_src") == "krx_vwap"][-20:]
    med = sorted(vols)[len(vols) // 2] if vols else None
    thin = (n["night_vol"] < 20000) or (med is not None and n["night_vol"] < 0.5 * med)
    slope = 1.0
    try:
        sj = json.loads((REPORT_DIR / "studies" / "derivs_signals.json").read_text(encoding="utf-8"))
        h8 = next((x for x in sj.get("signals", []) if x.get("id") == "H8"), {})
        if h8.get("grade") in ("A", "B", "C") and h8.get("slope"):
            slope = float(h8["slope"])
    except Exception:  # noqa: BLE001
        pass
    imp = prev["kospi_close"] * (1 + chg / 100 * slope) if prev.get("kospi_close") else None
    return {"close": px, "chg_pct": round(chg, 2), "volume": n["night_vol"], "thin": bool(thin), "vol_median20": med,
            "implied_kospi_open": round(imp, 1) if imp else None, "prev_fut_close": prev["fut_close"], "prev_date": prev["date"],
            "slope": slope, "src": n["night_src"], "session": f"{prev['date']} 18:00 ~ {today} 06:00"}


def night_line(nf: dict) -> str | None:
    """장전 텔레그램 한 줄 (HTML 이스케이프 불필요한 문자만)."""
    if not nf:
        return None
    thin = " (거래 적음)" if nf.get("thin") else ""
    kind = "평균가" if nf.get("src") == "krx_vwap" else "마감"
    tail = f" → 예상 시초가 코스피 {nf['implied_kospi_open']:,.0f} 근처" if nf.get("implied_kospi_open") else ""
    return f"🌙 야간선물 {kind} {nf['chg_pct']:+.1f}%{thin}{tail}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="run", choices=["run", "backfill", "night"])
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--redo", default=None, help="YYYY-MM-DD 이후 보드 값 재계산")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.task == "night":
        nf = night_futures()
        print(json.dumps(nf, ensure_ascii=False), night_line(nf))
        return
    run(a.task, a.days, a.redo)


if __name__ == "__main__":
    main()
