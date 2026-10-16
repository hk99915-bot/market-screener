"""STUDY v3 콘텐츠 검증 — 스키마·id 중복·prereq 순환·quiz 인덱스·빌드 동기화·study_daily 선택 로직 (네트워크 없음)."""
import copy
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import study_content_check as scc  # noqa: E402

from screener import study_daily  # noqa: E402


@pytest.fixture(scope="module")
def S():
    return scc.load_sources()


def test_real_content_passes(S):
    c = scc.check_all(S)
    assert not c.errors, "\n".join(c.errors)


def test_build_in_sync(S):
    built = scc.dumps(scc.build(S))
    assert (ROOT / "content" / "study.json").read_text(encoding="utf-8") == built, "python scripts/study_content_check.py --build 실행 필요"


def test_terminal_compat_keys(S):
    """Index.html eduModule() 이 읽는 구형 키가 빌드본 모든 모듈에 있다."""
    b = scc.build(S)
    for k in ("version", "updated", "title", "intro", "roadmap", "tesat", "tracks", "aptitude"):
        assert k in b
    for t in b["tracks"]:
        for m in t["modules"]:
            for k in ("id", "title", "tags", "level", "hours", "summary", "analogy", "terms", "prereq", "concepts", "formulas", "example", "mistakes", "quiz"):
                assert k in m, (m["id"], k)
            for q in m["quiz"]:
                assert {"t", "q", "a", "why"} <= set(q), (m["id"], q.get("q"))
            for f in m["formulas"]:
                assert "f" in f
            if m.get("today"):
                assert {"keys", "text"} <= set(m["today"])


def test_v3_modules_cited_and_capped(S):
    n = 0
    for t in S["tracks"]:
        for m in t["modules"]:
            if m.get("schema") == 3:
                n += 1
                assert m["est_min"] <= 20
                assert all(scc.CITE.search(x) for x in m["concepts"] + m["pitfalls"])
                assert m["sources"]
    assert n >= 25


def test_roadmap_hours_recomputed(S):
    b = scc.build(S)
    total = sum(float(m["hours"]) for t in b["tracks"] for m in t["modules"])
    assert b["roadmap"]["total_hours"] == round(total, 1)
    assert b["roadmap"]["total_modules"] == sum(len(t["modules"]) for t in b["tracks"])


def _mini():
    mod = {"schema": 3, "id": "X1", "track": "X", "title": "t", "tags": ["a"], "level": 1, "est_min": 10, "prereq": [], "objectives": ["a", "b"],
           "summary": "s", "analogy": "a", "terms": [{"t": "a", "d": "b"}], "concepts": ["c [교육 보충]"],
           "formulas": [{"name": "n", "f": "f", "example": "e", "src": "[교육 보충]"}], "example": "e",
           "market_hook": {"tab": "HOME", "fields": ["x"], "read": "r"}, "terminal_lookup": "l", "rule_link": "r", "pitfalls": ["p [교육 보충]"],
           "quiz": [{"kind": "knowledge", "q": "q", "choices": ["a", "b", "c", "d"], "answer": 0, "why": "w"}] * 3,
           "next_door": "n", "srs": {"intervals": [1, 3, 7, 21]}, "sources": ["교육 보충"]}
    idx = {"version": 3, "updated": "2026-10-16", "title": "t", "intro": "i", "tesat": {}, "track_order": ["X"],
           "roadmap": {"order": ["X1"], "steps": [{"name": "s", "ids": ["X1"]}]}}
    return {"index": idx, "tracks": [{"id": "X", "title": "X", "modules": [mod]}], "aptitude": {}, "quiz_bank": None, "srs": None}


def test_mini_passes():
    assert not scc.check_all(_mini()).errors


def test_duplicate_id_fails():
    S = _mini()
    S["tracks"][0]["modules"].append(copy.deepcopy(S["tracks"][0]["modules"][0]))
    assert any("id 중복" in e for e in scc.check_all(S).errors)


def test_prereq_cycle_fails():
    S = _mini()
    m2 = copy.deepcopy(S["tracks"][0]["modules"][0]); m2["id"] = "X2"; m2["prereq"] = ["X1"]
    S["tracks"][0]["modules"][0]["prereq"] = ["X2"]
    S["tracks"][0]["modules"].append(m2); S["index"]["roadmap"]["order"].append("X2"); S["index"]["roadmap"]["steps"][0]["ids"].append("X2")
    assert any("순환" in e for e in scc.check_all(S).errors)


def test_missing_prereq_fails():
    S = _mini(); S["tracks"][0]["modules"][0]["prereq"] = ["NOPE"]
    assert any("없는 모듈" in e for e in scc.check_all(S).errors)


def test_quiz_answer_out_of_range_fails():
    S = _mini(); S["tracks"][0]["modules"][0]["quiz"][0] = {**S["tracks"][0]["modules"][0]["quiz"][0], "answer": 4}
    assert any("answer 인덱스" in e for e in scc.check_all(S).errors)


def test_quiz_choices_not_four_fails():
    S = _mini(); S["tracks"][0]["modules"][0]["quiz"][0] = {**S["tracks"][0]["modules"][0]["quiz"][0], "choices": ["a", "b", "c"]}
    assert any("choices" in e for e in scc.check_all(S).errors)


def test_est_min_cap_fails():
    S = _mini(); S["tracks"][0]["modules"][0]["est_min"] = 45
    assert any("est_min" in e for e in scc.check_all(S).errors)


def test_uncited_concept_fails():
    S = _mini(); S["tracks"][0]["modules"][0]["concepts"] = ["출처 없는 문장"]
    assert any("출처 태그" in e for e in scc.check_all(S).errors)


def test_missing_field_fails():
    S = _mini(); del S["tracks"][0]["modules"][0]["rule_link"]
    assert any("rule_link" in e for e in scc.check_all(S).errors)


def test_banned_word_fails():
    S = _mini(); S["tracks"][0]["modules"][0]["summary"] = "누나"
    assert any("금지어" in e for e in scc.check_all(S).errors)


def test_cli_passes():
    r = subprocess.run([sys.executable, "scripts/study_content_check.py"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ── study_daily 선택 로직 ──
def test_study_daily_picks_without_progress(tmp_path):
    study = json.loads((ROOT / "content" / "study.json").read_text(encoding="utf-8"))
    bank = json.loads((ROOT / "content" / "study" / "quiz_bank.json").read_text(encoding="utf-8"))
    srs = json.loads((ROOT / "content" / "study" / "srs.json").read_text(encoding="utf-8"))
    o = study_daily.build(date(2026, 10, 20), study, bank, srs, None, {"title": "Headline", "date": "2026-10-20", "level": "B1"})
    assert o["review"] is None
    assert o["new"]["id"] == study["roadmap"]["first_two_weeks"][0]
    assert o["new"]["est_min"] <= 20
    assert o["quiz"]["module"] == o["new"]["id"] and len(o["quiz"]["choices"]) == 4
    assert o["english"]["title"] == "Headline"
    txt = study_daily.telegram_text(o)
    assert txt.startswith("📚 오늘 공부:") and "퀴즈 1" in txt and "누나" not in txt


def test_study_daily_review_and_progress(tmp_path):
    study = json.loads((ROOT / "content" / "study.json").read_text(encoding="utf-8"))
    bank = json.loads((ROOT / "content" / "study" / "quiz_bank.json").read_text(encoding="utf-8"))
    srs = json.loads((ROOT / "content" / "study" / "srs.json").read_text(encoding="utf-8"))
    ftw = study["roadmap"]["first_two_weeks"]
    progress = {"modules": {ftw[0]: {"done": ["2026-10-10"], "stage": 1, "next_due": "2026-10-13"},
                            ftw[1]: {"done": ["2026-10-18"], "stage": 0, "next_due": "2026-10-19"},
                            "R6": {"done": ["2026-09-01"], "stage": 4, "next_due": "2026-09-22"}}}
    o = study_daily.build(date(2026, 10, 20), study, bank, srs, progress, None)
    assert o["review"]["id"] == ftw[0] and o["review"]["overdue_days"] == 7      # 가장 오래 밀린 것, 정착(stage 4)은 제외
    assert o["new"]["id"] == ftw[2]                                                # 완료 2개 건너뜀
    assert o["quiz"]["module"] == ftw[0]                                           # 복습 모듈 우선
    # 같은 날 같은 문항 (결정적)
    o2 = study_daily.build(date(2026, 10, 20), study, bank, srs, progress, None)
    assert o2["quiz"]["id"] == o["quiz"]["id"]


def test_study_daily_run_writes_file(tmp_path):
    import shutil
    (tmp_path / "content" / "study").mkdir(parents=True)
    shutil.copy(ROOT / "content" / "study.json", tmp_path / "content" / "study.json")
    for f in ("quiz_bank.json", "srs.json"):
        shutil.copy(ROOT / "content" / "study" / f, tmp_path / "content" / "study" / f)
    o = study_daily.run(date(2026, 10, 21), send=False, root=tmp_path)
    assert (tmp_path / "reports" / "study_daily.json").exists()
    assert o["new"] is not None
