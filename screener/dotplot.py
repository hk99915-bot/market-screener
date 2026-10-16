"""기명 점도표 (named dot plot) — 데스크별 방향 판단을 자산 × 지평으로 점 하나씩 찍고, 지평이 지나면 채점한다.

    python -m screener.dotplot                 # 오늘 점도표 + 채점 (텔레그램은 환경변수 있을 때만)
    python -m screener.dotplot --no-send       # 텔레그램 없이
    python -m screener.dotplot --score-only    # 채점만
    python -m screener.main --mode dotplot [--no-send]   # 같은 일 (장후 운용회의 끝에도 자동 호출)

자산 (지수·업종 수준만 — 개인 보유·금액 없음)
    KOSPI    코스피 (reports/macro_series.json KOSPI 종가)
    SEMI_KR  국내 반도체 바스켓 — KODEX 반도체(139260, screener.hist) 를 대리로 씀. 없으면 종가 없음으로 두고 채점 보류
    SPX      S&P500 (macro_series SPX)
    US10Y    미 10년 금리 — '매수' = 금리 상승 쪽, '매도' = 금리 하락 쪽 (가격이 아니라 금리 방향)
지평: 5d · 20d (거래일). 데스크마다 점을 찍는 지평이 정해져 있다 (DESK_HORIZONS).

데스크별 규칙 (결정적 — 같은 입력이면 같은 점. 입력 파일이 없으면 그 데스크는 중립 '입력 없음')
    퀀트   급락일 종가(하루 −5% 이하) → 매수2 (entry_signals F, 등급 C) · 실행 대본 신호 '저점 +1% 위 마감' 충족 → 매수1
           · 그 외(20일선 아래 포함)는 중립. 금리(US10Y)는 규칙 없음 → 중립.
    파생   방향 점을 찍을 B 이상 렌즈가 아직 없다 → 항상 중립. 다만 감마 음수 / 선물 백워데이션 / PCR 극단(≥1.3 또는 ≤0.7) 은 사유에 적는다 (코스피·반도체만).
    매크로 바람 점수 ≤ −0.3 → 매도1, ≥ +0.3 → 매수1 (주가지수). 미 10년이 5일 +10bp 넘게 오르고 5.0% 위면 주가지수 매도1 (금리 우선).
           US10Y 자체는 5일 변화 +10bp 초과 → 매수1(상승 지속), −10bp 미만 → 매도1, 그 외 중립.
    리스크 SEMI_KR 20일 실현변동성(연율) ≥ 60% → 매도2, ≥ 40% → 매도1. KOSPI·SPX 는 200일선 아래 & 20일 저점에서 3% 안 → 매도1. US10Y 중립.
    애널   reports/valuation.json 의 금리조정 이익수익률(rate_adj = E/P − 무위험) 3분위: 상위 → 매수1, 하위 → 매도1, 중간 → 중립. 파일·항목 없으면 중립 '검증전'.
           읽는 순서: ① assets[<자산>]·최상위 <자산> 의 'tercile'(top/mid/bottom) 또는 'rate_adj_yield_pct'(0~1 백분위)
                      ② SEMI_KR 만: rows(KR·verified) 의 rate_adj 중앙값 — reports/archive/valuation/ 이력이 30일 이상이면 그 이력의 3분위,
                         아니면 고정 눈금(≥ +3%p 상위 · ≤ 0 하위 · 그 사이 중간, '임시 눈금' 표기). KOSPI·SPX 는 항목이 없어 '검증전'.
    CIO    운용회의 시나리오: 강세 확률 ≥ 45% → 매수1, 약세 ≥ 35% → 매도1, 그 외 중립 (KOSPI·SEMI_KR = committee.json, SPX = committee_us.json). US10Y 중립.
    PB     실행 대본 판정: 관망 → 중립, 분할 매수 → 매수1, 방어 → 매도1. SEMI_KR 은 테마 한도 글라이드(비중 축소 경로)가 켜져 있으면 매도1 '비중 축소 중'
           (켜짐 = 환경변수 SEMI_GLIDE=1 또는 실행 대본 steps 에 '반도체 비중 … 축소' 단계).
    겸이   reports/decisions.json 오늘 entry 의 '나'·'나🔥' 선택: 반도체 종목·ETF → SEMI_KR 매수(나🔥 2, 나 1), 그 외 국내 종목 → KOSPI 매수1,
           미국 종목 → SPX 매수1, 인버스 → 해당 지수 매도1, 현금 → 중립, 제출 없음 → 중립 '제출 없음'. 5d 만 (대결이 5거래일 기준).

근거 태그 (근거 겹침 집계용): rates 금리 · regime 레짐 · signal 신호 · valuation 밸류 · risk 리스크 · flows 수급 · none 없음.

채점 (score) — reports/archive/dotplot/*.json 중 지평이 지난 점:
    실현 방향 = 종가 대비 종가 (US10Y 는 금리 변화 bp). 매수 & 상승 / 매도 & 하락 = 적중.
    중립은 |변화| < 1%(5d) · 2%(20d) 면 적중 (US10Y 는 10bp · 20bp).
    Brier: 상승 확률 p = 0.5 + 부호×확신/6 (매수3 → 1.0, 매도3 → 0.0, 중립 0.5), y = 1(상승)·0(하락)·0.5(보합) → (p−y)² 평균.
    출력 reports/dotplot_score.json + docs/desk_kb/_scoreboard.md 행 추가 (같은 날짜 행은 교체).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import statistics as st
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
ROOT = Path(REPORT_DIR).parent

ASSETS = ("KOSPI", "SEMI_KR", "SPX", "US10Y")
ASSET_KO = {"KOSPI": "코스피", "SEMI_KR": "반도체(KR)", "SPX": "S&P500", "US10Y": "미10년"}
DESKS = ("퀀트", "파생", "매크로", "리스크", "애널", "CIO", "PB", "겸이")
DESK_INITIAL = {"퀀트": "Q", "파생": "D", "매크로": "M", "리스크": "R", "애널": "A", "CIO": "C", "PB": "P", "겸이": "G"}
DESK_HORIZONS = {"퀀트": ("5d", "20d"), "파생": ("5d",), "매크로": ("5d", "20d"), "리스크": ("5d", "20d"),
                 "애널": ("20d",), "CIO": ("20d",), "PB": ("5d", "20d"), "겸이": ("5d",)}
TAG_KO = {"rates": "금리", "regime": "레짐", "signal": "신호", "valuation": "밸류", "risk": "리스크", "flows": "수급", "none": "없음"}
STANCES = ("매수", "중립", "매도")
SIGN = {"매수": 1, "중립": 0, "매도": -1}
H_DAYS = {"5d": 5, "20d": 20}
NEUTRAL_BAND = {"5d": 0.01, "20d": 0.02}          # 주가지수: 중립 적중 범위
NEUTRAL_BAND_BP = {"5d": 10.0, "20d": 20.0}       # US10Y: bp
SEMI_PROXY = "139260"
SEMI_ETFS = {"139260", "091160", "396500", "395160", "449450", "475310", "PSI", "SOXX", "SMH", "SOXL", "SOXQ", "XSD", "SMHX"}
US_SEMIS = {"MU", "SNDK", "NVDA", "AMD", "AVGO", "TSM", "INTC", "QCOM", "ARM", "MRVL", "LRCX", "AMAT", "KLAC", "ASML", "WDC", "STX"}
INVERSE = {"114800", "252670", "251340", "252710", "SQQQ", "SOXS", "SPXU", "SH", "PSQ", "SDS"}


# ───────────────────────────── 입력 ─────────────────────────────
def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def load_inputs(root: Path | None = None) -> dict:
    """reports/*.json 을 있는 만큼 읽는다 (없는 파일은 None)."""
    r = Path(root or ROOT)
    rp = r / "reports"
    return {
        "committee": _read(rp / "committee.json"),
        "committee_us": _read(rp / "committee_us.json"),
        "derivs": _read(rp / "derivs.json"),
        "macro_view": _read(rp / "macro_view.json"),
        "macro_series": _read(rp / "macro_series.json"),
        "bonds": _read(rp / "bonds.json"),
        "valuation": _read(rp / "valuation.json"),
        "decisions": _read(rp / "decisions.json"),
        "gamma": _read(rp / "studies" / "gamma_regime.json"),
        "semi_closes": _semi_closes(),
    }


def _semi_closes() -> list[tuple[str, float]]:
    """KODEX 반도체 종가 (screener.hist, 네트워크 없음). 못 읽으면 빈 리스트."""
    try:
        from . import hist
        px = hist.load(SEMI_PROXY, start=(date.today() - timedelta(days=400)).isoformat())
        if px is None or px.is_empty():
            return []
        px = px.sort("date")
        return [(str(d), float(c)) for d, c in zip(px["date"].to_list(), px["close"].to_list()) if c is not None]
    except Exception as e:  # noqa: BLE001
        log.warning("반도체 대리(139260) 시세 없음: %s", e)
        return []


def _ms_closes(ms: dict | None, key: str) -> list[tuple[str, float]]:
    rows = ((ms or {}).get("series") or {}).get(key) or []
    out = []
    for row in rows:
        try:
            if row[4] is not None:
                out.append((str(row[0])[:10], float(row[4])))
        except Exception:  # noqa: BLE001
            continue
    return sorted(out)


def closes_by_asset(inputs: dict) -> dict[str, list[tuple[str, float]]]:
    ms = inputs.get("macro_series")
    return {"KOSPI": _ms_closes(ms, "KOSPI"), "SPX": _ms_closes(ms, "SPX"), "US10Y": _ms_closes(ms, "US10Y"),
            "SEMI_KR": list(inputs.get("semi_closes") or [])}


def _lows_kospi(ms: dict | None) -> list[tuple[str, float]]:
    rows = ((ms or {}).get("series") or {}).get("KOSPI") or []
    return sorted((str(r[0])[:10], float(r[3])) for r in rows if r[3] is not None)


# ───────────────────────────── 특징 ─────────────────────────────
def _ret(c: list[tuple[str, float]], n: int) -> float | None:
    if len(c) <= n or not c[-1 - n][1]:
        return None
    return c[-1][1] / c[-1 - n][1] - 1


def _chg(c: list[tuple[str, float]], n: int) -> float | None:
    return None if len(c) <= n else c[-1][1] - c[-1 - n][1]


def _sma(c: list[tuple[str, float]], n: int) -> float | None:
    return None if len(c) < n else sum(v for _, v in c[-n:]) / n


def _vol20(c: list[tuple[str, float]]) -> float | None:
    if len(c) < 22:
        return None
    rs = [math.log(c[i][1] / c[i - 1][1]) for i in range(len(c) - 20, len(c)) if c[i - 1][1] > 0 and c[i][1] > 0]
    return st.pstdev(rs) * math.sqrt(252) if len(rs) >= 10 else None


def _px_feats(c: list[tuple[str, float]]) -> dict:
    if not c:
        return {}
    sma200 = _sma(c, 200)
    low20 = min(v for _, v in c[-20:]) if len(c) >= 20 else None
    return {"last": c[-1][1], "date": c[-1][0], "r1": _ret(c, 1), "r5": _ret(c, 5), "r20": _ret(c, 20),
            "vs200": (c[-1][1] / sma200 - 1) if sma200 else None,
            "to_low20": (c[-1][1] / low20 - 1) if low20 else None, "vol20": _vol20(c)}


def _scen(c: dict | None) -> dict:
    out = {"bull": None, "bear": None}
    for s in (c or {}).get("scenarios") or []:
        n, p = str(s.get("name", "")), s.get("prob")
        if p is None:
            continue
        if n.startswith("강세") or "강세" in n[:3]:
            out["bull"] = float(p)
        elif n.startswith("약세") or "약세" in n[:3]:
            out["bear"] = float(p)
    return out


def _valuation_tercile(val: dict | None, asset: str) -> str | None:
    """valuation.json 에서 자산의 3분위(top/mid/bottom). 형식은 애널 쪽 산출에 맞춰 느슨하게 읽는다."""
    if not isinstance(val, dict):
        return None
    node = None
    for path in (("assets", asset), ("rate_adjusted", asset), (asset,), ("index", asset)):
        cur = val
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if isinstance(cur, dict):
            node = cur
            break
    if node is None:
        return _semi_tercile(val) if asset == "SEMI_KR" else None
    t = node.get("tercile") or node.get("rate_adj_tercile")
    if t in ("top", "mid", "bottom"):
        return t
    pct = node.get("rate_adj_yield_pct")
    if isinstance(pct, (int, float)):
        return "top" if pct >= 2 / 3 else "bottom" if pct <= 1 / 3 else "mid"
    return None


def _semi_median_rate_adj(val: dict | None) -> float | None:
    xs = [r.get("rate_adj") for r in (val or {}).get("rows") or []
          if isinstance(r, dict) and r.get("mk", "KR") == "KR" and r.get("verified") and isinstance(r.get("rate_adj"), (int, float))]
    return st.median(xs) if xs else None


def _semi_tercile(val: dict | None, history: list[float] | None = None) -> str | None:
    """반도체 바스켓 중앙 rate_adj 의 3분위. history(이력 중앙값들) 가 30개 이상이면 이력 3분위, 아니면 고정 눈금 (+3%p / 0)."""
    m = _semi_median_rate_adj(val)
    if m is None:
        return None
    if history is None:
        history = _valuation_history()
    if len(history) >= 30:
        hs = sorted(history)
        lo, hi = hs[len(hs) // 3], hs[(2 * len(hs)) // 3]
        return "top" if m >= hi else "bottom" if m <= lo else "mid"
    return "top" if m >= 0.03 else "bottom" if m <= 0.0 else "mid"


def _valuation_history() -> list[float]:
    try:
        hd = ROOT / "reports" / "archive" / "valuation"
        out = []
        for p in sorted(hd.glob("20*.json")):
            m = _semi_median_rate_adj(_read(p))
            if m is not None:
                out.append(m)
        return out
    except Exception:  # noqa: BLE001
        return []


def _picks_today(dec: dict | None, today: str) -> list[dict]:
    out = []
    for it in (dec or {}).get("items") or []:
        if str(it.get("date")) != today or it.get("kind") not in (None, "entry"):
            continue
        for who in ("나", "나🔥"):
            p = (it.get("picks") or {}).get(who)
            if isinstance(p, dict):
                out.append({"who": who, "market": it.get("market") or "KR", **p})
    return out


def _glide_active(cmt: dict | None) -> bool:
    if os.environ.get("SEMI_GLIDE", "").strip() in ("1", "true", "on", "yes"):
        return True
    steps = (((cmt or {}).get("stance") or {}).get("exec") or {}).get("steps") or []
    return any("반도체 비중" in str(s.get("do", "")) and "축소" in str(s.get("do", "")) for s in steps)


def derive_features(inputs: dict, today: str | None = None) -> dict:
    """원시 입력 → 규칙이 보는 숫자만 모은 사전 (테스트에서 직접 만들 수 있는 형태)."""
    today = today or datetime.now(KST).strftime("%Y-%m-%d")
    cmt, der, mv = inputs.get("committee"), inputs.get("derivs"), inputs.get("macro_view")
    closes = closes_by_asset(inputs)
    px = {a: _px_feats(closes.get(a) or []) for a in ASSETS}
    us10 = closes.get("US10Y") or []
    exec_sig = (((cmt or {}).get("stance") or {}).get("exec") or {}).get("signals") or []
    low_ok = any(s.get("ok") and re.search(r"저점.*\+1%", str(s.get("t", ""))) for s in exec_sig)
    gamma = inputs.get("gamma") or {}
    gex = (der or {}).get("gex_bn")
    if gex is None:
        gex = (gamma.get("latest") or {}).get("gex_bn")
    return {
        "date": today,
        "px": px,
        "us10y": {"level": us10[-1][1] if us10 else None, "d5_bp": (_chg(us10, 5) or 0) * 100 if len(us10) > 5 else None},
        "macro_score": (mv or {}).get("score"),
        "macro_label": (mv or {}).get("label"),
        "gex_bn": gex, "basis": ((der or {}).get("fut") or {}).get("basis"), "pcr_oi": (der or {}).get("pcr_oi"),
        "has_committee": cmt is not None, "has_derivs": der is not None or bool(gamma), "has_macro": mv is not None,
        "scen_kr": _scen(cmt), "scen_us": _scen(inputs.get("committee_us")),
        "pb_stance": ((cmt or {}).get("stance") or {}).get("stance"),
        "low_signal_ok": bool(low_ok),
        "glide": _glide_active(cmt),
        "valuation": {a: _valuation_tercile(inputs.get("valuation"), a) for a in ASSETS},
        "has_valuation": inputs.get("valuation") is not None,
        "valuation_scale": "hist" if len(_valuation_history()) >= 30 else "fixed",
        "picks": _picks_today(inputs.get("decisions"), today),
        "has_decisions": inputs.get("decisions") is not None,
    }


# ───────────────────────────── 규칙 ─────────────────────────────
def _dot(desk, asset, stance, conv, reason, tag, refs):
    conv = max(1, min(3, int(conv)))
    return [{"desk": desk, "asset": asset, "stance": stance, "conv": conv, "horizon": h, "reason": reason, "tag": tag, "refs": list(refs)}
            for h in DESK_HORIZONS[desk]]


def _pct(x):
    return "—" if x is None else f"{x * 100:+.1f}%"


def rule_quant(f: dict, asset: str) -> tuple:
    if asset == "US10Y":
        return "중립", 1, "금리 방향 규칙 없음", "none"
    p = f["px"].get(asset) or {}
    r1 = p.get("r1")
    if r1 is not None and r1 <= -0.05:
        return "매수", 2, f"급락일 종가(하루 {_pct(r1)}) — 기다리지 않기(F, 등급 C)", "signal"
    if asset in ("KOSPI", "SEMI_KR") and f.get("low_signal_ok"):
        return "매수", 1, "저점 +1% 위 마감 신호 충족(C — 참고)", "signal"
    if p.get("vs200") is not None and p["vs200"] < 0:
        return "중립", 1, f"200일선 아래({_pct(p['vs200'])}) · 진입 신호 없음", "regime"
    return "중립", 1, "신호 없음", "none"


def rule_derivs(f: dict, asset: str) -> tuple:
    if asset not in ("KOSPI", "SEMI_KR"):
        return "중립", 1, "검증된 렌즈 없음", "none"
    if not f.get("has_derivs"):
        return "중립", 1, "입력 없음(derivs)", "none"
    notes = []
    gex, basis, pcr = f.get("gex_bn"), f.get("basis"), f.get("pcr_oi")
    if gex is not None and gex < 0:
        notes.append(f"감마 음수({gex:,.0f}억) — 흔들림 크지만 방향 없음")
    if basis is not None and basis < 0:
        notes.append(f"선물 백워데이션({basis:+.2f})")
    if pcr is not None and (pcr >= 1.3 or pcr <= 0.7):
        notes.append(f"PCR {pcr:.2f} 극단(검증전)")
    return "중립", 1, (" · ".join(notes) or "특이 없음") + " — B 이상 방향 렌즈 없음", "flows"


def rule_macro(f: dict, asset: str) -> tuple:
    u = f.get("us10y") or {}
    lvl, d5 = u.get("level"), u.get("d5_bp")
    if asset == "US10Y":
        if d5 is None:
            return "중립", 1, "입력 없음(US10Y)", "none"
        if d5 > 10:
            return "매수", 1, f"5일 {d5:+.0f}bp — 상승 지속", "rates"
        if d5 < -10:
            return "매도", 1, f"5일 {d5:+.0f}bp — 하락 지속", "rates"
        return "중립", 1, f"5일 {d5:+.0f}bp — 방향 약함", "rates"
    if lvl is not None and d5 is not None and d5 > 10 and lvl > 5.0:
        return "매도", 1, f"미 10년 {lvl:.2f}% · 5일 {d5:+.0f}bp 상승", "rates"
    s = f.get("macro_score")
    if s is None:
        return "중립", 1, "입력 없음(macro_view)", "none"
    if s <= -0.3:
        return "매도", 1, f"매크로 바람 {s:+.2f}", "regime"
    if s >= 0.3:
        return "매수", 1, f"매크로 바람 {s:+.2f}", "regime"
    return "중립", 1, f"매크로 바람 {s:+.2f} 중립", "regime"


def rule_risk(f: dict, asset: str) -> tuple:
    p = f["px"].get(asset) or {}
    if asset == "US10Y":
        return "중립", 1, "한도 규칙 없음", "none"
    if asset == "SEMI_KR":
        v = p.get("vol20")
        if v is None:
            return "중립", 1, "입력 없음(반도체 시세)", "none"
        if v >= 0.6:
            return "매도", 2, f"20일 실현변동성 {v * 100:.0f}% ≥ 60% — 한도 초과", "risk"
        if v >= 0.4:
            return "매도", 1, f"20일 실현변동성 {v * 100:.0f}% ≥ 40%", "risk"
        return "중립", 1, f"20일 실현변동성 {v * 100:.0f}% 한도 안", "risk"
    vs200, tl = p.get("vs200"), p.get("to_low20")
    if vs200 is None or tl is None:
        return "중립", 1, "입력 없음(시세)", "none"
    if vs200 < 0 and tl <= 0.03:
        return "매도", 1, f"200일선 아래({_pct(vs200)}) · 20일 저점까지 {_pct(tl)}", "risk"
    return "중립", 1, f"200일선 {_pct(vs200)} · 20일 저점 위 {_pct(tl)}", "risk"


def rule_analyst(f: dict, asset: str) -> tuple:
    if asset == "US10Y":
        return "중립", 1, "밸류 규칙 없음", "none"
    t = (f.get("valuation") or {}).get(asset)
    scale = " (임시 눈금, 이력 30일 전)" if asset == "SEMI_KR" and f.get("valuation_scale") == "fixed" else ""
    if t == "top":
        return "매수", 1, "금리조정 이익수익률 상위 3분위" + scale, "valuation"
    if t == "bottom":
        return "매도", 1, "금리조정 이익수익률 하위 3분위" + scale, "valuation"
    if t == "mid":
        return "중립", 1, "금리조정 이익수익률 중간 3분위" + scale, "valuation"
    return "중립", 1, "검증전 (valuation.json 없음)" if not f.get("has_valuation") else "검증전 (자산 항목 없음)", "valuation"


def rule_cio(f: dict, asset: str) -> tuple:
    if asset == "US10Y":
        return "중립", 1, "시나리오 없음", "none"
    s = f.get("scen_us" if asset == "SPX" else "scen_kr") or {}
    b, r = s.get("bull"), s.get("bear")
    if b is None and r is None:
        return "중립", 1, "입력 없음(시나리오)", "none"
    if b is not None and b >= 0.45:
        return "매수", 1, f"강세 확률 {b * 100:.0f}%", "regime"
    if r is not None and r >= 0.35:
        return "매도", 1, f"약세 확률 {r * 100:.0f}%", "regime"
    return "중립", 1, f"강세 {(b or 0) * 100:.0f}% · 약세 {(r or 0) * 100:.0f}% — 과반 없음", "regime"


def rule_pb(f: dict, asset: str) -> tuple:
    if asset == "SEMI_KR" and f.get("glide"):
        return "매도", 1, "비중 축소 중 (테마 한도 글라이드)", "risk"
    if asset == "US10Y":
        return "중립", 1, "실행 대본 대상 아님", "none"
    s = f.get("pb_stance")
    if asset == "SPX" or s is None:
        return "중립", 1, "실행 대본 없음", "none"
    m = {"관망": ("중립", 1, "실행 대본 관망"), "분할 매수": ("매수", 1, "실행 대본 분할 매수"), "방어": ("매도", 1, "실행 대본 방어")}
    st_, c, why = m.get(s, ("중립", 1, f"실행 대본 '{s}'"))
    return st_, c, why, "signal"


def _is_semi(p: dict) -> bool:
    t, n = str(p.get("ticker") or "").upper(), str(p.get("name") or "")
    return t in SEMI_ETFS or t in US_SEMIS or "반도체" in n or re.search(r"SEMI|SOX", n.upper()) is not None


def _is_inverse(p: dict) -> bool:
    return str(p.get("ticker") or "").upper() in INVERSE or "인버스" in str(p.get("name") or "")


def rule_gyeom(f: dict, asset: str) -> tuple:
    if asset == "US10Y":
        return "중립", 1, "대결 대상 아님", "none"
    picks = f.get("picks") or []
    if not picks:
        return "중립", 1, "제출 없음" if f.get("has_decisions") else "입력 없음(decisions)", "none"
    best = None
    for p in picks:
        conv = 2 if p["who"] == "나🔥" else 1
        if p.get("cash"):
            cand = ("중립", 1, f"{p['who']} 현금")
        elif p.get("pending"):
            continue
        else:
            us = str(p.get("market", "KR")).upper() == "US"
            semi, inv = _is_semi(p), _is_inverse(p)
            tgt = "SPX" if us else ("SEMI_KR" if semi else "KOSPI")
            if inv:
                tgt = "SPX" if us else "KOSPI"
            if tgt != asset and not (asset == "KOSPI" and tgt == "SEMI_KR"):
                continue
            label = p.get("name") or p.get("ticker")
            if inv:
                cand = ("매도", conv, f"{p['who']} 인버스 선택({label})")
            elif asset == "KOSPI" and tgt == "SEMI_KR":
                cand = ("중립", 1, f"{p['who']} 반도체 선택 — 코스피 전체 의견 아님")
            else:
                cand = ("매수", conv, f"{p['who']} 선택 {label}")
        if best is None or cand[1] > best[1] or (best[0] == "중립" and cand[0] != "중립"):
            best = cand
    if best is None:
        return "중립", 1, "제출 없음", "none"
    return best[0], best[1], best[2], "signal"


RULES = {"퀀트": rule_quant, "파생": rule_derivs, "매크로": rule_macro, "리스크": rule_risk,
         "애널": rule_analyst, "CIO": rule_cio, "PB": rule_pb, "겸이": rule_gyeom}
REFS = {"퀀트": ["reports/studies/entry_signals.json", "reports/committee.json#stance.exec.signals", "reports/macro_series.json"],
        "파생": ["reports/derivs.json", "reports/studies/gamma_regime.json"],
        "매크로": ["reports/macro_view.json", "reports/macro_series.json#US10Y"],
        "리스크": ["reports/macro_series.json", "data/hist (139260)"],
        "애널": ["reports/valuation.json"], "CIO": ["reports/committee.json#scenarios", "reports/committee_us.json#scenarios"],
        "PB": ["reports/committee.json#stance", "reports/committee.json#stance.exec.steps"], "겸이": ["reports/decisions.json"]}


def make_dots(f: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for a in ASSETS:
        dots = []
        for d in DESKS:
            try:
                stance, conv, reason, tag = RULES[d](f, a)
            except Exception as e:  # noqa: BLE001
                stance, conv, reason, tag = "중립", 1, f"규칙 오류 {type(e).__name__}", "none"
            if stance not in STANCES:
                stance = "중립"
            dots += _dot(d, a, stance, conv, reason, tag if tag in TAG_KO else "none", REFS[d])
        out[a] = dots
    return out


# ───────────────────────────── 집계·출력 ─────────────────────────────
def summarize(dots: list[dict]) -> dict:
    """데스크당 한 표(지평이 여러 개면 첫 지평)로 매수·중립·매도 수와 근거 태그 겹침."""
    seen, cnt, tags = set(), {s: 0 for s in STANCES}, {}
    for d in dots:
        if d["desk"] in seen:
            continue
        seen.add(d["desk"])
        cnt[d["stance"]] += 1
        if d.get("tag") and d["tag"] != "none":
            tags[d["tag"]] = tags.get(d["tag"], 0) + 1
    return {"counts": cnt, "tags": dict(sorted(tags.items(), key=lambda kv: (-kv[1], kv[0])))}


def telegram_lines(dp: dict) -> list[str]:
    lines = []
    for a in ASSETS:
        s = summarize(dp["assets"].get(a) or [])
        c = s["counts"]
        ov = ", ".join(f"{TAG_KO.get(k, k)} {v}회" for k, v in s["tags"].items() if v >= 2) or "없음"
        lines.append(f"점도표 {ASSET_KO[a]}: 매수 {c['매수']}·중립 {c['중립']}·매도 {c['매도']} (근거 겹침: {ov})")
    return lines


def to_markdown(dp: dict) -> str:
    out = [f"# 기명 점도표 {dp['date']}", "",
           "데스크 × 자산 — 칸 = 판정(확신) · 지평. US10Y 는 금리 방향(매수 = 금리 상승). 규칙은 `screener/dotplot.py` 문서문자열.", "",
           "| 데스크 | " + " | ".join(ASSET_KO[a] for a in ASSETS) + " |", "|---|" + "---|" * len(ASSETS)]
    for d in DESKS:
        cells = []
        for a in ASSETS:
            ds = [x for x in dp["assets"].get(a) or [] if x["desk"] == d]
            cells.append(f"{ds[0]['stance']}{ds[0]['conv']} ({'/'.join(x['horizon'] for x in ds)})" if ds else "—")
        out.append(f"| {d} | " + " | ".join(cells) + " |")
    out += ["", "## 합계", ""] + [f"- {ln}" for ln in telegram_lines(dp)] + ["", "## 사유", ""]
    for a in ASSETS:
        out.append(f"### {ASSET_KO[a]}")
        seen = set()
        for x in dp["assets"].get(a) or []:
            if x["desk"] in seen:
                continue
            seen.add(x["desk"])
            out.append(f"- {x['desk']} {x['stance']}{x['conv']} — {x['reason']} [{TAG_KO.get(x['tag'], x['tag'])}]")
        out.append("")
    return "\n".join(out)


def build(send: bool = False, root: Path | None = None, today: str | None = None) -> dict:
    r = Path(root or ROOT)
    inputs = load_inputs(r)
    f = derive_features(inputs, today)
    dp = {"date": f["date"], "asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "assets": make_dots(f),
          "closes": {a: (f["px"].get(a) or {}).get("last") for a in ASSETS},
          "note": "지수·업종 수준 판단만. 개인 보유·금액 없음. 규칙: screener/dotplot.py"}
    dp["summary"] = {a: summarize(dp["assets"][a]) for a in ASSETS}
    (r / "reports").mkdir(parents=True, exist_ok=True)
    (r / "reports" / "dotplot.json").write_text(json.dumps(dp, ensure_ascii=False, indent=1), encoding="utf-8")
    (r / "reports" / "dotplot.md").write_text(to_markdown(dp), encoding="utf-8")
    arch = r / "reports" / "archive" / "dotplot"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / f"{dp['date']}.json").write_text(json.dumps(dp, ensure_ascii=False, indent=1), encoding="utf-8")
    if send:
        try:
            from .config import CFG
            from .report import send_telegram
            if CFG.telegram_token and CFG.telegram_chat:
                send_telegram("\n".join(telegram_lines(dp)))
            else:
                log.info("텔레그램 미설정 — 점도표 전송 생략")
        except Exception as e:  # noqa: BLE001
            log.warning("점도표 텔레그램 실패: %s", e)
    return dp


# ───────────────────────────── 채점 ─────────────────────────────
def _close_on_or_before(series: list[tuple[str, float]], d: str) -> int | None:
    idx = None
    for i, (sd, _) in enumerate(series):
        if sd <= d:
            idx = i
        else:
            break
    return idx


def realized(series: list[tuple[str, float]], d: str, horizon: str, is_yield: bool) -> float | None:
    """d(또는 그 이전 마지막 거래일) 종가 대비 h 거래일 뒤 변화. 아직 h 일이 안 지났으면 None. 금리는 bp."""
    i = _close_on_or_before(series, d)
    n = H_DAYS[horizon]
    if i is None or i + n >= len(series):
        return None
    a, b = series[i][1], series[i + n][1]
    if is_yield:
        return (b - a) * 100
    return b / a - 1 if a else None


def judge(stance: str, conv: int, move: float, horizon: str, is_yield: bool) -> tuple[bool, float]:
    band = NEUTRAL_BAND_BP[horizon] if is_yield else NEUTRAL_BAND[horizon]
    y = 0.5 if move == 0 else (1.0 if move > 0 else 0.0)
    p = 0.5 + SIGN[stance] * conv / 6
    brier = (p - y) ** 2
    if stance == "중립":
        return abs(move) < band, brier
    return (move > 0) if stance == "매수" else (move < 0), brier


def score_archive(archive: list[dict], series: dict[str, list[tuple[str, float]]]) -> dict:
    """순수 함수: 점도표 묶음 + 자산별 종가 시계열 → 데스크별 성적."""
    per: dict[str, dict] = {d: {"n": 0, "hit": 0, "dir_n": 0, "dir_ret_sum": 0.0, "brier_sum": 0.0, "by_asset": {}} for d in DESKS}
    rows = []
    for dp in archive:
        d0 = dp.get("date")
        for a, dots in (dp.get("assets") or {}).items():
            ser = series.get(a) or []
            isy = a == "US10Y"
            for x in dots:
                mv = realized(ser, d0, x["horizon"], isy)
                if mv is None:
                    continue
                ok, br = judge(x["stance"], int(x.get("conv", 1)), mv, x["horizon"], isy)
                P = per.setdefault(x["desk"], {"n": 0, "hit": 0, "dir_n": 0, "dir_ret_sum": 0.0, "brier_sum": 0.0, "by_asset": {}})
                P["n"] += 1
                P["hit"] += int(ok)
                P["brier_sum"] += br
                if x["stance"] != "중립":
                    P["dir_n"] += 1
                    P["dir_ret_sum"] += SIGN[x["stance"]] * mv
                ba = P["by_asset"].setdefault(a, {"n": 0, "hit": 0})
                ba["n"] += 1
                ba["hit"] += int(ok)
                rows.append({"date": d0, "desk": x["desk"], "asset": a, "horizon": x["horizon"], "stance": x["stance"],
                             "conv": x.get("conv", 1), "move": round(mv, 4), "hit": ok})
    out = {}
    for d, P in per.items():
        out[d] = {"n": P["n"], "hit": P["hit"], "hit_rate": round(P["hit"] / P["n"], 3) if P["n"] else None,
                  "avg_signed_ret": round(P["dir_ret_sum"] / P["dir_n"], 4) if P["dir_n"] else None, "dir_n": P["dir_n"],
                  "brier": round(P["brier_sum"] / P["n"], 4) if P["n"] else None,
                  "by_asset": {a: {**v, "hit_rate": round(v["hit"] / v["n"], 3) if v["n"] else None} for a, v in P["by_asset"].items()}}
    return {"desks": out, "scored": rows, "n_scored": len(rows)}


def _scoreboard_row(res: dict, today: str) -> list[str]:
    rows = []
    for d, v in res["desks"].items():
        if not v["n"]:
            continue
        hr = f"{v['hit_rate'] * 100:.0f}%" if v["hit_rate"] is not None else "—"
        ar = f"{v['avg_signed_ret'] * 100:+.2f}%" if v["avg_signed_ret"] is not None else "—"
        br = f"{v['brier']:.3f}" if v["brier"] is not None else "—"
        rows.append(f"| {today} | {d} | {v['n']} | {hr} | {ar} | {br} |")
    return rows


def append_scoreboard(res: dict, today: str, path: Path) -> None:
    header = ["# 데스크 스코어보드", "", "점도표(기명) 채점 — `screener/dotplot.py score`. 적중 = 방향 일치(중립은 소폭 변동). "
              "평균 부호수익 = 매수/매도 점만, 판정 방향 × 실현 변화 (US10Y 는 bp/100). Brier 는 낮을수록 좋음.", "",
              "| 채점일 | 데스크 | n | 적중률 | 평균 부호수익 | Brier |", "|---|---|---|---|---|---|"]
    rows = _scoreboard_row(res, today)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if not any(ln.startswith("| 채점일 |") for ln in lines):
        lines = (lines + [""] if lines else []) + header
    elif not rows:
        return
    lines = [ln for ln in lines if not ln.startswith(f"| {today} |")]
    path.write_text("\n".join(lines + rows) + "\n", encoding="utf-8")


def score(root: Path | None = None, today: str | None = None) -> dict:
    r = Path(root or ROOT)
    today = today or datetime.now(KST).strftime("%Y-%m-%d")
    archive = []
    for p in sorted((r / "reports" / "archive" / "dotplot").glob("*.json")) if (r / "reports" / "archive" / "dotplot").exists() else []:
        o = _read(p)
        if isinstance(o, dict) and o.get("assets"):
            archive.append(o)
    inputs = load_inputs(r)
    res = score_archive(archive, closes_by_asset(inputs))
    res.update({"asof": today, "n_archive": len(archive)})
    (r / "reports").mkdir(parents=True, exist_ok=True)
    (r / "reports" / "dotplot_score.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    append_scoreboard(res, today, r / "docs" / "desk_kb" / "_scoreboard.md")
    return res


def run(send: bool = False) -> dict:
    """main.py --mode dotplot / 장후 운용회의 뒤 호출용: 점도표 + 채점 (예외는 로그만)."""
    dp = build(send=send)
    try:
        score()
    except Exception as e:  # noqa: BLE001
        log.warning("점도표 채점 실패: %s", e)
    return dp


def main():
    ap = argparse.ArgumentParser(description="기명 점도표")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--score-only", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if a.score_only:
        res = score()
        print(json.dumps({k: v for k, v in res["desks"].items() if v["n"]}, ensure_ascii=False, indent=1))
        return
    dp = run(send=not a.no_send)
    print(to_markdown(dp))


if __name__ == "__main__":
    main()
