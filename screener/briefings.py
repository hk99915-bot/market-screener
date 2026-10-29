"""시간대별 브리핑 (텔레그램).

KR  08:10 premarket_kr  어제 스크리너 + 밤사이 미장 + 밤사이 리포트 → 오늘 관심종목(저장)
KR  10:30/13:30 intraday_kr  외국인·기관 잠정 수급 + 관심종목 수급 여부
KR  16:20 close_kr  (main.run 'KR' 뒤에) 지수·수급 확정 + 마감 코멘트
US  22:30 premarket_us  선물·매크로 + 어제 US 스크리너 + 오늘 국장 결과
US  01:00/03:30 intraday_us  지수·섹터 ETF 진행 중 + 거래대금 상위 등락
US  06:40 close_us  (main.run 'US' 뒤에) 지수·섹터·tone + 국장 시사점
reports  7/9/12/15/19시  신규 리포트 알림(기술 태그 포함)
"""
from __future__ import annotations

import glob
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from . import dart, flows, research, usmarket
from .config import DATA_DIR, REPORT_DIR
from .report import CLASS_KO, send_telegram

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
WATCH = REPORT_DIR / "watchlist_KR.json"


def _esc(x) -> str:
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _latest_signals(market: str) -> pl.DataFrame | None:
    files = sorted(glob.glob(str(REPORT_DIR / "signals" / f"*_{market}.csv")))
    if not files:
        return None
    return pl.read_csv(files[-1], schema_overrides={"symbol": pl.Utf8})


def _kr_prices() -> pl.DataFrame | None:
    """KR 일봉 (분할·병합 조정, 공통 로더) — 20일 지지선 등 지표용."""
    from .prices import load_kr
    px = load_kr()
    return px if len(px) else None


def _pct(x) -> str:
    return "" if x is None else f"{x*100:+.1f}%"


# ───────────── KR 장전 ─────────────

def premarket_kr(send: bool = True) -> str:
    now = datetime.now(KST)
    L = [f"<b>🌅 장전 브리핑</b> · {now:%m/%d(%a) %H:%M}"]

    # 1) 밤사이 미장
    idx = usmarket.snapshot(usmarket.INDICES)
    sec = usmarket.snapshot(usmarket.SECTORS)
    mac = usmarket.snapshot(usmarket.MACRO)
    if idx:
        L.append("")
        L.append("<b>[밤사이 미장]</b> " + " · ".join(
            f"{k} {v['chg']*100:+.1f}%" for k, v in idx.items() if k in ("S&P500", "나스닥", "필라델피아반도체", "러셀2000")))
        tl = usmarket.tone_line(idx, sec, mac)
        if tl:
            L.append(f"→ {_esc(tl)}")
        L += [_esc(x) for x in usmarket.sector_lines(sec, 3)]
        L.append("<b>[국장 시사점]</b>")
        L += ["• " + _esc(x) for x in usmarket.kr_implications(idx, sec, mac)]

    # 1-1) 야간선물 한 줄 (KRX 야간 세션 평균 체결가 → 예상 시초가). 화면·알림 추가 없이 이 한 줄만. 실패해도 브리핑은 계속
    try:
        from . import deriv_hist
        nl = deriv_hist.night_line(deriv_hist.night_futures())
        if nl:
            L.append(_esc(nl))
    except Exception as e:  # noqa: BLE001
        log.warning("야간선물 한 줄 실패: %s", e)

    # 2) 밤사이·아침 리포트: 조용히 수집(알림 없음, 19:10 다이제스트에 포함됨) 후 어제 16:00 이후 발간분 사용
    try:
        store, _ = research.update_store()
    except Exception as e:  # noqa: BLE001
        log.warning("장전 리포트 수집 실패: %s", e)
        store = research.load_store()
    sig = _latest_signals("KR")
    cls_of = {r["symbol"]: r for r in sig.to_dicts()} if sig is not None else {}
    # 10/21: collected_at 문자열 비교는 'backfill …' 행을 전부 '밤사이'로 잡았다 → 발간일(직전 영업일 이후) 기준·백필 제외
    overnight = research.overnight_reports(store, now.date())
    if len(overnight):
        L.append("")
        L.append(f"<b>[밤사이 리포트 {len(overnight)}건]</b>")
        ctp = {r["code"]: r["tp"] for r in research.consensus_tp(store, now.date()).to_dicts()}   # 증권사별 최신 목표가 중앙값
        top = (overnight.group_by("code", "name").agg(pl.len().alias("n"), pl.col("broker").n_unique().alias("b"))
                        .sort(["b", "n"], descending=True).head(8)
                        .with_columns(pl.col("code").replace_strict(ctp, default=None, return_dtype=pl.Float64).alias("tp")))
        for r in top.to_dicts():
            s = cls_of.get(r["code"], {})
            tag = f" · {CLASS_KO.get(s.get('class'), '')} T{s.get('trend_score', 0):.0f}" if s else ""
            up = f" 여력{(r['tp']/s['close']-1)*100:+.0f}%" if s and r["tp"] and s.get("close") else ""
            L.append(f"• {_esc(r['name'])} {r['b']}개 증권사{tag}{up}")

    # 3) 오늘 관심종목 = 어제 신호 ∩ (거래량 확인 또는 리포트 커버)
    watch = []
    if sig is not None:
        rep_codes = set(overnight["code"].to_list()) if len(overnight) else set()
        recent30 = set(store.filter(pl.col("date") >= (now.date() - timedelta(days=30)))["code"].to_list()) if len(store) else set()
        for r in sig.to_dicts():
            reasons = []
            if r["class"] == "TREND_LONG" and r["vol_ratio"] >= 1.5 and r["reversal_risk"] < 60:
                reasons.append("추세+거래량")
            if r["class"] == "PULLBACK_IN_UPTREND" and r["vol_ratio"] < 0.9:
                reasons.append("눌림(거래량 감소)")
            if r["symbol"] in rep_codes:
                reasons.append("밤사이 리포트")
            elif r["symbol"] in recent30 and r["class"] in ("TREND_LONG", "PULLBACK_IN_UPTREND"):
                reasons.append("최근 커버")
            if r["reversal_risk"] >= 75:
                reasons = ["과열 — 추격 금지"] if reasons else []
            if reasons:
                watch.append({"code": r["symbol"], "name": r["name"], "class": r["class"], "trend": r["trend_score"],
                              "why": " · ".join(reasons), "score": len(reasons) * 10 + r["trend_score"] / 10})
        watch.sort(key=lambda x: -x["score"])
        watch = watch[:12]
    L.append("")
    if watch:
        L.append(f"<b>[오늘 관심종목 {len(watch)}]</b> (어제 종가 기준, 매수 추천 아님)")
        for w in watch:
            L.append(f"• {_esc(w['name'])} ({w['code']}) {CLASS_KO.get(w['class'], '')} T{w['trend']:.0f} — {_esc(w['why'])}")
    else:
        L.append("<b>[오늘 관심종목]</b> 조건 충족 없음 (어제 스크리너 결과 없거나 약세장)")
    WATCH.write_text(json.dumps(watch, ensure_ascii=False), encoding="utf-8")

    # 4) 어제~오늘 아침 주요 공시 (관심·리포트·신호 종목)
    try:
        ddf, _ = dart.update(days=2)
        codes = {w["code"] for w in watch}
        codes |= set(store.filter(pl.col("date") >= (now.date() - timedelta(days=30)))["code"].to_list()) if len(store) else set()
        if sig is not None:
            codes |= set(sig["symbol"].to_list())
        dl = dart.brief_lines(ddf, codes, now.date() - timedelta(days=1))
        if dl:
            L.append("")
            L.append(f"<b>[주요 공시 {len(dl)}]</b> (관심·리포트·신호 종목, 어제~오늘)")
            L += ["• " + _esc(x) for x in dl]
    except Exception as e:  # noqa: BLE001
        log.warning("공시 섹션 실패: %s", e)

    if sig is not None:
        n200 = None
        try:
            hist = [json.loads(x) for x in (REPORT_DIR / "breadth_history.jsonl").read_text(encoding="utf-8").splitlines()]
            kr = [h for h in hist if h.get("market") == "KR"]
            if kr:
                n200 = kr[-1]["pct_above200"]
        except Exception:  # noqa: BLE001
            pass
        if n200 is not None and n200 < 0.4:
            L.append(f"⚠ 시장 폭 약함(200일선 위 {n200*100:.0f}%) — 개별 신호 신뢰도 낮음, 비중 보수적으로")

    try:   # 오늘~모레 이벤트 (실적·매크로·만기)
        from .calendar_ev import upcoming
        up = upcoming(2)
        if up:
            L.append("")
            L.append("<b>[이벤트 D-2]</b>")
            L += [f"• {e['date'][5:]} {'⭐' if e.get('imp', 1) >= 3 else ''}{_esc(e['name'])}" + (f" — {_esc(e['note'])}" if e.get("note") else "") for e in up[:8]]
    except Exception as e:  # noqa: BLE001
        log.warning("이벤트 캘린더 실패: %s", e)
    msg = "\n".join(L)
    if send:
        send_telegram(msg)
    return msg


# ───────────── KR 장중 ─────────────

def intraday_kr(send: bool = True, state_key: str = "intraday_snapshot") -> str:
    now = datetime.now(KST)
    closed = now.weekday() < 5 and now.hour * 100 + now.minute >= 1531
    L = [f"<b>📈 {'마감 정리' if closed else '장중 브리핑'}</b> · {now:%m/%d %H:%M} [{'종가 기준' if closed else 'LIVE·잠정'}]"]
    snap = {}
    try:
        snap = flows.intraday_snapshot()
    except Exception as e:  # noqa: BLE001
        log.warning("장중 스냅샷 실패: %s", e)
    try:
        from .live import kr_naver
        idx = kr_naver()
    except Exception:  # noqa: BLE001
        idx = {}
    mf = flows.intraday_market_flows()

    # 1) 지수·등락
    L.append("")
    L.append("<b>[지수]</b>")
    for mkt in ("KOSPI", "KOSDAQ"):
        q, sn = idx.get(mkt, {}), snap.get(mkt, {})
        if not q and not sn:
            continue
        line = f"{mkt} {q.get('last', 0):,.2f} ({q.get('chg', 0)*100:+.2f}%)" if q else mkt
        if sn.get("high") and sn.get("low") and sn.get("prev"):
            line += f" · 고 {(sn['high']/sn['prev']-1)*100:+.1f}% / 저 {(sn['low']/sn['prev']-1)*100:+.1f}%"
        if sn.get("value_mil"):
            line += f" · 대금 {sn['value_mil']/1e6:,.1f}조"
        L.append(line)
        if sn.get("up") is not None:
            tot = (sn.get("up") or 0) + (sn.get("down") or 0)
            L.append(f"  상승 {sn['up']:.0f}(상한 {sn.get('upper') or 0:.0f}) · 하락 {sn['down']:.0f}(하한 {sn.get('lower') or 0:.0f})"
                     + (f" · 하락 비율 {sn['down']/tot*100:.0f}%" if tot else ""))

    # 2) 투자자·프로그램
    L.append("")
    L.append("<b>[수급]</b>")
    for mkt in ("KOSPI", "KOSDAQ"):
        if mf.get(mkt):
            v = mf[mkt]
            L.append(f"{mkt}: 외국인 {v.get('외국인', 0):+,.0f}억 · 기관 {v.get('기관', 0):+,.0f}억 · 개인 {v.get('개인', 0):+,.0f}억")
        sn = snap.get(mkt, {})
        if sn.get("prog_total") is not None:
            L.append(f"  프로그램 {sn['prog_total']:+,.0f}억 (차익 {sn.get('prog_arb') or 0:+,.0f} · 비차익 {sn.get('prog_nonarb') or 0:+,.0f})")
    k = mf.get("KOSPI", {})
    if k.get("외국인") is not None and k.get("기관") is not None:
        f, i2 = k["외국인"], k["기관"]
        L.append("→ " + ("외국인·기관 동반 매수" if f > 0 and i2 > 0 else "외국인·기관 동반 매도" if f < 0 and i2 < 0
                        else f"외국인 {'매수' if f > 0 else '매도'} / 기관 {'매수' if i2 > 0 else '매도'} 엇갈림"))
    if not mf:
        L.append("⚠ 장중 시장 수급을 받지 못했습니다. 확정치는 16:20 마감 브리핑에 포함됩니다.")

    # 3) 시총 상위 종목
    top = (snap.get("KOSPI", {}).get("top") or [])[:10]
    if top:
        L.append("")
        L.append("<b>[시총 상위]</b> " + " · ".join(f"{_esc(t['name'])} {t['chg']:+.1f}%" for t in top if t.get("chg") is not None))

    # 4) 해석 (규칙 기반, 문장형)
    notes = []
    ks, kq = snap.get("KOSPI", {}), idx.get("KOSPI", {})
    chg = kq.get("chg")
    # ① 지수 위치: 장중 고저 범위 안에서 어디에 있나
    if ks.get("high") and ks.get("low") and ks.get("prev") and kq.get("last"):
        hi, lo, pv, la = ks["high"], ks["low"], ks["prev"], kq["last"]
        up_from_low = (la - lo) / pv * 100
        dn_from_high = (hi - la) / pv * 100
        pos = (la - lo) / (hi - lo) if hi > lo else 0.5
        if up_from_low >= 1.0 or (pos >= 0.35 and up_from_low >= 0.8):
            notes.append(f"코스피 {chg*100:+.2f}%, 장중 저점({(lo/pv-1)*100:+.1f}%)에서 <b>{up_from_low:.1f}%p 회복</b>" + (" 마감 — 저점에서 받쳐주는 매수가 있었음" if closed else " — 저점은 일단 지켜지는 중"))
        elif pos <= 0.15:
            notes.append(f"코스피 {chg*100:+.2f}%, <b>{'저점 부근 마감' if closed else '장중 저점 부근'}</b> — " + ("끝까지 매도 우위, 바닥 확인 전" if closed else "매도 압력이 아직 그치지 않음"))
        else:
            notes.append(f"코스피 {chg*100:+.2f}%, 장중 고점 대비 {dn_from_high:.1f}%p 밀린 " + ("채 마감 (범위 중간)" if closed else "상태 (범위 중간)"))
    # ② 누가 팔고 누가 받나
    if k.get("외국인") is not None:
        f, i2, ind = k.get("외국인", 0), k.get("기관", 0), k.get("개인", 0)
        jo = lambda v: f"{v/10000:+.2f}조" if abs(v) >= 10000 else f"{v:+,.0f}억"  # noqa: E731
        if f < -5000 and (i2 > 0 or ind > 0):
            buyers = " · ".join(x for x in (f"기관 {jo(i2)}" if i2 > 0 else "", f"개인 {jo(ind)}" if ind > 0 else "") if x)
            notes.append(f"외국인 현물 <b>{jo(f)}</b>가 하락의 주범, {buyers}가 받아 주는 중")
        elif f > 5000 and i2 > 0:
            notes.append(f"외국인 {jo(f)}·기관 {jo(i2)} 동반 매수 — 수급이 지수를 받치는 중")
        elif f < 0 and i2 < 0 and ind > 0:
            notes.append(f"외국인 {jo(f)}·기관 {jo(i2)} 동반 매도 — 개인({jo(ind)})만 받는 구조, 반등 동력 약함")
        elif f < 0 and i2 < 0 and ind <= 0:
            other = -(f + i2 + ind)   # 세 주체 합의 반대편 = 기타법인(자사주 매입 포함)·기타 — 장중 잠정치는 오차 큼
            notes.append(f"외국인 {jo(f)}·기관 {jo(i2)}·개인 {jo(ind)} 모두 순매도 — 받는 쪽은 기타법인 등 약 {jo(other)} 추정(자사주 매입 가능성). 잠정치라 마감 확정치로 재확인")
    # ③ 프로그램
    arb, nar = ks.get("prog_arb"), ks.get("prog_nonarb")
    if arb is not None and chg is not None:
        if arb > 3000 and chg < -0.01:
            notes.append(f"프로그램 <b>차익 {arb:+,.0f}억</b> — 선물이 과하게 빠졌다 붙으며 차익 매수 유입. 바닥권에서 자주 나오지만, 선물이 되밀리면 매도로 바뀔 수 있음")
        elif arb < -3000:
            notes.append(f"프로그램 차익 {arb:+,.0f}억 — 선물 약세로 차익 매도, 하락 가속 요인")
    if nar is not None and nar < -5000:
        notes.append(f"비차익 {nar:+,.0f}억 — 바스켓(패시브·외국인) 매도 성격")
    elif nar is not None and nar > 5000:
        notes.append(f"비차익 {nar:+,.0f}억 — 바스켓 매수 유입")
    # ④ 시장 폭·대형주
    if ks.get("up") is not None and ks.get("down"):
        r = ks["down"] / max(ks["up"] + ks["down"], 1)
        if r > 0.85:
            notes.append(f"하락 종목 {r*100:.0f}% — 업종 불문 전면 투매")
        elif r < 0.3:
            notes.append(f"상승 종목 {100-r*100:.0f}% — 지수보다 체감 장세가 강함")
    if top and chg is not None:
        big = [t for t in top[:3] if t.get("chg") is not None]
        if big and min(t["chg"] for t in big) / 100 < chg - 0.02:
            worst = sorted(big, key=lambda t: t["chg"])[:2]
            if chg < 0:
                notes.append("대형주가 지수보다 더 빠짐 (" + ", ".join(f"{_esc(t['name'])} {t['chg']:+.1f}%" for t in worst) + ") — 시총 상위 집중 매도")
            else:
                notes.append("대형주가 지수보다 덜 오름 (" + ", ".join(f"{_esc(t['name'])} {t['chg']:+.1f}%" for t in worst) + ") — 상승이 중소형 쪽")
        elif big and min(t["chg"] for t in big) / 100 > chg + 0.01:
            # 상승장에서 '덜 빠짐'은 틀린 문구 (10/28 13:34 코스피 +6.3% 브리핑 오표시)
            notes.append("대형주가 지수보다 덜 빠짐 — 중소형 쪽 매도가 더 큼" if chg < 0 else "대형주가 지수보다 더 오름 — 시총 상위가 상승 주도")
    # ⑤ 역사적 맥락 (검증 스터디)
    if chg is not None and chg <= -0.05:
        try:
            import json as _j
            stu = _j.loads((REPORT_DIR / "studies" / "crash_rebound.json").read_text(encoding="utf-8"))
            dp = (stu.get("conditional") or {}).get("deep_(20일 −15% 이상 하락 중)", {})
            d5 = (stu.get("drop_days") or {}).get("-5%", {})
            if d5.get("d1"):
                notes.append(f"역사적으로 코스피 −5% 이하 날 다음날 상승 {d5['d1']['up']*100:.0f}% (평균 {d5['d1']['avg']*100:+.1f}%)"
                             + (f", 이미 20일 −15% 빠진 상태면 {dp['d1']['up']*100:.0f}%" if dp.get("d1") else "") + " — 1999년 이후")
        except Exception:  # noqa: BLE001
            pass
    if notes:
        L.append("")
        L.append("<b>[해석]</b>")
        L += [f"• {x}" for x in notes]
    try:
        from . import dashboard
        dashboard.put_state(state_key, {"flows": mf, "snap": snap, "notes": notes, "phase": "마감" if closed else "장중 잠정",
                                                  "kospi": kq.get("last"), "kospi_chg": chg})
        if state_key == "close_snapshot":   # 판단 시점 → 마감 사이 변화 (막판 수급)
            from .committee import close_delta
            cur = json.loads(dashboard.STATE.read_text(encoding="utf-8"))
            cur["close_snapshot"]["value"]["delta"] = close_delta()
            dashboard.STATE.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.debug("장중 스냅샷 저장 실패: %s", e)

    fb = fs = ib = is_ = []
    # 5) 관심종목 실시간
    try:
        watch = json.loads(WATCH.read_text(encoding="utf-8")) if WATCH.exists() else []
    except Exception:  # noqa: BLE001
        watch = []
    if watch:
        rows = []
        for w in watch[:12]:
            try:
                q = flows.mobile_stock(w["code"])
                rows.append((w["name"], flows._n(q.get("fluctuationsRatio"))))
            except Exception as e:  # noqa: BLE001
                log.debug("관심종목 시세 %s 실패: %s", w["code"], e)
        rows = [r for r in rows if r[1] is not None]
        if rows:
            rows.sort(key=lambda r: -r[1])
            L.append("")
            L.append("<b>[오늘 관심종목]</b> " + " · ".join(f"{_esc(n)} {c:+.1f}%" for n, c in rows))
    L.append("")
    L.append("<i>종목별 외국인·기관 순매수 순위는 장중 공개 소스가 없어 16:20 마감 브리핑(KRX 확정치)에 포함</i>")
    msg = "\n".join(L)
    if send:
        send_telegram(msg)
    return msg


# ───────────── KR 마감 코멘트 (main.run 뒤에 호출) ─────────────

def close_kr(last: pl.DataFrame, br: dict) -> str:
    d = last["date"].max()
    idx = flows.index_close(d)
    inv = flows.investor_totals(d)
    fnet = flows.net_buy_top(d, "외국인")
    inet = flows.net_buy_top(d, "기관합계")
    big = last.sort("dollar_vol20", descending=True).head(100)
    up = big.sort("ret1", descending=True).head(4).to_dicts()
    dn = big.sort("ret1").head(4).to_dicts()
    sectors = None
    try:  # 업종·시총은 peers_KR.json(분류), 등락은 오늘 last
        peers = {r["s"]: r for r in json.loads((REPORT_DIR / "peers_KR.json").read_text(encoding="utf-8")).get("rows", [])}
        rows = []
        for r in last.select(["symbol", "ret1"]).to_dicts():
            p = peers.get(str(r["symbol"]).split(".")[0])
            if p:
                rows.append({"g": p.get("g"), "mc": p.get("mc"), "ret1": r["ret1"]})
        sectors = flows.sector_moves(rows)
    except Exception as e:  # noqa: BLE001
        log.debug("업종 등락 실패: %s", e)
    lines = flows.close_comment(idx, inv, br, up, dn, fnet, inet, sectors)
    return "\n".join(["<b>🔔 마감 코멘트</b>"] + [_esc(x) for x in lines]) if lines else ""


# ───────────── US ─────────────

def premarket_us(send: bool = True) -> str:
    now = datetime.now(KST)
    L = [f"<b>🇺🇸 미장 개장 전</b> · {now:%m/%d %H:%M}"]
    fut = usmarket.snapshot(usmarket.FUTURES)
    mac = usmarket.snapshot(usmarket.MACRO)
    if fut:
        L.append("선물: " + " · ".join(f"{k} {v['chg']*100:+.2f}%" for k, v in fut.items()))
    if mac:
        L.append("매크로: " + " · ".join(f"{k} {v['last']:,.2f}({v['chg']*100:+.1f}%)" for k, v in mac.items() if k in ("미10년물", "달러인덱스", "WTI", "비트코인")))
    # 오늘 국장 결과
    try:
        hist = [json.loads(x) for x in (REPORT_DIR / "breadth_history.jsonl").read_text(encoding="utf-8").splitlines()]
        kr = [h for h in hist if h.get("market") == "KR"]
        if kr and kr[-1]["date"] == now.date().isoformat():
            b = kr[-1]
            L.append(f"오늘 국장: 상승 {b['adv']}/하락 {b['dec']} · 200일선 위 {b['pct_above200']*100:.0f}%")
    except Exception:  # noqa: BLE001
        pass
    sig = _latest_signals("US")
    if sig is not None:
        tl = sig.filter(pl.col("class") == "TREND_LONG").sort("trend_score", descending=True).head(6)
        pb = sig.filter(pl.col("class") == "PULLBACK_IN_UPTREND").sort("trend_score", descending=True).head(4)
        ov = sig.filter(pl.col("reversal_risk") >= 70).sort("reversal_risk", descending=True).head(4)
        L.append("")
        L.append("<b>[어제 US 스크리너]</b>")
        if len(tl):
            L.append("추세 상승: " + ", ".join(f"{r['symbol']} T{r['trend_score']:.0f}" for r in tl.to_dicts()))
        if len(pb):
            L.append("눌림: " + ", ".join(f"{r['symbol']} RSI{r['rsi14']:.0f}" for r in pb.to_dicts()))
        if len(ov):
            L.append("과열: " + ", ".join(f"{r['symbol']} Risk{r['reversal_risk']:.0f}" for r in ov.to_dicts()))
    msg = "\n".join(L)
    if send:
        send_telegram(msg)
    return msg


def intraday_us(send: bool = True) -> str:
    now = datetime.now(KST)
    L = [f"<b>🇺🇸 미장 진행 중</b> · {now:%m/%d %H:%M} [LIVE]"]
    idx = usmarket.snapshot(usmarket.INDICES)
    sec = usmarket.snapshot(usmarket.SECTORS)
    mac = usmarket.snapshot(usmarket.MACRO)
    if idx:
        L.append(" · ".join(f"{k} {v['chg']*100:+.2f}%" for k, v in idx.items() if k != "VIX"))
        tl = usmarket.tone_line(idx, sec, mac)
        if tl:
            L.append(f"→ {_esc(tl)}")
    L += [_esc(x) for x in usmarket.sector_lines(sec, 3)]
    # 거래대금 상위 300 종목 당일 등락
    try:
        import yfinance as yf
        top = pl.read_csv(REPORT_DIR.parent / "universe" / "us_top.csv").head(300)
        raw = yf.download(top["yf"].to_list(), period="2d", interval="1d", auto_adjust=True, group_by="ticker",
                          progress=False, threads=True, timeout=60)
        mv = []
        for t in top["yf"].to_list():
            try:
                c = raw[t]["Close"].dropna()
                if len(c) >= 2:
                    mv.append((t, float(c.iloc[-1] / c.iloc[-2] - 1)))
            except Exception:  # noqa: BLE001
                continue
        mv.sort(key=lambda x: x[1])
        if mv:
            L.append("")
            L.append("강세: " + ", ".join(f"{t} {r*100:+.1f}%" for t, r in mv[::-1][:6]))
            L.append("약세: " + ", ".join(f"{t} {r*100:+.1f}%" for t, r in mv[:6]))
    except Exception as e:  # noqa: BLE001
        log.warning("US 장중 등락 실패: %s", e)
    msg = "\n".join(L)
    if send:
        send_telegram(msg)
    return msg


def close_us(last: pl.DataFrame, br: dict) -> str:
    idx = usmarket.snapshot(usmarket.INDICES)
    sec = usmarket.snapshot(usmarket.SECTORS)
    mac = usmarket.snapshot(usmarket.MACRO)
    L = ["<b>🔔 미장 마감 코멘트</b>"]
    if idx:
        L.append(" · ".join(f"{k} {v['chg']*100:+.2f}%" for k, v in idx.items() if k != "VIX"))
        tl = usmarket.tone_line(idx, sec, mac)
        if tl:
            L.append(f"→ {_esc(tl)}")
    L += [_esc(x) for x in usmarket.sector_lines(sec, 3)]
    up, dn = usmarket.movers(last)
    if up:
        L.append("거래대금 상위 300 중 강세: " + ", ".join(up))
    if dn:
        L.append("거래대금 상위 300 중 약세: " + ", ".join(dn))
    L.append("<b>[내일 국장 시사점]</b>")
    L += ["• " + _esc(x) for x in usmarket.kr_implications(idx, sec, mac)]
    return "\n".join(L)


# ───────────── 신규 리포트 알림 ─────────────

DIGEST_MARK = REPORT_DIR / "last_digest.txt"


def reports_alert(send: bool = True, max_items: int = 15) -> str:
    """하루 1회 다이제스트: 지난 다이제스트 이후 수집된 모든 리포트 (장전 수집분 포함)."""
    store, _ = research.update_store()
    try:
        dart.update(days=2)   # 공시는 조용히 갱신 (웹 터미널·종목 상세용)
    except Exception as e:  # noqa: BLE001
        log.warning("공시 갱신 실패: %s", e)
    since = DIGEST_MARK.read_text(encoding="utf-8").strip() if DIGEST_MARK.exists() else "0000"
    new = store.filter(pl.col("collected_at") > since)
    new = new.filter(~research.is_backfill())   # 공백 복구(백필) 행은 '오늘의 리포트'·의견 변경 알림에서 제외 (10/21)
    now_s = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    DIGEST_MARK.write_text(now_s, encoding="utf-8")
    if new.is_empty():
        log.info("신규 리포트 없음")
        return ""
    sig = _latest_signals("KR")
    cls_of = {r["symbol"]: r for r in sig.to_dicts()} if sig is not None else {}
    px = _kr_prices()
    sup = {}
    if px is not None:
        sup = {r["code"]: r["support20"] for r in research._support(px).to_dicts()}
    rv = research.revisions(store).filter(pl.col("key").is_in(new["key"].implode()))
    rv_of = {r["key"]: r for r in rv.to_dicts()}
    L = [f"<b>📝 오늘의 리포트 {len(new)}건</b> (지난 다이제스트 이후)"]
    # 여러 증권사가 겹친 종목 먼저, 그다음 최신순
    multi = new.group_by("code").len().rename({"len": "_n"})
    ordered = new.join(multi, on="code", how="left").sort(["_n", "date"], descending=[True, True])
    for r in ordered.head(max_items).to_dicts():
        s = cls_of.get(r["code"], {})
        tag = f" · {CLASS_KO.get(s.get('class'), '')} T{s.get('trend_score', 0):.0f}/M{s.get('momentum_score', 0):.0f}" if s else ""
        extra = ""
        if r["target"] and s.get("close"):
            up = r["target"] / s["close"] - 1
            extra += f" 여력{up*100:+.0f}%"
            sp = sup.get(r["code"])
            if sp and s["close"] > sp:
                extra += f" 손익비{(r['target']-s['close'])/(s['close']-sp):.1f}"
        v = rv_of.get(r["key"], {})
        if v.get("tp_chg") is not None and abs(v["tp_chg"]) > 0.001:
            extra += f" 목표가{'↑' if v['tp_chg'] > 0 else '↓'}{v['tp_chg']*100:+.0f}%"
        if v.get("op_chg"):
            extra += " 의견" + ("상향" if v["op_chg"] > 0 else "하향")
        name = f"<a href=\"{_esc(r['link'])}\">{_esc(r['name'])}</a>" if r["link"] else _esc(r["name"])
        tp = f" TP {r['target']:,.0f}" if r["target"] else ""
        L.append(f"• {name} {_esc(r['broker'])} {_esc(r['opinion'] or '')}{tp}{extra}{tag}")
        L.append(f"   {_esc(r['title'])[:60]}")
    if len(new) > max_items:
        L.append(f"… 외 {len(new)-max_items}건")
    cr = research.crowding(store, datetime.now(KST).date())
    if len(cr):
        L.append("")
        L.append("<b>[리포트 몰림 7일]</b> " + ", ".join(
            f"{_esc(r['name'])}({r['brokers']}사{', TP↑' + str(r['tp_up']) if r['tp_up'] else ''})" for r in cr.head(6).to_dicts()))
    msg = "\n".join(L)
    if send:
        send_telegram(msg)
        try:   # 하루 1회: 센터장 데일리 리서치 브리프 (탑다운 × 바텀업)
            from . import daily, dashboard
            dashboard.build()
            o = json.loads((REPORT_DIR / "daily_brief.json").read_text(encoding="utf-8"))
            send_telegram(daily.telegram_text(o))
        except Exception as e:  # noqa: BLE001
            log.warning("데일리 브리프 전송 실패: %s", e)
    return msg
