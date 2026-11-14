"""가설 DART 영업이익·순이익 괴리 필터 — 사전등록 백테스트 (연구 전용, 매매 지시 아님).

python3 scripts/study_op_ni_divergence.py   → reports/studies/2026-11-14_op_ni_divergence.json

## §0 사전등록 (결과 보기 전에 이 파일을 커밋한다)
- 주제: fundamental_divergence (현재 시도 N 0 — 같은 질문의 선행 연구 없음. 유사 주제 earnings_yoy 는
  lab_p1 '실적 둔화(영업이익 YoY≤0)+60일선 위' 로 질문이 다르다: 거기선 영업이익만 보고 이익 괴리를 안 본다.
  이 연구 m=2 추가. kb:quant#30)
- 데이터: `data/fin/multi.parquet` (DART 주요계정 2,517종목 2020~2026, 분기 단독값 복원)
          `data/fin/full.parquet` (전체재무제표 504종목 2023~2026 — 영업외손익 금융/기타 분해에만 사용)
          `data/hist/kr_YYYY.parquet` + `data/kr_prices.parquet` (분할 조정 일봉)
- 단위: 모든 재무값은 **분기 단독값(3개월)**. 1~3분기는 DART `amount`, 4분기는 `연간 − 3분기누적`.
- 시점(전방 누수 차단): 분기 보고서 공개 가정일 = **법정 제출기한**(1Q 5/15 · 반기 8/14 · 3Q 11/14 ·
  사업보고서 다음해 3/31). t = 그 기한 이후 첫 거래일. 신호는 t 종가까지의 정보로만 만들고
  **진입 = t 다음 거래일 종가**(t 시점의 보고서가 이미 공개됐다고 볼 수 있는 가장 이른 체결 시점).
- 지표: m_op = 영업이익/매출액, m_ni = 순이익/매출액, m_nonop = (법인세차감전순이익 − 영업이익)/매출액.
        d_op·d_ni·d_nonop = 전년동기(t−4분기) 대비 변화. r20 = t 종가 기준 최근 20거래일 수익률.
- 가설 m=2, α=0.05/2=0.025 (단측). 성과 = 진입 종가 → 20거래일 뒤 종가의 **초과수익**
  (같은 창의 DART 패널 전 종목 동일가중 평균을 뺀 값).
  H1 (영업외 일회성 미스 역추세): m_op(t)>0 · d_op ≥ 0 · d_ni ≤ −2%p · r20 ≤ −5% 인 종목의
      20일 초과수익이 같은 날짜 비사건 종목보다 **크다**
  H2 (자본배분·영업외 평가손 경고): m_op(t)>0 · d_nonop ≤ −3%p · |영업외손실|/영업이익 ≥ 0.5 인 종목의
      20일 초과수익이 같은 날짜 비사건 종목보다 **작다**
- 표본 필터: 매출액>0, 전년동기 같은 분기 값 존재, 진입일 20일 평균 거래대금(원시 종가×거래량) ≥ 1억원
        (거래 불가능한 초소형주 제외 — 실계좌 적용 가능성 기준. 문턱은 결과를 보기 전에 고정)
- 분할: IS = 진입일 ≤ 2023-12-31 / OOS ≥ 2024-01-01
- 등급: scripts/study_rule_audit.py 와 같은 규칙 —
        A=Bonferroni 통과 + IS·OOS 같은 방향 · B=Bonferroni 통과, 하위 구간 방향 불일치
        C=방향만(보정 전 p<0.10) · F=현행과 구별 안 됨 · 검증전=표본 부족(사건<10 또는 IS·OOS 한쪽<3)
- 탐색(등급 대상 아님, `exploratory`): 지평 5·60일, 낙폭 문턱 −3%·−8%, 순이익률 문턱 −3%p·−5%p,
        영업외손실/영업이익 문턱 1.0, 영업외손익의 금융/기타 분해(full 패널, 서술).
        **결과를 본 뒤 주 가설·문턱을 바꾸지 않는다.**
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from screener import earnings_quality as eq  # noqa: E402
from screener import prices as krpx  # noqa: E402

MULTI = ROOT / "data" / "fin" / "multi.parquet"
FULL = ROOT / "data" / "fin" / "full.parquet"
OUT = ROOT / "reports" / "studies" / "2026-11-14_op_ni_divergence.json"

M = 2
ALPHA = 0.05 / M
IS_END = "2023-12-31"
OOS_START = "2024-01-01"
HORIZON = 20
DROP_20 = -0.05
D_NI_MAX = -0.02
D_NONOP_MAX = -0.03
SHARE_MIN = 0.5
MIN_TURNOVER = 1e8          # 20일 평균 거래대금 하한(원) — 초소형·거래정지 종목 제외

# 계정명 → 지표 키. 위에서부터 우선(같은 키에 여러 이름이 오면 먼저 것).
ACC = {"매출액": "rev", "수익(매출액)": "rev", "영업수익": "rev",
       "영업이익": "op", "영업이익(손실)": "op",
       "당기순이익(손실)": "ni", "당기순이익": "ni", "분기순이익": "ni", "분기순이익(손실)": "ni",
       "반기순이익": "ni", "반기순이익(손실)": "ni",
       "법인세차감전순이익": "pt", "법인세차감전순이익(손실)": "pt", "법인세비용차감전순이익(손실)": "pt"}
REPRT_Q = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}


# ───────────── 재무 패널 ─────────────
def load_panel(path: Path = MULTI) -> pd.DataFrame:
    """DART 주요계정 → (code, year, q) 당 분기 단독값 wide. [code,year,q,avail,rev,op,ni,pt]"""
    m = pl.read_parquet(path)
    m = m.filter(pl.col("account").is_in(list(ACC)))
    rank = {k: i for i, k in enumerate(ACC)}
    m = (m.with_columns(pl.col("account").replace_strict(ACC, return_dtype=pl.Utf8).alias("key"),
                        pl.col("account").replace_strict(rank, return_dtype=pl.Int32).alias("arank"),
                        pl.col("reprt").replace_strict(REPRT_Q, return_dtype=pl.Int32).alias("q"),
                        pl.when(pl.col("fs_div") == "CFS").then(0).otherwise(1).alias("fprio"))
           .sort(["fprio", "arank"]))
    g = (m.group_by(["code", "year", "q", "key"], maintain_order=True)
          .agg(pl.col("amount").first(), pl.col("add_amount").first()))
    panel = None
    for key in ("rev", "op", "ni", "pt"):
        d = (g.filter(pl.col("key") == key).sort(["code", "year", "q"])
              .with_columns(pl.when(pl.col("q") == 1).then(pl.col("amount"))
                              .when(pl.col("q").is_in([2, 3])).then(pl.col("add_amount"))
                              .otherwise(pl.col("amount")).alias("cum")))
        d = d.with_columns(pl.col("cum").shift(1).over(["code", "year"]).alias("prev_cum"),
                           pl.col("q").shift(1).over(["code", "year"]).alias("prev_q"))
        d = d.with_columns(pl.when(pl.col("prev_q") != pl.col("q") - 1).then(None)
                             .otherwise(pl.col("prev_cum")).alias("prev_cum"))
        vals, srcs = [], []
        for r in d.select(["q", "amount", "add_amount", "prev_cum"]).iter_rows(named=True):
            v, s = eq.standalone_quarter(r["q"], r["amount"], r["add_amount"], r["prev_cum"])
            vals.append(v)
            srcs.append(s)
        part = d.select(["code", "year", "q"]).with_columns(
            pl.Series(key, vals, dtype=pl.Float64), pl.Series(f"src_{key}", srcs, dtype=pl.Utf8))
        panel = part if panel is None else panel.join(part, on=["code", "year", "q"], how="full", coalesce=True)
    panel = panel.with_columns(
        pl.Series("avail", [eq.report_due(y, q) for y, q in zip(panel["year"], panel["q"])], dtype=pl.Date))
    return panel.sort(["code", "year", "q"]).to_pandas()


def add_signals(panel: pd.DataFrame) -> pd.DataFrame:
    """전년동기 스냅샷 대비 이익률 변화 + 가설 1·2 판정(모듈 함수) + 탐색용 문턱 변형 플래그."""
    snap = {}
    for r in panel.itertuples(index=False):
        snap[(r.code, r.year, r.q)] = eq.snapshot(r.rev, r.op, r.ni, r.pt)
    cols = {k: [] for k in ("m_op", "d_op", "d_ni", "d_nonop", "nonop_share",
                            "h1", "h2", "h1_dni3", "h1_dni1", "h2_share1", "h2_dn5", "h1_reason", "h2_reason")}
    for r in panel.itertuples(index=False):
        py, pq = eq.prev_period(r.year, r.q)
        now, prv = snap[(r.code, r.year, r.q)], snap.get((r.code, py, pq))
        if not prv:
            for k in cols:
                cols[k].append(False if k.startswith("h") and "_" not in k[2:] else (False if k in ("h1_dni3", "h1_dni1", "h2_share1", "h2_dn5") else None))
            cols["h1_reason"].append("전년동기 없음"); cols["h2_reason"].append("전년동기 없음")
            continue
        h1 = eq.divergence(now, prv, d_ni_max=D_NI_MAX)
        h2 = eq.warning(now, prv, d_nonop_max=D_NONOP_MAX, share_min=SHARE_MIN)
        cols["m_op"].append(now["m_op"])
        cols["d_op"].append(h1["d_op"]); cols["d_ni"].append(h1["d_ni"]); cols["d_nonop"].append(h2["d_nonop"])
        cols["nonop_share"].append(h2["share"])
        cols["h1"].append(h1["is_event"]); cols["h2"].append(h2["warn"])
        cols["h1_reason"].append(h1["reason"]); cols["h2_reason"].append(h2["reason"])
        cols["h1_dni3"].append(eq.divergence(now, prv, d_ni_max=-0.03)["is_event"])
        cols["h1_dni1"].append(eq.divergence(now, prv, d_ni_max=-0.01)["is_event"])
        cols["h2_share1"].append(eq.warning(now, prv, d_nonop_max=D_NONOP_MAX, share_min=1.0)["warn"])
        cols["h2_dn5"].append(eq.warning(now, prv, d_nonop_max=-0.05, share_min=SHARE_MIN)["warn"])
    out = panel.copy()
    for k, v in cols.items():
        out[k] = v
    return out


# ───────────── 가격 ─────────────
def price_frames(hist_from: int = 2019):
    """분할 조정 종가 wide [date × yf] + 원시 종가·거래량(거래대금 필터용)."""
    adj = krpx.load_kr(hist_from=hist_from).to_pandas()
    raw = krpx.load_kr(raw=True, hist_from=hist_from).to_pandas()
    adj["date"] = pd.to_datetime(adj["date"]); raw["date"] = pd.to_datetime(raw["date"])
    px = adj.pivot(index="date", columns="yf", values="close").sort_index()
    rw = raw.pivot(index="date", columns="yf", values="close").sort_index()
    vol = raw.pivot(index="date", columns="yf", values="volume").sort_index()
    return px, rw, vol


def attach_returns(panel: pd.DataFrame, px: pd.DataFrame, rw: pd.DataFrame, vol: pd.DataFrame) -> pd.DataFrame:
    """사건 후보행 → 진입일·r20·초과수익. 시점 규칙: t=기한 이후 첫 거래일, 진입=t 다음 거래일 종가."""
    dates = px.index
    turn = (rw * vol).rolling(20, min_periods=15).mean()          # 20일 평균 거래대금(원)
    r20m = px / px.shift(20) - 1.0
    hz = (5, HORIZON, 60)
    fwd = {h: px.shift(-h) / px - 1.0 for h in hz}
    universe = [c for c in px.columns if c.split(".")[0] in set(panel["code"])]
    bench = {h: fwd[h][universe].mean(axis=1) for h in hz}
    have = set(px.columns)
    rows = []
    for r in panel.itertuples(index=False):
        yf = r.code + ".KS" if r.code + ".KS" in have else (r.code + ".KQ" if r.code + ".KQ" in have else None)
        if yf is None:
            continue
        i = int(dates.searchsorted(pd.Timestamp(r.avail)))        # 기한 이상 첫 거래일
        if i >= len(dates) - 1:
            continue
        t, e = dates[i], dates[i + 1]
        if not (np.isfinite(px.at[t, yf]) and np.isfinite(px.at[e, yf])):
            continue
        d = {**r._asdict(), "yf": yf, "t": t, "entry": e,
             "r20": float(r20m.at[t, yf]), "turn20": float(turn.at[t, yf]) if np.isfinite(turn.at[t, yf]) else np.nan}
        for h in hz:
            v = fwd[h].at[e, yf]
            d[f"raw{h}"] = float(v) if np.isfinite(v) else np.nan
            d[f"exc{h}"] = float(v - bench[h].at[e]) if np.isfinite(v) else np.nan
        rows.append(d)
    return pd.DataFrame(rows)


# ───────────── 검정 ─────────────
def grade(p, subs: dict[str, float | None], n: int, direction: int = +1, alpha: float = ALPHA) -> tuple[str, str]:
    """등급 규칙 — scripts/study_rule_audit.py 와 같은 문턱 + 하위 구간 방향 확인."""
    if p is None or n < 10:
        return "검증전", f"표본 {n}"
    landed = [s for s in subs.values() if s is not None]
    same = len(landed) == 2 and all(np.sign(s) * direction >= 0 for s in landed)
    if p < alpha:
        if same:
            return "A", f"Bonferroni 유의(p={p:.4f}) + IS·OOS 같은 방향"
        return "B", f"Bonferroni 유의(p={p:.4f}), 하위 구간 방향 불일치/부족"
    if p < 0.10:
        return "C", f"방향만(p={p:.3f}, Bonferroni α={alpha:.4f} 미달)"
    return "F", f"현행과 구별 안 됨(p={p:.2f})"


def test_flag(df: pd.DataFrame, col: str, *, horizon: int = HORIZON, drop: float | None = DROP_20,
              direction: int = +1, alpha: float = ALPHA) -> dict:
    """플래그 집단 vs 같은 진입일 비플래그 집단(짝지은 대조) — 초과수익 차이 단측 검정."""
    x = df.dropna(subset=[f"exc{horizon}"]).copy()
    if drop is not None:
        x = x[x["r20"] <= drop]
    ev = x[x[col]]
    if ev.empty:
        return {"n_ev": 0, "grade": "검증전", "why": "사건 없음"}
    ctrl = x[(~x[col]) & x["entry"].isin(set(ev["entry"]))]
    ev_r = ev[f"exc{horizon}"].to_numpy(float)
    ct_r = ctrl[f"exc{horizon}"].to_numpy(float)
    a, b = ev_r * direction, ct_r * direction
    w = eq.welch(a, b)
    one = eq.mean_t(a)
    cl = eq.cluster_mean(a, ev["entry"].astype(str))

    def sub(mask):
        part = ev[mask]
        if part.empty:
            return {"n_ev": 0, "n_ctrl": 0, "mean_ev": None, "mean_ctrl": None, "diff": None, "p_one": None}
        aa = part[f"exc{horizon}"].to_numpy(float) * direction
        bb = x[(~x[col]) & x["entry"].isin(set(part["entry"]))][f"exc{horizon}"].to_numpy(float) * direction
        r = eq.welch(aa, bb)
        return {"n_ev": int(len(part)), "n_ctrl": int(bb.size), "mean_ev": r["mean_a"], "mean_ctrl": r["mean_b"],
                "diff": r["diff"], "p_one": r["p_one"]}

    is_ = sub(ev["entry"] <= pd.Timestamp(IS_END))
    oos = sub(ev["entry"] >= pd.Timestamp(OOS_START))
    g, why = grade(w["p_one"], {"is": is_["diff"], "oos": oos["diff"]}, len(ev), direction=direction, alpha=alpha)
    st_ev, st_ct = eq.group_stats(ev_r), eq.group_stats(ct_r)
    return {
        "n_ev": int(len(ev)), "n_ctrl": int(len(ctrl)),
        "mean_ev": w["mean_a"], "mean_ctrl": w["mean_b"], "diff": w["diff"], "t": w["t"], "p_one": w["p_one"],
        "vs_zero": {"mean": one["mean"], "t": one["t"], "p_one": one["p_one"]},
        "cluster": cl, "is": is_, "oos": oos,
        "win_ev": st_ev.get("win"), "win_ctrl": st_ct.get("win"),
        "false_ev": st_ev.get("false_rate"), "payoff_ev": st_ev.get("payoff"),
        "median_ev": st_ev.get("median"), "mean_ev_raw": st_ev.get("mean"),
        "grade": g, "why": why,
    }


def split_nonop(df: pd.DataFrame, path: Path = FULL) -> dict:
    """탐색·서술 — 영업외손익을 금융손익 / 기타(지분법·기타영업외)로 나눌 수 있는 종목(504)에서 성분 비중."""
    if not path.exists():
        return {"available": False, "why": "data/fin/full.parquet 없음"}
    f = pl.read_parquet(path)
    f = f.filter(pl.col("sj_div").is_in(["IS", "CIS"]))
    names = {"금융수익": "fin_p", "금융비용": "fin_m", "금융원가": "fin_m", "이자수익": "int_p", "이자비용": "int_m",
             "기타수익": "etc_p", "기타비용": "etc_m", "기타영업외수익": "etc_p", "기타영업외비용": "etc_m",
             "지분법이익": "eq_p", "지분법손실": "eq_m", "지분법손익": "eq_p", "파생상품평가손익": "der"}
    f = f.filter(pl.col("account").is_in(list(names)))
    f = (f.with_columns(pl.col("account").replace_strict(names, return_dtype=pl.Utf8).alias("k"),
                        pl.col("reprt").replace_strict(REPRT_Q, return_dtype=pl.Int32).alias("q"),
                        pl.when(pl.col("fs_div") == "CFS").then(0).otherwise(1).alias("fprio"))
           .sort("fprio").group_by(["code", "year", "q", "k"], maintain_order=True)
           .agg(pl.col("amount").first()))
    w = f.pivot(on="k", index=["code", "year", "q"], values="amount").to_pandas()
    for c in ("fin_p", "fin_m", "etc_p", "etc_m", "eq_p", "eq_m", "der", "int_p", "int_m"):
        if c not in w.columns:
            w[c] = np.nan
    w["fin"] = w["fin_p"].fillna(0) - w["fin_m"].fillna(0)
    w["etc"] = w["etc_p"].fillna(0) - w["etc_m"].fillna(0) + w["eq_p"].fillna(0) - w["eq_m"].fillna(0)
    m = df.merge(w[["code", "year", "q", "fin", "etc"]], on=["code", "year", "q"], how="inner")
    for tag, mask in (("h1", m["h1"]), ("h2", m["h2"])):
        s = m[mask]
        if s.empty:
            continue
        tot = (s["fin"].abs() + s["etc"].abs()).replace(0, np.nan)
        m.loc[s.index, f"{tag}_fin_share"] = (s["fin"].abs() / tot)
    h1s = m[m["h1"]]
    h2s = m[m["h2"]]
    return {"available": True, "codes_full": int(w["code"].nunique()),
            "h1_matched": int(len(h1s)), "h2_matched": int(len(h2s)),
            "h1_fin_share_median": float(h1s["h1_fin_share"].median()) if len(h1s) else None,
            "h2_fin_share_median": float(h2s["h2_fin_share"].median()) if len(h2s) else None,
            "h1_fin_negative_share": float((h1s["fin"] < 0).mean()) if len(h1s) else None,
            "h2_fin_negative_share": float((h2s["fin"] < 0).mean()) if len(h2s) else None,
            "note": "금융손익=금융수익−금융비용, 기타=기타·영업외·지분법. full 패널(504종목 2023~)에만 있음"}


def run() -> dict:
    panel = add_signals(load_panel())
    px, rw, vol = price_frames()
    df = attach_returns(panel, px, rw, vol)
    base = df[(df["turn20"] >= MIN_TURNOVER) & df[f"exc{HORIZON}"].notna()].copy()

    h1 = test_flag(base, "h1")
    h2 = test_flag(base, "h2", direction=-1)
    exp = {
        "h1_h5": test_flag(base, "h1", horizon=5),
        "h1_h60": test_flag(base, "h1", horizon=60),
        "h1_drop3": test_flag(base, "h1", drop=-0.03),
        "h1_drop8": test_flag(base, "h1", drop=-0.08),
        "h1_drop0": test_flag(base, "h1", drop=None),
        "h1_dni3": test_flag(base, "h1_dni3"),
        "h1_dni1": test_flag(base, "h1_dni1"),
        "h2_share1": test_flag(base, "h2_share1", direction=-1),
        "h2_dn5": test_flag(base, "h2_dn5", direction=-1),
        "h2_h5": test_flag(base, "h2", horizon=5, direction=-1),
        "h2_h60": test_flag(base, "h2", horizon=60, direction=-1),
        "h2_drop0": test_flag(base, "h2", drop=None, direction=-1),
    }
    out = {
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "id": "op_ni_divergence",
        "title": "영업이익 vs 순이익 괴리 — 본업 견조 + 영업외 일회성 미스 vs 자본배분·평가손 경고",
        "prereg": {"m": M, "alpha_bonf": round(ALPHA, 5), "is_end": IS_END, "oos_start": OOS_START,
                   "horizon": HORIZON, "drop_20": DROP_20, "d_ni_max": D_NI_MAX, "d_nonop_max": D_NONOP_MAX,
                   "share_min": SHARE_MIN, "min_turnover_krw": MIN_TURNOVER,
                   "timing": "avail = 법정 제출기한 → t = 이후 첫 거래일 → 진입 = t 다음 거래일 종가",
                   "data": "data/fin/multi.parquet + data/hist/kr_*.parquet + data/kr_prices.parquet"},
        "panel": {"codes": int(panel["code"].nunique()), "rows": int(len(panel)),
                  "years": [int(panel["year"].min()), int(panel["year"].max())],
                  "priced_rows": int(len(df)), "tradable_rows": int(len(base)),
                  "h1_raw": int(df["h1"].sum()), "h2_raw": int(df["h2"].sum()),
                  "h1_events": int(base["h1"].sum()), "h2_events": int(base["h2"].sum()),
                  "src_q4_derived": int((panel.get("src_ni") == "annual_minus_cum3").sum()) if "src_ni" in panel else None,
                  "price_range": [str(px.index.min().date()), str(px.index.max().date())]},
        "H1": h1, "H2": h2, "exploratory": exp, "nonop_split": split_nonop(df),
        "grades": {"H1": h1["grade"], "H2": h2["grade"]},
        "meta": {"run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    }
    return out


def main(argv=None) -> int:
    out = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    p = out["panel"]
    print(f"[{out['id']}] 패널 {p['codes']}종목 {p['rows']}행 → 가격결합 {p['priced_rows']} · 거래가능 {p['tradable_rows']}")
    for k in ("H1", "H2"):
        r = out[k]
        if not r.get("n_ev"):
            print(f"  {k}: 사건 없음 → {r['grade']}")
            continue
        print(f"  {k} [{r['grade']}] 사건 {r['n_ev']} vs 대조 {r['n_ctrl']}: 초과 "
              f"{r['mean_ev']:+.4f} vs {r['mean_ctrl']:+.4f} (차 {r['diff']:+.4f}, 단측 p {r['p_one']:.4f})")
        print(f"      IS {r['is']['n_ev']}건 {r['is']['diff']} p {r['is']['p_one']} | "
              f"OOS {r['oos']['n_ev']}건 {r['oos']['diff']} p {r['oos']['p_one']}")
        print(f"      vs0 {r['vs_zero']['mean']:+.4f} p {r['vs_zero']['p_one']} · 클러스터 {r['cluster']['dates']}일 "
              f"p {r['cluster']['p_one']} · 승률 {r['win_ev']} vs {r['win_ctrl']}")
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
