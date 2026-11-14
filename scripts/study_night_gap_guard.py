"""가설 ② 야간선물 시초 갭 반납 방지 필터 — 사전등록 백테스트 (연구 전용, 매매 지시 아님).

python3 scripts/study_night_gap_guard.py     → reports/studies/2026-11-14_night_gap_guard.json

## §0 사전등록 (결과 보기 전에 이 파일을 커밋한다)
- 주제: night_gap — 신규 주제(첫 연구, 이전 N 0). 이 연구 m=2, α 0.025. 같은 질문을 다시 보면 N 이 누적된다(kb:quant#30)
- 데이터: `data/deriv/daily.csv` 의 야간 세션(`night_vwap`·`night_vol`, 2025-09-01~) + 선물 시초·종가
- 정의: 야간 갭 = night_vwap / 전일 선물종가 − 1
        시초 갭 = fut_open / 전일 선물종가 − 1
        괴리     = 시초 갭 − 야간 갭
- 가설 m=2, α=0.05/2=0.025 (단측)
  H1: 야간 갭 ≥ +0.5% 인 날 중 **괴리 ≤ −0.3%p**(시초가 야간 상승을 반납) 집단의 갭 반납률
      (종가 < 전일 종가)이 나머지 집단보다 높다 … Fisher 정확검정(양측)
  H2: 같은 두 집단의 시초→종가 손익(시초 추격 진입 손익) 평균이 괴리 집단에서 더 낮다 … Welch 단측
- 분할: IS ≤ 2026-05-31 / OOS ≥ 2026-06-01 (야간 세션 표본이 14개월이라 이 분할은 참고용)
- 등급: A=Bonferroni 통과 + IS·OOS 같은 방향 · B=Bonferroni 통과, 하위 구간 방향 불일치
        C=방향만(보정 전 p<0.10) · F=현행과 구별 안 됨 · 검증전=사전 최소 표본 미달(IS 30건 미만)
- 탐색(등급 대상 아님): 시초 오버슈트형(야간 ≤ +0.5% & 괴리 ≥ +1.5%p), 현물 기준 교차확인,
        야간 갭 문턱 0.3%·1.0%, 11/12~11/13 사례 표.
- **검증 불가(등록에 적어 둔 한계)**: '본장 초반 수급·체결강도' 는 저장소에 분봉·초반 수급 이력이
  없다(선물 투자자별 `fut_frgn` 은 2026-10-16~ 18행). 두 다리(야간 갭·시초 갭)만 검정한다.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from screener import gap_guard as gg  # noqa: E402

CSV = ROOT / "data" / "deriv" / "daily.csv"
OUT = ROOT / "reports" / "studies" / "2026-11-14_night_gap_guard.json"

M = 2
ALPHA = 0.05 / M
IS_END = "2026-05-31"
MIN_NIGHT = gg.MIN_NIGHT_GAP
DIV_BACK = gg.DIV_BACK


def grade(p, subs: dict[str, float | None], n_small: int, alpha: float = ALPHA) -> tuple[str, str]:
    """등급 규칙 — scripts/study_rule_audit.grade() 문턱 + '검증전'은 작은 집단 표본 기준."""
    if p is None:
        return "검증전", "검정 불가(표본 없음)"
    if n_small < 10:
        return "검증전", f"작은 집단 표본 {n_small}건 — 사전 최소 표본 미달"
    if p < alpha:
        if all(s is None or np.sign(s) >= 0 for s in subs.values()):
            return "A", f"Bonferroni 유의(p={p:.4g}) + IS·OOS 같은 방향"
        return "B", f"Bonferroni 유의(p={p:.4g}), 하위 구간 방향 불일치"
    if p < 0.10:
        return "C", f"방향만(p={p:.3f}, Bonferroni α={alpha:.4f} 미달)"
    return "F", f"현행과 구별 안 됨(p={p:.3f})"


def build_table(df: pd.DataFrame, *, prev_night: str = "fut_close", prev_open: str = "fut_close",
                open_col: str = "fut_open", close_col: str = "fut_close",
                min_night: float = MIN_NIGHT, div_back: float = DIV_BACK) -> pd.DataFrame:
    """일별 표 — 야간 갭·시초 갭·괴리·갭 반납·시초→종가 손익.

    prev_night: 야간 VWAP 과 비교할 전일 종가 계열(선물 고정 — night_vwap 이 선물 값이라서)
    prev_open : 시초 갭·갭 반납·당일 손익의 기준 계열(선물 기준 / 현물 기준 교차확인이 갈리는 자리)
    """
    d = df.copy()
    prev_n = d[prev_night].shift(1)
    prev_o = d[prev_open].shift(1)
    d["night_gap"] = [gg.night_gap(a, b) for a, b in zip(d["night_vwap"], prev_n)]
    d["open_gap"] = [gg.open_gap(a, b) for a, b in zip(d[open_col], prev_o)]
    d["div"] = [gg.divergence(a, b) for a, b in zip(d["open_gap"], d["night_gap"])]
    d["give_back"] = [(None if not (c == c) else bool(c < p)) for c, p in zip(d[close_col], prev_o)]
    d["o2c"] = [gg.open_to_close(c, o) for c, o in zip(d[close_col], d[open_col])]
    d["day"] = [(None if not (c == c) else c / p - 1.0) for c, p in zip(d[close_col], prev_o)]
    d = d.dropna(subset=["night_gap", "open_gap", "give_back"])
    d["hold"] = [(ng >= min_night and dv <= div_back) for ng, dv in zip(d["night_gap"], d["div"])]
    d["night_up"] = d["night_gap"] >= min_night
    return d.reset_index(drop=True)


def test(d: pd.DataFrame) -> dict:
    """H1(갭 반납률)·H2(시초→종가 손익) 두 집단 비교."""
    base = d[d["night_up"]]
    a = base[base["hold"]]        # 괴리(반납) — 필터가 보류하는 날
    b = base[~base["hold"]]       # 시초가 확인한 날
    f = gg.fisher_two_by_two([int(x) for x in a["give_back"]], [int(x) for x in b["give_back"]])
    w = _welch(a["o2c"].to_numpy(float), b["o2c"].to_numpy(float))
    return {"n_hold": int(len(a)), "n_go": int(len(b)),
            "give_back_hold": f["rate_a"], "give_back_go": f["rate_b"], "fisher_p": f["p"], "odds": f["odds"],
            "o2c_hold": float(a["o2c"].mean()) if len(a) else None, "o2c_go": float(b["o2c"].mean()) if len(b) else None,
            "o2c_win_hold": float((a["o2c"] > 0).mean()) if len(a) else None,
            "o2c_win_go": float((b["o2c"] > 0).mean()) if len(b) else None,
            "day_hold": float(a["day"].mean()) if len(a) else None, "day_go": float(b["day"].mean()) if len(b) else None,
            "welch": w}


def _welch(a: np.ndarray, b: np.ndarray) -> dict:
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if a.size < 3 or b.size < 3:
        return {"n_a": int(a.size), "n_b": int(b.size), "diff": None, "p_one": None}
    va, vb = a.var(ddof=1) / a.size, b.var(ddof=1) / b.size
    se = math.sqrt(va + vb)
    diff = float(a.mean() - b.mean())
    t = diff / se if se > 0 else 0.0
    return {"n_a": int(a.size), "n_b": int(b.size), "mean_a": float(a.mean()), "mean_b": float(b.mean()),
            "diff": diff, "t": float(t), "p_one": 0.5 * math.erfc(t / math.sqrt(2))}


def run(csv: Path = CSV) -> dict:
    df = pd.read_csv(csv, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    need = ["date", "kospi_open", "kospi_close", "fut_open", "fut_close", "night_vwap", "night_vol"]
    df = df[[c for c in need if c in df.columns]].dropna(subset=["night_vwap", "fut_close", "fut_open"])
    d = build_table(df)
    allres = test(d)
    dates = d["date"].dt.strftime("%Y-%m-%d")
    d = d.assign(day_str=dates)
    is_d = d[d["day_str"] <= IS_END]
    oos_d = d[d["day_str"] > IS_END]
    isres, oosres = test(is_d), test(oos_d)

    h1p = allres["fisher_p"]
    h1_grade = grade(h1p, {"is": (None if isres["give_back_hold"] is None or isres["give_back_go"] is None
                                else isres["give_back_hold"] - isres["give_back_go"]),
                           "oos": (None if oosres["give_back_hold"] is None or oosres["give_back_go"] is None
                                   else oosres["give_back_hold"] - oosres["give_back_go"])},
                     min(allres["n_hold"], allres["n_go"], isres["n_hold"], isres["n_go"]))
    p_h2 = None if (allres["welch"] or {}).get("p_one") is None else 1.0 - allres["welch"]["p_one"]
    h2_grade = grade(p_h2,
                     {"is": (None if (isres["welch"] or {}).get("diff") is None else -isres["welch"]["diff"]),
                      "oos": (None if (oosres["welch"] or {}).get("diff") is None else -oosres["welch"]["diff"])},
                     min(allres["n_hold"], allres["n_go"]))
    h2p = p_h2

    # 현물 기준 교차확인 · 탐색 변형
    try:
        spot = build_table(df.assign(fut_open=df["kospi_open"]), prev_night="fut_close", prev_open="kospi_close",
                           open_col="kospi_open", close_col="kospi_close")
        spot_res = test(spot)
    except Exception:  # noqa: BLE001
        spot_res = None
    variants = {}
    for k, kw in {"min_night_0.003": {"min_night": 0.003}, "min_night_0.010": {"min_night": 0.010},
                  "div_back_-0.005": {"div_back": -0.005}}.items():
        variants[k] = test(build_table(df, **kw))
    # 시초 오버슈트형 — 야간 ≤ +0.5% & 괴리 ≥ +1.5%p
    over = d[(~d["night_up"]) & (d["div"] >= gg.DIV_OVER)]
    over_res = {"n": int(len(over)), "give_back": float(over["give_back"].mean()) if len(over) else None,
                "o2c": float(over["o2c"].mean()) if len(over) else None,
                "o2c_win": float((over["o2c"] > 0).mean()) if len(over) else None,
                "base_o2c": float(d["o2c"].mean()), "base_win": float((d["o2c"] > 0).mean())}
    cases = d[d["day_str"].between("2026-11-10", "2026-11-13")][
        ["day_str", "night_gap", "open_gap", "div", "give_back", "o2c", "day"]]

    return {
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "id": "night_gap_guard",
        "title": "야간선물 갭 · 시초 갭 괴리 → 시초 추격 보류",
        "prereg": {"m": M, "alpha_bonf": round(ALPHA, 5), "is_end": IS_END, "min_night": MIN_NIGHT,
                   "div_back": DIV_BACK, "data": "data/deriv/daily.csv", "rows": int(len(d)),
                   "range": [d["day_str"].min(), d["day_str"].max()],
                   "instruments": "코스피200 선물(최근월) · night_vwap 은 상품군 합계 VWAP(프록시)"},
        "main": {"all": allres, "is": isres, "oos": oosres},
        "hypotheses": {"H1": {"grade": h1_grade[0], "why": h1_grade[1], "p": h1p,
                              "give_back_hold": allres["give_back_hold"], "give_back_go": allres["give_back_go"],
                              "n_hold": allres["n_hold"], "n_go": allres["n_go"]},
                       "H2": {"grade": h2_grade[0], "why": h2_grade[1], "p": h2p,
                              "o2c_hold": allres["o2c_hold"], "o2c_go": allres["o2c_go"],
                              "win_hold": allres["o2c_win_hold"], "win_go": allres["o2c_win_go"]}},
        "grades": {"H1": h1_grade[0], "H2": h2_grade[0]},
        "exploratory": {"spot_basis": spot_res, "variants": variants, "open_overshoot": over_res},
        "cases": cases.round(5).to_dict(orient="records"),
        "limits": [
            "야간 세션 표본 14개월(2025-09-01~) — 실계좌 룰로 옮기려면 모의 ≥60거래일 추적 필요",
            "night_vwap 은 상품군 합계(10종목) VWAP 이라 최근월 선물과 계약이 다르다(프록시)",
            "'본장 초반 수급·체결강도' 입력은 저장소에 이력이 없어 검증 불가(두 다리만 검정)",
            "갭 반납률(종가<전일 종가)과 시초→종가 손익은 다른 질문 — 전자는 강하게 갈리지만 후자는 표본이 작다",
        ],
        "meta": {"run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    }


def main(argv=None) -> int:
    out = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    a = out["main"]["all"]
    print(f"[{out['id']}] 표본 {out['prereg']['rows']}일 ({out['prereg']['range'][0]}~{out['prereg']['range'][1]})")
    print(f"  H1 갭반납률 괴리 {a['give_back_hold']:.3f}(n {a['n_hold']}) vs 확인 {a['give_back_go']:.3f}(n {a['n_go']}) "
          f"Fisher p={a['fisher_p']:.2g} → {out['hypotheses']['H1']['grade']}")
    print(f"  H2 시초→종가 {a['o2c_hold']:+.4f} vs {a['o2c_go']:+.4f} p_one={out['hypotheses']['H2']['p']} → {out['hypotheses']['H2']['grade']}")
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
