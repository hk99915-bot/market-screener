"""미국장 보조 데이터 (yfinance): 지수·선물·섹터 ETF 등락, 장중 상위 종목, 마감 코멘트.
미국은 투자자 주체별 수급이 공개되지 않으므로 '섹터 자금 흐름(ETF 등락)'과 '거래량 급증'으로 대체한다.
"""
from __future__ import annotations

import logging

import polars as pl

log = logging.getLogger(__name__)

INDICES = {"S&P500": "^GSPC", "나스닥": "^IXIC", "다우": "^DJI", "러셀2000": "^RUT", "필라델피아반도체": "^SOX", "VIX": "^VIX"}
FUTURES = {"S&P선물": "ES=F", "나스닥선물": "NQ=F"}
SECTORS = {"기술": "XLK", "반도체": "SMH", "커뮤니케이션": "XLC", "임의소비재": "XLY", "금융": "XLF", "헬스케어": "XLV",
           "산업재": "XLI", "에너지": "XLE", "소재": "XLB", "필수소비재": "XLP", "유틸리티": "XLU", "부동산": "XLRE"}
MACRO = {"미10년물": "^TNX", "달러인덱스": "DX-Y.NYB", "원달러": "KRW=X", "WTI": "CL=F", "금": "GC=F", "비트코인": "BTC-USD"}

# 미장 → 국장 연결 (규칙 기반 문장용)
KR_LINK = {
    "필라델피아반도체": "국내 반도체(삼성전자·SK하이닉스·장비주)",
    "반도체": "국내 반도체",
    "나스닥": "국내 성장·기술주",
    "에너지": "국내 정유·에너지",
    "WTI": "국내 정유·항공(역방향)",
    "원달러": "외국인 수급(원화 약세 시 부담)",
}


def snapshot(tickers: dict[str, str]) -> dict[str, dict]:
    """{표시명: {'last':.., 'chg':..}} — 일봉 기준(장중이면 진행 중인 당일봉)."""
    import yfinance as yf
    out = {}
    try:
        raw = yf.download(list(tickers.values()), period="7d", interval="1d", auto_adjust=True,
                          group_by="ticker", progress=False, threads=True, timeout=30)
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance 스냅샷 실패: %s", e)
        return out
    for name, t in tickers.items():
        try:
            c = raw[t]["Close"].dropna()
            if len(c) >= 2:
                out[name] = {"last": float(c.iloc[-1]), "chg": float(c.iloc[-1] / c.iloc[-2] - 1)}
        except Exception:  # noqa: BLE001
            continue
    return out


def _fmt(snap: dict, name: str, pct: bool = True) -> str:
    v = snap.get(name)
    if not v:
        return ""
    if name in ("미10년물",):
        return f"{name} {v['last']:.2f}% ({v['chg']*100:+.1f}%)"
    return f"{name} {v['last']:,.2f} ({v['chg']*100:+.2f}%)"


def sector_lines(sec: dict, n: int = 3) -> list[str]:
    if not sec:
        return []
    srt = sorted(sec.items(), key=lambda kv: kv[1]["chg"], reverse=True)
    up = ", ".join(f"{k} {v['chg']*100:+.1f}%" for k, v in srt[:n])
    dn = ", ".join(f"{k} {v['chg']*100:+.1f}%" for k, v in srt[-n:][::-1])
    return [f"강한 섹터: {up}", f"약한 섹터: {dn}"]


def tone_line(idx: dict, sec: dict, mac: dict) -> str:
    bits = []
    sp = idx.get("S&P500", {}).get("chg")
    nq = idx.get("나스닥", {}).get("chg")
    rut = idx.get("러셀2000", {}).get("chg")
    vix = idx.get("VIX", {}).get("last")
    if sp is not None:
        bits.append("S&P " + ("급등" if sp > 0.015 else "강세" if sp > 0.003 else "보합" if sp > -0.003 else "약세" if sp > -0.015 else "급락"))
    if sp is not None and nq is not None and abs(nq - sp) > 0.007:
        bits.append("기술주 주도" if nq > sp else "기술주 부진")
    if sp is not None and rut is not None and abs(rut - sp) > 0.008:
        bits.append("중소형주 강세(위험선호)" if rut > sp else "중소형주 약세(위험회피)")
    if sec:
        defensive = sum(sec.get(k, {}).get("chg", 0) for k in ("필수소비재", "유틸리티", "헬스케어")) / 3
        cyclical = sum(sec.get(k, {}).get("chg", 0) for k in ("기술", "임의소비재", "금융")) / 3
        if defensive - cyclical > 0.006:
            bits.append("방어주로 자금 이동")
        elif cyclical - defensive > 0.006:
            bits.append("경기민감주 선호")
    if vix is not None:
        bits.append("VIX " + ("25 이상 — 불안" if vix >= 25 else "20 이상 — 경계" if vix >= 20 else "안정"))
    tnx = mac.get("미10년물", {}).get("chg")
    if tnx is not None and abs(tnx) > 0.015:
        bits.append("금리 " + ("급등 — 성장주 부담" if tnx > 0 else "급락 — 성장주 우호"))
    return " · ".join(bits)


def kr_implications(idx: dict, sec: dict, mac: dict) -> list[str]:
    """밤사이 미장 → 오늘 국장 영향 (규칙)."""
    out = []
    sox = idx.get("필라델피아반도체", {}).get("chg")
    if sox is not None and abs(sox) >= 0.015:
        out.append(f"필라델피아반도체 {sox*100:+.1f}% → {KR_LINK['필라델피아반도체']} {'강세' if sox > 0 else '약세'} 출발 가능")
    nq = idx.get("나스닥", {}).get("chg")
    if nq is not None and abs(nq) >= 0.01:
        out.append(f"나스닥 {nq*100:+.1f}% → {KR_LINK['나스닥']} {'우호' if nq > 0 else '부담'}")
    en = sec.get("에너지", {}).get("chg")
    wti = mac.get("WTI", {}).get("chg")
    if wti is not None and abs(wti) >= 0.02:
        out.append(f"WTI {wti*100:+.1f}% → 정유 {'우호' if wti > 0 else '부담'} / 항공 {'부담' if wti > 0 else '우호'}")
    elif en is not None and abs(en) >= 0.015:
        out.append(f"미 에너지 섹터 {en*100:+.1f}% → 국내 정유·에너지 연동 가능")
    krw = mac.get("원달러", {})
    if krw and abs(krw.get("chg", 0)) >= 0.005:
        out.append(f"원달러 {krw['last']:,.0f}원({krw['chg']*100:+.1f}%) → {'외국인 매도 압력 가능' if krw['chg'] > 0 else '외국인 매수 우호'}")
    if not out:
        out.append("밤사이 미장 변동 제한적 — 국내 개별 이슈 중심 장세 예상")
    return out


def movers(last_us: pl.DataFrame | None, n: int = 5) -> tuple[list[str], list[str]]:
    """US 스크리너 최신행에서 거래대금 상위 300 중 등락 상위·하위."""
    if last_us is None or last_us.is_empty():
        return [], []
    big = last_us.sort("dollar_vol20", descending=True).head(300)
    up = big.sort("ret1", descending=True).head(n)
    dn = big.sort("ret1").head(n)
    f = lambda df: [f"{r['symbol']} {r['ret1']*100:+.1f}%" for r in df.to_dicts()]  # noqa: E731
    return f(up), f(dn)
