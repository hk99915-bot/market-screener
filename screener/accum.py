"""국장 외인·기관 매집 스캐너 + 시장 거래대금 (KOSPI·KOSDAQ 전 종목, ETF·ETN·스팩 제외).

비유: 큰손(외국인·기관)이 '조용히 담는' 종목은 가격보다 장부(순매수)에 먼저 흔적이 남는다.
용어: 순매수 = 매수대금 − 매도대금. 매집 강도 = 기간 순매수 ÷ 시가총액(%) — 회사 크기를 지운 값.
      거래대금 대비 = 기간 순매수 ÷ 기간 거래대금(%) — 그 기간 '손바뀜' 중 큰손 몫.

데이터 (Actions 전용 — 샌드박스는 KRX 차단):
  pykrx get_market_cap(d, mkt)                       종가·시총·거래대금 (시장당 1콜)
  pykrx get_market_net_purchases_of_equities(d,d,…)  투자자별 종목 순매수대금 (시장×투자자당 1콜)
  → 하루 10콜(2시장 × [시총 + 외국인·기관합계·연기금·투신]). 일별 저장소 data/flows/kr_inv_YYYY.parquet.
  ETF·ETN 은 KRX '주식' 조회에 원래 안 들어오지만, 이름 규칙으로 한 번 더 거른다 — ETF 의 '기관'은 대부분 LP(유동성공급자)가
  개인 매매를 받아주는 거울이라 매집 신호가 아니다.

단위(저장소): close 원 · mcap 억원 · tv/f/i/pen/trust 백만원(int32). 산출물(reports/accum.json)은 억원·%.

  python -m screener.accum daily   [--budget-min 12]   # 최근 결측일 채움 → 스캔 → reports/accum.json
  python -m screener.accum backfill --since 2022-01-01 --budget-min 50   # 과거 거꾸로 채움(재개 가능)
  python -m screener.accum scan                       # 저장소만으로 스캔(네트워크 없음)
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("accum")
ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "flows"
OUT = ROOT / "reports" / "accum.json"
ARCH = ROOT / "reports" / "archive" / "accum"
KST = timezone(timedelta(hours=9))
INV = {"f": "외국인", "i": "기관합계", "pen": "연기금", "trust": "투신"}
MKTS = {"KOSPI": "K", "KOSDAQ": "Q"}
INT_COLS = ["close", "mcap", "tv", "f", "i", "pen", "trust"]
COLS = ["date", "code", "mkt"] + INT_COLS
# 이름 규칙: ETF 운용사 브랜드·ETN·스팩. KRX 주식 조회에 원래 거의 없지만 방어적으로.
EXCL = re.compile(r"스팩|SPAC|ETN|^(?:KODEX|TIGER|KBSTAR|RISE|ACE|SOL|HANARO|ARIRANG|KOSEF|PLUS|KIWOOM|TIMEFOLIO|WOORI|1Q|BNK|FOCUS|TRUSTON|마이다스|에셋플러스|UNICORN|HK|파워|마이티|VITA|DAISHIN343|ITF|KoAct)\b")
MIN_MCAP = 300        # 억원 — 이보다 작은 종목은 순매수 몇 억에도 비율이 튄다
MIN_TV20 = 100        # 백만원/일(=1억) 20일 평균 거래대금 하한
DIV_RET = 0.02        # 매집 후보: 20일 수익률 ≤ +2% (가격은 안 갔는데 큰손이 담음)
TOP_Q = 0.90          # 매집 강도 상위 10%


# ───────────── 저장소 ─────────────

def _year_path(y: int, root: Path = STORE) -> Path:
    return root / f"kr_inv_{y}.parquet"


def load_store(start: str | None = None, root: Path = STORE) -> pd.DataFrame:
    fs = sorted(root.glob("kr_inv_*.parquet"))
    if start:
        y0 = int(start[:4])
        fs = [f for f in fs if int(f.stem[-4:]) >= y0]
    if not fs:
        return pd.DataFrame(columns=COLS)
    df = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    return df.sort_values(["code", "date"]).reset_index(drop=True)


def stored_dates(root: Path = STORE) -> set[str]:
    out: set[str] = set()
    for f in root.glob("kr_inv_*.parquet"):
        try:
            d = pd.read_parquet(f, columns=["date"])["date"]
            out |= set(pd.to_datetime(d).dt.strftime("%Y-%m-%d").unique())
        except Exception as e:  # noqa: BLE001
            log.warning("저장소 읽기 실패 %s: %s", f.name, e)
    return out


def save_days(frames: list[pd.DataFrame], root: Path = STORE) -> int:
    """하루치 프레임들을 연도 파일에 병합(같은 날짜는 교체). 쓴 행 수."""
    frames = [f for f in frames if f is not None and len(f)]
    if not frames:
        return 0
    root.mkdir(parents=True, exist_ok=True)
    new = pd.concat(frames, ignore_index=True)
    new["date"] = pd.to_datetime(new["date"])
    n = 0
    for y, g in new.groupby(new["date"].dt.year):
        p = _year_path(int(y), root)
        if p.exists():
            old = pd.read_parquet(p)
            old["date"] = pd.to_datetime(old["date"])
            old = old[~old["date"].isin(g["date"].unique())]
            g = pd.concat([old, g], ignore_index=True)
        g = _typed(g).sort_values(["date", "code"]).reset_index(drop=True)
        g.to_parquet(p, index=False, compression="zstd")
        n += len(g)
    return n


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["mkt"] = df["mkt"].astype(str)
    for c in INT_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).round().clip(-2**31 + 1, 2**31 - 1).astype("int32")
    return df[COLS]


def load_names(root: Path = STORE) -> dict[str, str]:
    try:
        return json.loads((root / "names.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ───────────── 수집 (pykrx, Actions) ─────────────

def trading_days(start: date, end: date) -> list[date]:
    """KOSPI 지수 일봉 날짜 = 거래일. 실패 시 data/hist 지수 파일 + 평일로 폴백."""
    try:
        from pykrx import stock  # type: ignore
        df = stock.get_index_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "1001")
        if df is not None and len(df):
            return [d.date() for d in df.index]
    except Exception as e:  # noqa: BLE001
        log.warning("거래일 조회 실패(폴백): %s", e)
    try:
        ix = pd.read_parquet(ROOT / "data" / "hist" / "kr_index_daily.parquet")
        ds = sorted({pd.Timestamp(x).date() for x in ix[ix["symbol"] == "KOSPI"]["date"]})
        ds = [d for d in ds if start <= d <= end]
        if ds:
            return ds
    except Exception:  # noqa: BLE001
        pass
    return [d.date() for d in pd.bdate_range(start, end)]


def _col(df: pd.DataFrame, key: str) -> str | None:
    cs = [c for c in df.columns if key in str(c)]
    return cs[0] if cs else None


def _relogin() -> None:
    """KRX 세션 재로그인 — 같은 KRX_ID 로 다른 잡이 로그인하면 기존 세션이 끊겨 HTML(비JSON)이 온다(10/17 첫 실행)."""
    import os
    try:
        from pykrx.website.comm.auth import get_auth_session  # type: ignore
        s = get_auth_session()
        if s is not None and os.environ.get("KRX_ID"):
            ok = s.refresh(os.environ["KRX_ID"], os.environ.get("KRX_PW", ""))
            log.info("KRX 재로그인 %s", "성공" if ok else "실패")
    except Exception as e:  # noqa: BLE001
        log.warning("KRX 재로그인 오류: %s", str(e)[:120])


def _call(fn, *a, tries: int = 3, **k):
    """pykrx 호출 + 빈/비JSON 응답 재시도(재로그인). 마지막까지 실패하면 None."""
    for t in range(tries):
        try:
            r = fn(*a, **k)
            time.sleep(0.25)          # KRX 차단 방지
            if r is not None and not r.empty:
                return r
        except Exception as e:  # noqa: BLE001
            log.warning("%s%s 실패(%d): %s", fn.__name__, a, t + 1, str(e)[:120])
        time.sleep(2 + 3 * t)
        _relogin()
    return None


def fetch_day(d: date, names: dict | None = None) -> pd.DataFrame | None:
    """하루 전 종목(KOSPI·KOSDAQ). 시총 조회가 비면 None(휴장·미집계). 투자자 조회 실패는 0 이 아니라 NaN→행 제외."""
    from pykrx import stock  # type: ignore
    ymd = d.strftime("%Y%m%d")
    parts = []
    for mkt, tag in MKTS.items():
        cap = _call(stock.get_market_cap, ymd, market=mkt)
        if cap is None or cap.empty:
            return None
        c_close, c_cap, c_tv = _col(cap, "종가"), _col(cap, "시가총액"), _col(cap, "거래대금")
        if not (c_close and c_cap and c_tv) or float(cap[c_tv].sum()) <= 0:
            return None
        g = pd.DataFrame({"code": cap.index.astype(str), "close": cap[c_close].astype(float).values,
                          "mcap": cap[c_cap].astype(float).values / 1e8, "tv": cap[c_tv].astype(float).values / 1e6})
        g["mkt"] = tag
        for k, inv in INV.items():
            nb = _call(stock.get_market_net_purchases_of_equities, ymd, ymd, mkt, inv)
            if nb is None or nb.empty or _col(nb, "순매수거래대금") is None:
                if k in ("f", "i"):
                    log.warning("%s %s %s 비어 있음 → 그날 시장 제외", ymd, mkt, inv)
                    g = g.iloc[0:0]
                    break
                g[k] = 0.0      # 연기금·투신은 보조 — 없으면 0, 로그만
                continue
            s = nb[_col(nb, "순매수거래대금")].astype(float) / 1e6
            s.index = s.index.astype(str)
            g[k] = g["code"].map(s).fillna(0.0).values
            if names is not None and _col(nb, "종목명"):
                for t, nm in nb[_col(nb, "종목명")].items():
                    names[str(t)] = str(nm)
        parts.append(g)
    if not parts or not sum(len(p) for p in parts):
        return None
    out = pd.concat(parts, ignore_index=True)
    out["date"] = d
    for k in INV:
        if k not in out:
            out[k] = 0.0
    return _typed(out)


def fill(days: list[date], budget_min: float, root: Path = STORE, flush_every: int = 20) -> dict:
    """주어진 거래일(순서대로)을 시간 예산 안에서 채운다. 반환: 채운 날·건너뛴 날."""
    t0 = time.time()
    names = load_names(root)
    buf, done, skipped, fails = [], [], [], 0
    for d in days:
        if (time.time() - t0) / 60 > budget_min:
            log.info("시간 예산 %.0f분 소진 — 남은 %d일은 다음 실행", budget_min, len(days) - len(done) - len(skipped))
            break
        try:
            f = fetch_day(d, names)
        except Exception as e:  # noqa: BLE001
            log.warning("%s 수집 실패: %s", d, str(e)[:200])
            f = None
        if f is None:
            skipped.append(str(d))
            fails += 1
            if fails >= 5:
                log.warning("연속 %d일 수집 실패 — KRX 차단/세션 문제로 보고 중단 (마지막 %s)", fails, d)
                break
            continue
        fails = 0
        buf.append(f)
        done.append(str(d))
        if len(buf) >= flush_every:
            save_days(buf, root)
            buf = []
            log.info("저장 %d일 (최근 %s, %.1f분)", len(done), d, (time.time() - t0) / 60)
    save_days(buf, root)
    if names:
        root.mkdir(parents=True, exist_ok=True)
        (root / "names.json").write_text(json.dumps(names, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {"filled": done, "skipped": skipped, "min": round((time.time() - t0) / 60, 1)}


# ───────────── 지표 ─────────────

def add_returns(df: pd.DataFrame) -> pd.DataFrame:
    """종목별 일간수익 r (분할 보정): 상장주식수(=시총/종가)가 1.5배 이상/0.67배 이하로 바뀐 날은 시총 비율, 아니면 종가 비율.
    |r|>0.45 이고 주식수 변화가 없으면 데이터 오류로 보고 0."""
    df = df.sort_values(["code", "date"]).copy()
    c = df["close"].astype(float).replace(0, np.nan)
    sh = df["mcap"].astype(float) / c
    g = df.groupby("code", sort=False)
    pc, psh, pm = g["close"].shift(1).astype(float), sh.groupby(df["code"]).shift(1), g["mcap"].shift(1).astype(float)
    r_px = c / pc - 1
    ratio = sh / psh
    r_cap = df["mcap"].astype(float) / pm - 1
    split = (ratio >= 1.5) | (ratio <= 1 / 1.5)
    r = np.where(split, r_cap, r_px)
    r = np.where((~split) & (np.abs(r) > 0.45), 0.0, r)
    df["r"] = pd.Series(r, index=df.index).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["lv"] = df.groupby("code", sort=False)["r"].transform(lambda s: np.log1p(s).cumsum())   # 누적 로그가격
    return df


def _streak(x: np.ndarray) -> int:
    """끝에서부터 연속 양수 일수."""
    n = 0
    for v in x[::-1]:
        if v > 0:
            n += 1
        else:
            break
    return n


def features(df: pd.DataFrame) -> pd.DataFrame:
    """종목×날짜 롤링 지표 (연구와 스캔이 같은 정의를 쓴다). df 는 add_returns 결과."""
    df = df.sort_values(["code", "date"]).copy()
    df["fi"] = df["f"].astype(float) + df["i"].astype(float)
    g = df.groupby("code", sort=False)
    for w in (5, 20, 60):
        for k in ("f", "i", "fi", "pen", "trust", "tv"):
            if k in ("pen", "trust") and w != 20:
                continue
            df[f"{k}{w}"] = g[k].transform(lambda s, w=w: s.astype(float).rolling(w, min_periods=w).sum())
        df[f"ret{w}"] = np.expm1(df["lv"] - g["lv"].shift(w))
    mc = df["mcap"].astype(float).replace(0, np.nan) * 100      # 억원 → 백만원
    for w in (5, 20, 60):
        df[f"fi{w}_cap"] = df[f"fi{w}"] / mc * 100                 # %
        df[f"fi{w}_tv"] = df[f"fi{w}"] / df[f"tv{w}"].replace(0, np.nan) * 100
        df[f"f{w}_cap"] = df[f"f{w}"] / mc * 100
        df[f"i{w}_cap"] = df[f"i{w}"] / mc * 100
    df["pen20_cap"] = df["pen20"] / mc * 100
    df["trust20_cap"] = df["trust20"] / mc * 100
    for k in ("f", "i"):
        pos = (df[k] > 0).astype(int)
        grp = (pos != pos.groupby(df["code"]).shift(1)).cumsum()
        df[f"st_{k}"] = pos.groupby([df["code"], grp]).cumsum() * pos
    both = ((df["f"] > 0) & (df["i"] > 0)).astype(int)
    grp = (both != both.groupby(df["code"]).shift(1)).cumsum()
    df["st_fi"] = both.groupby([df["code"], grp]).cumsum() * both
    df["tv_avg5"] = g["tv"].transform(lambda s: s.astype(float).rolling(5, min_periods=5).mean())
    df["tv_avg20"] = g["tv"].transform(lambda s: s.astype(float).rolling(20, min_periods=5).mean())   # 적격 판정용(이력 짧아도)
    prior60 = g["tv"].transform(lambda s: s.astype(float).shift(5).rolling(60, min_periods=40).mean())
    df["tv_x"] = df["tv_avg5"] / prior60                                              # 최근 5일 ÷ 그 전 60일
    a = g["tv"].transform(lambda s: s.astype(float).shift(5).rolling(20, min_periods=15).mean())
    b = g["tv"].transform(lambda s: s.astype(float).shift(25).rolling(60, min_periods=40).mean())
    df["tv_dry"] = a / b                                                              # 6~25일 전 ÷ 26~85일 전
    return df


def eligible(df: pd.DataFrame, names: dict | None = None) -> pd.Series:
    nm = df["code"].map(names or {}).fillna("")
    return (df["mcap"] >= MIN_MCAP) & (df["tv_avg20"] >= MIN_TV20) & ~nm.str.contains(EXCL)


def flags(df: pd.DataFrame, elig: pd.Series) -> pd.DataFrame:
    """날짜별 단면 문턱(상위 10%)으로 신호. 연구(scripts/study_accum.py)와 같은 정의."""
    df = df.copy()
    df["elig"] = elig
    for col in ("fi20_cap", "fi60_cap", "pen20_cap"):
        q = df[df["elig"]].groupby("date")[col].quantile(TOP_Q)
        thr = df["date"].map(q)
        df[f"top_{col}"] = df["elig"] & (df[col] > 0) & (df[col] >= thr)
    df["sig_accum"] = df["top_fi20_cap"]
    df["sig_diverge"] = df["top_fi20_cap"] & (df["ret20"] <= DIV_RET)
    df["sig_fstreak"] = df["elig"] & (df["st_f"] >= 5)
    df["sig_istreak"] = df["elig"] & (df["st_i"] >= 5)
    df["sig_both3"] = df["elig"] & (df["st_fi"] >= 3)
    df["sig_pen"] = df["top_pen20_cap"]
    df["sig_dryexp"] = df["elig"] & (df["tv_dry"] <= 0.7) & (df["tv_x"] >= 1.5) & (df["fi5"] > 0)
    df["sig_accum60"] = df["top_fi60_cap"]
    return df


SIGNALS = {
    "sig_accum": "외인+기관 20일 순매수/시총 상위10%",
    "sig_diverge": "위 + 20일 수익률 ≤ +2% (가격 정체 속 매집)",
    "sig_fstreak": "외국인 5일+ 연속 순매수",
    "sig_istreak": "기관 5일+ 연속 순매수",
    "sig_both3": "외인·기관 같은 날 동반 순매수 3일+ 연속",
    "sig_pen": "연기금 20일 순매수/시총 상위10%",
    "sig_dryexp": "거래대금 마름(6~25일 전 ≤ 0.7×그 전 60일) 뒤 확대(최근5일 ≥ 1.5×) + 외인·기관 5일 순매수>0",
    "sig_accum60": "외인+기관 60일 순매수/시총 상위10%",
}


# ───────────── 스캔 ─────────────

def _r(x, n=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, n)


def market_agg(df: pd.DataFrame, days: int = 60) -> dict:
    """시장 거래대금·투자자 순매수 합계 (억원). 저장소에 들어온 전 종목 기준 — ETF 제외 주식만."""
    out = {}
    for tag, name in (("K", "KOSPI"), ("Q", "KOSDAQ")):
        g = df[df["mkt"] == tag].groupby("date")[["tv", "f", "i", "pen", "trust"]].sum().sort_index() / 100   # 백만원→억원
        if g.empty:
            continue
        tv = g["tv"]
        ser = [{"d": d.strftime("%Y-%m-%d"), "tv": _r(r.tv, 0), "f": _r(r.f, 0), "i": _r(r.i, 0)}
               for d, r in g.tail(days).iterrows()]
        out[name] = {
            "tv_last": _r(tv.iloc[-1], 0), "tv5": _r(tv.tail(5).mean(), 0), "tv20": _r(tv.tail(20).mean(), 0),
            "tv60": _r(tv.tail(60).mean(), 0) if len(tv) >= 60 else None,
            "tv5_vs_60": _r(tv.tail(5).mean() / tv.tail(60).mean(), 2) if len(tv) >= 60 else None,
            "f5": _r(g["f"].tail(5).sum(), 0), "f20": _r(g["f"].tail(20).sum(), 0),
            "i5": _r(g["i"].tail(5).sum(), 0), "i20": _r(g["i"].tail(20).sum(), 0),
            "pen20": _r(g["pen"].tail(20).sum(), 0), "trust20": _r(g["trust"].tail(20).sum(), 0),
            "f60": _r(g["f"].tail(60).sum(), 0) if len(g) >= 60 else None,
            "i60": _r(g["i"].tail(60).sum(), 0) if len(g) >= 60 else None,
            "series": ser,
        }
    return out


def _row(x: pd.Series, names: dict) -> dict:
    return {"code": x["code"], "name": names.get(x["code"], x["code"]), "mkt": "KOSPI" if x["mkt"] == "K" else "KOSDAQ",
            "mcap": _r(x["mcap"], 0), "close": int(x["close"]),
            "f5": _r(x["f5"] / 100, 1), "i5": _r(x["i5"] / 100, 1), "f20": _r(x["f20"] / 100, 1), "i20": _r(x["i20"] / 100, 1),
            "f60": _r(x.get("f60", np.nan) / 100, 1), "i60": _r(x.get("i60", np.nan) / 100, 1),
            "pen20": _r(x["pen20"] / 100, 1), "trust20": _r(x["trust20"] / 100, 1),
            "fi5_cap": _r(x["fi5_cap"], 3), "fi20_cap": _r(x["fi20_cap"], 3), "fi60_cap": _r(x.get("fi60_cap"), 3),
            "fi20_tv": _r(x["fi20_tv"], 1), "st_f": int(x["st_f"]), "st_i": int(x["st_i"]), "st_fi": int(x["st_fi"]),
            "ret5": _r(x["ret5"], 4), "ret20": _r(x["ret20"], 4), "ret60": _r(x.get("ret60"), 4),
            "tv_x": _r(x["tv_x"], 2), "tv_dry": _r(x["tv_dry"], 2),
            "tags": [k[4:] for k in SIGNALS if bool(x.get(k))]}


def scan(df: pd.DataFrame, names: dict, top_n: int = 30, today: date | None = None) -> dict:
    now = datetime.now(KST)
    base = {"generated_at": now.isoformat(timespec="minutes"), "source": "pykrx/KRX (data/flows/kr_inv_*.parquet)",
            "unit": "금액 억원 · 비율 % · 수익률 소수", "universe": "KOSPI+KOSDAQ 주식 (ETF·ETN·스팩 제외)",
            "filters": {"min_mcap_eok": MIN_MCAP, "min_tv20_eok": MIN_TV20 / 100, "top_q": TOP_Q, "div_ret20_max": DIV_RET},
            "signals_doc": SIGNALS,
            "caveat": "검증전 신호 — 근거 등급은 reports/studies/accum_signals.json. ETF 기관=LP 거울이라 제외. 확정치는 KRX 18시 이후."}
    if df is None or df.empty:
        return {**base, "asof": None, "status": "fail", "reason": "저장소 비어 있음(data/flows) — 수집 실패 또는 미백필", "n": 0}
    days = sorted(df["date"].unique())
    asof = pd.Timestamp(days[-1])
    hist_days = len(days)
    # 스캔은 최근 ~100거래일만 있으면 된다
    keep = set(days[-100:])
    d = features(add_returns(df[df["date"].isin(keep)]))
    d = flags(d, eligible(d, names))
    last = d[d["date"] == asof]
    el = last[last["elig"]]
    if el.empty:
        return {**base, "asof": asof.strftime("%Y-%m-%d"), "status": "fail", "reason": "적격 종목 0 (필터 후)", "n": 0,
                "history_days": hist_days}
    status, reason = "ok", ""
    if hist_days < 60:
        status, reason = "partial", f"이력 {hist_days}거래일 < 60 — 60일 지표·거래대금 마름 지표 비어 있음"
    t = today or now.date()
    if (t - asof.date()).days > 5:
        status, reason = "stale", f"마지막 데이터 {asof.date()} — {(t - asof.date()).days}일 경과"
    # 점수: 20일 매집 강도 50% + 60일 30% + 거래대금 대비 20% (단면 백분위)
    sc = (0.5 * el["fi20_cap"].rank(pct=True) + 0.3 * el["fi60_cap"].rank(pct=True).fillna(0.5)
          + 0.2 * el["fi20_tv"].rank(pct=True))
    el = el.assign(score=sc).sort_values("score", ascending=False)

    def top(frame, n=top_n):
        return [{**_row(x, names), "score": _r(x["score"], 3)} for _, x in frame.head(n).iterrows()]

    out = {**base, "asof": asof.strftime("%Y-%m-%d"), "status": status, "reason": reason, "history_days": hist_days,
           "n": int(len(el)), "n_all": int(len(last)),
           "counts": {k[4:]: int(el[k].sum()) for k in SIGNALS},
           "top": {
               "accum": top(el[el["sig_accum"]]),
               "diverge": top(el[el["sig_diverge"]].sort_values("fi20_cap", ascending=False)),
               "foreign": top(el.sort_values("f20_cap", ascending=False)),
               "inst": top(el.sort_values("i20_cap", ascending=False)),
               "pension": top(el[el["pen20"] > 0].sort_values("pen20_cap", ascending=False), 15),
               "streak": top(el[el["st_fi"] >= 3].sort_values(["st_fi", "fi20_cap"], ascending=False), 20),
               "dryexp": top(el[el["sig_dryexp"]].sort_values("fi5_cap", ascending=False), 20),
               "distrib": top(el.sort_values("fi20_cap", ascending=True), 15),
           },
           "market": market_agg(df[df["date"].isin(set(days[-130:]))]),
           }
    return out


def archive(out: dict) -> None:
    if not out.get("asof"):
        return
    try:
        ARCH.mkdir(parents=True, exist_ok=True)
        # 화면용 전체본: getArchAt('accum','latest') — Code.gs·build_pages 에 전용 getter 를 넣기 전 임시 경로(공유 파일 잠금 중)
        (ARCH / "latest.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
        slim = {k: out[k] for k in ("asof", "generated_at", "status", "n", "counts") if k in out}
        slim["top"] = {k: [{"code": r["code"], "name": r["name"], "fi20_cap": r["fi20_cap"], "ret20": r["ret20"]}
                           for r in v[:15]] for k, v in (out.get("top") or {}).items()}
        (ARCH / f"{out['asof']}.json").write_text(json.dumps(slim, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        idx = sorted({p.stem for p in ARCH.glob("20*.json")}, reverse=True)
        (ARCH / "_index.json").write_text(json.dumps({"days": [{"id": x, "date": x} for x in idx]}, ensure_ascii=False),
                                          encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("보관 실패: %s", e)


def write(out: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    archive(out)
    log.info("accum.json: status=%s asof=%s n=%s %s", out.get("status"), out.get("asof"), out.get("n"), out.get("reason", ""))


def run_scan(fetch_log: dict | None = None) -> dict:
    df = load_store(start=(date.today() - timedelta(days=200)).isoformat())
    out = scan(df, load_names())
    if fetch_log is not None:
        out["fetch"] = fetch_log
    write(out)
    return out


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["daily", "backfill", "scan"])
    ap.add_argument("--since", default="2022-01-01")
    ap.add_argument("--budget-min", type=float, default=12)
    ap.add_argument("--lookback", type=int, default=150, help="daily: 최근 몇 달력일의 결측을 채우나")
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        out = run_scan()
        return 0 if out["status"] != "fail" else 1
    have = stored_dates()
    end = datetime.now(KST).date()
    if a.cmd == "daily":
        tds = trading_days(end - timedelta(days=a.lookback), end)
        miss = [d for d in reversed(tds) if str(d) not in have]          # 최신부터
        log.info("최근 %d일 중 결측 %d일", len(tds), len(miss))
        res = fill(miss, a.budget_min)
        out = run_scan({k: (v if k == "min" else len(v)) for k, v in res.items()} | {"skipped_days": res["skipped"][:10]})
        return 0 if out["status"] != "fail" else 1
    tds = trading_days(date.fromisoformat(a.since), end)
    miss = [d for d in reversed(tds) if str(d) not in have]
    log.info("백필 대상 %d일 (%s~)", len(miss), a.since)
    res = fill(miss, a.budget_min)
    log.info("백필: 채움 %d · 건너뜀 %d · %.1f분", len(res["filled"]), len(res["skipped"]), res["min"])
    run_scan({k: (v if k == "min" else len(v)) for k, v in res.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
