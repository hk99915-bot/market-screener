"""VIEW 레지스트리 계산 — views/registry.json 의 렌즈(관점)마다 지금 상태를 읽어 reports/views.json 으로.

판단 종류 3개(entry 진입 · exit 청산/축소 · allocation 자산배분)마다
  게이트(통과/불통과) · 가중 기울기(−1~+1) · 주의(alert) · 참고(reference) 를 나눠 요약한다.
규칙(역할·등급·수명주기)은 views/README.md. 입력 파일이 없거나 깨지면 그 렌즈만 state 'n/a' — 전체는 멈추지 않는다.
개인(personal.*) 렌즈는 공개 저장소에서 판정하지 않는다 (state 'private', 판정은 pb-private views/personal.json).

사용: python -m screener.main --mode views   (또는 python -m screener.views)
"""
from __future__ import annotations

import json
import logging
import statistics as st
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import REPORT_DIR, ROOT
from .kospi_ma import sma_tail

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
REG = ROOT / "views" / "registry.json"
OUT = REPORT_DIR / "views.json"
HIST = REPORT_DIR / "views_hist.json"
DECS = ("entry", "exit", "allocation")
DEC_KO = {"entry": "진입", "exit": "청산·축소", "allocation": "자산배분"}
GATE_OK = {"A", "B", "C"}          # 게이트: 위험 축소 방향은 C 이상 (README)
WEIGHT_OK = {"A", "B"}             # 가중: B 이상


def _j(name: str, default=None):
    try:
        return json.loads((REPORT_DIR / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _today() -> date:
    return datetime.now(KST).date()


def _row(mv: dict, key: str) -> dict:
    return next((r for r in (mv or {}).get("rows") or [] if r.get("key") == key), {}) or {}


# ───────────── 공통 입력 ─────────────
def _kospi(mv: dict) -> dict:
    """코스피 1일·20일 낙폭·200/20일선. macro_series 종가에 macro_view(더 최신이면)를 덮어씀. 네트워크 안 씀."""
    ms = (_j("macro_series.json", {}) or {}).get("series", {}).get("KOSPI") or []
    rows = [(str(r[0]), r[4] if len(r) >= 6 else r[1]) for r in ms if r and r[0]]
    k = _row(mv, "KOSPI")
    if k.get("last") and k.get("date"):
        if rows and rows[-1][0] == k["date"]:
            rows[-1] = (k["date"], k["last"])
        elif not rows or rows[-1][0] < k["date"]:
            rows.append((k["date"], k["last"]))
    c = [x[1] for x in rows if x[1]]
    if len(c) < 30:
        return {}
    last = c[-1]
    return {"date": rows[-1][0], "last": last, "ret1": last / c[-2] - 1, "dd20": last / max(c[-21:]) - 1,
            "sma20": sma_tail(c, 20), "sma200": st.mean(c[-200:]) if len(c) >= 200 else None,
            "vs200": k.get("vs200")}


def _r(state, value=None, bias=None, alert=False, gate=None, note="", asof=None) -> dict:
    return {"state": state, "value": value, "bias": bias, "alert": bool(alert), "gate": gate or {}, "note": note, "asof": asof}


NA = lambda why="입력 없음": _r("n/a", note=why)  # noqa: E731


# ───────────── 렌즈별 판독 (id → 함수(lens, ctx)) ─────────────
def _kr_regime(L, x):
    k = x["k"]
    if not k:
        return NA("코스피 시계열 없음")
    p = L["read"]["params"]
    below200 = (k["vs200"] < 0) if k.get("vs200") is not None else (k["sma200"] is not None and k["last"] < k["sma200"])
    if below200 or k["dd20"] <= p.get("dd20_bear", -0.15):
        s, b = "하락장", "bear"
    elif k["last"] < k["sma20"]:
        s, b = "회복 확인 전", "neutral"
    else:
        s, b = "상승장", "bull"
    return _r(s, {"dd20": round(k["dd20"], 4), "below200": bool(below200), "above20": k["last"] >= k["sma20"]}, b,
              alert=(s == "하락장"), gate={"allocation": "fail" if s == "하락장" else "pass"}, asof=k["date"],
              note="하락장 = 위성 북 노출 상한 낮춤 (수치는 개인 규정)" if s == "하락장" else "")


def _crash_day(L, x):
    k = x["k"]
    if not k:
        return NA("코스피 시계열 없음")
    p = L["read"]["params"]
    hit = k["ret1"] <= p["ret1"] and k["dd20"] <= p["dd20"]
    deep = hit and k["ret1"] <= p["ret1_deep"]
    s = "급락일(−5%)" if deep else "급락일(−3%)" if hit else "해당 없음"
    return _r(s, {"ret1": round(k["ret1"], 4), "dd20": round(k["dd20"], 4)}, "bull" if hit else None, asof=k["date"],
              note="진입한다면 오늘 종가에 — 확인 신호를 기다리면 평균적으로 더 비싸게 삼 (지수 대비 초과수익 근거는 아님)" if hit else "")


def _confirm(L, x):
    sig = ((x["cmt"].get("stance") or {}).get("exec") or {}).get("signals") or []
    if not sig:
        return NA("운용회의 실행 대본 없음")
    on = sum(1 for g in sig if g.get("ok"))
    return _r(f"켜짐 {on}/{len(sig)}", on, None, asof=x["cmt"].get("asof"), note="강등된 신호 — 진입 근거로 인용 금지")


def _flows(L, x):
    ds = x["ds"]
    t = str(_today())
    for key in ("close_snapshot", "intraday_snapshot"):
        sn = ds.get(key) or {}
        f = (((sn.get("value") or {}).get("flows") or {}).get("KOSPI") or {}).get("외국인")
        if f is not None:
            stale = not str(sn.get("at", "")).startswith(t)
            s = "대량 순매도" if f <= L["read"]["params"]["big"] else "순매도" if f <= 0 else "순매수"
            return _r(s, f, "bull" if f > 0 else "bear", asof=sn.get("at"),
                      note=f"{f/1e4:+.2f}조 ({'마감' if key == 'close_snapshot' else '장중'}{', 오늘 아님' if stale else ''})")
    return NA()


def _macro(L, x):
    mv = x["mv"]
    if mv.get("score") is None:
        return NA()
    p, s = L["read"]["params"], mv["score"]
    st_ = "순풍" if s >= p["tail"] else "역풍" if s <= p["head"] else "중립"
    return _r(st_, s, "bull" if st_ == "순풍" else "bear" if st_ == "역풍" else "neutral", asof=mv.get("asof"), note=mv.get("label") or "")


def _breadth(L, x):
    b = x["br"].get("KR")
    if not b:
        return NA()
    p, v = L["read"]["params"], b.get("pct_above200")
    if v is None:
        return NA()
    s = "약함" if v < p["weak"] else "강함" if v >= p["strong"] else "보통"
    return _r(s, round(v, 3), "bear" if s == "약함" else "bull" if s == "강함" else "neutral", asof=b.get("date"),
              note=f"신고가 {b.get('new_high52')} / 신저가 {b.get('new_low52')}")


def _scen(L, x):
    sc = x["cmt"].get("scenarios") or []
    if not sc:
        return NA()
    best = max(sc, key=lambda s: s.get("prob") or 0)
    nm = best["name"].split(" —")[0]
    return _r(f"{nm} 우위", {s["name"].split(" —")[0]: s.get("prob") for s in sc}, None, asof=x["cmt"].get("asof"),
              note=f"근거 '{(x['cmt'].get('scenario_basis') or {}).get('basis', '')}' n={(x['cmt'].get('scenario_basis') or {}).get('n')}")


def _stock_trend(L, x):
    sg = (x["sig"].get("signals") or {})
    t = sg.get("trend_score") or {}
    if not t:
        return NA()
    return _r(t.get("verdict") or "—", (t.get("h20") or {}).get("ic"), None, asof=x["sig"].get("asof"), note="h20 IC")


def _absmom(L, x):
    r = ((x["lab"].get("results") or {}).get("DUAL_MOMENTUM_INDEX") or {})
    s = r.get("state") or {}
    if not r:
        return NA()
    return _r(("지수 보유" if s.get("hold") else "현금") if s else "상태 없음", s.get("k12m"), None, asof=s.get("date"), note=f"lab 등급 {r.get('grade')}")


def _gamma(L, x):
    d = x["der"]
    if d.get("gex_bn") is None:
        return NA()
    neg = d["gex_bn"] < 0
    return _r("감마 음수" if neg else "감마 양수", d["gex_bn"], None, alert=neg, asof=d.get("asof") or d.get("date"),
              note=f"풋/콜 OI {d.get('pcr_oi')} · ATM IV {d.get('atm_iv')} · RV20 {d.get('rv20')}" + (" — 흔들림 큼, 사이즈 주의" if neg else ""))


def _ai_credit(L, x):
    a = (x["bonds"].get("ai_credit") or {})
    al = a.get("alert") or {}
    if not a or al.get("lv") is None:
        return NA()
    lv = int(al["lv"])
    stale = a.get("asof") and (_today() - date.fromisoformat(str(a["asof"])[:10])).days > 5
    s = "경계" if lv >= 2 else "주의" if lv >= 1 else "정상"
    return _r(s, lv, "bear" if lv >= 1 else None, alert=(lv >= L["read"]["params"]["warn_lv"] and not stale), asof=a.get("asof"),
              note=("오래된 값 — " if stale else "") + str(al.get("line") or "")[:160])


def _sb_corr(L, x):
    c = ((x["bonds"].get("corr") or {}).get("IEF_SPX") or {}).get("c250")
    if c is None:
        return NA()
    s = "같이 움직임" if c > L["read"]["params"]["pos"] else "헤지 작동"
    return _r(s, c, None, asof=x["bonds"].get("asof"), note="장기채보다 단기채·현금" if s == "같이 움직임" else "")


def _us10y(L, x):
    r = _row(x["mv"], "US10Y")
    if r.get("last") is None:
        return NA()
    d20 = r.get("d20")
    bp = d20 * 100 if d20 is not None and abs(d20) < 5 else d20   # macro_view 의 d20 은 %p 단위
    up = L["read"]["params"]["up_bp"]
    s = "급등" if bp is not None and bp >= up else "급락" if bp is not None and bp <= -up else "보합"
    return _r(s, {"level": r["last"], "d20_bp": round(bp, 1) if bp is not None else None}, "bear" if s == "급등" else "bull" if s == "급락" else "neutral", asof=r.get("date"))


def _carry(L, x):
    c = x["jp"].get("carry") or {}
    if c.get("chg5") is None:
        return NA()
    hit = bool(c.get("flag")) or c["chg5"] <= L["read"]["params"]["chg5"]
    return _r("경계" if hit else "평온", c["chg5"], "bear" if hit else None, alert=hit, asof=x["jp"].get("date"))


def _jp_semi(L, x):
    g = next((g for g in x["jp"].get("groups") or [] if g.get("id") == "equip"), None)
    if not g or (g.get("jp") or {}).get("chg1") is None:
        return NA()
    v = g["jp"]["chg1"]
    return _r("일본 장비 강세" if v > 0 else "일본 장비 약세", v, None, asof=x["jp"].get("date"), note=f"60일 상관 {g.get('corr_kr')}")


def _chains(L, x):
    ch = x["chains"]
    if not ch:
        return NA()
    p = L["read"]["params"]
    ow = [c["name"] for c in ch.values() if (c.get("score") or 0) >= p["ow"]]
    uw = [c["name"] for c in ch.values() if c.get("score") is not None and c["score"] <= p["uw"]]
    return _r(f"확대 {len(ow)} / 축소 {len(uw)}", {"ow": ow[:5], "uw": uw[:5]}, None, note=("확대: " + ", ".join(ow[:3])) if ow else "")


def _ideas(L, x):
    tr = ((x["cmt"].get("track") or {}).get("summary") or {})
    h = tr.get("h5")
    if not h:
        return _r("채점 전", None, None, asof=x["cmt"].get("asof"), note="5거래일 뒤부터 채점")
    return _r(f"채점 {h['n']}회 · 5일 초과 {h['long_avg']*100:+.1f}%", h, None, asof=x["cmt"].get("asof"),
              note="표본 부족 — 재등급 전" if h["n"] < L["read"]["params"]["min_n"] else "재등급 대상")


def _events(L, x):
    cal = x["cal"]
    p, t = L["read"]["params"], _today()
    big = []
    for e in cal:
        try:
            d = date.fromisoformat(e["date"])
        except Exception:  # noqa: BLE001
            continue
        if t <= d <= t + timedelta(days=p["days"]) and (e.get("imp") or 1) >= p["imp"]:
            big.append(e)
    tod = [e for e in big if e["date"] == str(t)]
    s = "당일 있음" if tod else f"7일 안 {len(big)}건" if big else "없음"
    return _r(s, len(big), None, alert=bool(tod), note=", ".join(f"{e['date'][5:]} {e.get('name', '')}" for e in big[:4]))


def _atr(L, x):
    return _r("종목별", None, None, gate={"exit": "종목별"}, note="보유 종목별 손절선은 운용회의·종목 상세에서 판정 (공개 화면엔 보유 없음)")


def _us_regime(L, x):
    s_, v = _row(x["mv"], "SPX"), _row(x["mv"], "VIX")
    if s_.get("last") is None:
        return NA()
    vix = v.get("last")
    corr = (s_.get("vs50") or 0) < 0 and (s_.get("chg20") or 0) < -0.05
    s = "조정" if corr else "변동성 높음" if vix and vix >= L["read"]["params"]["vix_hi"] else "정상"
    return _r(s, {"vs50": s_.get("vs50"), "chg20": s_.get("chg20"), "vix": vix}, "bear" if s != "정상" else "neutral", asof=s_.get("date"))


def _private(L, x):
    return _r("private", None, None, note="판정은 비공개 저장소 views/personal.json")


def _cand(L, x):
    return _r("후보", None, None, note="가중 0 — 사전등록·검증 전")


EVAL = {"kr_regime": _kr_regime, "crash_day_close": _crash_day, "confirm_signals": _confirm, "foreign_flow": _flows,
        "macro_wind": _macro, "breadth_kr": _breadth, "scenario_base_rate": _scen, "stock_trend_score": _stock_trend,
        "index_abs_momentum": _absmom, "options_gamma": _gamma, "gamma_regime": _gamma, "ai_credit": _ai_credit, "stock_bond_corr": _sb_corr,
        "us10y": _us10y, "yen_carry": _carry, "japan_semi_lead": _jp_semi, "supply_chain": _chains,
        "committee_ideas": _ideas, "event_calendar": _events, "atr_stop": _atr, "us_regime": _us_regime}


def _breadth_last() -> dict:
    out = {}
    try:
        for ln in (REPORT_DIR / "breadth_history.jsonl").read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                out[r.get("market")] = r
    except Exception:  # noqa: BLE001
        pass
    return out


def _ctx() -> dict:
    mv = _j("macro_view.json", {}) or {}
    return {"mv": mv, "k": _kospi(mv), "cmt": _j("committee.json", {}) or {}, "ds": _j("dashboard_state.json", {}) or {},
            "br": _breadth_last(), "sig": _j("signal_scores.json", {}) or {}, "lab": _j("lab.json", {}) or {},
            "der": _j("derivs.json", {}) or {}, "bonds": _j("bonds.json", {}) or {}, "jp": _j("japan.json", {}) or {},
            "chains": (_j("chains_view.json", {}) or {}).get("chains") or {}, "cal": (_j("calendar.json", {}) or {}).get("events") or []}


# ───────────── 레지스트리 점검 (수명주기 규칙 위반을 숨기지 않고 표시) ─────────────
def lint(reg: dict, today: date | None = None) -> list[str]:
    t = today or _today()
    out = []
    for L in reg.get("lenses", []):
        g = (L.get("evidence") or {}).get("grade")
        for d, role in (L.get("roles") or {}).items():
            if role == "weight" and g not in WEIGHT_OK:
                out.append(f"{L['id']}: {DEC_KO.get(d, d)} 가중인데 등급 {g} (B 이상 필요)")
            if role == "gate" and g not in GATE_OK:
                out.append(f"{L['id']}: {DEC_KO.get(d, d)} 게이트인데 등급 {g} (C 이상 필요)")
            if role in ("gate", "weight") and L.get("status") in ("후보", "사전등록", "강등", "폐기"):
                out.append(f"{L['id']}: 상태 '{L.get('status')}' 인데 {DEC_KO.get(d, d)} {role}")
        try:
            if L.get("review_by") and date.fromisoformat(L["review_by"]) < t:
                out.append(f"{L['id']}: 재검토 기한 {L['review_by']} 지남")
        except ValueError:
            out.append(f"{L['id']}: review_by 날짜 형식 오류")
        hd = sorted(date.fromisoformat(h["date"]) for h in L.get("history") or [] if h.get("date"))
        if any((b - a).days < 7 for a, b in zip(hd, hd[1:])):
            out.append(f"{L['id']}: 7일 안에 변경 2회 이상 (주 1회 규칙)")
    for o in reg.get("overrides") or []:
        if not o.get("expires"):
            out.append(f"{o.get('id')}: 이벤트 예외에 만료일 없음 — 무효 처리")
    return out


def _active_overrides(reg: dict, t: date) -> tuple[list, list]:
    on, off = [], []
    for o in reg.get("overrides") or []:
        try:
            ok = bool(o.get("expires")) and date.fromisoformat(o["created"]) <= t <= date.fromisoformat(o["expires"])
        except Exception:  # noqa: BLE001
            ok = False
        (on if ok else off).append(o)
    return on, off


# ───────────── 요약 ─────────────
def _summary(lenses: list[dict], ovr: list[dict]) -> dict:
    out = {}
    for d in DECS:
        gates, wts, alerts, refs, priv = [], [], [], [], []
        for L in lenses:
            role = (L.get("roles") or {}).get(d, "none")
            base = {"id": L["id"], "name": L["name_ko"], "state": L["state"], "grade": L["grade"]}
            if role == "gate":
                if L["state"] == "private":
                    priv.append(base)
                else:
                    gates.append({**base, "result": L["gate"].get(d) or ("n/a" if L["state"] == "n/a" else "pass")})
            elif role == "weight":
                sgn = {"bull": 1, "bear": -1, "neutral": 0}.get(L.get("bias"))
                wts.append({**base, "sign": sgn})
            elif role == "alert":
                if L.get("alert"):
                    alerts.append({**base, "line": L.get("note") or L["state"]})
            elif role == "reference":
                refs.append(base)
        live = [w["sign"] for w in wts if w["sign"] is not None]
        for o in ovr:
            if o.get("scope") in (d, "all"):
                alerts.append({"id": o["id"], "name": "이벤트 예외", "state": "예외", "grade": "—", "line": o.get("line", ""), "expires": o.get("expires")})
        fails = [g for g in gates if g["result"] == "fail"]
        passes = [g for g in gates if g["result"] == "pass"]
        out[d] = {"label": DEC_KO[d], "gate": "fail" if fails else "pass" if passes else "n/a" if gates else "없음",
                  "gates": gates, "private_gates": priv, "tilt": round(sum(live) / len(live), 2) if live else None,
                  "weights": wts, "alerts": alerts, "reference": refs}
    return out


def _changes(cur: dict, hist: dict, today: str) -> list[str]:
    """직전 '다른 날짜' 기록 대비: 게이트 뒤집힘·새 주의. committee 텔레그램 한 줄에 씀."""
    prev_days = sorted(d for d in hist.get("days", {}) if d < today)
    if not prev_days:
        return []
    p = hist["days"][prev_days[-1]]
    out = []
    for d in DECS:
        pg = {g["id"]: g["r"] for g in (p.get("gates") or {}).get(d, [])}
        for g in cur[d]["gates"]:
            if g["id"] in pg and pg[g["id"]] != g["result"] and "n/a" not in (pg[g["id"]], g["result"]):
                out.append(f"{DEC_KO[d]} 게이트 {g['name']}: {pg[g['id']]}→{g['result']}")
        pa = set((p.get("alerts") or {}).get(d, []))
        for a in cur[d]["alerts"]:
            if a["id"] not in pa:
                out.append(f"{DEC_KO[d]} 주의 새로: {a['name']}")
    return out


def compact(v: dict | None = None) -> dict:
    """PB 판단 기록(decisions.json)에 붙일 작은 스냅샷: 렌즈별 상태·방향만."""
    v = v or (_j("views.json", {}) or {})
    return {"asof": v.get("asof"), "lenses": {L["id"]: {"s": L["state"], "b": L.get("bias")} for L in v.get("lenses") or []
                                             if L["state"] not in ("private", "후보")}}


def build() -> dict:
    reg = json.loads(REG.read_text(encoding="utf-8"))
    x = _ctx()
    t = _today()
    lenses = []
    for L in reg.get("lenses", []):
        fam = L.get("family")
        try:
            fn = _private if fam == "personal" else _cand if L.get("status") == "후보" else EVAL.get(L["id"])
            r = fn(L, x) if fn else NA("판독 함수 없음")
        except Exception as e:  # noqa: BLE001
            log.info("렌즈 %s 실패: %s", L["id"], e)
            r = NA(f"판독 실패: {type(e).__name__}")
        ev = L.get("evidence") or {}
        lenses.append({"id": L["id"], "name_ko": L["name_ko"], "family": fam, "status": L.get("status"), "grade": ev.get("grade"),
                       "evidence_src": ev.get("source"), "roles": L.get("roles") or {}, "review_by": L.get("review_by"), **r})
    on, off = _active_overrides(reg, t)
    summ = _summary(lenses, on)
    hist = _j("views_hist.json", {"days": {}}) or {"days": {}}
    hist.setdefault("days", {})
    changes = _changes(summ, hist, str(t))
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "date": str(t), "registry_updated": reg.get("updated"),
           "summary": summ, "changes": changes, "lenses": lenses,
           "overrides": {"active": on, "expired": [o for o in off if o.get("expires") and o["expires"] < str(t)][-5:]},
           "lifecycle": {s: [L["id"] for L in reg.get("lenses", []) if L.get("status") == s] for s in reg.get("status_doc") or []},
           "lint": lint(reg, t),
           "how_to_use": "게이트 불통과면 그 판단 안 함 · 가중은 B 이상 렌즈만 합산 · 주의는 사이즈·확인용(방향 결정 금지) · 참고는 인용 시 '참고' 표시. 개인 게이트는 pb-private views/personal.json."}
    OUT.write_text(json.dumps(out, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
    # 날짜별 마지막 상태 (변경 감지·사후 귀속용, 작게)
    hist["days"][str(t)] = {"asof": out["asof"], "states": {L["id"]: [L["state"], L.get("bias")] for L in lenses if L["state"] not in ("private", "후보")},
                            "gates": {d: [{"id": g["id"], "r": g["result"]} for g in summ[d]["gates"]] for d in DECS},
                            "alerts": {d: [a["id"] for a in summ[d]["alerts"]] for d in DECS},
                            "tilt": {d: summ[d]["tilt"] for d in DECS}}
    keep = sorted(hist["days"])[-400:]
    hist["days"] = {d: hist["days"][d] for d in keep}
    HIST.write_text(json.dumps(hist, ensure_ascii=False, default=str), encoding="utf-8")
    log.info("VIEW 레지스트리: 렌즈 %d개, 변경 %d건, 점검 %d건", len(lenses), len(changes), len(out["lint"]))
    return out


def committee_summary(v: dict | None = None) -> dict | None:
    """운용회의 stance.views: 진입·자산배분 게이트/기울기/주의 짧게."""
    v = v or (_j("views.json", {}) or {})
    s = v.get("summary") or {}
    if not s:
        return None
    def one(d):
        x = s.get(d) or {}
        return {"gate": x.get("gate"), "fails": [g["name"] for g in x.get("gates", []) if g["result"] == "fail"],
                "tilt": x.get("tilt"), "alerts": [a["name"] for a in x.get("alerts", [])][:4],
                "private_gates": len(x.get("private_gates") or [])}
    return {"asof": v.get("asof"), "entry": one("entry"), "allocation": one("allocation"), "changes": v.get("changes") or []}


def telegram_line(v: dict | None = None) -> str | None:
    """게이트가 뒤집혔거나 새 주의가 떴을 때만 한 줄."""
    v = v or (_j("views.json", {}) or {})
    ch = v.get("changes") or []
    if not ch:
        return None
    return "🔭 관점 변화: " + " · ".join(ch[:4]) + (f" 외 {len(ch)-4}건" if len(ch) > 4 else "")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    o = build()
    for d in DECS:
        s = o["summary"][d]
        print(d, s["gate"], s["tilt"], [g["name"] + ":" + g["result"] for g in s["gates"]], [a["name"] for a in s["alerts"]])
    print("changes", o["changes"])
    print("lint", o["lint"])
