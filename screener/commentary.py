"""규칙 기반 해석 코멘트 (LLM 없음).

종목: 거래량·위치(이평/52주)·과열·추세강도·모멘텀 변화를 문장 조각으로 만들고 우선순위 상위 N개만 사용.
시장: 시장 폭·신고/신저·상승/하락 비율로 한 줄 요약.
코멘트는 '현재 상태 서술'이며 매수·매도 권유가 아님.
"""
from __future__ import annotations


def _g(r: dict, k: str, default=None):
    v = r.get(k)
    return default if v is None else v


def stock_comment(r: dict, max_parts: int = 3) -> str:
    parts: list[tuple[int, str]] = []  # (우선순위 낮을수록 먼저, 문장)
    cls = _g(r, "class", "")
    ret1, ret5 = _g(r, "ret1", 0.0), _g(r, "ret5", 0.0)
    vr = _g(r, "vol_ratio", 1.0)
    rsi, adx = _g(r, "rsi14", 50.0), _g(r, "adx14", 0.0)
    dist = _g(r, "dist_sma20_atr", 0.0)
    fh = _g(r, "from_high52", -1.0)
    c = _g(r, "close", 0.0)
    s20, s50, s200 = _g(r, "sma20"), _g(r, "sma50"), _g(r, "sma200")
    h0, h1, h2 = _g(r, "macd_hist"), _g(r, "macd_hist_p1"), _g(r, "macd_hist_p2")

    # ── 거래량 (가장 중요한 확인 신호) ──
    if vr >= 3 and ret1 > 0:
        parts.append((0, f"거래량 {vr:.0f}배 실린 상승 — 매수세 유입"))
    elif vr >= 3 and ret1 < 0:
        parts.append((0, f"거래량 {vr:.0f}배 실린 하락 — 매물 출회"))
    elif vr >= 1.8 and ret1 > 0.02:
        parts.append((1, f"거래량 {vr:.1f}배 동반 상승"))
    elif vr < 0.7 and ret1 > 0.02 and cls != "PULLBACK_IN_UPTREND":
        parts.append((1, "거래량 없는 상승 — 신뢰도 낮음"))
    if cls == "PULLBACK_IN_UPTREND" and ret1 <= 0.005:
        if vr < 0.8:
            parts.append((0, "거래량 줄며 조정 — 매물 압력 약한 눌림"))
        elif vr > 1.5 and ret1 < 0:
            parts.append((0, "거래량 실린 하락 — 눌림보다 이탈 가능성"))

    # ── 위치: 52주 고점·이평선 ──
    if fh is not None and fh >= -0.02:
        parts.append((1, "52주 신고가권"))
    elif fh is not None and fh <= -0.4 and cls in ("TREND_SHORT", "COUNTERTREND_BOUNCE"):
        parts.append((3, f"52주 고점 대비 {fh*100:.0f}%"))
    if s20 and s50 and c:
        if cls == "PULLBACK_IN_UPTREND":
            if c < s20 and c >= s50:
                parts.append((1, "20일선 이탈, 50일선 지지 시험"))
            elif c < s50:
                parts.append((1, "50일선까지 이탈 — 추세 훼손 주의"))
            elif abs(dist) < 0.5:
                parts.append((1, "20일선 부근 지지 확인 구간"))
    if s200 and c and cls == "COUNTERTREND_BOUNCE" and c < s200:
        parts.append((1, f"200일선 아래 반등 — 위 저항 {(s200 / c - 1) * 100:.0f}%"))

    # ── 과열·이격 ──
    if dist > 2.5:
        parts.append((1, f"20일선과 괴리 {dist:.1f}ATR — 추격 주의"))
    if rsi > 75:
        parts.append((2, f"RSI {rsi:.0f} 과매수"))
    elif rsi < 30:
        parts.append((2, f"RSI {rsi:.0f} 과매도"))
    if ret5 > 0.3:
        parts.append((2, f"5일 {ret5*100:+.0f}% 급등"))

    # ── 추세 강도·모멘텀 변화 ──
    pdi, mdi = _g(r, "pdi", 0.0), _g(r, "mdi", 0.0)
    if adx >= 40 and pdi > mdi:
        parts.append((3, "상승 추세 강도 매우 강함"))
    elif adx >= 30 and mdi > pdi:
        parts.append((2, "하락 방향 힘이 우세(-DI>+DI)"))
    elif adx < 18 and cls in ("TREND_LONG", "COUNTERTREND_BOUNCE"):
        parts.append((3, "추세 강도 약함(횡보성)"))
    if None not in (h0, h1, h2):
        if h0 > h1 > h2 and h0 > 0:
            parts.append((3, "모멘텀 가속"))
        elif h0 < h1 < h2 and h0 > 0 and cls in ("TREND_LONG", "TREND_OVEREXTENDED"):
            parts.append((2, "모멘텀 둔화 시작"))
        elif h0 > h1 > h2 and h0 <= 0 and cls in ("PULLBACK_IN_UPTREND", "COUNTERTREND_BOUNCE"):
            parts.append((2, "하락 모멘텀 약화"))
    if cls == "TREND_LONG" and ret1 <= -0.02:
        parts.append((2, "추세 속 당일 약세"))

    parts.sort(key=lambda x: x[0])
    seen, out = set(), []
    for _, t in parts:
        if t not in seen:
            out.append(t); seen.add(t)
        if len(out) >= max_parts:
            break
    return " · ".join(out)


def market_comment(br: dict) -> str:
    if not br:
        return ""
    p200, p20 = br.get("pct_above200", 0), br.get("pct_above20", 0)
    adv, dec = br.get("adv", 0), br.get("dec", 0)
    nh, nl = br.get("new_high52", 0), br.get("new_low52", 0)
    prev200 = br.get("pct_above200_20d_ago")

    if p200 >= 0.6:
        regime = "강세장(200일선 위 종목 다수)"
    elif p200 >= 0.4:
        regime = "중립 구간"
    else:
        regime = "약세장(200일선 위 종목 소수) — 개별 종목 상승 신호의 신뢰도 낮음"
    bits = [regime]
    if prev200 is not None:
        d = (p200 - prev200) * 100
        if abs(d) >= 5:
            bits.append(f"20일 전보다 {'개선' if d > 0 else '악화'}({d:+.0f}%p)")
    if adv + dec:
        ratio = adv / max(dec, 1)
        if ratio >= 2:
            bits.append("상승 종목 압도")
        elif ratio <= 0.5:
            bits.append("하락 종목 압도")
    if nl > nh * 2 and nl >= 5:
        bits.append("신저가가 신고가보다 많음")
    elif nh > nl * 2 and nh >= 5:
        bits.append("신고가 확산")
    if p20 < 0.3 and p200 >= 0.4:
        bits.append("단기 조정 중")
    return " · ".join(bits)
