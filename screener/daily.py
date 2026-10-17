"""센터장 데일리 리포트: 탑다운(매크로·시장 체력·수급) × 바텀업(테마별 리서치 컨센서스) 통합.

규칙 기반으로 만든다(LLM 없음). 리포트 문장은 notes/research_manual.json 정리본이 있으면 그걸, 없으면 자동 구조화 결과를 쓴다.
출력: reports/daily_brief.json, reports/daily_brief.md, 텔레그램용 요약 텍스트
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

# 리포트에서 공통 화두를 잡는 키워드 사전 (화두, 패턴)
TOPICS: list[tuple[str, str]] = [
    ("원화 강세·환율", r"원화\s*강세|환율\s*(하락|부담|영향|역풍)|원/달러\s*하락|얄미운 환율"),
    ("실적 컨센 하회", r"컨센(서스)?\s*(를|을)?\s*(소폭\s*)?하회|기대치\s*(를|을)?\s*하회|미스"),
    ("실적 컨센 상회", r"컨센(서스)?\s*(를|을)?\s*(소폭\s*|대폭\s*)?상회|서프라이즈|기대치\s*(를|을)?\s*상회"),
    ("메모리 판가·HBM", r"메모리|DRAM|NAND|HBM|판가"),
    ("데이터센터·AI 인프라", r"데이터센터|AIDC|AI\s*인프라|GPU|빅테크"),
    ("수주·잔고", r"수주|잔고|계약"),
    ("ESS·배터리", r"ESS|배터리|2차전지|양극재|LFP"),
    ("유가·원자재", r"유가|벙커유|원자재|정제마진|LPG|구리|니켈|철스크랩"),
    ("주주환원", r"주주환원|자사주|배당|소각"),
    ("파업·조업일수", r"파업|조업일수|임단협"),
    ("관세·정책", r"관세|FERC|규제|입법|정책"),
    ("K-뷰티 수출", r"화장품|K-뷰티|뷰티|스킨케어|색조"),
    ("신작·IP", r"신작|IP|월드투어|투어|DLC"),
    ("금리", r"금리"),
]
POS_TONE = {"낙관", "긍정(유지)"}
WEAK_TONE = {"신중한 매수", "사실상 중립", "중립", "사실상 매도", "매도"}


def _load(name: str) -> dict:
    p = REPORT_DIR / name
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _state(st: dict, key: str):
    v = st.get(key)
    return v.get("value") if isinstance(v, dict) else v


def _text(it: dict) -> str:
    ev = it.get("evidence") or []
    return " ".join([it.get("title") or "", it.get("thesis") or "", it.get("view") or "", " ".join(ev),
                     it.get("risk") or "", it.get("summary") if it.get("summary") not in (None, "-") else ""])


def build(days: int = 7) -> dict:
    now = datetime.now(KST)
    res, dash, live = _load("research.json"), _load("dashboard.json"), _load("live.json")
    st = dash.get("state") or {}
    cut = (now.date() - timedelta(days=days)).isoformat()
    items = [i for i in (res.get("items") or []) if i.get("date", "") >= cut]
    close = res.get("close") or {}

    # ── 탑다운 ──
    macro = {d["key"]: d for d in (_state(st, "macro_US") or _state(st, "macro_KR") or [])}
    lv = {d["key"]: d for d in (live.get("items") or [])}

    def chg(k):
        if k in lv:
            return lv[k].get("chg")
        return (macro.get(k) or {}).get("chg1")

    br = [b for b in (dash.get("breadth") or []) if b.get("market") == "KR"]
    b200 = br[-1]["pct_above200"] if br else None
    # 장 마감 후엔 마감 스냅샷(확정에 가까운 수급)을 우선 — 같은 날짜이고 더 최근일 때만
    _i, _c = st.get("intraday_snapshot") or {}, st.get("close_snapshot") or {}
    use_close = isinstance(_c, dict) and str(_c.get("at", ""))[:10] == str(_i.get("at", ""))[:10] and str(_c.get("at", "")) > str(_i.get("at", ""))
    snap = (_c.get("value") if use_close else _state(st, "intraday_snapshot")) or {}
    flow_tag = "마감" if use_close else ("잠정 " + str(_i.get("at", ""))[11:16] if _i else "")
    fk = ((snap.get("flows") or {}).get("KOSPI") or {})
    top_lines = []
    for k, label in (("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ"), ("SPX", "S&P500"), ("NASDAQ", "나스닥"), ("VIX", "VIX"),
                     ("US10Y", "미10년"), ("USDKRW", "원/달러"), ("WTI", "WTI")):
        c = chg(k)
        last = (lv.get(k) or macro.get(k) or {}).get("last")
        if c is not None and last is not None:
            top_lines.append(f"{label} {last:,.2f} ({c*100:+.1f}%)")
    usdkrw20 = (macro.get("USDKRW") or {}).get("chg20")
    regime = []
    try:
        _mv = json.loads((REPORT_DIR / "macro_view.json").read_text(encoding="utf-8"))
        if _mv.get("summary"):
            regime.append(_mv["summary"])
    except Exception:  # noqa: BLE001
        pass
    if b200 is not None:
        regime.append(f"KR 200일선 위 {b200*100:.0f}% — " + ("강세 체력" if b200 >= 0.6 else "중립" if b200 >= 0.4 else "약세 체력"))
    if fk.get("외국인") is not None:
        regime.append(f"외국인 현물 {fk['외국인']:+,.0f}억 · 기관 {fk.get('기관', 0):+,.0f}억 · 개인 {fk.get('개인', 0):+,.0f}억 ({flow_tag})")
    if (chg("VIX") or 0) > 0.08:
        regime.append("VIX 급등 — 위험회피")

    # ── 바텀업: 테마별 ──
    by: dict[str, list[dict]] = {}
    for it in items:
        by.setdefault(it.get("theme") or it.get("sector") or "기타", []).append(it)
    themes = []
    all_topics = Counter()
    for th, its in by.items():
        tones = Counter(i.get("tone") or "?" for i in its)
        topics = Counter()
        for i in its:
            t = _text(i)
            for name, pat in TOPICS:
                if re.search(pat, t):
                    topics[name] += 1
        all_topics.update(topics)
        ups = sum(1 for i in its if (i.get("tp_chg") or 0) > 0.001)
        dns = sum(1 for i in its if (i.get("tp_chg") or 0) < -0.001)
        stocks = Counter(i["name"] for i in its)
        pos = sum(v for k, v in tones.items() if k in POS_TONE)
        weak = sum(v for k, v in tones.items() if k in WEAK_TONE)
        views = [i.get("view") for i in sorted(its, key=lambda x: x.get("date", ""), reverse=True) if i.get("view")][:3]
        themes.append({"theme": th, "n": len(its), "stocks": len(stocks), "top_stocks": [s for s, _ in stocks.most_common(4)],
                       "tones": dict(tones), "pos_share": round(pos / len(its), 2), "weak": weak,
                       "topics": [t for t, _ in topics.most_common(3)], "topic_counts": dict(topics.most_common(5)),
                       "tp_up": ups, "tp_down": dns, "views": views})
    themes.sort(key=lambda x: -x["n"])

    # ── 통합 체크 (탑다운 × 바텀업) ──
    n = max(len(items), 1)
    links = []
    fx_share = all_topics.get("원화 강세·환율", 0) / n
    miss_share = all_topics.get("실적 컨센 하회", 0) / n
    if fx_share >= 0.2:
        links.append(f"원화 강세가 이번 실적 시즌의 공통 변수 — 리포트 {fx_share*100:.0f}%가 환율을 언급"
                     + (f", 원/달러 20일 {usdkrw20*100:+.1f}%" if usdkrw20 is not None else "")
                     + ". 수출 비중 큰 반도체·조선·전력기기·자동차의 3Q 눈높이 하향 압력")
    if miss_share >= 0.25:
        links.append(f"리포트 {miss_share*100:.0f}%가 '컨센 하회'를 예고 — 실적 발표 주간에 '하회 → 하지만 매수 유지' 패턴이 반복될 가능성")
    pos_all = sum(1 for i in items if i.get("tone") in POS_TONE) / n
    kchg = chg("KOSPI")
    if pos_all >= 0.6 and ((kchg is not None and kchg < -0.03) or (b200 is not None and b200 < 0.4)):
        links.append(f"현장(애널리스트) {pos_all*100:.0f}% 긍정 vs 시장 투매 — 목표가가 가격을 따라오지 못하는 괴리. "
                     "급락 후 목표가 하향 리포트가 뒤따르는지 확인 필요")
    if fk.get("외국인") is not None and fk["외국인"] < -10000:
        semi = next((t for t in themes if t["theme"] in ("반도체", "반도체 장비·소재")), None)
        if semi and semi["pos_share"] >= 0.6:
            links.append("외국인 대규모 현물 매도가 반도체 낙관 컨센서스와 정면 충돌 — 리포트는 실적(판가)을, 외국인은 포지션·환율을 보고 있음")
    if all_topics.get("유가·원자재", 0) / n >= 0.1 and (chg("WTI") or 0) > 0:
        links.append("유가·원자재 비용 전가 시차가 운송·화학·철강 이익의 공통 변수")
    if all_topics.get("데이터센터·AI 인프라", 0) / n >= 0.15:
        links.append("AI 인프라(데이터센터·전력·기판)가 업종을 가로지르는 공통 성장 논리 — 반도체 외 전력기기·통신·기판까지 같은 수요에 기대고 있어 동반 조정 위험")

    # ── 이탈 신호 ──
    dissent = [{"name": i["name"], "broker": i["broker"], "tone": i.get("tone"), "why": i.get("tone_why"), "date": i["date"]}
               for i in sorted(items, key=lambda x: x.get("date", ""), reverse=True)
               if i.get("tone") in ("사실상 중립", "사실상 매도", "매도", "중립")][:10]
    cuts = [{"name": i["name"], "broker": i["broker"], "tp_chg": i.get("tp_chg"), "date": i["date"]}
            for i in items if (i.get("tp_chg") or 0) < -0.001]

    # ── 공시 ──
    disc = [d for d in (_load("disclosures.json").get("items") or []) if d.get("date", "") >= (now.date() - timedelta(days=2)).isoformat()
            and d.get("flag") in ("희석", "주의")][:8]

    # ── 헤드라인 ──
    head = []
    if kchg is not None:
        kst = (lv.get("KOSPI") or {}).get("status")
        tag = "확정" if kst and kst != "OPEN" else ("장중 " + str(live.get("updated_at", ""))[6:11]) if "KOSPI" in lv else "전일"
        head.append(f"KOSPI {kchg*100:+.1f}% ({tag})")
    if fk.get("외국인") is not None:
        head.append(f"외국인 {fk['외국인']/10000:+.1f}조")
    if themes:
        head.append(f"리서치는 {themes[0]['theme']} 중심({themes[0]['n']}건)")
    if links:
        head.append(links[0].split(" — ")[0])

    out = {"asof": now.strftime("%Y-%m-%d %H:%M KST"), "days": days, "n_reports": len(items),
           "headline": " · ".join(head), "topdown": {"markets": top_lines, "regime": regime},
           "themes": themes[:12], "links": links, "dissent": dissent, "tp_cuts": cuts, "disclosures": disc,
           "topics": dict(all_topics.most_common(8))}
    from .guard import write_json
    if write_json(REPORT_DIR / "daily_brief.json", out):   # asof 역행이면 json·md 둘 다 건너뜀
        (REPORT_DIR / "daily_brief.md").write_text(to_markdown(out), encoding="utf-8")
    archive(out)
    log.info("데일리 리포트: 리포트 %d건, 테마 %d개, 통합 체크 %d개", len(items), len(themes), len(links))
    return out


def to_markdown(o: dict) -> str:
    L = [f"# 데일리 리서치 브리프 — {o['asof']}", "", f"**{o['headline']}**", "", "## 1. 탑다운"]
    L += [f"- {x}" for x in o["topdown"]["markets"]] + [f"- {x}" for x in o["topdown"]["regime"]]
    L += ["", f"## 2. 바텀업 — 최근 {o['days']}일 리포트 {o['n_reports']}건, 테마별"]
    for t in o["themes"]:
        tones = ", ".join(f"{k} {v}" for k, v in sorted(t["tones"].items(), key=lambda x: -x[1]))
        L.append(f"- **{t['theme']}** {t['n']}건/{t['stocks']}종목 ({', '.join(t['top_stocks'])}) · 톤: {tones}"
                 + (f" · 화두: {', '.join(t['topics'])}" if t["topics"] else "")
                 + (f" · 목표가 상향 {t['tp_up']}/하향 {t['tp_down']}" if t["tp_up"] or t["tp_down"] else ""))
        for v in t["views"][:2]:
            L.append(f"  - {v}")
    L += ["", "## 3. 통합 판단 (탑다운 × 바텀업)"] + [f"- {x}" for x in (o["links"] or ["특이 연결 신호 없음"])]
    if o["dissent"]:
        L += ["", "## 4. 컨센서스 이탈 (실질 중립·매도 톤)"]
        L += [f"- {d['date']} {d['name']} · {d['broker']} — {d['tone']}" + (f" ({d['why']})" if d.get("why") else "") for d in o["dissent"]]
    if o["disclosures"]:
        L += ["", "## 5. 주의 공시"] + [f"- {d['date']} {d['name']} · {d['category']} · {d['title']}" for d in o["disclosures"]]
    L += ["", "_규칙 기반 자동 생성 · 리포트 원문 요약은 정리본 우선 · 투자 권유 아님_"]
    return "\n".join(L)


def telegram_text(o: dict) -> str:
    L = [f"<b>🧭 데일리 리서치 브리프</b> · {o['asof']}", f"<b>{o['headline']}</b>", ""]
    if o["topdown"]["markets"]:
        L.append("<b>[탑다운]</b> " + " · ".join(o["topdown"]["markets"][:6]))
        L += [f"• {x}" for x in o["topdown"]["regime"]]
    L.append("")
    L.append(f"<b>[바텀업 · 최근 {o['days']}일 {o['n_reports']}건]</b>")
    for t in o["themes"][:6]:
        pos = int(round(t["pos_share"] * 100))
        L.append(f"• {t['theme']} {t['n']}건 · 긍정 {pos}%" + (f" · {', '.join(t['topics'][:2])}" if t["topics"] else ""))
    if o["links"]:
        L.append("")
        L.append("<b>[통합 판단]</b>")
        L += [f"• {x}" for x in o["links"][:4]]
    if o["dissent"]:
        L.append("")
        L.append("<b>[이탈]</b> " + " · ".join(f"{d['name']}({d['broker']}, {d['tone']})" for d in o["dissent"][:5]))
    return "\n".join(L)


def archive(o: dict) -> None:
    """날짜별 누적: reports/daily_hist/YYYY-MM-DD.json (그날 마지막 실행본) + _index.json (날짜·헤드라인 목록)."""
    d = str(o.get("asof", ""))[:10]
    if len(d) != 10:
        return
    hd = REPORT_DIR / "daily_hist"
    hd.mkdir(parents=True, exist_ok=True)
    (hd / f"{d}.json").write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
    try:
        idx = json.loads((hd / "_index.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        idx = {"days": []}
    idx["days"] = sorted([x for x in idx["days"] if x["date"] != d] + [{"date": d, "asof": o.get("asof"), "headline": o.get("headline", "")}],
                         key=lambda x: x["date"], reverse=True)
    (hd / "_index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
