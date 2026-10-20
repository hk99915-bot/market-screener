"""리서치 종합 (애널 research-synthesis, 10/21) — 리포트 목록 위에 '증권가 집계' 뷰 7장.

입력(읽기만): data/research.parquet(종목) · data/research_views.parquet(비종목) · reports/research.json(종목→업종·테마)
          · reports/detail/KR/<code>.json(컨센서스·종가) · reports/committee.json(테마 등락·아이디어·체인 스탠스)
출력: reports/research_synthesis.json
실행: python -m screener.research_synthesis   (fin.yml 수집 단계, research_views 수집 직후 — 03:30 KST)

원칙
- 전부 '증권가 집계'다. 우리 판단·매매 신호가 아니다(label 필드).
- 기간은 발간일(date) 기준. 백필 행(collected_at 'backfill …')은 이력(리비전·컨센서스·추이)에는 쓰되
  '신규'(직전 발간일 새로 들어온 건수)에는 넣지 않는다 — 10/21 '밤사이 리포트 6476건' 사고 원인.
- 영업일 = 주말 제외 평일 근사(공휴일 미반영) — method 에 표기.
- 톤 지수 = 어휘 사전 카운트(검증전). 문맥·부정문을 못 읽는다.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "research_synthesis.json"
LABEL = "증권가 집계 — 우리 판단·매매 신호 아님"
TP_EPS = 0.005   # 목표가 ±0.5% 미만 변화는 '유지'

BULL = ["상승", "반등", "강세", "회복", "개선", "확대", "기대", "매수", "상향", "호조", "랠리", "긍정", "성장", "견조",
        "서프라이즈", "모멘텀", "저평가", "기회", "수혜", "턴어라운드", "증가", "최고", "돌파", "비중확대"]
BEAR = ["하락", "약세", "둔화", "우려", "리스크", "부진", "하향", "축소", "위축", "침체", "조정", "부담", "급락", "경계",
        "악화", "불확실", "감소", "쇼크", "매도", "비중축소", "고평가", "변동성", "긴축", "역성장"]
STOP = set("""리포트 보고서 증권 투자 투자의견 목표주가 목표가 전망 분석 기업 실적 시장 국내 글로벌 이번 지난 올해 내년
대한 관련 주간 월간 데일리 Daily Weekly Monthly weekly daily monthly 코멘트 Comment comment 업데이트 Update 리뷰 Review
NOTE Note note 이슈 산업 섹터 전략 매크로 경제 채권 외환 파생 분기 연간 그리고 하지만 위한 통해 대비 가능성 예상 기준
있는 없는 하는 되는 것은 것이 에서 으로 까지 부터 the and for of in to 2Q 3Q 4Q 1Q 2Q25 3Q25 4Q25 3Q26 4Q26 2026 2025 2027
매수 BUY Buy 유지 상향 하향 중립 Hold HOLD 실적발표 Preview Review Earnings 컨퍼런스콜 탐방 후기 Check 체크
것으로 것이다 억원 조원 영업이익 매출액 순이익 YoY QoQ yoy qoq 따른 따라 이후 다만 추가 전년 동기 예정 지속 확인 가운데
기록 수준 최근 현재 해당 이는 이에 이어 또한 특히 경우 대해 때문 위해 전일 금일 전주 금주 대비해 달러 원화 Comment 기타투자
아이디어 Morning Letter 모닝 레터 시황 마감 주요 오늘 어제 컨센서스 컨센 하회 상회 부합 영업익 OP
있다 있음 전망이다 전망됨 매출 이익 OPM 높은 낮은 통해 같은 크게 다소 이상 이하 대한 중이다 것 수 등 및 또 더 영향 주가 중심 예상치 압력 동사 당사""".split()) | set(BULL) | set(BEAR)


def _bdays_back(d: date, n: int) -> date:
    """d 에서 평일 n 개 전 날짜(주말 제외 근사)."""
    while n > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _is_backfill(col: str = "collected_at") -> pl.Expr:
    return pl.col(col).fill_null("").str.starts_with("backfill")


def _links(df: pl.DataFrame, k: int = 3) -> list[dict]:
    if df.is_empty():
        return []
    rows = df.sort("date", descending=True).head(k).to_dicts()
    return [{"date": str(r["date"]), "broker": r.get("broker"), "title": r.get("title"), "link": r.get("link")} for r in rows]


JOSA = ("으로", "에서", "에게", "까지", "부터", "은", "는", "이", "가", "을", "를", "의", "에", "로", "과", "와", "도")


def _strip(t: str) -> str:
    if re.fullmatch(r"[가-힣]{3,}", t):
        for j in JOSA:
            if t.endswith(j) and len(t) - len(j) >= 2:
                return t[: -len(j)]
    return t


def _tokens(text: str, drop: set[str]) -> list[str]:
    out = []
    for t in (_strip(x) for x in re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9&]{1,14}", text or "") if x not in STOP):
        if t in STOP or t in drop or any(ch.isdigit() for ch in t):
            continue
        out.append(t)
    return out


def tone_of(texts: list[str]) -> dict:
    bull = bear = 0
    for t in texts:
        t = t or ""
        bull += sum(t.count(w) for w in BULL)
        bear += sum(t.count(w) for w in BEAR)
    tot = bull + bear
    return {"bull": bull, "bear": bear, "n_docs": len(texts), "index": round((bull - bear) / tot, 3) if tot else None}


def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _revisions(store: pl.DataFrame) -> pl.DataFrame:
    from .research import revisions
    return revisions(store)


def _consensus(store: pl.DataFrame, asof: date, days: int = 90) -> dict[str, float]:
    from .research import _norm_broker
    r = store.filter((pl.col("date") <= asof) & (pl.col("date") > asof - timedelta(days=days)) & pl.col("target").is_not_null())
    if r.is_empty():
        return {}
    r = (r.with_columns(pl.col("broker").map_elements(_norm_broker, return_dtype=pl.Utf8).alias("_b"))
          .sort("date").group_by("code", "_b").last().group_by("code").agg(pl.col("target").median().alias("tp")))
    return dict(zip(r["code"].to_list(), r["tp"].to_list()))


def _match(a: str, b: str) -> bool:
    ta = {t for t in re.split(r"[·\s—,/()-]+", a or "") if len(t) >= 2}
    tb = {t for t in re.split(r"[·\s—,/()-]+", b or "") if len(t) >= 2}
    return bool(ta & tb) or (a and b and (a in b or b in a))


def build(store: pl.DataFrame, views: pl.DataFrame, meta: dict[str, dict], committee: dict | None,
          details: dict[str, dict] | None = None, today: date | None = None) -> dict:
    """순수 함수 — 테스트는 합성 데이터로 이걸 부른다. meta: code→{name,sector,theme}."""
    details = details or {}
    committee = committee or {}
    asof = store["date"].max() if len(store) else (today or date.today())
    d5, d20 = _bdays_back(asof, 5), _bdays_back(asof, 20)
    th = lambda c: (meta.get(c) or {}).get("theme") or (meta.get(c) or {}).get("sector") or "기타"  # noqa: E731
    rv = _revisions(store) if len(store) else store
    rv = rv.with_columns(pl.col("code").map_elements(th, return_dtype=pl.Utf8).alias("theme")) if len(rv) else rv
    names = {r["code"]: r["name"] for r in store.select("code", "name").unique("code").to_dicts()} if len(store) else {}
    n_backfill = store.filter(_is_backfill()).height if len(store) else 0
    new_rows = store.filter((pl.col("date") == asof) & ~_is_backfill()) if len(store) else store

    # ② 목표가·의견 변화 맵
    def rev_window(since: date) -> dict:
        w = rv.filter(pl.col("date") > since) if len(rv) else rv
        if w.is_empty():
            return {"n": 0, "up": 0, "down": 0, "op_up": 0, "op_down": 0, "top_up": [], "top_down": [], "themes": []}
        w = w.with_columns((pl.col("tp_chg") > TP_EPS).fill_null(False).alias("u"), (pl.col("tp_chg") < -TP_EPS).fill_null(False).alias("dn"),
                           (pl.col("op_chg") > 0).fill_null(False).alias("ou"), (pl.col("op_chg") < 0).fill_null(False).alias("od"))
        g = (w.group_by("code").agg(pl.len().alias("n"), pl.col("u").sum().alias("up"), pl.col("dn").sum().alias("down"),
                                    pl.col("tp_chg").filter(pl.col("tp_chg").is_not_null()).median().alias("med")))

        def top(col: str) -> list[dict]:
            out = []
            for r in g.filter(pl.col(col) > 0).sort([col, "n"], descending=True).head(6).to_dicts():
                out.append({"code": r["code"], "name": names.get(r["code"]), "theme": th(r["code"]), "n": r["n"], "up": r["up"],
                            "down": r["down"], "med_tp_chg": None if r["med"] is None else round(r["med"], 4),
                            "reports": _links(w.filter(pl.col("code") == r["code"]), 2)})
            return out
        tg = (w.group_by("theme").agg(pl.len().alias("n"), pl.col("u").sum().alias("up"), pl.col("dn").sum().alias("down"))
               .sort("n", descending=True).head(8).to_dicts())
        return {"n": w.height, "up": int(w["u"].sum()), "down": int(w["dn"].sum()), "op_up": int(w["ou"].sum()),
                "op_down": int(w["od"].sum()), "top_up": top("up"), "top_down": top("down"), "themes": tg}

    r5, r20 = rev_window(d5), rev_window(d20)
    c_now, c_then = _consensus(store, asof), _consensus(store, d20)
    chg = {c: c_now[c] / c_then[c] - 1 for c in c_now if c in c_then and c_then[c]}
    med_chg = sorted(chg.values())[len(chg) // 2] if chg else None
    movers = sorted(chg.items(), key=lambda kv: kv[1])
    mv = lambda kvs: [{"code": c, "name": names.get(c), "chg": round(x, 4), "tp_now": c_now[c]} for c, x in kvs if abs(x) > TP_EPS]  # noqa: E731
    revisions_card = {"d5": r5, "d20": r20, "since5": str(d5), "since20": str(d20),
                      "consensus": {"n_codes": len(chg), "median_chg_20d": None if med_chg is None else round(med_chg, 4),
                                    "top_up": mv(movers[::-1][:5]), "top_down": mv(movers[:5]),
                                    "def": "증권사별 최신 목표가(90일)의 중앙값 — 오늘 vs 20영업일 전"}}

    # ③ 섹터 온도: 테마별 20일 리포트 건수·상향 비율 × 위원회 테마 등락(r5·r20)
    tmove = {t["theme"]: t for t in (committee.get("themes") or []) if isinstance(t, dict) and t.get("theme")}
    sectors = []
    for t in r20["themes"]:
        m = tmove.get(t["theme"]) or {}
        ud = t["up"] + t["down"]
        sectors.append({"theme": t["theme"], "n": t["n"], "up": t["up"], "down": t["down"],
                        "up_ratio": round(t["up"] / ud, 3) if ud else None,
                        "r5": None if m.get("r5") is None else round(m["r5"], 4), "r20": None if m.get("r20") is None else round(m["r20"], 4)})
    vs = views.filter(pl.col("date") > d20) if len(views) else views
    sector_views = vs.filter(pl.col("kind") == "섹터") if len(vs) else vs

    # ① 톤 지수(전략·매크로, 5영업일·20영업일 + 주별 추이)
    def txt(df: pl.DataFrame) -> list[str]:
        return [f"{r.get('title') or ''} {r.get('summary') or ''}" for r in df.select("title", "summary").to_dicts()] if len(df) else []
    sm = views.filter(pl.col("kind").is_in(["전략", "매크로"])) if len(views) else views
    tone5 = tone_of(txt(sm.filter(pl.col("date") > d5))) if len(sm) else tone_of([])
    tone20 = tone_of(txt(sm.filter(pl.col("date") > d20))) if len(sm) else tone_of([])
    weeks = [asof - timedelta(days=asof.weekday()) - timedelta(weeks=i) for i in range(4, -1, -1)]   # 5주, 월요일 시작
    tone_weekly = []
    for w0 in weeks:
        part = sm.filter((pl.col("date") >= w0) & (pl.col("date") < w0 + timedelta(days=7))) if len(sm) else sm
        tw = tone_of(txt(part))
        tone_weekly.append({"week": str(w0), "index": tw["index"], "n_docs": tw["n_docs"]})

    # ④ 테마 클러스터: 제목·요약 키워드 5주 추이
    drop = set(names.values()) | {n[:2] for n in names.values() if n}
    wk_counts: list[Counter] = []
    for w0 in weeks:
        c = Counter()
        for df in (store, views):
            if df.is_empty():
                continue
            part = df.filter((pl.col("date") >= w0) & (pl.col("date") < w0 + timedelta(days=7)))
            for r in part.select("title", "summary").to_dicts():
                c.update(set(_tokens(f"{r.get('title') or ''} {r.get('summary') or ''}", drop)))
        wk_counts.append(c)
    recent = wk_counts[-1] + wk_counts[-2]
    clusters = []
    for kw, n in recent.most_common(10):
        prev = sum(wc[kw] for wc in wk_counts[:3]) / 3
        clusters.append({"kw": kw, "n2w": n, "weekly": [wc[kw] for wc in wk_counts], "vs_prev": round((n / 2) / prev, 2) if prev else None})

    # ⑤ 거시·채권·외환 뷰
    mfx = vs.filter(pl.col("kind").is_in(["매크로", "채권", "외환"])).sort("date", descending=True) if len(vs) else vs
    macro_items = []
    for r in (mfx.head(10).to_dicts() if len(mfx) else []):
        s = (r.get("summary") or "").strip()
        one = re.split(r"(?<=[.다])\s", s)[0][:90] if s else None
        macro_items.append({"date": str(r["date"]), "kind": r["kind"], "broker": r.get("broker"), "title": r.get("title"),
                            "line": one, "link": r.get("link")})
    mk = Counter()
    for r in (mfx.to_dicts() if len(mfx) else []):
        mk.update(set(_tokens(f"{r.get('title') or ''} {r.get('summary') or ''}", drop)))

    # ⑥ 괴리: 위원회(우리) vs 증권가
    div = []
    w20 = rv.filter(pl.col("date") > d20) if len(rv) else rv
    def side(code: str) -> tuple[int, int]:
        x = w20.filter(pl.col("code") == code) if len(w20) else w20
        if x.is_empty():
            return 0, 0
        return int((x["tp_chg"] > TP_EPS).fill_null(False).sum()), int((x["tp_chg"] < -TP_EPS).fill_null(False).sum())
    ideas = committee.get("ideas") or {}
    for kind, lst, bad in (("롱 후보", ideas.get("long") or [], "down"), ("회피", ideas.get("avoid") or [], "up")):
        for it in lst:
            code = it.get("s")
            u, d = side(code)
            cc = chg.get(code)
            if (bad == "down" and (d > u or (cc is not None and cc < -0.03))) or (bad == "up" and (u > d or (cc is not None and cc > 0.03))):
                div.append({"type": "종목", "ours": f"위원회 {kind}", "street": f"20일 목표가 상향 {u}·하향 {d}" + (f" · 컨센 {cc:+.1%}" if cc is not None else ""),
                            "code": code, "name": it.get("n") or names.get(code),
                            "reports": _links(w20.filter(pl.col("code") == code), 2) if len(w20) else []})
    for s in committee.get("sectors") or []:
        st, ch = s.get("stance") or "", s.get("chain") or ""
        for t in sectors:
            if not _match(ch, t["theme"]) or t["up_ratio"] is None or t["up"] + t["down"] < 3:
                continue
            if ("확대" in st and t["up_ratio"] < 0.4) or ("축소" in st and t["up_ratio"] > 0.6):
                div.append({"type": "섹터", "ours": f"위원회 {ch} {st}", "street": f"{t['theme']} 상향 비율 {t['up_ratio']:.0%} (상향 {t['up']}·하향 {t['down']})",
                            "theme": t["theme"]})

    # ⑦ 몰림: 같은 종목 5영업일 리포트 vs 직전 60영업일 5일 평균
    crowd = []
    if len(store):
        d65 = _bdays_back(asof, 65)
        g5 = store.filter(pl.col("date") > d5).group_by("code").agg(pl.len().alias("n5"), pl.col("broker").n_unique().alias("b5"))
        gb = store.filter((pl.col("date") > d65) & (pl.col("date") <= d5)).group_by("code").agg((pl.len() / 12).alias("base"))
        j = g5.join(gb, on="code", how="left").with_columns(pl.col("base").fill_null(0.0))
        j = j.with_columns((pl.col("n5") / pl.max_horizontal(pl.col("base"), pl.lit(0.5))).alias("x"))
        for r in j.filter((pl.col("n5") >= 3) & (pl.col("x") >= 3)).sort(["x", "n5"], descending=True).head(6).to_dicts():
            crowd.append({"code": r["code"], "name": names.get(r["code"]), "n5": r["n5"], "brokers": r["b5"], "base5": round(r["base"], 2),
                          "x": round(r["x"], 1), "reports": _links(store.filter((pl.col("code") == r["code"]) & (pl.col("date") > d5)), 3)})

    # 컨센서스 여력(detail) — 몰림·상향 상위 종목에 붙임(목표가 인플레 경고용)
    for lst in (crowd, r5["top_up"], r20["top_up"]):
        for x in lst:
            dt = details.get(x["code"]) or {}
            x["tp_upside"] = dt.get("tp_upside")

    top_kw = clusters[0]["kw"] if clusters else None
    tone_s = "—" if tone5["index"] is None else f"{tone5['index']:+.2f}"
    headline = (f"증권가 {asof:%m/%d} 기준 5영업일: 종목 리포트 {r5['n']}건 · 목표가 상향 {r5['up']}/하향 {r5['down']}"
                f" · 전략·매크로 톤 {tone_s}(검증전)" + (f" · 최다 키워드 '{top_kw}'" if top_kw else "")
                + (f" · 컨센 목표가 20일 중앙 {med_chg:+.1%}" if med_chg is not None else ""))
    by_src = dict(Counter(store["source"].to_list())) if len(store) else {}
    return {
        "schema_version": 1,
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "asof": str(asof),
        "label": LABEL,
        "inputs": {"stock_n": store.height, "views_n": views.height, "backfill_n": n_backfill, "stock_by_source": by_src,
                   "new_on_asof": new_rows.height, "views_asof": str(views["date"].max()) if len(views) else None},
        "headline": {"text": headline, "tone5": tone5, "tone20": tone20, "tone_weekly": tone_weekly,
                     "new_on_asof": new_rows.height, "reports": _links(new_rows, 3)},
        "revisions": revisions_card,
        "sectors": {"rows": sectors, "sector_reports_20d": sector_views.height, "sector_links": _links(sector_views, 3)},
        "themes": {"weeks": [str(w) for w in weeks], "rows": clusters},
        "macro": {"items": macro_items, "n": mfx.height if len(vs) else 0, "keywords": [{"kw": k, "n": n} for k, n in mk.most_common(8)]},
        "divergence": div[:10],
        "crowding": crowd,
        "method": {
            "window": "발간일 기준 · 영업일 = 평일 근사(공휴일 미반영)",
            "new": "신규 = asof 발간일 & collected_at 이 'backfill' 아닌 행",
            "revision": f"같은 종목·같은 증권사 직전 리포트 대비 목표가 ±{TP_EPS:.1%} 초과 = 상·하향 (research.revisions)",
            "tone": "전략·매크로 리포트 제목+요약에서 강세/약세 어휘 사전 출현 수 → (강−약)/(강+약). 부정문·문맥 미반영 — 검증전",
            "themes": "제목·요약 2~15자 토큰(끝 조사 1개 제거), 불용어·종목명·톤 어휘 제거, 문서당 1회 카운트, 최근 2주 상위 10. 수집 범위가 10/07(비종목)·10/14(네이버 종목) 이후 넓어져 그 전 주는 과소 — vs_prev 배수는 수집 확대분 포함",
            "crowding": "5영업일 건수 ≥3 이고 직전 60영업일의 5일 평균(최소 0.5) 대비 3배 이상",
            "divergence": "위원회 롱 후보인데 20일 하향>상향 또는 컨센 −3% 초과 / 회피인데 상향>하향 또는 컨센 +3% 초과 / 체인 스탠스와 테마 상향 비율(≥3건) 40%·60% 문턱",
            "sector_moves": "테마 등락 r5·r20 = reports/committee.json themes(우리 수집 시세)",
        },
    }


def run() -> dict | None:
    from .guard import write_json
    sp, vp = DATA_DIR / "research.parquet", DATA_DIR / "research_views.parquet"
    store = pl.read_parquet(sp) if sp.exists() else pl.DataFrame()
    views = pl.read_parquet(vp) if vp.exists() else pl.DataFrame()
    if store.is_empty():
        log.warning("research.parquet 없음 — 리서치 종합 건너뜀")
        return None
    if views.is_empty():
        views = pl.DataFrame(schema={"date": pl.Date, "kind": pl.Utf8, "title": pl.Utf8, "summary": pl.Utf8,
                                     "broker": pl.Utf8, "link": pl.Utf8, "sector": pl.Utf8})
    rj = _load_json(REPORT_DIR / "research.json") or {}
    meta = {}
    for it in rj.get("items") or []:
        meta.setdefault(it["code"], {"name": it.get("name"), "sector": it.get("sector"), "theme": it.get("theme")})
    details = {}
    for code in set(store.filter(pl.col("date") >= store["date"].max() - timedelta(days=45))["code"].to_list()):
        d = _load_json(REPORT_DIR / "detail" / "KR" / f"{code}.json")
        if d:
            rs = d.get("research") or {}
            details[code] = {"tp_upside": None if rs.get("tp_upside") is None else round(rs["tp_upside"], 4)}
            if code not in meta:
                meta[code] = {"name": d.get("name"), "theme": d.get("theme")}
    out = build(store, views, meta, _load_json(REPORT_DIR / "committee.json"), details)
    if write_json(OUT, out, key="asof"):
        log.info("research_synthesis.json — %s", out["headline"]["text"])
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    o = run()
    if o:
        print(o["headline"]["text"])
