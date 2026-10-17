"""미국 매집(accumulation) 흔적 스캔 — 퀀트(US)+매크로 데스크 (2026-10-17).

미국은 투자자별 일간 수급(외국인·기관 순매수)이 없다. 그래서 '기관 발자국'을 가격·거래량으로 추정한다.
신호 정의는 reports/studies/us_accum.md §0 에 사전등록(결과 보기 전 고정)했고, 여기 숫자를 바꾸면 새 가설이다.

  S1 OBV_DIV   20일 OBV 증가(20일 거래량 합 대비 ≥ +15%) 인데 20일 수익 ≤ 0          (가격↓·거래량 흐름↑ 괴리)
  S2 AD_DIV    종가가 직전 창(t−40..t−21) 최저보다 낮은데 A/D 선은 그 창 최저보다 높음   (저점 낮추기 vs A/D 저점 높이기)
  S3 CMF       Chaikin Money Flow(20) ≥ 0.20                                         (강한 매수 압력)
  S4 UDVOL     50일 상승일 거래량 / 하락일 거래량 ≥ 1.5                                 (IBD 식 U/D 비율)
  S5 BASE_BO   40일 박스(고/저 ≤ 1.30) + 직전 10일 거래량 ≤ 그 앞 50일 평균×0.75(마름) + 박스 상단 돌파 + 거래량 ≥ 50일 평균×1.5
  S6 POCKET    상승일 + 거래량 > 직전 10일 하락일 최대 거래량 + 종가 ≥ 10일선·50일선      (포켓 피벗)
  S7 ACC_DAY   상대거래량(RVOL) ≥ 2 + 종가위치(CLV) ≥ 0.5 + 상승일                        (매집일)
  S8 GAP_VOL   시가 갭 ≥ +3% + RVOL ≥ 2 + 종가 ≥ 시가                                    (거래량 동반 갭상승 유지)
  S9 COMBO     S1~S8 중 같은 날 2개 이상

공통 필터: 종가 ≥ $5, 50일 평균 거래대금 ≥ $5M, 관측 ≥ 61일.
연구(scripts/study_us_accum.py)와 일일 스캔(scan())이 같은 features() 를 쓴다 — 정의가 둘로 갈라지지 않게.

입력(일일)  reports/detail/US/*.json 의 chart(최근 260거래일 OHLCV; 미장 마감 스크리너 06:52 KST 가 갱신)
출력        reports/us_accum.json  {asof, generated_at, source, status(ok|fail), reason, n_scanned, n_hits, hits[], grades{}}
            빈 결과·입력 없음 = status "fail" + reason (조용히 넘기지 않음, STANDARD §3).
실행        python -m screener.us_accum            (.github/workflows/us_accum.yml, 평일 07:37 KST — 네트워크 없음)
영향 범위   새 파일만 씀. 텔레그램·탭·다른 워크플로 변경 없음. 롤백 = git revert(파일 5개).
"""
from __future__ import annotations

import json
import logging
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DETAIL_DIR = ROOT / "reports" / "detail" / "US"
OUT = ROOT / "reports" / "us_accum.json"
STUDY = ROOT / "reports" / "studies" / "us_accum.json"
KST = timezone(timedelta(hours=9))
log = logging.getLogger("us_accum")

SIGNALS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]
NAMES = {
    "S1": "OBV 괴리", "S2": "A/D 괴리", "S3": "CMF≥0.20", "S4": "U/D 거래량≥1.5",
    "S5": "베이스 마름→돌파", "S6": "포켓 피벗", "S7": "매집일(RVOL≥2·CLV≥0.5)", "S8": "거래량 갭상승", "S9": "복합(2개+)",
}
# 사전등록 문턱 (us_accum.md §0) — 바꾸면 새 가설 id
P = {"obv_div": 0.15, "cmf": 0.20, "udv": 1.5, "base_rng": 1.30, "dry": 0.75, "bo_rv": 1.5,
     "rvol": 2.0, "clv": 0.5, "gap": 0.03, "min_px": 5.0, "min_dv": 5e6, "min_obs": 61}


def features(df: pd.DataFrame) -> pd.DataFrame:
    """한 종목 OHLCV(날짜 오름차순, 열 open high low close volume) → 지표·신호(bool) 열을 붙인 프레임.

    모든 창은 t 일 종가까지의 정보만 쓴다(미래 정보 없음). 50일 평균 거래량(vol50)은 t 일을 뺀 직전 50일.
    """
    d = df[["open", "high", "low", "close", "volume"]].astype(float).reset_index(drop=True).copy()
    o, h, l, c, v = (d[k] for k in ("open", "high", "low", "close", "volume"))
    c1 = c.shift(1)
    rng = (h - l)
    clv = ((c - l) - (h - c)) / rng.where(rng > 0)
    d["clv"] = clv.fillna(0.0)
    up, dn = c > c1, c < c1
    d["obv"] = (np.sign(c - c1).fillna(0) * v).cumsum()
    d["ad"] = (d["clv"] * v).cumsum()
    v20 = v.rolling(20).sum()
    d["vol50"] = v.shift(1).rolling(50).mean()
    d["rvol"] = v / d["vol50"]
    d["ret20"] = c / c.shift(20) - 1
    d["obv20"] = (d["obv"] - d["obv"].shift(20)) / v20
    d["cmf20"] = (d["clv"] * v).rolling(20).sum() / v20
    upv = v.where(up, 0.0).rolling(50).sum()
    dnv = v.where(dn, 0.0).rolling(50).sum()
    d["udv50"] = upv / dnv.where(dnv > 0)
    sma10, sma50 = c.rolling(10).mean(), c.rolling(50).mean()
    d["dv50"] = (c * v).shift(1).rolling(50).mean()
    # 괴리 S2: 직전 창 t-40..t-21 의 최저 종가·최저 A/D
    prev_cmin = c.shift(21).rolling(20).min()
    prev_admin = d["ad"].shift(21).rolling(20).min()
    # 베이스 S5
    hh40 = h.shift(1).rolling(40).max()
    ll40 = l.shift(1).rolling(40).min()
    v_recent = v.shift(1).rolling(10).mean()
    v_prior = v.shift(11).rolling(50).mean()
    # 포켓 피벗 S6: 직전 10일 하락일 최대 거래량
    dn_maxv = v.where(dn, 0.0).shift(1).rolling(10).max()

    d["S1"] = (d["obv20"] >= P["obv_div"]) & (d["ret20"] <= 0)
    d["S2"] = (c < prev_cmin) & (d["ad"] > prev_admin)
    d["S3"] = d["cmf20"] >= P["cmf"]
    d["S4"] = d["udv50"] >= P["udv"]
    d["S5"] = ((hh40 / ll40) <= P["base_rng"]) & (v_recent <= P["dry"] * v_prior) & (c > hh40) & (d["rvol"] >= P["bo_rv"])
    d["S6"] = up & (v > dn_maxv) & (c >= sma10) & (c >= sma50)
    d["S7"] = (d["rvol"] >= P["rvol"]) & (d["clv"] >= P["clv"]) & up
    d["S8"] = (o / c1 - 1 >= P["gap"]) & (d["rvol"] >= P["rvol"]) & (c >= o)
    base = SIGNALS[:8]
    d["n_sig"] = d[base].sum(axis=1).astype(int)
    d["S9"] = d["n_sig"] >= 2
    elig = (c >= P["min_px"]) & (d["dv50"] >= P["min_dv"]) & (pd.Series(np.arange(len(d))) >= P["min_obs"] - 1)
    d["elig"] = elig.fillna(False)
    for s in SIGNALS:
        d[s] = d[s].fillna(False).astype(bool) & d["elig"]
    d["n_sig"] = d[base].sum(axis=1).astype(int)
    if "date" in df.columns:
        d.insert(0, "date", df["date"].astype(str).str[:10].values)
    return d


def wilson_lo(k: int, n: int, z: float = 1.96) -> float | None:
    """승률 k/n 의 Wilson 95% 하한. 예: 60/100 → 0.502."""
    if not n:
        return None
    p, z2 = k / n, z * z
    return (p + z2 / (2 * n) - z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / (1 + z2 / n)


def _chart_df(path: Path) -> tuple[pd.DataFrame | None, dict]:
    j = json.loads(path.read_text(encoding="utf-8"))
    ch = j.get("chart") or []
    if len(ch) < P["min_obs"]:
        return None, j
    df = pd.DataFrame([{"date": r.get("t"), "open": r.get("o"), "high": r.get("h"), "low": r.get("l"),
                        "close": r.get("c"), "volume": r.get("v")} for r in ch])
    df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    for k in ("open", "high", "low"):
        df[k] = df[k].fillna(df["close"])
    df["volume"] = df["volume"].fillna(0)
    return df, j


def _grades() -> dict:
    """연구 등급(reports/studies/us_accum.json) — 없으면 빈 dict(스캔은 '등급 미확인'으로 표시)."""
    try:
        g = json.loads(STUDY.read_text(encoding="utf-8")).get("grades") or {}
        return {k: (v.get("grade") if isinstance(v, dict) else v) for k, v in g.items()}
    except Exception:  # noqa: BLE001
        return {}


GRADE_W = {"A": 3, "B": 2, "C": 1}


def scan(detail_dir: Path = DETAIL_DIR, grades: dict | None = None, top: int = 30) -> dict:
    """마지막 거래일 신호. 점수 = Σ(신호 등급 가중 A3·B2·C1, F·검증전 0) — 등급 없으면 신호 개수."""
    grades = _grades() if grades is None else grades
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    out = {"asof": None, "generated_at": now, "source": f"{detail_dir.relative_to(ROOT) if detail_dir.is_relative_to(ROOT) else detail_dir}/*.json chart (260거래일 OHLCV)",
           "status": "fail", "reason": "", "n_scanned": 0, "n_hits": 0, "grades": grades, "names": NAMES,
           "params": P, "doc": "reports/studies/us_accum.md · docs/valuation_notes/2026-10-17_us_accumulation.md",
           "caveat": "가격·거래량 기반 추정치(실제 기관 순매수 아님). 등급 C 이하 신호는 참고용. 매매 지시 아님.",
           "hits": []}
    files = sorted(detail_dir.glob("*.json")) if detail_dir.exists() else []
    if not files:
        out["reason"] = f"입력 없음: {detail_dir} 에 종목 상세 json 0개"
        return out
    rows, asofs, errs, skipped_etf = [], [], 0, 0
    graded = any(GRADE_W.get(g, 0) for g in grades.values())
    for f in files:
        try:
            df, j = _chart_df(f)
        except Exception as e:  # noqa: BLE001
            errs += 1
            log.warning("%s 읽기 실패: %s", f.name, e)
            continue
        if df is None:
            continue
        if _is_etf(j):
            skipped_etf += 1     # 연구 유니버스(개별 종목)와 다름 → 제외
            continue
        feat = features(df)
        last = feat.iloc[-1]
        asofs.append(str(last["date"]))
        out["n_scanned"] += 1
        on = [s for s in SIGNALS if bool(last[s])]
        if not on:
            continue
        score = sum(GRADE_W.get(grades.get(s, ""), 0) for s in on) if graded else len(on)
        rows.append({"symbol": f.stem, "name": j.get("name"), "date": str(last["date"]), "close": round(float(last["close"]), 2),
                     "signals": on, "score": score, "n_sig": int(last["n_sig"]),
                     "rvol": _r(last["rvol"], 2), "cmf20": _r(last["cmf20"], 3), "obv20": _r(last["obv20"], 3),
                     "udv50": _r(last["udv50"], 2), "clv": _r(last["clv"], 2), "ret20": _r(last["ret20"], 3)})
    if not asofs:
        out["reason"] = f"차트 61일 이상 종목 0개 (파일 {len(files)}, 읽기 실패 {errs})"
        return out
    asof = max(asofs)
    out["asof"] = asof
    stale = [r for r in rows if r["date"] != asof]
    rows = [r for r in rows if r["date"] == asof]    # 마지막 거래일이 다른(낡은) 종목은 제외
    rows.sort(key=lambda r: (-r["score"], -r["n_sig"], -(r["cmf20"] or -9)))
    out["n_hits"] = len(rows)
    out["n_etf_skipped"] = skipped_etf
    out["score_basis"] = "등급 가중(A3·B2·C1)" if graded else "신호 개수 — 연구 등급이 전부 F/검증전이라 가중 없음(참고용 관찰 목록)"
    out["n_stale"] = len(stale)
    out["hits"] = rows[:top]
    out["counts"] = {s: sum(s in r["signals"] for r in rows) for s in SIGNALS}
    if rows:
        out["status"] = "ok"
    else:
        out["reason"] = f"{asof} 신호 0건 (스캔 {out['n_scanned']}종목) — 데이터는 있으나 해당 없음"
    return out


def _is_etf(j: dict) -> bool:
    """종목 상세의 market 이 'ETF' 이거나 이름에 'ETF' 단어가 있으면 ETF (예: BND → market 'ETF')."""
    return str(j.get("market") or "").upper() == "ETF" or bool(re.search(r"\bETF\b", j.get("name") or ""))


def _r(x, k):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(x) else round(x, k)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    o = scan()
    OUT.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("us_accum: status=%s asof=%s scanned=%d hits=%d %s", o["status"], o["asof"], o["n_scanned"], o["n_hits"], o["reason"])
    if o["status"] != "ok":
        print(f"::warning::us_accum {o['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
