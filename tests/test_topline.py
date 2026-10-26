"""보고 상단 형식 공통 모듈(screener/topline.py) + 생성기 어댑터(topline_from) — STANDARD.md 8절, 보드 report-format-rollout 묶음 A."""
from screener import config, topline as T, topline_from as F


def _ok():
    return T.make(["코스피 5,469 (-1.5%)"], ["판정 관망 · 최다 시나리오 강세 44%(검증전)"], ["조치 없음(변화 없음)"],
                  evidence=["시계: 15:05 점검"], src=["reports/committee.json"], asof="2026-10-26 15:53", grade="검증전")


class TestRender:
    def test_tg3(self):
        s = T.render_tg3(_ok())
        ls = s.split("\n")
        assert len(ls) == 4 and ls[0].startswith("① What: ") and ls[1].startswith("② So What: ") and ls[2].startswith("③ Now What: ")
        assert ls[3] == "기준 2026-10-26 15:53 · 원본: reports/committee.json"

    def test_tg3_escapes_html(self):
        t = _ok()
        t["what"] = ["S&P500 <b> 7,624"]
        assert "S&amp;P500 &lt;b&gt;" in T.render_tg3(t)

    def test_md_top(self):
        s = T.render_md(_ok())
        assert s.startswith("> 기준 2026-10-26 15:53 · 등급 검증전") and "① **What**: 코스피" in s and "원본: reports/committee.json" in s

    def test_md_doc_order(self):
        s = T.render_md(_ok(), doc=True)
        i = [s.index(k) for k in ("**What**", "**So What**", "**근거 데이터 발췌**", "**Now What**", "**원본**")]
        assert i == sorted(i)   # 샘플 v3 순서: What → So What → 근거 → Now What → 원본

    def test_empty_field_rendered_not_dropped(self):
        t = _ok()
        t["so_what"] = []
        assert "해당 없음" in T.render_tg3(t)


class TestLint:
    def test_pass(self):
        assert T.lint(_ok()) == []

    def test_missing_field(self):
        t = _ok()
        t["now_what"] = []
        assert any("Now What 칸 누락" in v for v in T.lint(t))

    def test_per_field_max(self):
        t = _ok()
        t["what"] = [f"줄 {i}" for i in range(5)]
        assert any("What 5줄 > 4" in v for v in T.lint(t))

    def test_total_max(self):
        t = _ok()
        t["what"], t["so_what"], t["now_what"] = ["a"] * 4, ["b"] * 4, ["c"] * 3
        assert any("합계 11줄" in v for v in T.lint(t))

    def test_line_length(self):
        t = _ok()
        t["what"] = ["가" * 91]
        assert any("91자" in v for v in T.lint(t))

    def test_bad_endings(self):
        for bad in ("관망 유지합니다", "현금 유지해요", "급락!"):
            t = _ok()
            t["so_what"] = [bad]
            assert any("종결어미" in v for v in T.lint(t)), bad

    def test_noun_yo_allowed(self):
        t = _ok()
        t["now_what"] = ["재검증 필요", "이벤트 결과 확인 중요"]
        assert T.lint(t) == []

    def test_asof_and_src_required(self):
        t = _ok()
        t["asof"], t["src"] = None, []
        v = T.lint(t)
        assert any("asof" in x for x in v) and any("원본" in x for x in v)

    def test_not_dict(self):
        assert T.lint(None) == ["top 없음"]


def test_fit_splits_on_dot_boundary():
    s = " · ".join(["항목 %d 내용 길게 적은 문장" % i for i in range(12)])
    ls = T.fit(s, max_lines=2)
    assert len(ls) == 2 and all(len(x) <= 90 for x in ls) and ls[-1].endswith("…")


COMMITTEE = {"asof": "2026-10-26 15:53", "date": "2026-10-26", "session": "장후",
             "head": ["코스피 5,469.47 (-1.5%) · 20일 고점 대비 -22.8%"],
             "scenarios": [{"name": "강세", "prob": 0.438}, {"name": "기본", "prob": 0.4}],
             "premortem": {"wrong": "관망이 틀린 경우: V자 반등", "tell": "20일선 2일 연속 회복"},
             "bottom_line": {"light": "yellow", "label": "🟡 관찰", "stance": "관망",
                             "lines": ["직전 회의 대비: 코스피 5,526→5,469 (-1.0%) · 판정 유지(관망)", "오늘의 시계: 15:05 점검",
                                       "할 일: 판정 유지 · 신규 행동 없음. 하지 말 일: 레버리지 확대"]}}


def test_committee_adapter_keeps_bottom_line_and_lints():
    top = F.committee(COMMITTEE, "KR")
    assert T.lint(top) == [] and top["evidence"] == ["오늘의 시계: 15:05 점검"]
    assert "판정 관망" in top["so_what"][0] and top["src"] == ["reports/committee.json"]


def test_adapters_lint_clean_on_fixtures():
    cases = [F.macro({"summary": "매크로 바람 중립 (-0.11) — 주된 요인: 나스닥 − → 매크로 반전만으론 회복 근거 부족"}),
             F.bonds({"generated_at": "2026-10-26 15:53", "us": {"chg": {"10Y": {"v": 5.0, "m1": -11}}}, "kr": {"chg": {"3Y": {"v": 3.79, "m1": -21}}},
                      "spreads": {"us_10_2": {"v": 0.31}}, "notes": ["미 10년물 5.00% — 성장주 밸류에이션에 부담"], "reco": ["장기채보다 단기채·현금 우선"],
                      "corr": {"IEF_SPX": {"c250": 0.33}}}),
             F.derivs({"asof": "2026-10-26 15:53", "pcr_oi": 1.18, "max_pain": 950.0, "spot": 851.5, "expiry": "2026-11-12", "dte": 17,
                       "gex_bn": -930.2, "flip": 898.0, "atm_iv": 0.518, "rv20": 0.479, "insight": {"one_line": "변동성 확대 국면", "so_what": "분할 실행"}}),
             F.daily({"asof": "2026-10-26 16:47 KST", "headline": "KOSPI -1.5% · 외국인 -0.7조", "tp_cuts": [1], "dissent": [], "disclosures": []}),
             F.research({"generated_at": "2026-10-26 08:56 KST", "headline": {"text": "리포트 212건 · 상향 22/하향 36"}, "divergence": []}),
             F.hf_ideas({"generated_at": "2026-10-26 18:35 KST", "counts": {"total": 288, "거래량 급증": 3}, "ideas": [{"name": "A", "type": "거래량 급증"}]}),
             F.hf_book({"asof": "2026-10-26 17:07", "open": [], "closed": [{"r": -0.1}], "limits": {"pnl": -0.0012, "dd": -0.0012}}),
             F.alphabook({"updated": "2026-10-26 15:53 KST", "summary": {"KR": {"lines": ["알파북 현재(KR): 포지션 3개", "이번 제안: 없음"]}}})]
    for t in cases:
        assert T.lint(t) == [], (t, T.lint(t))


def test_telegram_switch_default_off_keeps_old_lines(monkeypatch):
    from screener import committee as C
    o = dict(COMMITTEE, top=F.committee(COMMITTEE, "KR"))
    assert config.TOPLINE_TG is False
    old = C._tg_top3(o, o["bottom_line"])
    assert old[0] == "① 직전 회의 대비: 코스피 5,526→5,469 (-1.0%) · 판정 유지(관망)" and len(old) == 3
    monkeypatch.setattr(config, "TOPLINE_TG", True)
    new = C._tg_top3(o, o["bottom_line"])
    assert new[0].startswith("① What: ") and new[-1].startswith("기준 2026-10-26 15:53")


def test_bundle_b_adapters_lint_clean():
    """묶음 B(10/26) 생성기 어댑터 — 빈 입력·최소 입력에서도 3칸·lint 0(칸 누락 없음, '해당 없음/조치 없음' 사유로 채움)."""
    from screener import topline, topline_from as tf
    cases = [tf.realestate({"rates": [{"name": "기준금리", "status": "ok", "last": 3.0, "unit": "%", "month": "2026-09", "chg1m": 0}],
                            "prices": {"status": "키 필요", "why": "무키"}, "label": "표시 전용", "asof": "2026-10-26"}),
             tf.realestate({}), tf.valuation({"basket": {"median_per": 20.0, "n": 3, "n_verified": 2}, "asof": "2026-10-26"}), tf.valuation({}),
             tf.commodities({"summary": "1개월 ±10% 넘게 움직인 원자재 없음", "rows": [], "asof": "2026-10-26"}),
             tf.scorecard({"telegram": "📊 주간 성적표 준비됨 (10/19~10/25) — 대결 6건 · 나 승률 33% · 코스피 주간 −2.1%", "asof": "2026-10-25 10:21"})]
    for top in cases:
        assert topline.lint(top) == [], top
