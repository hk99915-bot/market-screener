"""오늘의 영어 v2 스키마(10/21~) 픽스처·화면 계약 — english-v2-ui.
픽스처는 tests/fixtures 에만 둔다(reports/english/ 에 가짜 날짜 파일 금지). 화면 스모크는 scripts/ui_smoke.py check_eng."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
V2 = json.loads((FIX / "english_v2_sample.json").read_text(encoding="utf-8"))
V1 = json.loads((FIX / "english_v1_2026-10-15.json").read_text(encoding="utf-8"))
TAB = (ROOT / "apps-script" / "tab_study.html").read_text(encoding="utf-8")


def _mc(q):
    return isinstance(q["choices"], list) and len(q["choices"]) >= 2 and 0 <= q["a"] < len(q["choices"]) and q["exp_ko"]


def test_v2_fixture_shape():
    assert V2["level"] == "A2~B1"
    assert len(V2["vocab"]) == 5 and all({"w", "pos", "ko", "en_easy", "ipa", "ex"} <= set(v) for v in V2["vocab"])
    assert all(f"**{v['w']}**" in V2["body"] for v in V2["vocab"])
    assert len(V2["grammar"]) == 2 and len(V2["tense"]) == 2
    assert len(V2["review"]) == 3 and all({"w", "from_date", "q"} <= set(q) and _mc(q) for q in V2["review"])
    assert len(V2["quiz"]) == 3 and all(_mc(q) for q in V2["quiz"])
    assert isinstance(V2["talk"], list) and [t["kind"] for t in V2["talk"]] == ["시사", "일상"]
    for t in V2["talk"]:
        assert t["dialogue"] and all({"who", "en", "ko"} <= set(d) for d in t["dialogue"])
        assert len(t["expressions"]) == 5 and {"q_en", "hint_ko", "sample_answer"} <= set(t["your_turn"])
    o = V2["opic"]
    assert len(o["combo"]) == 3 and len(o["useful"]) == 5 and o["survey_topic"] and o["practice_ko"]
    assert all({"type", "q_en", "q_ko", "strategy_ko", "model_answer", "key_phrases"} <= set(c) for c in o["combo"])


def test_v1_fixture_is_old_schema():
    assert len(V1["vocab"]) == 10 and "review" not in V1 and "talk" not in V1 and "opic" not in V1


def test_no_fake_dates_in_reports():
    assert V2["title"].startswith("SAMPLE")
    for f in (ROOT / "reports" / "english").glob("*.json"):
        assert not str(json.loads(f.read_text(encoding="utf-8")).get("title", "")).startswith("SAMPLE"), f


def test_screen_contract():
    for k in ("mt_eng_score_v1", "mt_opic_v1", "engTalks", "getEnglishAt('opic_profile')", "data-kind", "data-ch"):
        assert k in TAB, k
    # 정답·해설은 응답 기록(r)이 있을 때만 렌더 — 고르기 전 비공개
    assert re.search(r"data-eexp=\"\$\{escA\(k\)\}\">\$\{r\?engExp\(q\):''\}", TAB)
    idx = (ROOT / "apps-script" / "Index.html").read_text(encoding="utf-8")
    assert "'eng_review','eng_review_ok','eng_quiz','eng_quiz_ok'" in idx and "...ENGE]" in idx
