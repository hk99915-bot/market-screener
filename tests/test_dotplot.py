"""screener/dotplot.py — 규칙 매핑(합성 입력)과 채점(합성 아카이브). 네트워크·실제 파일 없이."""
import json

from screener import dotplot as dp


def _px(r1=0.0, vs200=0.05, to_low20=0.1, vol20=0.3):
    return {"last": 100.0, "date": "2026-10-16", "r1": r1, "r5": 0.0, "r20": 0.0, "vs200": vs200, "to_low20": to_low20, "vol20": vol20}


def _feats(**kw):
    f = {"date": "2026-10-16", "px": {a: _px() for a in dp.ASSETS}, "us10y": {"level": 4.5, "d5_bp": 0.0},
         "macro_score": 0.0, "macro_label": "중립", "gex_bn": 100.0, "basis": 0.5, "pcr_oi": 1.0,
         "has_committee": True, "has_derivs": True, "has_macro": True,
         "scen_kr": {"bull": 0.3, "bear": 0.3}, "scen_us": {"bull": 0.3, "bear": 0.3}, "pb_stance": "관망",
         "low_signal_ok": False, "glide": False, "valuation": {a: None for a in dp.ASSETS}, "has_valuation": False,
         "picks": [], "has_decisions": True,
         "band_prob": {a: {"5d": 0.4, "20d": 0.3} for a in dp.ASSETS},
         "triggers": {a: {"up": "종가 > 50일선 110", "down": "종가 < 20일 저점 90"} for a in dp.ASSETS}}
    f.update(kw)
    return f


def _stance(dots, asset, desk):
    xs = [x for x in dots[asset] if x["desk"] == desk]
    assert xs, (asset, desk)
    return xs[0]["stance"], xs[0]["conv"]


def test_quant_crash_day_and_low_signal():
    f = _feats()
    f["px"]["KOSPI"] = _px(r1=-0.06)
    d = dp.make_dots(f)
    assert _stance(d, "KOSPI", "퀀트") == ("매수", 2)
    f = _feats(low_signal_ok=True)
    d = dp.make_dots(f)
    assert _stance(d, "KOSPI", "퀀트") == ("매수", 1)
    assert _stance(d, "SEMI_KR", "퀀트") == ("매수", 1)
    assert _stance(d, "US10Y", "퀀트")[0] == "중립"
    f = _feats()
    f["px"]["KOSPI"] = _px(vs200=-0.1)          # 신호 없음 + 200일선 아래 → 중립이 아니라 약매도(확신 낮음)
    x = [x for x in dp.make_dots(f)["KOSPI"] if x["desk"] == "퀀트"][0]
    assert (x["stance"], x["lean"], x["lean_label"], x["confidence"]) == ("매도", -1, "약매도", "낮음")
    assert x["p_up"] < 0.5 and "급락일" in x["flip_up"]


def test_derivs_always_neutral_with_notes():
    f = _feats(gex_bn=-500.0, basis=-0.3, pcr_oi=1.4)
    d = dp.make_dots(f)
    x = [x for x in d["KOSPI"] if x["desk"] == "파생"][0]
    assert "감마 음수" in x["reason"] and "백워데이션" in x["reason"] and "PCR" in x["reason"]
    assert (x["lean_label"], x["confidence"]) == ("약매도", "낮음")      # 백워데이션 부호를 버리지 않음
    y = [x for x in d["SPX"] if x["desk"] == "파생"][0]
    assert y["stance"] == "중립" and y.get("na") and y["lean_label"] == "해당없음"


def test_macro_rules():
    assert _stance(dp.make_dots(_feats(macro_score=-0.4)), "KOSPI", "매크로") == ("매도", 1)
    assert _stance(dp.make_dots(_feats(macro_score=0.4)), "SPX", "매크로") == ("매수", 1)
    assert _stance(dp.make_dots(_feats(macro_score=0.0)), "KOSPI", "매크로")[0] == "중립"
    d = dp.make_dots(_feats(macro_score=0.5, us10y={"level": 5.1, "d5_bp": 15.0}))   # 금리 우선
    assert _stance(d, "KOSPI", "매크로") == ("매도", 1)
    assert _stance(d, "US10Y", "매크로") == ("매수", 1)
    assert _stance(dp.make_dots(_feats(us10y={"level": 4.0, "d5_bp": -12.0})), "US10Y", "매크로") == ("매도", 1)
    assert _stance(dp.make_dots(_feats(macro_score=None)), "KOSPI", "매크로")[0] == "중립"


def test_risk_rules():
    f = _feats()
    f["px"]["SEMI_KR"] = _px(vol20=0.65)
    f["px"]["KOSPI"] = _px(vs200=-0.05, to_low20=0.02)
    f["px"]["SPX"] = _px(vs200=0.05, to_low20=0.01)
    d = dp.make_dots(f)
    assert _stance(d, "SEMI_KR", "리스크") == ("매도", 2)
    assert _stance(d, "KOSPI", "리스크") == ("매도", 1)
    assert _stance(d, "SPX", "리스크")[0] == "중립"      # 200일선 위면 매도 아님
    f["px"]["SEMI_KR"] = _px(vol20=0.45)
    assert _stance(dp.make_dots(f), "SEMI_KR", "리스크") == ("매도", 1)


def test_analyst_valuation_terciles_and_missing():
    d = dp.make_dots(_feats(valuation={"KOSPI": "top", "SEMI_KR": "bottom", "SPX": "mid", "US10Y": None}, has_valuation=True))
    assert _stance(d, "KOSPI", "애널") == ("매수", 1)
    assert _stance(d, "SEMI_KR", "애널") == ("매도", 1)
    assert _stance(d, "SPX", "애널")[0] == "중립"
    x = [x for x in dp.make_dots(_feats())["KOSPI"] if x["desk"] == "애널"][0]
    assert x["stance"] == "중립" and "검증전" in x["reason"]
    assert dp._valuation_tercile({"assets": {"KOSPI": {"rate_adj_yield_pct": 0.9}}}, "KOSPI") == "top"
    assert dp._valuation_tercile({"KOSPI": {"tercile": "bottom"}}, "KOSPI") == "bottom"
    assert dp._valuation_tercile({"other": 1}, "KOSPI") is None


def test_cio_scenarios():
    assert _stance(dp.make_dots(_feats(scen_kr={"bull": 0.46, "bear": 0.2})), "KOSPI", "CIO") == ("매수", 1)
    assert _stance(dp.make_dots(_feats(scen_kr={"bull": 0.3, "bear": 0.36})), "SEMI_KR", "CIO") == ("매도", 1)
    assert _stance(dp.make_dots(_feats(scen_us={"bull": 0.5, "bear": 0.1})), "SPX", "CIO") == ("매수", 1)
    assert _stance(dp.make_dots(_feats(scen_kr={"bull": None, "bear": None})), "KOSPI", "CIO")[0] == "중립"


def test_pb_mapping_and_glide():
    assert _stance(dp.make_dots(_feats(pb_stance="분할 매수")), "KOSPI", "PB") == ("매수", 1)
    assert _stance(dp.make_dots(_feats(pb_stance="방어")), "KOSPI", "PB") == ("매도", 1)
    assert _stance(dp.make_dots(_feats(pb_stance="관망")), "KOSPI", "PB")[0] == "중립"
    d = dp.make_dots(_feats(pb_stance="분할 매수", glide=True))
    x = [x for x in d["SEMI_KR"] if x["desk"] == "PB"][0]
    assert (x["stance"], x["conv"]) == ("매도", 1) and "비중 축소 중" in x["reason"]
    assert _stance(d, "KOSPI", "PB") == ("매수", 1)


def test_gyeom_from_picks():
    picks = [{"who": "나🔥", "market": "KR", "ticker": "139260", "name": "KODEX 반도체"}]
    d = dp.make_dots(_feats(picks=picks))
    assert _stance(d, "SEMI_KR", "겸이") == ("매수", 2)
    assert _stance(d, "KOSPI", "겸이")[0] == "중립"
    picks = [{"who": "나", "market": "KR", "ticker": "475310", "name": "SOL 반도체후공정"}]
    assert _stance(dp.make_dots(_feats(picks=picks)), "SEMI_KR", "겸이") == ("매수", 1)
    picks = [{"who": "나", "market": "KR", "ticker": "252670", "name": "KODEX 200선물인버스2X"}]
    assert _stance(dp.make_dots(_feats(picks=picks)), "KOSPI", "겸이") == ("매도", 1)
    picks = [{"who": "나", "market": "KR", "cash": True}]
    assert _stance(dp.make_dots(_feats(picks=picks)), "KOSPI", "겸이")[0] == "중립"
    picks = [{"who": "나", "market": "US", "ticker": "AAPL", "name": "Apple"}]
    assert _stance(dp.make_dots(_feats(picks=picks)), "SPX", "겸이") == ("매수", 1)
    x = [x for x in dp.make_dots(_feats(picks=[]))["KOSPI"] if x["desk"] == "겸이"][0]
    assert x["stance"] == "중립" and "제출 없음" in x["reason"]


def test_horizons_tags_and_summary():
    d = dp.make_dots(_feats(macro_score=0.5, scen_kr={"bull": 0.5, "bear": 0.1}))
    for a in dp.ASSETS:
        for desk in dp.DESKS:
            hs = sorted(x["horizon"] for x in d[a] if x["desk"] == desk)
            assert hs == sorted(dp.DESK_HORIZONS[desk])
        for x in d[a]:
            assert x["stance"] in dp.STANCES and 1 <= x["conv"] <= 3 and x["tag"] in dp.TAG_KO and x["refs"]
    s = dp.summarize(d["KOSPI"])
    assert sum(s["counts"].values()) + s["na"] == len(dp.DESKS)
    assert sum(s["lean_counts"].values()) == len(dp.DESKS)
    assert s["counts"]["매수"] == 3 and s["tags"]["regime"] >= 2          # 퀀트(200일선 위 약매수)+매크로+CIO
    assert s["lean_counts"]["약매수"] == 3 and s["net_lean"] > 0
    line = dp.telegram_lines({"assets": d})[0]
    assert line.startswith("점도표 코스피: 강매수 0·약매수 3·") and "근거 겹침: 레짐" in line


def test_neutral_requires_base_and_flips_lint():
    d = dp.make_dots(_feats())
    assert dp.lint_dots(d) == []
    for a in dp.ASSETS:
        for x in d[a]:
            assert x["lean"] in dp.LEANS and x["base_prob"] is not None and x["flip_up"] and x["flip_down"]
    bare = dp.make_dots(_feats(band_prob={}, triggers={}))
    errs = dp.lint_dots(bare)
    assert any("중립 불허" in e for e in errs)


def test_small_signs_tilt_not_neutral():
    d = dp.make_dots(_feats(macro_score=-0.11, macro_label="약한 역풍"))
    x = [x for x in d["KOSPI"] if x["desk"] == "매크로"][0]
    assert (x["lean_label"], x["confidence"]) == ("약매도", "낮음") and "−0.05" in x["flip_up"].replace("-", "−")
    assert [x for x in dp.make_dots(_feats(macro_score=0.02))["KOSPI"] if x["desk"] == "매크로"][0]["lean"] == 0
    assert [x for x in dp.make_dots(_feats(us10y={"level": 4.9, "d5_bp": 5.0}))["US10Y"] if x["desk"] == "매크로"][0]["lean"] == 1
    c = [x for x in dp.make_dots(_feats(scen_kr={"bull": 0.44, "bear": 0.22}))["KOSPI"] if x["desk"] == "CIO"][0]
    assert c["lean"] == 1 and c["base_prob"] == 0.44
    rc = {"sign": -1, "label": "🔴 하방", "src": "docs/desk_kb/rounds/2026-10-26/event_cio.md"}
    c = [x for x in dp.make_dots(_feats(scen_kr={"bull": 0.44, "bear": 0.22}, round_cio=rc))["KOSPI"] if x["desk"] == "CIO"][0]
    assert c["lean"] == -1 and rc["src"] in c["refs"]


def test_event_trigger_adapter(tmp_path):
    rd = tmp_path / "docs" / "desk_kb" / "rounds" / "2026-10-26"
    rd.mkdir(parents=True)
    (rd / "event_macro.md").write_text("## 트래킹 트리거(x)\n\n| 지표 | 지금 | 위험 쪽 트리거 | 완화 쪽 트리거 | 확인 |\n|---|---|---|---|---|\n"
                                       "| 미 10Y | 4.99% | > 5.15%(9월 고점권) | < 4.80% | 10/29 |\n"
                                       "| 코스피 | 5,469 | 20일 고점 대비 −25%(5,310) 이탈 | 50일선 6,583 회복 | 상시 |\n", encoding="utf-8")
    (rd / "event_cio.md").write_text("- **So What**: 🔴 레짐 = 하락장 — 비대칭 하방\n", encoding="utf-8")
    ev = dp.event_inputs(tmp_path, "2026-10-27")
    assert ev["triggers"]["US10Y"] == {"up": "미 10Y > 5.15%", "down": "미 10Y < 4.80%", "src": "docs/desk_kb/rounds/2026-10-26/event_macro.md"}
    assert "6,583" in ev["triggers"]["KOSPI"]["up"] and "이탈" in ev["triggers"]["KOSPI"]["down"]
    assert ev["round_cio"]["sign"] == -1
    assert dp.event_inputs(tmp_path, "2026-11-05")["triggers"] == {}         # 3일 지난 라운드는 안 씀


def test_top_follows_standard8():
    from screener.topline import lint
    d = {"date": "2026-10-26", "asof": "2026-10-26 19:40", "assets": dp.make_dots(_feats(macro_score=-0.11))}
    d["lint"] = dp.lint_dots(d["assets"])
    assert lint(dp.make_top(d)) == []


def test_derive_features_from_synthetic_inputs():
    closes = [[f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", 0, 0, 100.0, 100.0 + i, 0] for i in range(60)]
    closes[-1][4] = 100.0   # 마지막 날 급락
    inputs = {"committee": {"scenarios": [{"name": "강세 — x", "prob": 0.5}, {"name": "약세 — y", "prob": 0.1}],
                            "stance": {"stance": "분할 매수", "exec": {"signals": [{"t": "오늘 저점 +1% 위 마감", "ok": True}],
                                                                       "steps": [{"do": "반도체 비중을 테마 한도 40%까지 단계적 축소"}]}}},
              "committee_us": None, "derivs": {"gex_bn": -10, "fut": {"basis": -1}, "pcr_oi": 1.5}, "macro_view": {"score": 0.35},
              "macro_series": {"series": {"KOSPI": closes, "SPX": closes, "US10Y": [[r[0], 0, 0, 0, 5.0 + i * 0.03, 0] for i, r in enumerate(closes)]}},
              "bonds": None, "valuation": None, "decisions": {"items": [{"date": "2026-10-16", "kind": "entry", "picks": {"나": {"cash": True}}}]},
              "gamma": None, "semi_closes": []}
    f = dp.derive_features(inputs, today="2026-10-16")
    assert f["low_signal_ok"] and f["glide"] and f["pb_stance"] == "분할 매수" and f["scen_kr"]["bull"] == 0.5
    assert f["px"]["KOSPI"]["r1"] < -0.05 and f["px"]["SEMI_KR"] == {}
    assert abs(f["us10y"]["d5_bp"] - 15.0) < 1e-6 and f["us10y"]["level"] > 5.0
    assert f["picks"] == [{"who": "나", "market": "KR", "cash": True}]
    d = dp.make_dots(f)
    assert _stance(d, "KOSPI", "퀀트") == ("매수", 2)
    assert _stance(d, "KOSPI", "매크로") == ("매도", 1)       # 금리 우선
    assert _stance(d, "SEMI_KR", "리스크")[0] == "중립"       # 시세 없음 → 중립


def test_score_synthetic_archive():
    ser = [(f"2026-09-{i + 1:02d}", 100.0 + i) for i in range(20)]          # 매일 +1 (20일 지평은 아직 미경과)
    yld = [(f"2026-09-{i + 1:02d}", 4.0 + 0.05 * i) for i in range(20)]    # 매일 +5bp
    arch = [{"date": "2026-09-05", "assets": {
        "KOSPI": [{"desk": "퀀트", "stance": "매수", "conv": 2, "horizon": "5d"},
                  {"desk": "리스크", "stance": "매도", "conv": 1, "horizon": "5d"},
                  {"desk": "파생", "stance": "중립", "conv": 1, "horizon": "5d"},
                  {"desk": "CIO", "stance": "매수", "conv": 1, "horizon": "20d"},
                  {"desk": "애널", "stance": "매수", "conv": 1, "horizon": "20d"}],   # 지평 미경과 → 채점 제외
        "US10Y": [{"desk": "매크로", "stance": "매수", "conv": 1, "horizon": "5d"},
                  {"desk": "PB", "stance": "중립", "conv": 1, "horizon": "5d"}]}}]
    res = dp.score_archive(arch, {"KOSPI": ser, "US10Y": yld})
    d = res["desks"]
    assert d["퀀트"]["n"] == 1 and d["퀀트"]["hit"] == 1 and d["퀀트"]["avg_signed_ret"] > 0
    assert d["리스크"]["hit"] == 0 and d["리스크"]["avg_signed_ret"] < 0
    assert d["파생"]["hit"] == 0            # 5일 +4.8% → 중립 범위(1%) 밖
    assert d["CIO"]["n"] == 0 and d["애널"]["n"] == 0
    assert d["매크로"]["hit"] == 1 and d["PB"]["hit"] == 0     # +25bp > 10bp
    assert d["퀀트"]["brier"] < d["리스크"]["brier"]
    assert res["n_scored"] == 5
    # 보합이면 중립 적중, 매수 미적중
    ok, br = dp.judge("중립", 1, 0.0, "5d", False)
    assert ok and abs(br) < 1e-9
    ok, br = dp.judge("매수", 3, 0.0, "5d", False)
    assert not ok and abs(br - 0.25) < 1e-9


def test_score_writes_scoreboard(tmp_path):
    root = tmp_path
    (root / "reports" / "archive" / "dotplot").mkdir(parents=True)
    ser = [[f"2026-09-{i + 1:02d}", 0, 0, 0, 100.0 + i, 0] for i in range(30)]
    (root / "reports" / "macro_series.json").write_text(json.dumps({"series": {"KOSPI": ser, "SPX": ser, "US10Y": ser}}), encoding="utf-8")
    (root / "reports" / "archive" / "dotplot" / "2026-09-05.json").write_text(json.dumps(
        {"date": "2026-09-05", "assets": {"KOSPI": [{"desk": "퀀트", "stance": "매수", "conv": 1, "horizon": "5d"}]}}), encoding="utf-8")
    res = dp.score(root=root, today="2026-09-20")
    assert res["desks"]["퀀트"]["n"] == 1
    sb = (root / "docs" / "desk_kb" / "_scoreboard.md").read_text(encoding="utf-8")
    assert "| 2026-09-20 | 퀀트 | 1 | 100% |" in sb
    dp.score(root=root, today="2026-09-20")      # 같은 날 다시 → 행 교체(중복 없음)
    assert (root / "docs" / "desk_kb" / "_scoreboard.md").read_text(encoding="utf-8").count("| 2026-09-20 | 퀀트 |") == 1
    assert (root / "reports" / "dotplot_score.json").exists()


def test_semi_tercile_from_valuation_rows():
    val = {"rows": [{"mk": "KR", "verified": True, "rate_adj": 0.066}, {"mk": "KR", "verified": True, "rate_adj": 0.01},
                    {"mk": "KR", "verified": False, "rate_adj": -0.5}, {"mk": "US", "verified": True, "rate_adj": 0.2}]}
    assert abs(dp._semi_median_rate_adj(val) - 0.038) < 1e-9
    assert dp._semi_tercile(val, history=[]) == "top"                       # 고정 눈금 ≥ +3%p
    assert dp._semi_tercile({"rows": [{"mk": "KR", "verified": True, "rate_adj": -0.01}]}, history=[]) == "bottom"
    assert dp._semi_tercile({"rows": [{"mk": "KR", "verified": True, "rate_adj": 0.02}]}, history=[]) == "mid"
    hist = [i / 1000 for i in range(60)]                                     # 이력 0~5.9%p → 3.8%p 는 중간 3분위
    assert dp._semi_tercile(val, history=hist) == "mid"
    assert dp._semi_tercile({"rows": []}, history=[]) is None


def test_macro_wind_label_signed_small_scores():
    from screener.macroview import wind_label
    assert wind_label(-0.11) == "약한 역풍" and wind_label(0.07) == "약한 순풍"
    assert wind_label(0.04) == "중립" and wind_label(-0.049) == "중립" and wind_label(None) is None
    assert wind_label(-0.2) == "역풍" and wind_label(0.45) == "강한 순풍"


def test_unconditioned_neutral_is_refused_not_counted():
    """검수 req-dev-afc2e971 ①: 보드 '조건 없는 중립은 기록 거부' — lint 위반 중립은 해당없음(거부)로, 집계에서 빠짐."""
    ok = {"desk": "PB", "horizon": "5d", "lean": 0, "stance": "중립", "conv": 1, "reason": "관망", "tag": "none",
          "base_prob": 0.4, "flip_up": "코스피 +2%", "flip_down": "코스피 −2%"}
    bad = {**ok, "desk": "리스크", "flip_down": None}
    assets = {"KOSPI": [dict(ok), dict(bad)]}
    assert len(dp.lint_dots(assets)) == 1
    assert dp.refuse_unconditioned(assets) == 1
    a, b = assets["KOSPI"]
    assert not a.get("na") and b["na"] and b["refused"] and b["lean_label"] == dp.NA_LABEL and "기록 거부" in b["reason"]
    s = dp.summarize(assets["KOSPI"])
    assert s["lean_counts"]["중립"] == 1 and s["na"] == 1
    assert dp.lint_dots(assets) == []          # 거부된 점은 형식 검사 대상 아님


def test_base_text_band_vs_scenario():
    """검수 req-dev-afc2e971 ②: 보합 실측 빈도를 '기본' 으로 표기하지 않음 + 33% 미만 중립은 '근거 약함'."""
    band = {"lean": 0, "base_prob": 0.112, "base_src": "보합(±2%) 1년 실측 빈도", "base_kind": "band"}
    assert dp.base_text(band) == "보합(±2%) 실측 11% ⚠ 중립 근거 약함"
    assert dp.base_text({**band, "base_prob": 0.568}) == "보합(±2%) 실측 57%"
    assert dp.base_text({"lean": 0, "base_prob": 0.5, "base_src": "운용회의 기본 시나리오"}) == "기본 50%"
    assert dp.base_text({"lean": 1, "base_prob": None}) == "기본 —"
    assert dp._base_kind("규칙 환산(검증전)") == "rule" and dp._base_kind("운용회의 강세 시나리오") == "scenario"
