"""신입 온보딩 확인 퀴즈(교육 10/24, 프론트 온보딩) — 문서엔 문제만, 키는 content/onboarding, 채점 drill_grade (G1 같은 규칙). 네트워크 없음."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import drill_grade as G  # noqa: E402


def test_onboarding_doc_key_consistent():
    assert G.check_onboarding() == []
    q = {k: v for k, v in G.load_onboarding().items() if v["desk"] == "front"}
    assert sorted(q) == [f"front-q{i}" for i in range(1, 9)]
    for it in q.values():
        assert it.get("src") and len(it["keys"]) >= 4, it["id"]       # 문항 출처(실제 파일·커밋) + 키 4개 이상(부분 점수 의미)


def test_model_answer_passes_and_vague_answer_fails():
    for qid, it in G.load_onboarding().items():
        assert G.grade(it, it["answer"])["score"] == 1.0, qid
        assert not G.grade(it, "잘 모르겠다, 상황 봐서 화면 확인하고 판단")["pass"], qid
        assert not G.grade(it, it["q"])["pass"], qid                   # 문제를 그대로 베껴도 통과 못 함


def test_check_catches_answer_in_doc_and_missing_key(tmp_path):
    doc, keys = tmp_path / "doc", tmp_path / "keys"
    doc.mkdir(); keys.mkdir()
    (keys / "zz.json").write_text('{"desk":"zz","items":[{"id":"zz-q1","q":"q","answer":"a 1","keys":[{"n":1}]}]}', encoding="utf-8")
    (doc / "zz.md").write_text("- 퀴즈 [zz-q1]: 문제? **답:** 1\n- 퀴즈 [zz-q2]: 키 없는 문제\n", encoding="utf-8")
    errs = G.check_onboarding(doc, keys)
    assert any("답이 문서에 남음" in e for e in errs) and any("zz-q2 키 없음" in e for e in errs)


def test_grade_sheet_reads_quiz_and_drill_lines():
    keys = {**G.load_keys(), **G.load_onboarding()}
    sheet = ("## 퀴즈\n퀴즈: front-q4 --fs-2 12.5px, test_font_tokens 빨강, font_tokens.py --fix\n"
             "- 퀴즈: front-q9 없는 문항\n드릴: front-d1 모름\n")
    res = {r["id"]: r for r in G.grade_sheet(sheet, keys)}
    assert res["front-q4"]["pass"] and res["front-q4"]["score"] == 1.0
    assert res["front-q9"]["score"] is None and not res["front-d1"]["pass"]
