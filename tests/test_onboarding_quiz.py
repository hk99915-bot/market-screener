"""신입 온보딩 확인 퀴즈(교육 10/24, 프론트·컴플라이언스·포지션리스크) — 문서엔 문제만, 키는 content/onboarding, 채점 drill_grade (G1 같은 규칙). 네트워크 없음."""
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


def test_risk_courses_six_items_and_doc_text_does_not_pass():
    """10/24 리스크본부 신입 2명 과정 — 6문항씩, 문서의 문제 문장을 그대로 답으로 내도 통과 못 함(문두에 키 노출 금지)."""
    keys = G.load_onboarding()
    # 컴플은 10/28 평행 재시험 q7~q12(문제 compliance_retest_1028.md, 답안 커밋 뒤 키 공개)까지 12문항
    n_items = {"compliance": 12, "posrisk": 6}
    docs = {"compliance": ["compliance_quiz.md", "compliance_retest_1028.md"], "posrisk": ["posrisk_quiz.md"]}
    for desk in ("compliance", "posrisk"):
        q = {k: v for k, v in keys.items() if v["desk"] == desk}
        assert sorted(q, key=lambda s: int(s.rsplit("q", 1)[1])) == [f"{desk}-q{i}" for i in range(1, n_items[desk] + 1)], desk
        doc = "\n".join((G.ONB_DOC_DIR / f).read_text(encoding="utf-8") for f in docs[desk])
        for ln in doc.splitlines():
            m = G.DOC_QUIZ.match(ln)
            if m and m.group(1) in q:
                assert not G.grade(q[m.group(1)], ln)["pass"], m.group(1)
                assert q[m.group(1)].get("src") and len(q[m.group(1)]["keys"]) >= 4


def test_check_catches_quiz_in_wrong_course_doc(tmp_path):
    doc, keys = tmp_path / "doc", tmp_path / "keys"
    doc.mkdir(); keys.mkdir()
    (keys / "aa.json").write_text('{"desk":"aa","items":[{"id":"aa-q1","q":"q","answer":"a 1","keys":[{"n":1}]}]}', encoding="utf-8")
    (doc / "bb_quiz.md").write_text("- 퀴즈 [aa-q1]: 남의 과정 문서에 들어간 문제\n", encoding="utf-8")
    assert any("다른 과정 문서" in e for e in G.check_onboarding(doc, keys))
