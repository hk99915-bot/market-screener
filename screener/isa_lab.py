"""ISA 비중 실험실 — 데이터 변환 + Python 기준 구현 (화면 계산은 apps-script/tab_isalab.html 의 같은 로직, tests/test_isa_lab.py 가 숫자 대조).

데이터: pb-private analysis/2026-10-15-alloc/monthly_returns_krw.csv (2004-01~2026-10 원화 월수익률, **비용 차감 전**)
      + reports/isa_lab_ext_monthly.csv (그 뒤 달 — 같은 정의로 일간 종가에서 다시 잰 월수익률, `extend` 가 만든다. 같은 달이면 덮어씀).
그 보고서(run.py DRAG)와 같은 연 비용을 월 1/12씩 빼서 쓴다: S&P·NDX 0.6%, KOSPI200 0.2%, 미국채 0.4%, 금 0.5%, 국고 0.
시장 데이터만 담는다 — 개인 금액·보유 없음. 월 적립 금액은 화면에서 '100(단위 자유)' 기준 배수로만 보여 준다.

사용:  python -m screener.isa_lab extend [--thru YYYY-MM-DD]   (yfinance 일간 → 확장 CSV; 원천 스냅샷 마지막 달 2026-10 부터)
       python -m screener.isa_lab build [--src CSV] [--ext CSV] [--out reports/isa_lab_returns.json]
       python -m screener.isa_lab check   (현행·매크로 비교안 일시금 월 리밸 지표 출력)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DEFAULT = Path("/home/user/pb-private/analysis/2026-10-15-alloc/monthly_returns_krw.csv")
OUT_DEFAULT = ROOT / "reports" / "isa_lab_returns.json"
EXT_DEFAULT = ROOT / "reports" / "isa_lab_ext_monthly.csv"

ASSETS = ["SP", "NDX", "KS", "KR3Y", "KR10Y", "UST", "GOLD"]
NAMES = {"SP": "S&P500", "NDX": "나스닥100", "KS": "KOSPI200", "KR3Y": "국고3년", "KR10Y": "국고10년", "UST": "미국채7-10", "GOLD": "금"}
DRAG = {"SP": 0.006, "NDX": 0.006, "KS": 0.002, "KR3Y": 0.0, "KR10Y": 0.0, "UST": 0.004, "GOLD": 0.005}
# 첫 프리셋 = 화면 비교 기준. C안 = 11/7 확정 현행 코어(pb-private analysis/2026-11-07-alloc/core_442.md 17행, req-quant-a74f9f91).
# 옛 '현행 ISA'(금15·NDX10)는 '이전안', 옛 '나스닥안(금10·NDX15)'은 C안과 같은 비중이라 C안으로 합침.
PRESETS = {
    "C안(현행)": {"SP": 40, "NDX": 15, "KS": 15, "KR3Y": 20, "GOLD": 10},
    "이전안(금15·NDX10)": {"SP": 40, "NDX": 10, "KS": 15, "KR3Y": 20, "GOLD": 15},
    "매크로안 (금10·국고25)": {"SP": 40, "NDX": 10, "KS": 15, "KR3Y": 25, "GOLD": 10},
}
# 위기 구간 (월말 기준 포함 범위) — 2008 은 2026-10-15 배분 보고서와 같은 07-11~09-02
CRISES = [
    ["2008 금융위기", "2007-11", "2009-02"],
    ["2020 코로나", "2020-02", "2020-04"],
    ["2022 금리쇼크", "2022-01", "2022-12"],
    ["2026-06~10", "2026-06", "2026-10"],
]
# 위기 유형(국면) 축 — 정의 = pb-private analysis/2026-11-07-alloc/regime_rebalance.md §3 표(89·90·92행) 문구 그대로,
# 사건 배정 = 같은 표 '근거 사건' 열 + §1-A 40행 'A와 D는 서로 거울'(원화 강세형 2026-07 / 원화 약세·인플레형 2022) + 416행 보험금 표(2008형·2022형 = 원화 약세형).
# 숫자는 이 파일의 월수익으로 재생(월 리밸·비용 차감 — regime_rebalance §1-B 와 같은 월 리밸). 비중 변경 권고 아님.
REGIME_SRC = "pb-private analysis/2026-11-07-alloc/regime_rebalance.md"
REGIMES = [
    {"key": "K2", "name": "원화 약세·인플레형 위기",
     "def": "원/달러 월말 > 12개월 평균 그리고 (미 10년 BEI ≥ 2.5% 또는 직전 24개월 국고–주식 상관 > +0.20)",
     "def_src": "§3 90행", "events": [["2008형", "2007-11", "2009-02", "416행 보험금 표 · §1-A 2008 열"],
                                     ["2022형", "2022-01", "2022-12", "§3 90행 근거 사건 · 416행"]]},
    {"key": "K1", "name": "원화 강세·국장 주도 급락형 위기",
     "def": "원/달러 월말 < 직전 12개월 평균 그리고 코스피 20일 고점 대비 ≤ −15%(rules 35행 하락장 문턱)",
     "def_src": "§3 89행", "events": [["2026-07형", "2026-06", "2026-10", "§3 89행 근거 사건 · §1-B '코어 2026-06~10' 월간 창"]]},
    {"key": "K0", "name": "평시 / 전체 기간", "def": "위기 창 3개를 뺀 월(사후 선택, 위로 치우침)",
     "def_orig": "위 셋 아님", "def_src": "§3 92행 원문 「위 셋 아님」 — 실험실 계산은 국면 신호가 아니라 위기 창 제외", "events": []},
]
SCEN_REBAL = "M"


def scenarios(D: dict) -> dict:
    """프리셋 × 국면 표. 위기 = 구간 누적수익률(일시금, 시간가중), 평시 = 위 위기 구간 월을 뺀 월들의 연환산, 전체 = 전 기간 CAGR."""
    M = net_returns(D, True)
    m = D["months"]
    evs = [(ev, a, b) for g in REGIMES for ev, a, b, _ in g["events"] if a in m and b in m]   # 창이 데이터 밖이면 칸 없음
    crisis_idx = set()
    for _, a, b in evs:
        crisis_idx |= set(range(m.index(a), m.index(b) + 1))
    # 진행 중 부분 월(asof < 그 달 말일)은 평시에서 뺀다 — 전체 기간 연복리에는 포함 (피어리뷰 97341c82a)
    partial = m[-1] if D.get("asof") and D["asof"][:7] == m[-1] and int(D["asof"][8:10]) < 28 else None
    excl = crisis_idx | ({len(m) - 1} if partial else set())
    rows = {}
    for name, wm in D["presets"].items():
        twr = simulate(M, weights(D, wm), SCEN_REBAL, 0)["twr"]
        cell = {}
        for ev, a, b in evs:
            acc = 1.0
            for t in range(m.index(a), m.index(b) + 1):
                acc *= 1 + twr[t]
            cell[ev] = round(acc - 1, 6)
        calm = [twr[t] for t in range(len(m)) if t not in excl]
        g_c = 1.0
        for r in calm:
            g_c *= 1 + r
        cell["평시 연환산"] = round(g_c ** (12 / len(calm)) - 1, 6) if calm else None
        cell["전체 기간 연복리"] = round(twr_stats(twr)["cagr"], 6)
        rows[name] = cell
    return {"regimes": REGIMES, "source": REGIME_SRC, "desk": _desk_block(D["presets"]),
            "now": {"regime_rebalance": "현재 상태(부록 C-매크로 424행, 11/7 작성): 「K1 진행 중(문턱 충족, 11/5 종가 기준·11/6 미반영) · K2·K3 꺼짐」 · 기준일 2026-11-05 종가",
                    "vs_frm": "FRM regime 「하락장」은 rules 35행 시장 국면(반도체 밴드 상한용) 하나를 본 판정이고, 배분 K1 은 그 하락장 문턱에 원/달러 < 12개월 평균(원화 강세)까지 겹친 위기 유형 판정 — 같은 하락 쪽이나 축이 달라 FRM 은 원화 방향을 말하지 않는다"},
            "calm_excluded_partial": partial, "rebal": SCEN_REBAL, "cost": True,
            "window": f"{m[0]}~{m[-1]}", "rows": rows,
            "note": "과거 구간 재생(월 리밸·비용 차감)이지 기대수익 예측 아님 · 비중 변경 권고 아님. "
                    "위기 창은 사후 선택 — 다음 위기의 크기·유형 예측 아님. "
                    "K3(동반 하락+원화 강세)는 표본 없음 — 표에 없는 유형 가능. "
                    "배분 노트 §1-B 값(−13.22/−7.43/−12.14%)은 비용 차감 전·2026-10 10/15 부분 월 기준이라 이 표와 다르다. "
                    "2026-07형은 엔진 일간 재생(06/22→07/30) 대신 월간 창 2026-06~10. "
                    + (f"{partial}(진행 중 부분 월)은 위기 열·평시에서 빼고 전체 기간 연복리에 포함." if partial else "")}


# ---- 데스크 국면 블록 (B): 각 데스크가 이미 정리한 국면/시나리오를 문구 그대로 + 원천에 자산별 숫자가 있을 때만 프리셋 값 ----
FRM_SRC = Path("/home/user/pb-private/risk/frm.json")       # 'regime'(rulebook.regime_key 상승장/회복확인/하락장) · current.stress[].shock(상품별 %)
FRM_CODE = {"SP": "360750", "NDX": "379810", "KS": "069500", "KR3Y": "114260", "GOLD": "411060"}   # 국내 상장 ETF ↔ 실험실 자산
FRM_SKIP = {"hypo_semi22": "개별 반도체 대상 규정 시나리오 — ETF 칸 충격 0 이라 프리셋 값 무의미"}


def _frm_block(presets: dict, src: Path = FRM_SRC) -> dict:
    if not src.exists():
        return {"available": False, "why": f"{src} 없음 — 원천 미확인"}
    F = json.loads(src.read_text(encoding="utf-8"))
    rows, scen = {}, []
    for st in F["current"]["stress"]:
        if st["id"] in FRM_SKIP:
            continue
        sh = {a: st["shock"][c] for a, c in FRM_CODE.items() if c in st["shock"]}   # 상품별 충격 % 만 (금액 칸 pnl·by_pos 는 옮기지 않음)
        scen.append({"id": st["id"], "label": st["label"], "shock": sh})
    for name, wm in presets.items():
        tot = sum(wm.values())
        rows[name] = {sc["id"]: (round(sum(wm.get(a, 0) / tot * sc["shock"][a] for a in wm if wm.get(a)), 6)
                                 if all(a in sc["shock"] for a in wm if wm.get(a)) else None) for sc in scen}
    return {"available": True, "asof": F.get("asof"), "price_asof": F.get("price_asof"), "regime": F.get("regime"),
            "regime_def": "rulebook.regime_key: 공개 레짐 문구 → 상승장 / 회복확인 / 하락장 (모르면 하락장 — 반도체 밴드 상한용)",
            "limit_stress": (F.get("limits") or {}).get("stress"), "scenarios": scen, "rows": rows,
            "src": "pb-private risk/frm.json regime · current.stress[].shock (프리셋 값 = Σ 비중 × 상품 충격, 즉시 충격·리밸 없음)",
            "skipped": FRM_SKIP}


def _desk_block(presets: dict, root: Path = ROOT) -> dict:
    def j(p):
        try:
            return json.loads((root / p).read_text(encoding="utf-8"))
        except Exception:
            return {}
    mv, cm = j("reports/macro_view.json"), j("reports/committee.json")
    an = [ln for ln in (root / "docs/desk_kb/analyst.md").read_text(encoding="utf-8").splitlines() if "베어/베이스/불" in ln] \
        if (root / "docs/desk_kb/analyst.md").exists() else []
    none = {k: None for k in presets}
    return {
        "frm": _frm_block(presets),
        "macro": {"src": "reports/macro_view.json score·label·summary", "asof": mv.get("asof"), "score": mv.get("score"),
                  "label": mv.get("label"), "summary": mv.get("summary"),
                  "label_def": "screener/macroview.py wind_label: |s|<0.05 중립 · 0.05~0.15 약한 역풍/순풍 · 0.15~0.4 역풍/순풍 · ≥0.4 강한 (표시 로직·검증전)",
                  "rows": none, "why_blank": "원천에 수치 없음 — rows.impact 는 바람 점수 기여도(수익률 아님)라 프리셋 수익으로 바꾸지 않음"},
        "committee": {"src": "reports/committee.json scenarios (운용회의 강세/기본/약세)", "asof": cm.get("asof"),
                      "scenarios": [{"name": x.get("name"), "prob": x.get("prob"), "def": x.get("def")} for x in cm.get("scenarios") or []],
                      "basis": (cm.get("scenario_basis") or {}).get("basis"), "n": (cm.get("scenario_basis") or {}).get("n"),
                      "rows": none, "why_blank": "원천에 수치 없음 — 정의가 코스피 20거래일 변화뿐(나머지 자산 수치 없음)"},
        "analyst": {"src": "docs/desk_kb/analyst.md", "quote": an[0].strip() if an else None, "rows": none,
                    "why_blank": "원천에 수치 없음 — 단일 종목 목표 범위 작성 규약(지수·자산별 베어/베이스/불 숫자 없음)"},
        "mapping": "regime_rebalance K1 원화 강세·국장 급락형 ≈ FRM replay_2026-07·hypo_fx-10 / K2 원화 약세·인플레형 ≈ FRM proxy_2008-10(USD +7.0%)·hypo_fx10 "
                   "/ FRM regime(하락장) = rules 35행 하락장 문턱 = K1 정의의 둘째 조건 / 매크로 역풍·순풍 = 바람 점수 부호(위기 유형 아님) "
                   "/ 운용회의 강세·기본·약세 = 애널 규약의 불·베이스·베어 이름에 대응하나 코스피 20거래일 정의 — 정의가 서로 달라 1:1 대응 아님",
    }


# 원천 CSV 마지막 행은 월말 라벨이지만 실제 데이터는 그 달 중간까지일 수 있다 — asof 는 실제 마지막 날
# (uxui req-quant-14188e23, 미래 날짜 표기 수정). 원천 스냅샷은 10/15 까지, 확장 CSV 는 'thru' 칸에 실제 마지막 날을 적는다.
SRC_THRU = "2026-10-15"
# 확장 CSV 를 만드는 일간 티커 (원천 build_returns.py 와 같은 정의: 미국 상장분 × KRW=X, 국내 ETF 는 원화 그대로, 수정주가)
EXT_TICKERS = {"SP": ("SPY", True), "NDX": ("QQQ", True), "KS": ("069500.KS", False), "KR3Y": ("114260.KS", False),
               "KR10Y": ("148070.KS", False), "UST": ("IEF", True), "GOLD": ("GLD", True)}
EXT_FROM = "2026-10"   # 원천 스냅샷의 부분 월부터 다시 잰다


def _rows(src: Path, ext: Path | None) -> tuple[list[dict], str]:
    rows = list(csv.DictReader(src.open(encoding="utf-8")))
    hdr = list(rows[0].keys())
    assert hdr[0] == "date" and hdr[1:] == ASSETS, hdr
    thru = {r["date"][:7]: min(r["date"], SRC_THRU) if r["date"][:7] == SRC_THRU[:7] else r["date"] for r in rows}
    if ext and ext.exists():
        by = {r["date"][:7]: i for i, r in enumerate(rows)}
        for e in csv.DictReader(ext.open(encoding="utf-8")):
            row = {"date": e["date"], **{a: e[a] for a in ASSETS}}
            m = e["date"][:7]
            if m in by:
                rows[by[m]] = row
            else:
                assert m > rows[-1]["date"][:7], m
                rows.append(row)
                by[m] = len(rows) - 1
            thru[m] = e["thru"]
    return rows, thru[rows[-1]["date"][:7]]


def _note(rows: list[dict], asof: str) -> str:
    last = rows[-1]["date"]
    part = f"{last[:7]} 은 {int(asof[5:7])}/{int(asof[8:10])} 까지의 부분 월" if asof < last else f"{last[:7]} 까지 전체 월"
    return (f"{part}. 2026-10 이후는 일간 수정종가로 다시 잰 값(reports/isa_lab_ext_monthly.csv, 이전 스냅샷의 10/15 부분 월 대체). "
            "원화 기준 월수익률(비용 차감 전) — 화면이 drag 를 월 1/12씩 뺀다.")


def build(src: Path = SRC_DEFAULT, out: Path = OUT_DEFAULT, ext: Path | None = EXT_DEFAULT) -> dict:
    rows, asof = _rows(src, ext)
    months = [r["date"][:7] for r in rows]
    R = {a: [round(float(r[a]), 6) for r in rows] for a in ASSETS}
    o = {
        "schema_version": 1,
        "asof": asof,
        "note": _note(rows, asof),
        "source": "pb-private analysis/2026-10-15-alloc (SPY·QQQ·IEF·GLD × KRW=X, 069500·114260·148070 + 이전 구간 대용치)"
                  " + 2026-10~ yfinance 일간 수정종가(같은 티커·같은 정의)",
        "assets": ASSETS, "names": NAMES, "drag": DRAG, "months": months, "r": R,
        "presets": PRESETS, "crises": CRISES,
    }
    o["scenarios"] = scenarios(o)
    out.write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return o


def _daily_levels(start: str, end: str):
    """yfinance 일간 수정종가 → 자산별 원화 수준 (DataFrame). 네트워크 실패 시 예외 그대로 — 값 지어내지 않음."""
    import pandas as pd
    import yfinance as yf
    px = {}
    for t in {t for t, _ in EXT_TICKERS.values()} | {"KRW=X"}:
        d = yf.download(t, start=start, end=end, auto_adjust=True, progress=False, threads=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        if not len(d):
            raise RuntimeError(f"{t} 시세 없음")
        px[t] = d["Close"]
    P = pd.DataFrame(px).sort_index().ffill()
    return pd.DataFrame({a: P[t] * (P["KRW=X"] if usd else 1.0) for a, (t, usd) in EXT_TICKERS.items()}).dropna()


def extend(ext: Path = EXT_DEFAULT, thru: str | None = None) -> list[dict]:
    """EXT_FROM 직전 달 말일 종가 → 각 달 마지막 거래일 종가 월수익률. 마지막 달이 끝나지 않았으면 thru < 월말 (부분 월)."""
    import calendar
    import datetime as dt
    y, m = map(int, EXT_FROM.split("-"))
    start = (dt.date(y, m, 1) - dt.timedelta(days=20)).isoformat()
    end = (dt.date.fromisoformat(thru) + dt.timedelta(days=1)).isoformat() if thru else (dt.date.today() + dt.timedelta(days=1)).isoformat()
    L = _daily_levels(start, end)
    L = L[L.index < end]
    out, prev = [], L[L.index < f"{EXT_FROM}-01"].iloc[-1]
    for per in sorted({d.strftime("%Y-%m") for d in L.index if d.strftime("%Y-%m") >= EXT_FROM}):
        seg = L[L.index.strftime("%Y-%m") == per]
        last = seg.iloc[-1]
        yy, mm = map(int, per.split("-"))
        out.append({"date": f"{per}-{calendar.monthrange(yy, mm)[1]:02d}", "thru": seg.index[-1].strftime("%Y-%m-%d"),
                    **{a: f"{last[a] / prev[a] - 1:.6f}" for a in ASSETS}})
        prev = last
    with ext.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "thru", *ASSETS])
        w.writeheader()
        w.writerows(out)
    return out


# ---------- 기준 구현 (JS 와 같은 순서·같은 정의) ----------

def net_returns(D: dict, cost: bool = True) -> list[list[float]]:
    """월 × 자산 행렬 (비용 차감 선택)."""
    A = D["assets"]
    n = len(D["months"])
    return [[D["r"][a][t] - (D["drag"][a] / 12 if cost else 0.0) for a in A] for t in range(n)]


def weights(D: dict, wmap: dict) -> list[float]:
    w = [float(wmap.get(a, 0)) for a in D["assets"]]
    s = sum(w)
    return [x / s for x in w] if s > 0 else w


def simulate(M: list[list[float]], w: list[float], rebal: str, contrib: float) -> dict:
    """rebal: 'M' 매월 · 'A' 연 1회(12개월마다, 첫 달 제외) · 'N' 없음. contrib=0 → 일시금 1, >0 → 매달 초 contrib 적립(일시금 없음).
    반환: V(월말 잔고), twr(월별 시간가중 수익률), inv(누적 납입)."""
    A = len(w)
    H = [wi * (1.0 if contrib == 0 else 0.0) for wi in w]
    V, twr, inv = [], [], []
    paid = 1.0 if contrib == 0 else 0.0
    for t, r in enumerate(M):
        if contrib > 0:
            for i in range(A):
                H[i] += contrib * w[i]
            paid += contrib
        if t > 0 and (rebal == "M" or (rebal == "A" and t % 12 == 0)):
            tot = sum(H)
            H = [tot * wi for wi in w]
        start = sum(H)
        H = [H[i] * (1 + r[i]) for i in range(A)]
        end = sum(H)
        twr.append(end / start - 1 if start > 0 else 0.0)
        V.append(end)
        inv.append(paid)
    return {"V": V, "twr": twr, "inv": inv}


def _std(x: list[float]) -> float:
    m = sum(x) / len(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def twr_stats(twr: list[float]) -> dict:
    n = len(twr)
    idx, I = [1.0], 1.0
    for r in twr:
        I *= 1 + r
        idx.append(I)
    pk, mdd = idx[0], 0.0
    for v in idx:
        pk = max(pk, v)
        mdd = max(mdd, 1 - v / pk)
    w12 = min(idx[t + 12] / idx[t] - 1 for t in range(n - 11)) if n >= 12 else float("nan")
    return {"cagr": idx[-1] ** (12 / n) - 1, "vol": _std(twr) * math.sqrt(12), "mdd": -mdd, "worst12": w12, "mult": idx[-1]}


def irr_monthly(contrib: float, n: int, final: float) -> float:
    """매달 초 contrib 납입, n개월 뒤 final 의 월 IRR (이분법 — JS 와 같은 100회)."""
    lo, hi = -0.99, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        fv = contrib * sum((1 + mid) ** (n - k) for k in range(n))
        if fv > final:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def dca_stats(sim: dict, contrib: float) -> dict:
    V, inv = sim["V"], sim["inv"]
    n = len(V)
    under = min(V[t] / inv[t] - 1 for t in range(n))
    pk, mdd = 0.0, 0.0
    for v in V:
        pk = max(pk, v)
        mdd = max(mdd, 1 - v / pk)
    return {"irr": (1 + irr_monthly(contrib, n, V[-1])) ** 12 - 1, "mult": V[-1] / inv[-1], "under": under, "bal_mdd": -mdd}


def crisis(D: dict, twr: list[float]) -> dict:
    m = D["months"]
    out = {}
    for name, a, b in D["crises"]:
        if a not in m or b not in m:
            continue
        i, j = m.index(a), m.index(b)
        g = 1.0
        for t in range(i, j + 1):
            g *= 1 + twr[t]
        out[name] = g - 1
    return out


def evaluate(D: dict, wmap: dict, rebal: str = "A", cost: bool = True, contrib: float = 100.0) -> dict:
    M = net_returns(D, cost)
    w = weights(D, wmap)
    lump = simulate(M, w, rebal, 0)
    dca = simulate(M, w, rebal, contrib)
    return {"lump": twr_stats(lump["twr"]), "dca": dca_stats(dca, contrib), "crisis": crisis(D, lump["twr"])}


# ---------- 블록 부트스트랩 (JS 와 같은 난수: mulberry32) ----------

def mulberry32(seed: int):
    s = seed & 0xFFFFFFFF

    def nxt() -> float:
        nonlocal s
        s = (s + 0x6D2B79F5) & 0xFFFFFFFF
        t = s
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return nxt


def quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    p = (len(s) - 1) * q
    lo = math.floor(p)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (p - lo)


def bootstrap(D: dict, wmap: dict, rebal: str = "A", cost: bool = True, P: int = 1000, T: int = 120, L: int = 12, seed: int = 7) -> dict:
    """정상(Politis-Romano) 블록 부트스트랩, 평균 블록 L개월, 원형. 경로마다 일시금 CAGR·적립 배수·TWR MDD."""
    M = net_returns(D, cost)
    w = weights(D, wmap)
    n = len(M)
    rnd = mulberry32(seed)
    cagr, mult, mdd = [], [], []
    for _ in range(P):
        k = math.floor(rnd() * n)
        path = []
        for t in range(T):
            if t > 0:
                k = math.floor(rnd() * n) if rnd() < 1 / L else (k + 1) % n
            path.append(M[k])
        lump = twr_stats(simulate(path, w, rebal, 0)["twr"])
        d = simulate(path, w, rebal, 1.0)
        cagr.append(lump["cagr"])
        mdd.append(lump["mdd"])
        mult.append(d["V"][-1] / d["inv"][-1])
    return {"cagr_med": quantile(cagr, .5), "cagr_p10": quantile(cagr, .1), "mult_med": quantile(mult, .5),
            "mult_p10": quantile(mult, .1), "mdd_med": quantile(mdd, .5), "mdd_p10": quantile(mdd, .1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "check", "extend"])
    ap.add_argument("--ext", type=Path, default=EXT_DEFAULT)
    ap.add_argument("--thru")
    ap.add_argument("--src", type=Path, default=SRC_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    a = ap.parse_args(argv)
    if a.cmd == "extend":
        for r in extend(a.ext, a.thru):
            print(r)
        return 0
    if a.cmd == "build":
        o = build(a.src, a.out, a.ext)
        print(f"{a.out} {len(o['months'])}개월 asof {o['asof']}")
        return 0
    D = json.loads(a.out.read_text(encoding="utf-8"))
    for name, wm in PRESETS.items():
        for rb in "MAN":
            e = evaluate(D, wm, rb)
            L = e["lump"]
            print(f"{name:22s} {rb} CAGR {L['cagr']:.2%} vol {L['vol']:.2%} MDD {L['mdd']:.2%} 최악12m {L['worst12']:.2%} "
                  f"| 적립 IRR {e['dca']['irr']:.2%} 배수 {e['dca']['mult']:.2f} | " + " ".join(f"{k} {v:.1%}" for k, v in e["crisis"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
