"""2022 고금리 국면 멀티플 압축 수치화 (퀀트·애널 데스크, 2026-11-03).
ln(P1/P0)=ln(E1/E0)+ln(PE1/PE0). 지수 EPS 이력은 저장소에 없음 → 종목 합산(Σ시총/ΣTTM순이익) 대용.
데이터: data/hist (us_2021/2022, kr_2021/2022, 릴리스 us_daily·kr_index_daily), data/fin/us_quarterly.parquet,
data/fin/multi.parquet(KR DART 2020~22), universe/kr_shares.csv. 실행: python3 scripts/study_multiple_compression_2022.py [DS_ROOT]
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DS = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT
D0, DE = "2021-12-30", "2022-12-30"
LOW_WIN = ("2022-10-01", "2022-10-31")
P = pd.concat([pd.read_parquet(ROOT/"data/hist/us_2021.parquet"), pd.read_parquet(ROOT/"data/hist/us_2022.parquet")])
P["date"] = pd.to_datetime(P["date"])
px = P.pivot(index="date", columns="yf", values="close")
ud = pd.read_parquet(DS/"data/hist/us_daily.parquet")
ud["date"] = pd.to_datetime(ud["date"])
ucol = "symbol" if "symbol" in ud.columns else "yf"
ux_all = ud.pivot(index="date", columns=ucol, values="close")
ux = ud[(ud.date >= "2021-12-01") & (ud.date <= "2022-12-31")].pivot(index="date", columns=ucol, values="close")
ki = pd.read_parquet(DS/"data/hist/kr_index_daily.parquet"); ki["date"] = pd.to_datetime(ki["date"])
kcol = "symbol" if "symbol" in ki.columns else [c for c in ki.columns if c not in ("date","open","high","low","close","volume")][0]
kx_all = ki.pivot(index="date", columns=kcol, values="close")
kx = ki[(ki.date >= "2021-12-01") & (ki.date <= "2022-12-31")].pivot(index="date", columns=kcol, values="close")

def px_on(s, d):  # 마지막 거래일 종가(≤d)
    s = s.dropna(); s = s[s.index <= pd.Timestamp(d)]; return s.index[-1], float(s.iloc[-1])
def low_of(s):
    s = s.dropna(); w = s[(s.index >= LOW_WIN[0]) & (s.index <= LOW_WIN[1])]; return w.idxmin(), float(w.min())

# ---- US 종목 합산 EPS 대용
q = pd.read_parquet(ROOT/"data/fin/us_quarterly.parquet"); q["end"] = pd.to_datetime(q["end"])
def split_adj_shares(sh):  # 분할 감지: 직전 분기 대비 ×1.8↑/÷1.8↓ 점프를 분할로 보고 과거를 최신 기준으로 환산
    sh = sh[sh.value > 0].sort_values("end").reset_index(drop=True); f = 1.0; out = sh.value.values.astype(float).copy()
    for i in range(len(sh)-1, 0, -1):
        if out[i-1] <= 0 or out[i] <= 0: continue
        r = out[i]/out[i-1]; rr = r if r >= 1 else 1/r
        if rr >= 1.8 and abs(rr-round(rr)) < 0.12*round(rr):  # 정수배 점프만 분할로 인정
            out[:i] *= (round(rr) if r >= 1 else 1/round(rr))
    sh = sh.copy(); sh["adj"] = out; return sh
def ttm_ni(g, cut):
    g = g[g.end <= cut].sort_values("end").tail(4)
    if len(g) < 4 or (cut - g.end.iloc[0]).days > 420 or (g.end.iloc[-1]-g.end.iloc[0]).days > 330: return np.nan
    return g.value.sum()
def basket(tick, label):
    rows = []
    cuts = {"t0": pd.Timestamp(D0)-pd.Timedelta(45, 'D'), "low": None, "t1": pd.Timestamp(DE)-pd.Timedelta(45, 'D')}
    return rows
def us_agg(tickers, dates):
    """dates: {name: Timestamp} -> {name: (cap, ttm)} 동일 종목 집합."""
    ni = q[q.item == "ni"]; sh = q[q.item == "shares"]
    res = {k: [] for k in dates}; used = []
    for t in tickers:
        if t not in px.columns: continue
        g = ni[ni.ticker == t]; s = sh[sh.ticker == t]
        if g.empty or s.empty: continue
        s = split_adj_shares(s); vals = {}
        ok = True
        for k, d in dates.items():
            cut = d - pd.Timedelta(45, 'D')
            e = ttm_ni(g, cut); ss = s[s.end <= cut]
            if np.isnan(e) or ss.empty or (cut-ss.end.iloc[-1]).days > 420: ok = False; break
            try: _, p = px_on(px[t], d)
            except IndexError: ok = False; break
            vals[k] = (p*float(ss.adj.iloc[-1]), e)
        if ok:
            used.append(t)
            for k in dates: res[k].append(vals[k])
    return {k: (sum(v[0] for v in res[k]), sum(v[1] for v in res[k])) for k in dates}, used

def decomp(m0, e0, m1, e1):
    pe0, pe1 = m0/e0, m1/e1
    return dict(dP=np.log(m1/m0), dE=np.log(e1/e0), dM=np.log(pe1/pe0), pe0=pe0, pe1=pe1)

out = {"windows": {}, "price": {}, "agg": {}}
# 가격표
spec = {"S&P500(^GSPC)": ux["^GSPC"], "SPY": ux["SPY"], "나스닥100(QQQ)": ux["QQQ"], "필라델피아반도체(^SOX)": ux["^SOX"],
        "반도체 ETF(SMH)": ux["SMH"], "코스피": kx["KOSPI"]}
tnx = ux["^TNX"]
for n, s in spec.items():
    d0, p0 = px_on(s, D0); dl, pl = low_of(s); d1, p1 = px_on(s, DE)
    out["price"][n] = dict(d0=str(d0.date()), dl=str(dl.date()), d1=str(d1.date()), p0=p0, pl=pl, p1=p1,
        to_low=np.log(pl/p0), low_to_end=np.log(p1/pl), full=np.log(p1/p0))
t0 = px_on(tnx, D0)[1]; tl = px_on(tnx, str(low_of(spec["S&P500(^GSPC)"])[0].date()))[1]; t1 = px_on(tnx, DE)[1]
tmax = tnx[(tnx.index>="2022-01-01")&(tnx.index<="2022-12-31")]
out["tnx"] = dict(t0=t0, t_low_date=tl, t1=t1, max=float(tmax.max()), max_date=str(tmax.idxmax().date()))
# US 합산
uni = sorted(set(q.ticker.unique()) & set(px.columns) - {"SPY","QQQ","SMH","SOXX","TLT","VOO","GOOG"})  # GOOG=GOOGL 이중 계상 제거
lowd = low_of(spec["S&P500(^GSPC)"])[0]
dates = {"t0": pd.Timestamp(D0), "low": lowd, "t1": pd.Timestamp(DE)}
semis = [t for t in ["NVDA","AMD","AVGO","MU","AMAT","LRCX","KLAC","TXN","QCOM","INTC","MCHP","ADI","NXPI","ON","MPWR","TER","SWKS","QRVO","WDC","STX","TSM","ASML"] if t in uni]
ex = lambda L: L
for name, tl_ in [("미 종목 합산(전체)", uni), ("미 반도체 바스켓", semis)]:
    r, used = us_agg(tl_, dates)
    a = {"n": len(used), "tickers": used if len(used) <= 30 else None}
    a["t0_low"] = decomp(r["t0"][0], r["t0"][1], r["low"][0], r["low"][1])
    a["low_t1"] = decomp(r["low"][0], r["low"][1], r["t1"][0], r["t1"][1])
    a["full"] = decomp(r["t0"][0], r["t0"][1], r["t1"][0], r["t1"][1])
    out["agg"][name] = a
# KR 합산
mu = pd.read_parquet(DS/"data/fin/multi.parquet"); mu = mu[mu.account == "당기순이익(손실)"]
mu = mu.sort_values("fs_div").drop_duplicates(["code","year","reprt"], keep="first")  # CFS 우선
def cum(code_df, y, rp):
    r = code_df[(code_df.year == y) & (code_df.reprt == rp)]
    if r.empty: return np.nan
    r = r.iloc[0]; v = r.add_amount if (rp != "11011" and pd.notna(r.add_amount)) else r.amount
    return float(v)
def kr_ttm(cdf, y, rp):  # y 년 rp 시점 TTM = FY(y-1) + cum(y,rp) - cum(y-1,rp)
    fy = cum(cdf, y-1, "11011"); a = cum(cdf, y, rp); b = cum(cdf, y-1, rp)
    return fy + a - b
sh = pd.read_csv(ROOT/"universe/kr_shares.csv", dtype={"code": str}).sort_values("year").drop_duplicates("code", keep="last").set_index("code")["out_total"]
k = pd.concat([pd.read_parquet(ROOT/"data/hist/kr_2021.parquet"), pd.read_parquet(ROOT/"data/hist/kr_2022.parquet")]); k["date"] = pd.to_datetime(k["date"])
kp = k.pivot(index="date", columns="yf", values="close")
kd = {"t0": (pd.Timestamp(D0), "11014", 2021), "low": (low_of(spec["코스피"])[0], "11012", 2022), "t1": (pd.Timestamp(DE), "11014", 2022)}
rows = []
for c, cdf in mu.groupby("code"):
    t = f"{c}.KS"
    if t not in kp.columns or c not in sh.index or not (sh[c] > 0): continue
    v = {}
    for kk, (d, rp, y) in kd.items():
        e = kr_ttm(cdf, y, rp)
        try: _, p = px_on(kp[t], d)
        except IndexError: p = np.nan
        v[kk] = (p*float(sh[c]), e)
    if any(np.isnan(x[1]) or np.isnan(x[0]) for x in v.values()): continue
    rows.append((c, v))
res = {kk: (sum(r[1][kk][0] for r in rows), sum(r[1][kk][1] for r in rows)) for kk in kd}
out["agg"]["코스피 종목 합산(DART)"] = {"n": len(rows), "t0_low": decomp(*res["t0"], *res["low"]), "low_t1": decomp(*res["low"], *res["t1"]), "full": decomp(*res["t0"], *res["t1"])}
# KR 반도체 2종
for nm, cs in [("삼성전자+SK하이닉스(DART)", ["005930", "000660"])]:
    rr = [r for r in rows if r[0] in cs]
    rs = {kk: (sum(r[1][kk][0] for r in rr), sum(r[1][kk][1] for r in rr)) for kk in kd}
    out["agg"][nm] = {"n": len(rr), "t0_low": decomp(*rs["t0"], *rs["low"]), "low_t1": decomp(*rs["low"], *rs["t1"]), "full": decomp(*rs["t0"], *rs["t1"])}
# KR 국고 10Y
kt = pd.read_csv(ROOT/"data/hist/kr_ktb_ecos_daily.csv", parse_dates=["date"]).set_index("date")
out["ktb"] = {kk: dict(zip(("ktb3y","ktb10y"), [float(kt[c][kt.index <= d].iloc[-1]) for c in ("ktb3y","ktb10y")])) for kk, d in [("t0", pd.Timestamp(D0)), ("low", kd["low"][0]), ("t1", pd.Timestamp(DE))]}

# ---- 2026 최근: 합산 TTM 순이익 y/y (종목 시총은 2026 종목 가격 부재 → 배수는 S&P 가격 − 합산 이익 근사, 검증전)
def _ttm(g, cut):
    g = g[g.end <= cut].sort_values("end").tail(4)
    if len(g) < 4 or (g.end.iloc[-1]-g.end.iloc[0]).days > 330 or (cut-g.end.iloc[0]).days > 420: return np.nan
    return g.value.sum()
L = pd.Timestamp("2026-10-30")
c1, c0 = L-pd.Timedelta(45,'D'), L-pd.Timedelta(365+45,'D')
_r = {}
for t, g in q[q.item == "ni"].groupby("ticker"):
    if t == "GOOG": continue
    a, b = _ttm(g, c0), _ttm(g, c1)
    if not (np.isnan(a) or np.isnan(b)): _r[t] = (a, b)
_d = pd.DataFrame(_r, index=["a","b"]).T; _d["d"] = _d.b-_d.a
top5 = _d.d.nlargest(5)
semi26 = _d.loc[[t for t in semis if t in _d.index]]
out["us2026"] = dict(n=len(_d), dE=float(np.log(_d.b.sum()/_d.a.sum())), top5=list(top5.index), top5_share=float(top5.sum()/_d.d.sum()),
    dE_ex_top5=float(np.log(_d.drop(top5.index).b.sum()/_d.drop(top5.index).a.sum())), dE_semis=float(np.log(semi26.b.sum()/semi26.a.sum())), n_semis=len(semi26),
    share_up=float((_d.b > _d.a).mean()))
_w = {}
for n_, s_ in [("^GSPC", ux_all["^GSPC"]), ("QQQ", ux_all["QQQ"]), ("^SOX", ux_all["^SOX"]), ("SMH", ux_all["SMH"]), ("^TNX", ux_all["^TNX"]), ("KOSPI", kx_all["KOSPI"])]:
    s_ = s_.dropna(); l_ = s_.index[-1]; y0 = s_[s_.index <= l_-pd.Timedelta(365,'D')]; w = s_[s_.index > l_-pd.Timedelta(365,'D')]
    _w[n_] = dict(last=str(l_.date()), v=float(s_.iloc[-1]), y0d=str(y0.index[-1].date()), y0=float(y0.iloc[-1]), ret1y=float(np.log(s_.iloc[-1]/y0.iloc[-1])),
                  hi=float(w.max()), hi_date=str(w.idxmax().date()), dd_from_hi=float(np.log(s_.iloc[-1]/w.max())))
out["now2026"] = _w
# ---- 2026 최근: 합산 TTM 순이익 y/y (종목 시총은 2026 종목 가격 부재 → 배수는 S&P 가격 − 합산 이익 근사, 검증전)
def _ttm(g, cut):
    g = g[g.end <= cut].sort_values("end").tail(4)
    if len(g) < 4 or (g.end.iloc[-1]-g.end.iloc[0]).days > 330 or (cut-g.end.iloc[0]).days > 420: return np.nan
    return g.value.sum()
L = pd.Timestamp("2026-10-30")
c1, c0 = L-pd.Timedelta(45,'D'), L-pd.Timedelta(365+45,'D')
_r = {}
for t, g in q[q.item == "ni"].groupby("ticker"):
    if t == "GOOG": continue
    a, b = _ttm(g, c0), _ttm(g, c1)
    if not (np.isnan(a) or np.isnan(b)): _r[t] = (a, b)
_d = pd.DataFrame(_r, index=["a","b"]).T; _d["d"] = _d.b-_d.a
top5 = _d.d.nlargest(5)
semi26 = _d.loc[[t for t in semis if t in _d.index]]
out["us2026"] = dict(n=len(_d), dE=float(np.log(_d.b.sum()/_d.a.sum())), top5=list(top5.index), top5_share=float(top5.sum()/_d.d.sum()),
    dE_ex_top5=float(np.log(_d.drop(top5.index).b.sum()/_d.drop(top5.index).a.sum())), dE_semis=float(np.log(semi26.b.sum()/semi26.a.sum())), n_semis=len(semi26),
    share_up=float((_d.b > _d.a).mean()))
_w = {}
for n_, s_ in [("^GSPC", ux_all["^GSPC"]), ("QQQ", ux_all["QQQ"]), ("^SOX", ux_all["^SOX"]), ("SMH", ux_all["SMH"]), ("^TNX", ux_all["^TNX"]), ("KOSPI", kx_all["KOSPI"])]:
    s_ = s_.dropna(); l_ = s_.index[-1]; y0 = s_[s_.index <= l_-pd.Timedelta(365,'D')]; w = s_[s_.index > l_-pd.Timedelta(365,'D')]
    _w[n_] = dict(last=str(l_.date()), v=float(s_.iloc[-1]), y0d=str(y0.index[-1].date()), y0=float(y0.iloc[-1]), ret1y=float(np.log(s_.iloc[-1]/y0.iloc[-1])),
                  hi=float(w.max()), hi_date=str(w.idxmax().date()), dd_from_hi=float(np.log(s_.iloc[-1]/w.max())))
out["now2026"] = _w
out["prereg"] = dict(m=0, kind="기술통계(가설검정 아님)", windows=[D0, "2022-10 저점(자산별 10월 종가 최저)", DE], filing_lag_days=45,
    note="집계 정의(창·45일 지연·동일 종목 집합)는 결과 전 고정. GOOG 중복 제거·분할 감지는 데이터 정합 수정")
out["grades"] = {"2022 멀티플 압축 크기(미 합산·반도체·코스피)": "C", "2026 대조 판정": "검증전"}
print(json.dumps(out, ensure_ascii=False, indent=1, default=float))
json.dump(out, open(ROOT/"reports/studies/multiple_compression_2022.json", "w"), ensure_ascii=False, indent=1, default=float)
