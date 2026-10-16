"""감마 레짐 검증 (gamma_regime) — '숏감마(감마 음수) 구간을 노릴 수 있나?'

python scripts/study_gamma.py  → reports/studies/gamma_regime.json (+ views/registry.json 의 gamma_regime 근거 갱신)
데이터: data/deriv/daily.csv (screener/deriv_hist.py — KRX 확정치, 하루 1행). 매일 deriv-hist 워크플로가 적재 뒤 다시 돌린다.

══════════════ 사전 등록 (2026-10-16, 결과를 보기 전에 이 머리말을 커밋) ══════════════
결과를 본 뒤 아래 정의·방향·기준을 바꾸지 않는다. 바꿔야 하면 새 id 로 다시 등록한다.

배경 — 감마 근사 gex_bn(십억원)은 '딜러가 옵션을 판 쪽'이라는 가정 아래 계산한 추정치다.
  gex_bn < 0 (숏감마): 딜러가 헤지하려면 오를 때 사고 내릴 때 판다 → 움직임을 '따라가며' 키운다.
  gex_bn ≥ 0 (롱감마): 오를 때 팔고 내릴 때 산다 → 움직임을 '받아내며' 줄인다.
  flip = 감마 합이 0 이 되는 코스피200 가격. 현물이 flip 아래면 숏감마 쪽.

데이터·정의 (모두 t일 장 마감 후 알 수 있는 값만 신호로 씀)
  - 행: daily.csv 에서 gex_bn·k200_close 가 있는 날 (옵션 보드 백필 시작 2025-08-29 ~).
  - r_t = ln(K200 종가_t / K200 종가_{t-1}). 결과 y = |r_{t+1}| (다음날 절대수익률).
  - 내재 하루 흔들림 = atm_iv_t / √252 (atm_iv 는 소수, 0.40 = 40%). 실현/내재 비 = |r_{t+1}| ÷ (atm_iv_t/√252).
  - 장중 방향: 코스피200 시가가 이력에 없어 **코스피 시가·종가로 대신**한다 (두 지수 일중 방향은 거의 같음).
    cont_{t+1} = 1 if sign(코스피 종가_{t+1} − 코스피 시가_{t+1}) == sign(r_t) else 0 (0 수익률 날 제외).

가설 (방향은 단측으로 미리 적음)
  H1  NEG_ABS   gex_bn<0 vs ≥0 → |r_{t+1}| 평균 차이 (음수 − 양수)             예상 +
  H1b NEG_RATIO gex_bn<0 vs ≥0 → 실현/내재 비 평균 차이                         예상 +  (IV 가 이미 반영한 몫을 뺀 '감마 고유' 흔들림)
  H2  NEG_PERSIST gex_bn<0 vs ≥0 → cont_{t+1} 비율 차이 (선형확률)              예상 +  (따라가는 헤지 → 추세 지속)
  ── 탐색 (Bonferroni 묶음 밖, 등급 최대 C) ──
  H2x GAP_CONT  gex_bn<0 vs ≥0 → t+1 시가갭과 t+1 장중(시가→종가) 부호 일치 비율    예상 +
  H3x FLIP_DIST 현물의 flip 대비 거리 (K200−flip)/K200 와 |r_{t+1}| 의 기울기 (NW 회귀)   예상 − (flip 아래로 멀수록 더 흔들림)

통계
  - 각 검정은 회귀 y ~ 1 + 더미(gex<0), Newey-West(지연 5) t — 변동성 군집·레짐 연속성 때문에 단순 Welch 는 t 를 부풀린다.
  - 다중검정: 주 검정 m = 3 (H1, H1b, H2), Bonferroni 단측 α = 0.05/3 ≈ 0.0167.
  - 표본 분할: 날짜순 앞 70% = IS, 뒤 30% = OOS.
  - 최소 표본: 전체 n ≥ 60 이 아니면 서술 통계만, 등급 '검증전', next_eval = n 이 60 에 닿는 예상 날짜(영업일).
    n ≥ 60 이어도 IS 에서 각 레짐 ≥ 20일이 아니면 '검증전'. OOS 판정은 각 레짐 ≥ 10일일 때만.
  - 등급: A = IS Bonferroni 통과 + OOS p<0.05 같은 방향 · B = IS Bonferroni 통과(OOS 미확인/미달)
          C = 전체 p<0.10 + 예상 방향 · F = 그 밖(효과 없음/반대) · 검증전 = 표본 미달.
    렌즈 gamma_regime 등급 = 주 검정(H1·H1b·H2) 중 최고 등급. 단 H1 만 통과하고 H1b 가 F 이면 'IV 재표현'으로 보고 최대 C.
  - 함정 미리 적기: 숏감마 날은 급락기에 몰린다(2026-03·06~08·10). 한 국면이 결과를 좌우할 수 있어 국면별 비중을 같이 적는다.
════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from statistics import NormalDist
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "gamma_regime.json"
REG = ROOT / "views" / "registry.json"
KST = ZoneInfo("Asia/Seoul")
LENS = "gamma_regime"
M = 3
ALPHA_B = 0.05 / M
MIN_N = 60
MIN_GROUP_IS = 20
MIN_GROUP_OOS = 10
NW_LAG = 5
N = NormalDist()


def _r(x, k=5):
    try:
        return None if x is None or not np.isfinite(x) else round(float(x), k)
    except TypeError:
        return None


def p_one(t, direction):
    return float("nan") if t is None or not np.isfinite(t) else 1 - N.cdf(t * direction)


def ols_nw(y, X, lag):
    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    y, X = y[ok], X[ok]
    n, k = X.shape
    if n <= k + 2 or np.linalg.matrix_rank(X) < k:
        return np.full(k, np.nan), np.full(k, np.nan)
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    u = y - X @ b
    Xu = X * u[:, None]
    S = Xu.T @ Xu
    for L in range(1, min(lag, n - 1) + 1):
        w = 1 - L / (lag + 1)
        G = Xu[L:].T @ Xu[:-L]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(V), 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        return b, b / se


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV, low_memory=False)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    df = df[df["k200_close"].notna()].reset_index(drop=True)
    lc = np.log(df["k200_close"].astype(float))
    df["r0"] = lc - lc.shift(1)
    df["abs_r1"] = (lc.shift(-1) - lc).abs()
    iv_d = df["atm_iv"].astype(float) / math.sqrt(252)
    df["ratio1"] = df["abs_r1"] / iv_d.where(iv_d > 0)
    o, c = df["kospi_open"].astype(float), df["kospi_close"].astype(float)
    intra = np.sign(c - o)
    s0 = np.sign(df["r0"])
    nxt_intra = intra.shift(-1)
    df["cont1"] = np.where((s0 != 0) & (nxt_intra != 0) & s0.notna() & nxt_intra.notna(), (s0 == nxt_intra).astype(float), np.nan)
    gap_next = np.sign(o.shift(-1) - c)
    df["gapcont1"] = np.where((gap_next != 0) & (nxt_intra != 0) & gap_next.notna() & nxt_intra.notna(),
                              (gap_next == nxt_intra).astype(float), np.nan)
    df["flip_dist"] = (df["k200_close"] - df["flip"]) / df["k200_close"]
    df = df[df["gex_bn"].notna()].reset_index(drop=True)
    df["neg"] = (df["gex_bn"] < 0).astype(float)
    return df


def _desc(d: pd.DataFrame, y: str) -> dict:
    out = {}
    for lab, sub in (("neg", d[d["neg"] == 1]), ("pos", d[d["neg"] == 0])):
        v = sub[y].dropna()
        out[lab] = {"n": int(len(v)), "mean": _r(v.mean()), "median": _r(v.median())}
    return out


def _grade(p_is, p_oos, p_all, eff_all, eff_oos, direction, enough_is, enough_oos, exploratory=False):
    if not enough_is:
        return "검증전"
    if not exploratory and np.isfinite(p_is) and p_is < ALPHA_B:
        if enough_oos and np.isfinite(p_oos) and p_oos < 0.05 and eff_oos * direction > 0:
            return "A"
        return "B"
    if np.isfinite(p_all) and p_all < 0.10 and eff_all * direction > 0:
        return "C"
    return "F"


def two_group(df, ycol, direction, hid, name, unit, cut, exploratory=False):
    d = df[["date", ycol, "neg"]].dropna()
    res = {}
    for part, sub in (("is", d[d["date"] < cut]), ("oos", d[d["date"] >= cut]), ("all", d)):
        y = sub[ycol].to_numpy(float)
        x = sub["neg"].to_numpy(float)
        b, t = ols_nw(y, np.column_stack([np.ones(len(x)), x]), NW_LAG)
        res[part] = {"n": int(len(sub)), "n_neg": int(x.sum()), "n_pos": int(len(x) - x.sum()),
                     "diff": b[1], "t": t[1], "p": p_one(t[1], direction)}
    enough_is = len(d) >= MIN_N and res["is"]["n_neg"] >= MIN_GROUP_IS and res["is"]["n_pos"] >= MIN_GROUP_IS
    enough_oos = res["oos"]["n_neg"] >= MIN_GROUP_OOS and res["oos"]["n_pos"] >= MIN_GROUP_OOS
    g = _grade(res["is"]["p"], res["oos"]["p"], res["all"]["p"], res["all"]["diff"], res["oos"]["diff"], direction,
               enough_is, enough_oos, exploratory)
    return {"id": hid, "name": name, "exploratory": exploratory, "grade": g, "direction": "+" if direction > 0 else "−",
            "effect_unit": unit, "desc": _desc(d, ycol),
            **{f"{k}_{p}": (_r(res[p][src], 5 if k == "effect" else 2 if k == "t" else 4) if k != "n" else res[p][src])
               for p in ("is", "oos", "all") for k, src in (("effect", "diff"), ("t", "t"), ("p", "p"), ("n", "n"))},
            "n_neg": res["all"]["n_neg"], "n_pos": res["all"]["n_pos"],
            "n_neg_is": res["is"]["n_neg"], "n_neg_oos": res["oos"]["n_neg"],
            "enough_is": enough_is, "enough_oos": enough_oos}


def flip_slope(df, cut):
    d = df[["date", "abs_r1", "flip_dist"]].dropna()
    res = {}
    for part, sub in (("is", d[d["date"] < cut]), ("oos", d[d["date"] >= cut]), ("all", d)):
        b, t = ols_nw(sub["abs_r1"].to_numpy(float), np.column_stack([np.ones(len(sub)), sub["flip_dist"].to_numpy(float)]), NW_LAG)
        res[part] = {"n": int(len(sub)), "slope": b[1], "t": t[1], "p": p_one(t[1], -1)}
    rho = d[["abs_r1", "flip_dist"]].corr(method="spearman").iloc[0, 1] if len(d) > 5 else float("nan")
    enough = len(d) >= MIN_N and res["is"]["n"] >= 40
    g = _grade(res["is"]["p"], res["oos"]["p"], res["all"]["p"], res["all"]["slope"], res["oos"]["slope"], -1,
               enough, res["oos"]["n"] >= 20, exploratory=True)
    below = d[d["flip_dist"] < 0]["abs_r1"]
    above = d[d["flip_dist"] >= 0]["abs_r1"]
    return {"id": "H3x", "name": "flip 대비 거리 → 다음날 |수익률| (탐색)", "exploratory": True, "grade": g, "direction": "−",
            "effect_unit": "기울기: 거리 1(=100%) 당 |r1| 변화", "spearman_all": _r(rho, 3),
            **{f"{k}_{p}": (_r(res[p][src], 5 if k == "effect" else 2 if k == "t" else 4) if k != "n" else res[p][src])
               for p in ("is", "oos", "all") for k, src in (("effect", "slope"), ("t", "t"), ("p", "p"), ("n", "n"))},
            "desc": {"below_flip": {"n": int(len(below)), "mean": _r(below.mean())}, "above_flip": {"n": int(len(above)), "mean": _r(above.mean())}}}


def next_eval(last: pd.Timestamp, n: int) -> str | None:
    if n >= MIN_N:
        return None
    return str((last + pd.offsets.BDay(MIN_N - n)).date())


def episodes(df) -> list[dict]:
    """숏감마 날이 어느 국면에 몰렸나 (월별 일수)."""
    neg = df[df["neg"] == 1]
    vc = neg["date"].dt.strftime("%Y-%m").value_counts().sort_index()
    return [{"month": k, "neg_days": int(v)} for k, v in vc.items()]


def lens_grade(main: list[dict]) -> str:
    order = {"A": 4, "B": 3, "C": 2, "F": 1, "검증전": 0}
    gs = {h["id"]: h["grade"] for h in main}
    if all(g == "검증전" for g in gs.values()):
        return "검증전"
    best = max(gs.values(), key=lambda g: order[g])
    if gs.get("H1") in ("A", "B") and gs.get("H1b") == "F" and order[best] > order["C"] and max(order[gs["H1b"]], order[gs["H2"]]) < order["C"]:
        best = "C"
    return best


def summary_ko(n, grade, H, nxt) -> str:
    h1, h1b, h2 = H["H1"], H["H1b"], H["H2"]
    pct = lambda x: "—" if x is None else f"{x*100:.2f}%"  # noqa: E731
    d1n, d1p = h1["desc"]["neg"], h1["desc"]["pos"]
    rn, rp = h1b["desc"]["neg"], h1b["desc"]["pos"]
    cn, cp = h2["desc"]["neg"], h2["desc"]["pos"]
    s = ("감마가 음수인 날은 옵션 딜러가 '오르면 따라 사고, 내리면 따라 파는' 쪽에 서 있다고 본다. 그래서 흔들림이 커지고 "
         "한 방향으로 밀리기 쉽다는 게 통설이다. 이 연구는 그 통설이 코스피200 에서도 맞는지, 그리고 그게 옵션 가격(IV)에 이미 "
         "들어 있는 정보 이상인지 본다. ")
    s += (f"지금까지 {n}거래일(감마 음수 {h1['n_neg']}일): 다음날 절대 등락은 음수 구간 평균 {pct(d1n['mean'])} vs 양수 {pct(d1p['mean'])}, "
          f"IV 가 예고한 흔들림 대비 실제 비율은 {rn['mean']} vs {rp['mean']}, 다음날 장중이 전날 방향을 이어간 비율은 "
          f"{pct(cn['mean'])} vs {pct(cp['mean'])}. ")
    if grade == "검증전":
        s += "표본이 사전 등록 기준에 못 미쳐 위 숫자는 서술 통계일 뿐 유의성 판정이 아니다."
        if nxt:
            s += f" 표본 60일 도달 예상 {nxt} 에 자동 판정."
        else:
            s += " 감마 음수 날이 IS 구간에 충분히 쌓이면 매일 재계산으로 자동 판정."
    else:
        s += f"사전 등록 기준 판정: 렌즈 등급 {grade} (H1 {h1['grade']} · H1b {h1b['grade']} · H2 {h2['grade']}). "
        if h1b["grade"] in ("F", "C") and h1["grade"] in ("A", "B", "C"):
            s += "흔들림이 커 보이는 건 맞지만 IV 로 나누면 차이가 약해진다 → 이미 옵션값에 반영된 위험이라 '숏감마라서' 추가로 얻을 몫은 작다. "
        if h2["grade"] in ("F", "검증전"):
            s += "방향이 이어진다는(추세 지속) 근거는 없다 → '숏감마 구간에 추세 추종으로 노린다'는 아직 쓸 수 없다. "
        s += "용도는 사이즈·손절폭 조절(흔들림 크기)까지. 방향 판단 근거로 인용 금지."
    return s


def update_registry(out: dict) -> bool:
    try:
        reg = json.loads(REG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    L = next((x for x in reg.get("lenses", []) if x.get("id") == LENS), None)
    if not L:
        return False
    ev = L.setdefault("evidence", {})
    old = ev.get("grade")
    new = out["grade"]
    H = {h["id"]: h for h in out["hypotheses"]}
    eff = (f"|r1| 음수−양수 {H['H1']['effect_all']} (p_is {H['H1']['p_is']}) · 실현/내재 {H['H1b']['effect_all']} (p_is {H['H1b']['p_is']}) · "
           f"방향 지속 {H['H2']['effect_all']} (p_is {H['H2']['p_is']})")
    changed = (old != new) or ev.get("n") != out["n"]
    ev.update({"grade": new, "source": "reports/studies/gamma_regime.json", "n": out["n"], "date": out["computed"][:10],
               "effect": eff, "next_eval": out.get("next_eval")})
    if old != new:
        L.setdefault("history", []).append({"date": out["computed"][:10], "change": f"등급 {old} → {new} (자동 판정)",
                                            "why": "scripts/study_gamma.py 사전등록 기준"})
    if changed:
        REG.write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return changed


def main() -> None:
    df = load()
    n = int(df["abs_r1"].notna().sum())
    d_ok = df[df["abs_r1"].notna()]
    cut = d_ok["date"].iloc[int(len(d_ok) * 0.7)] if len(d_ok) > 10 else d_ok["date"].iloc[-1]
    H = {
        "H1": two_group(df, "abs_r1", +1, "H1", "감마 음수 → 다음날 |수익률| 확대", "|r1| 평균 차이(로그)", cut),
        "H1b": two_group(df, "ratio1", +1, "H1b", "감마 음수 → 실현/내재(IV) 흔들림 비 확대", "|r1|÷(IV/√252) 평균 차이", cut),
        "H2": two_group(df, "cont1", +1, "H2", "감마 음수 → 다음날 장중이 전날 방향 지속", "지속 비율 차이(선형확률)", cut),
        "H2x": two_group(df, "gapcont1", +1, "H2x", "감마 음수 → 시가갭 방향으로 장중 지속 (탐색)", "지속 비율 차이", cut, exploratory=True),
    }
    H["H3x"] = flip_slope(df, cut)
    main_h = [H["H1"], H["H1b"], H["H2"]]
    g = lens_grade(main_h) if n >= MIN_N else "검증전"
    last = df["date"].iloc[-1]
    nxt = next_eval(last, n)
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    out = {
        "id": LENS, "registered": "2026-10-16", "computed": now, "question": "숏감마(감마 음수) 구간을 노릴 수 있나?",
        "data": "data/deriv/daily.csv (KRX 확정치 · 옵션 보드 백필 2025-08-29~)", "period": f"{df['date'].iloc[0].date()} ~ {last.date()}",
        "n": n, "n_min": MIN_N, "n_neg": int(df.loc[df["abs_r1"].notna(), "neg"].sum()), "is_until": str(pd.Timestamp(cut).date()),
        "m": M, "alpha_bonf": round(ALPHA_B, 4), "nw_lag": NW_LAG, "grade": g, "next_eval": nxt,
        "grades_doc": "A=IS Bonferroni+OOS · B=IS Bonferroni(OOS 미확인) · C=방향만(p<0.10) · F=효과 없음/반대 · 검증전=표본 미달. 탐색(x)은 최대 C",
        "hypotheses": [H[k] for k in ("H1", "H1b", "H2", "H2x", "H3x")],
        "neg_by_month": episodes(df),
        "latest": {"date": str(last.date()), "gex_bn": _r(df["gex_bn"].iloc[-1], 1), "flip": _r(df["flip"].iloc[-1], 1),
                   "k200": _r(df["k200_close"].iloc[-1], 2), "atm_iv": _r(df["atm_iv"].iloc[-1], 4),
                   "regime": "감마 음수" if df["neg"].iloc[-1] == 1 else "감마 양수"},
        "caveats": ["gex_bn 은 딜러 포지션 부호를 가정한 근사치다 (실제 딜러 장부 아님).",
                    "장중 방향은 코스피200 시가 이력이 없어 코스피 시가·종가로 대신했다.",
                    "감마 음수 날은 급락 국면(neg_by_month)에 몰려 있어 한두 국면이 결과를 좌우할 수 있다.",
                    "derivs_signals H7(하위 1/3) 결과: IV 를 통제하면 감마 효과가 사라졌다 — H1b 가 그 질문의 사전등록 재검정."],
    }
    out["ui_line"] = (f"감마 레짐 검증: {g} (n={n}/{MIN_N}" + (f", 판정 예정 {nxt[5:]}" if nxt else "") + ")")
    out["summary_ko"] = summary_ko(n, g, H, nxt)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    reg_changed = update_registry(out)
    print(out["ui_line"], "| registry", "갱신" if reg_changed else "그대로")
    for h in out["hypotheses"]:
        print(f"  {h['id']:4} {h['grade']:3} eff_all={h.get('effect_all')} t_is={h.get('t_is')} p_is={h.get('p_is')} "
              f"t_oos={h.get('t_oos')} p_oos={h.get('p_oos')} n={h.get('n_all')}")
    print(out["summary_ko"])


if __name__ == "__main__":
    main()
