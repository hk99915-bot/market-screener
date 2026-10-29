"""수급·지수 데이터 + 마감 코멘트.

확정치(장 마감 후): pykrx (KRX 로그인 필요, KRX_ID/KRX_PW)
  - 지수 OHLCV, 투자자별 거래대금(시장 전체), 종목별 외국인/기관 순매수 상위
잠정치(장중): 네이버 금융 페이지 스크래핑
  - 시장별 투자자 순매수(억원), 외국인/기관 순매수·순매도 상위 종목
모든 함수는 실패 시 빈 값 반환 — 브리핑 전체를 멈추지 않음.
"""
from __future__ import annotations

import html as htmlmod
import logging
import re
from zoneinfo import ZoneInfo
from datetime import datetime, date, timedelta

import requests

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"}
IDX_CODE = {"KOSPI": "1001", "KOSDAQ": "2001"}


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


# ───────────── 확정치 (pykrx) ─────────────

def index_close(d: date) -> dict:
    """{'KOSPI': {'close':..,'chg':..}, 'KOSDAQ': {...}} — d 이전 최근 영업일 기준."""
    out = {}
    try:
        from pykrx import stock  # type: ignore
        for name, code in IDX_CODE.items():
            df = stock.get_index_ohlcv(_ymd(d - timedelta(days=10)), _ymd(d), code)
            if df is None or len(df) < 2:
                continue
            c, p = float(df["종가"].iloc[-1]), float(df["종가"].iloc[-2])
            out[name] = {"close": c, "chg": c / p - 1, "date": df.index[-1].date()}
    except Exception as e:  # noqa: BLE001
        log.warning("지수 조회 실패: %s", e)
    return out


def investor_totals(d: date) -> dict:
    """시장별 투자자 순매수(억원) 확정치. {'KOSPI': {'외국인': -3200, '기관': 1100, '개인': 2000}, ...}"""
    out = {}
    try:
        from pykrx import stock  # type: ignore
        for mkt in ("KOSPI", "KOSDAQ"):
            df = stock.get_market_trading_value_by_investor(_ymd(d), _ymd(d), mkt)
            if df is None or df.empty:
                continue
            col = [c for c in df.columns if "순매수" in str(c)][0]

            def pick(*names):
                for n in names:
                    for idx in df.index:
                        if n in str(idx):
                            return float(df.loc[idx, col]) / 1e8
                return None
            out[mkt] = {"외국인": pick("외국인합계", "외국인"), "기관": pick("기관합계", "기관"), "개인": pick("개인")}
    except Exception as e:  # noqa: BLE001
        log.warning("투자자별 확정치 실패: %s", e)
    return out


def net_buy_top(d: date, investor: str, n: int = 5) -> list[dict]:
    """종목별 순매수 상위·하위 (확정치). investor: '외국인' | '기관합계'"""
    rows = []
    try:
        from pykrx import stock  # type: ignore
        for mkt in ("KOSPI", "KOSDAQ"):
            df = stock.get_market_net_purchases_of_equities(_ymd(d), _ymd(d), mkt, investor)
            if df is None or df.empty:
                continue
            col = [c for c in df.columns if "순매수거래대금" in str(c)][0]
            name_col = [c for c in df.columns if "종목명" in str(c)][0]
            for t, r in df.iterrows():
                rows.append({"code": str(t), "name": r[name_col], "amt": float(r[col]) / 1e8})
    except Exception as e:  # noqa: BLE001
        log.warning("종목별 순매수(%s) 실패: %s", investor, e)
    rows.sort(key=lambda x: x["amt"], reverse=True)
    return rows[:n] + [r for r in rows[::-1][:n] if r["amt"] < 0]


# ───────────── 잠정치 (네이버) ─────────────

def _naver(url: str) -> str:
    r = requests.get(url, headers={**UA, "Referer": "https://finance.naver.com/sise/"}, timeout=20)
    r.raise_for_status()
    r.encoding = "euc-kr"
    return r.text


def intraday_market_flows() -> dict:
    """{'KOSPI': {'개인': +1234, '외국인': -800, '기관': -400}, 'KOSDAQ': {...}} 억원, 잠정."""
    out = {}
    for name in ("KOSPI", "KOSDAQ"):
        try:
            h = _naver(f"https://finance.naver.com/sise/sise_index.naver?code={name}")
            seg = h[h.find("투자자별"):][:3000] if "투자자별" in h else h
            vals = {}
            for who in ("개인", "외국인", "기관"):
                m = re.search(who + r"[\s\S]{0,120}?([+-]?\s*[\d,]+)\s*(?:<[^>]+>\s*)*억", seg)
                if m:
                    vals[who] = float(m.group(1).replace(",", "").replace(" ", ""))
            if vals:
                out[name] = vals
        except Exception as e:  # noqa: BLE001
            log.warning("장중 투자자 %s 실패: %s", name, e)
    if not out:   # 네이버 PC 페이지 종료 → 네이버 모바일 지수 통합 정보의 투자자별 매매동향
        out = _mobile_index_flows()
    if not out:   # 그래도 없으면 KRX(pykrx) 당일 집계 (보통 장 마감 후에만 있음)
        try:
            out = {k: {w: v.get(w) for w in ("개인", "외국인", "기관") if v.get(w) is not None}
                   for k, v in investor_totals(datetime.now(KST).date()).items()}
            if out:
                log.info("장중 시장 수급: KRX 당일 집계 사용")
        except Exception as e:  # noqa: BLE001
            log.warning("KRX 장중 수급 실패: %s", e)
    return out


_MI: dict[str, dict] = {}
M_UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
        "Referer": "https://m.stock.naver.com/"}


def mobile_index(name: str) -> dict:
    """네이버 모바일 지수 통합 정보 (시세·투자자·프로그램·등락 종목 수·시총 상위 구성종목). 실행 중 1회 캐시."""
    if name not in _MI:
        r = requests.get(f"https://m.stock.naver.com/api/index/{name}/integration", headers=M_UA, timeout=15)
        r.raise_for_status()
        _MI[name] = r.json()
    return _MI[name]


def mobile_stock(code: str) -> dict:
    r = requests.get(f"https://m.stock.naver.com/api/stock/{code}/basic", headers=M_UA, timeout=10)
    r.raise_for_status()
    return r.json()


def _n(v):
    try:
        return float(str(v).replace(",", "").replace("+", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def intraday_snapshot() -> dict:
    """장중 브리핑용 시장 스냅샷: 지수 시가·고가·저가·대금, 프로그램 매매, 등락 종목 수, 시총 상위 종목."""
    out = {}
    for name in ("KOSPI", "KOSDAQ"):
        try:
            j = mobile_index(name)
        except Exception as e:  # noqa: BLE001
            log.warning("모바일 지수 %s 실패: %s", name, e)
            continue
        ti = {x.get("code"): x.get("value") for x in j.get("totalInfos") or []}
        pg = j.get("programTrendInfo") or {}
        ud = j.get("upDownStockInfo") or {}
        top = []
        for s in (j.get("enrollStocks") or [])[:12]:
            top.append({"code": s.get("itemCode"), "name": s.get("stockName"), "chg": _n(s.get("fluctuationsRatio")),
                        "px": _n(s.get("closePrice")), "tv": _n(s.get("accumulatedTradingValue"))})
        out[name] = {
            "prev": _n(ti.get("lastClosePrice")), "open": _n(ti.get("openPrice")), "high": _n(ti.get("highPrice")),
            "low": _n(ti.get("lowPrice")), "value_mil": _n(str(ti.get("accumulatedTradingValue", "")).replace("백만", "")),
            "prog_arb": _n(pg.get("indexDifferenceReal")), "prog_nonarb": _n(pg.get("indexBiDifferenceReal")),
            "prog_total": _n(pg.get("indexTotalReal")),
            "up": _n(ud.get("riseCount")), "upper": _n(ud.get("upperCount")), "down": _n(ud.get("fallCount")),
            "lower": _n(ud.get("lowerCount")), "flat": _n(ud.get("steadyCount")), "top": top,
        }
    return out


def _mobile_index_flows() -> dict:
    """m.stock.naver.com 지수 통합 정보에서 개인·외국인·기관 순매수(억원)를 찾는다.
    응답 구조가 바뀌어도 키 이름(personal/foreign/institution)으로 재귀 탐색. 진단용으로 원본 일부를 logs 에 남김."""
    import json as _json
    out: dict[str, dict] = {}
    UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
          "Referer": "https://m.stock.naver.com/"}
    keymap = {"개인": ("personal", "individual"), "외국인": ("foreign",), "기관": ("institution", "organ")}

    def num(v):
        try:
            return float(str(v).replace(",", "").replace("+", ""))
        except ValueError:
            return None

    def walk(o, found):
        if isinstance(o, dict):
            for k, v in o.items():
                kl = k.lower()
                for who, keys in keymap.items():
                    if who not in found and any(x in kl for x in keys) and not isinstance(v, (dict, list)):
                        x = num(v)
                        if x is not None:
                            found[who] = x
                walk(v, found)
        elif isinstance(o, list) and o:
            walk(o[0], found)   # 최신 1건(당일)
        return found

    for name in ("KOSPI", "KOSDAQ"):
        try:
            j = mobile_index(name)
            try:
                from .config import REPORT_DIR
                (REPORT_DIR / "logs").mkdir(parents=True, exist_ok=True)
                (REPORT_DIR / "logs" / f"naver_m_{name}.json").write_text(_json.dumps(j, ensure_ascii=False)[:6000], encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            trend = j.get("dealTrendInfos") or j.get("investorTrend") or j
            vals = walk(trend, {})
            if vals:
                out[name] = vals
        except Exception as e:  # noqa: BLE001
            log.warning("네이버 모바일 %s 수급 실패: %s", name, e)
    if out:
        log.info("장중 시장 수급: 네이버 모바일 %s", out)
    return out


def intraday_rank(investor: str, side: str = "buy", n: int = 7) -> list[dict]:
    """네이버 외국인(9000)/기관(1000) 순매수·순매도 상위 (잠정). side: buy|sell"""
    gubun = {"외국인": "9000", "기관": "1000"}[investor]
    rows = []
    for sosok in ("01", "02"):
        try:
            h = _naver(f"https://finance.naver.com/sise/sise_deal_rank_iframe.naver?sosok={sosok}"
                       f"&investor_gubun={gubun}&type={side}")
        except Exception as e:  # noqa: BLE001
            log.warning("장중 %s %s 순위 실패: %s", investor, side, e)
            continue
        for tr in re.split(r"<tr[\s>]", h, flags=re.I)[1:]:
            m = re.search(r"code=(\d{6})[^>]*>([^<]+)</a>", tr)
            if not m:
                continue
            nums = [x.replace(",", "") for x in re.findall(r">\s*([+-]?[\d,]+)\s*<", tr)]
            amt = float(nums[-1]) if nums else 0.0  # 마지막 숫자열 = 금액(백만원)
            rows.append({"code": m.group(1), "name": htmlmod.unescape(m.group(2)).strip(), "amt_mil": amt})
    if not rows:   # KRX 당일 종목별 순매수(투자자별) — 유가·코스닥 합쳐 정렬
        try:
            from pykrx import stock  # type: ignore
            ymd = datetime.now(KST).strftime("%Y%m%d")
            name = {"외국인": "외국인", "기관": "기관합계"}[investor]
            for mkt in ("KOSPI", "KOSDAQ"):
                df = stock.get_market_net_purchases_of_equities(ymd, ymd, mkt, name)
                if df is None or df.empty:
                    continue
                col = [c for c in df.columns if "순매수거래대금" in str(c)][0]
                for code, r in df.iterrows():
                    rows.append({"code": str(code).zfill(6), "name": str(r.get("종목명", code)),
                                 "amt_mil": float(r[col]) / 1e6})
            rows = [r for r in rows if (r["amt_mil"] > 0) == (side == "buy")]
            if rows:
                log.info("장중 %s %s 순위: KRX 당일 집계 사용", investor, side)
        except Exception as e:  # noqa: BLE001
            log.warning("KRX 장중 순위 실패: %s", e)
    rows.sort(key=lambda x: abs(x["amt_mil"]), reverse=True)
    return rows[:n]


# ───────────── 마감 코멘트 (규칙) ─────────────

def _won(x: float | None) -> str:
    return "-" if x is None else f"{x:+,.0f}억"


def sector_moves(rows: list[dict], n: int = 3, min_k: int = 5) -> tuple[list[tuple], list[tuple]]:
    """업종(g)별 시총 가중 당일 등락 — 종목 min_k 개 미만·'기타' 제외. (업종, 등락, 종목 수, 쏠림) 상위·하위 n.
    쏠림 = 한 종목 시총 비중이 50% 초과면 (종목명, 비중), 아니면 None — 업종 등락이 사실상 한 종목인 경우 표시."""
    agg: dict[str, list] = {}
    for r in rows:
        g, mc, r1 = r.get("g"), r.get("mc"), r.get("ret1")
        if not g or g == "기타" or not mc or r1 is None or mc <= 0:
            continue
        a = agg.setdefault(g, [0.0, 0.0, 0, None, 0.0])
        a[0] += mc * r1
        a[1] += mc
        a[2] += 1
        if mc > a[4]:
            a[3], a[4] = r.get("name"), mc
    out = sorted(((g, a[0] / a[1], a[2], (a[3], a[4] / a[1]) if a[3] and a[4] / a[1] > 0.5 else None)
                  for g, a in agg.items() if a[2] >= min_k), key=lambda x: -x[1])
    if len(out) < 2 * n:
        return out[: len(out) // 2], out[len(out) // 2:][::-1]
    return out[:n], out[-n:][::-1]


def close_comment(idx: dict, inv: dict, br: dict, movers_up: list[dict], movers_dn: list[dict],
                  fnet: list[dict], inet: list[dict], sectors: tuple[list, list] | None = None) -> list[str]:
    L = []
    if idx:
        L.append(" · ".join(f"{k} {v['close']:,.2f} ({v['chg']*100:+.2f}%)" for k, v in idx.items()))
    if inv.get("KOSPI"):
        k = inv["KOSPI"]
        L.append(f"코스피 수급: 외국인 {_won(k.get('외국인'))} · 기관 {_won(k.get('기관'))} · 개인 {_won(k.get('개인'))}")
    if inv.get("KOSDAQ"):
        q = inv["KOSDAQ"]
        L.append(f"코스닥 수급: 외국인 {_won(q.get('외국인'))} · 기관 {_won(q.get('기관'))} · 개인 {_won(q.get('개인'))}")

    # 한 줄 총평
    bits = []
    kc = idx.get("KOSPI", {}).get("chg")
    if kc is not None:
        tone = ("급등" if kc > 0.02 else "강세" if kc > 0.005 else "보합" if kc > -0.005 else "약세" if kc > -0.02 else "급락")
        bits.append(f"코스피 {tone}")
    fk = inv.get("KOSPI", {}).get("외국인")
    ik = inv.get("KOSPI", {}).get("기관")
    if fk is not None and ik is not None:
        if fk > 0 and ik > 0:
            bits.append("외국인·기관 동반 순매수")
        elif fk < 0 and ik < 0:
            bits.append("외국인·기관 동반 순매도 — 개인이 받아냄")
        else:
            bits.append(f"외국인 {'매수' if fk > 0 else '매도'} / 기관 {'매수' if ik > 0 else '매도'} 엇갈림")
    if br:
        a, d = br.get("adv", 0), br.get("dec", 0)
        if kc is not None and a + d:
            if kc > 0 and d > a:
                bits.append("지수는 올랐지만 하락 종목이 더 많음 — 대형주 쏠림")
            elif kc < 0 and a > d:
                bits.append("지수는 내렸지만 상승 종목이 더 많음 — 대형주만 약세")
    if bits:
        L.append("→ " + " · ".join(bits))
    if sectors and sectors[0]:
        f = lambda xs: ", ".join(f"{g} {r * 100:+.1f}%" + (f"({d[0]} 비중 {d[1] * 100:.0f}%)" if d else "")  # noqa: E731
                                 for g, r, _, d in xs)
        L.append("강한 업종(시총 가중): " + f(sectors[0]))
        if sectors[1]:
            L.append("약한 업종(시총 가중): " + f(sectors[1]))
    if movers_up:
        L.append("거래대금 상위 100 중 강세: " + ", ".join(f"{m['name']} {m['ret1']*100:+.1f}%" for m in movers_up))
    if movers_dn:
        L.append("거래대금 상위 100 중 약세: " + ", ".join(f"{m['name']} {m['ret1']*100:+.1f}%" for m in movers_dn))
    if fnet:
        L.append("외국인 순매수 상위: " + ", ".join([f"{r['name']}({r['amt']:+,.0f}억)" for r in fnet if r["amt"] > 0][:5]))
    if inet:
        L.append("기관 순매수 상위: " + ", ".join([f"{r['name']}({r['amt']:+,.0f}억)" for r in inet if r["amt"] > 0][:5]))
    return L
