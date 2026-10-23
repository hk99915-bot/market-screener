"""ISA 비중 실험실 — 데이터 변환 + Python 기준 구현 (화면 계산은 apps-script/tab_isalab.html 의 같은 로직, tests/test_isa_lab.py 가 숫자 대조).

데이터: pb-private analysis/2026-10-15-alloc/monthly_returns_krw.csv (2004-01~2026-10 원화 월수익률, **비용 차감 전**).
그 보고서(run.py DRAG)와 같은 연 비용을 월 1/12씩 빼서 쓴다: S&P·NDX 0.6%, KOSPI200 0.2%, 미국채 0.4%, 금 0.5%, 국고 0.
시장 데이터만 담는다 — 개인 금액·보유 없음. 월 적립 금액은 화면에서 '100(단위 자유)' 기준 배수로만 보여 준다.

사용:  python -m screener.isa_lab build [--src CSV] [--out reports/isa_lab_returns.json]
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

ASSETS = ["SP", "NDX", "KS", "KR3Y", "KR10Y", "UST", "GOLD"]
NAMES = {"SP": "S&P500", "NDX": "나스닥100", "KS": "KOSPI200", "KR3Y": "국고3년", "KR10Y": "국고10년", "UST": "미국채7-10", "GOLD": "금"}
DRAG = {"SP": 0.006, "NDX": 0.006, "KS": 0.002, "KR3Y": 0.0, "KR10Y": 0.0, "UST": 0.004, "GOLD": 0.005}
PRESETS = {
    "현행 ISA": {"SP": 40, "NDX": 10, "KS": 15, "KR3Y": 20, "GOLD": 15},
    "매크로안 (금10·국고25)": {"SP": 40, "NDX": 10, "KS": 15, "KR3Y": 25, "GOLD": 10},
    "나스닥안 (금10·NDX15)": {"SP": 40, "NDX": 15, "KS": 15, "KR3Y": 20, "GOLD": 10},
}
# 위기 구간 (월말 기준 포함 범위) — 2008 은 2026-10-15 배분 보고서와 같은 07-11~09-02
CRISES = [
    ["2008 금융위기", "2007-11", "2009-02"],
    ["2020 코로나", "2020-02", "2020-04"],
    ["2022 금리쇼크", "2022-01", "2022-12"],
    ["2026-06~10", "2026-06", "2026-10"],
]


# 원천 CSV 마지막 행은 월말 라벨(2026-10-31)이지만 실제 데이터는 이 날까지 — asof 는 실제 마지막 날(uxui req-quant-14188e23, 미래 날짜 표기 수정)
DATA_THRU = "2026-10-15"


def _asof(last_label: str) -> str:
    return DATA_THRU if last_label[:7] == DATA_THRU[:7] and last_label > DATA_THRU else last_label


def build(src: Path = SRC_DEFAULT, out: Path = OUT_DEFAULT) -> dict:
    rows = list(csv.DictReader(src.open(encoding="utf-8")))
    hdr = list(rows[0].keys())
    assert hdr[0] == "date" and hdr[1:] == ASSETS, hdr
    months = [r["date"][:7] for r in rows]
    R = {a: [round(float(r[a]), 6) for r in rows] for a in ASSETS}
    o = {
        "schema_version": 1,
        "asof": _asof(rows[-1]["date"]),
        "note": "2026-10 은 10/15 까지의 부분 월. 원화 기준 월수익률(비용 차감 전) — 화면이 drag 를 월 1/12씩 뺀다.",
        "source": "pb-private analysis/2026-10-15-alloc (SPY·QQQ·IEF·GLD × KRW=X, 069500·114260·148070 + 이전 구간 대용치)",
        "assets": ASSETS, "names": NAMES, "drag": DRAG, "months": months, "r": R,
        "presets": PRESETS, "crises": CRISES,
    }
    out.write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return o


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
    ap.add_argument("cmd", choices=["build", "check"])
    ap.add_argument("--src", type=Path, default=SRC_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        o = build(a.src, a.out)
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
