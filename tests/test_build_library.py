"""리포트 서고 색인(scripts/build_library.py) — 합성 폴더, 네트워크 없음 (req-dev-16bbc8e5 ①)."""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_library as bl  # noqa: E402


def _w(p: Path, txt: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")
    return p


def _tree(tmp: Path) -> Path:
    r = tmp / "docs" / "desk_kb" / "rounds"
    _w(r / "2026-10-30" / "macro_gold.md", "# 매크로 — 금\n- 자료: macro_series.json\n\n- **What:** 금 하루 −3.6%. 등급 B · 신뢰도 중\n")
    _w(r / "2026-10-31" / "quant_trend.md", "# 퀀트 추세\n\n## What\n- 추세 규칙 전부 F\n등급 F\n")
    _w(r / "2026-10-26" / "okr_edu.md", "# 교육 OKR\n첫 문단 내용이 여기 있다.\n")
    _w(r / "2026-10-24" / "_xlearn_brief.md", "# 숨김\n")
    _w(r / "2026-10-29-msg-1241.md", "# 사내 메신저 라운드\n진행자 메모 한 줄입니다.\n")
    _w(r / "2026-10-29-hf-1155.md", "# HF 점심\n바스켓 점검 메모입니다.\n")
    _w(r / "2026-10-28.md", "# 라운드 종합\n모은 기록 한 줄입니다.\n")
    s = tmp / "reports" / "studies"
    _w(s / "hollzzak_preregistration.md", "# 사전등록\n가설 H1~H3 를 먼저 적는다.\n")
    _w(s / "hollzzak.md", "# 홀짝 본연구\n**What**\n- H1 기각, 등급 C\n")
    _w(s / "hollzzak.json", json.dumps({"study": "hollzzak", "asof": "2026-10-20", "grades": {"H1": "C", "H2": "F"}}))
    _w(s / "replication_hollzzak.md", "# 재현\n독립 재현 결과 기록입니다. 등급: A\n")
    _w(s / "profit_lock.json", json.dumps({
        "study": "profit_lock", "prereg": "docs/desk_kb/rounds/2026-10-31/quant_trend.md §0 (commit x)",
        "params": {"start": "2023-01-02", "end": "2026-10-27", "sizes": [1, 2, 3]},
        "verdict": {"verdict": "유효", "P1": True}, "robust": {"n": 36, "paths": list(range(36))},
        "grade_cap": "C (단일 경로)"}))
    _w(s / "trial_log.md", "# 시도 일지\n등급 F 같은 말이 본문에 있어도 원장은 등급 없음\n")
    _w(tmp / "docs" / "valuation_notes" / "2026-10-23_ndx_core.md", "# NDX 코어 비교 (자산배분, 2026-10-23)\n\n## 0. 결론 (등급 B — 1년)\n1. 변경은 중립.\n")
    _w(tmp / "docs" / "peer_reviews" / "2026-10-24_pick_gate.md", "# 반대 의견서\n- 발행: 피어리뷰 데스크\n\n**게이트는 글로만 잰다.**\n")
    return tmp


def test_build_items_fields_and_order(tmp_path):
    d = bl.build(_tree(tmp_path), now=datetime(2026, 11, 1, 9, 0))
    paths = [i["path"] for i in d["items"]]
    assert "docs/desk_kb/rounds/2026-10-24/_xlearn_brief.md" not in paths
    for it in d["items"]:
        assert {"path", "date", "desk", "desk_ko", "cat", "topic", "title", "summary", "grade", "size"} <= set(it)
        assert len(it["summary"]) <= bl.SUMMARY_MAX
    dates = [i["date"] for i in d["items"]]
    assert dates == sorted(dates, reverse=True)
    by = {i["path"]: i for i in d["items"]}
    g = by["docs/desk_kb/rounds/2026-10-30/macro_gold.md"]
    assert (g["desk"], g["desk_ko"], g["topic"], g["date"]) == ("macro", "매크로", "gold", "2026-10-30")
    assert g["title"] == "매크로 — 금" and g["summary"].startswith("금 하루") and g["grade"] == "B"
    assert by["docs/desk_kb/rounds/2026-10-31/quant_trend.md"]["summary"] == "추세 규칙 전부 F"
    assert by["docs/desk_kb/rounds/2026-10-26/okr_edu.md"]["desk"] == "edu"
    assert by["docs/desk_kb/rounds/2026-10-29-msg-1241.md"]["desk"] == "msg"
    assert by["docs/desk_kb/rounds/2026-10-29-hf-1155.md"]["desk"] == "hf"
    assert by["docs/desk_kb/rounds/2026-10-28.md"]["desk"] == "round"
    v = by["docs/valuation_notes/2026-10-23_ndx_core.md"]
    assert (v["cat"], v["desk"], v["grade"]) == ("valuation", "alloc", "B")
    p = by["docs/peer_reviews/2026-10-24_pick_gate.md"]
    assert p["summary"] == "게이트는 글로만 잰다."   # '발행:' 머리말 줄은 건너뜀
    assert d["pinned"][0]["path"] == "reports/studies/trial_log.md"
    assert by["reports/studies/trial_log.md"]["grade"] == ""


def test_json_only_study_and_series(tmp_path):
    d = bl.build(_tree(tmp_path), now=datetime(2026, 11, 1, 9, 0))
    by = {i["path"]: i for i in d["items"]}
    pl = by["reports/studies/profit_lock.json"]
    assert pl["cat"] == "study" and pl["desk"] == "quant" and pl["grade"] == "C"
    assert "판정 유효" in pl["summary"] and "2023-01-02~2026-10-27" in pl["summary"] and "N 36" in pl["summary"]
    assert pl["body_md"].count("\n| `") >= 5 and "`params.start`" in pl["body_md"] and "목록 36개" in pl["body_md"]
    hz = by["reports/studies/hollzzak.md"]
    assert hz["json"] == "reports/studies/hollzzak.json" and hz["grade"] == "C"   # md+json 은 한 항목
    assert "reports/studies/hollzzak.json" not in by
    assert by["reports/studies/replication_hollzzak.md"]["desk"] == "verify"
    chain = [x["path"].split("/")[-1] for x in d["series"]["hollzzak"]]
    assert chain == ["hollzzak_preregistration.md", "hollzzak.md", "replication_hollzzak.md"]
    assert [x["stage"] for x in d["series"]["hollzzak"]] == [0, 1, 3]
    # json 'prereg' 필드가 가리키는 라운드 파일 → 단계 0 으로 묶음
    assert d["series"]["profit_lock"][0] == {"path": "docs/desk_kb/rounds/2026-10-31/quant_trend.md", "stage": 0}


def test_series_and_desk_rules():
    assert bl.series_of("hollzzak_preregistration") == ("hollzzak", 0)
    assert bl.series_of("replication_semis_cap") == ("semis_cap", 3)
    assert bl.series_of("2026-10-30_winner_ex_ante_round2") == ("winner_ex_ante", 2)
    assert bl.series_of("trend_expectancy_verify") == ("trend_expectancy", 3)
    assert bl.desk_of_name("event_cio") == ("cio", "event")
    assert bl.desk_of_name("analyst_us_semis") == ("analyst", "us_semis")
    assert bl.study_desk("2026-10-21_hf_ls_vol") == "hf" and bl.study_desk("crash_rebound") == "quant"
    assert bl.md_grade("등급 **A** · 신뢰도") == "A" and bl.md_grade("등급 A1 은 아님") == ""
    assert bl.json_grade({"grades": {"a": "F", "b": "A", "c": "C"}}) == ("A", "가설 3개 · A1 C1 F1")


def test_real_repo_builds_and_no_private_paths():
    d = bl.build()
    assert d["n"] >= 200 and d["cats"].get("study", 0) >= 40
    assert all(not i["path"].startswith(("ledger/", "journal/", "household/")) for i in d["items"])
    assert len(json.dumps(d, ensure_ascii=False)) < 1_500_000   # 본문은 안 묶음 — 색인만


def test_mask_amounts_and_dump_one_item_per_line(tmp_path):
    amt = "1" + "만원"   # 소스 줄에 금액 문자열을 그대로 두면 prepush 4a 가 이 테스트 줄을 잡는다
    assert bl.mask_amounts(f"QLD 매일 {amt} 적립 백테스트") == "QLD 매일 [금액] 적립 백테스트"
    assert bl.mask_amounts("SOX −11.91% · S&P −2.35%") == "SOX −11.91% · S&P −2.35%"   # 개인 문맥 없으면 그대로
    d = bl.build(_tree(tmp_path), now=datetime(2026, 11, 1, 9, 0))
    txt = bl.dump(d)
    assert json.loads(txt) == json.loads(json.dumps(d))
    assert len(txt.splitlines()) == d["n"] + 2
