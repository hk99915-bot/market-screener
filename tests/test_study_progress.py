"""STUDY 진행 기록 — 이슈 파싱·채점·오답 피드백 큐·2주 게이트·출석·study_daily 연동 (네트워크 없음)."""
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import study_content_check as scc  # noqa: E402

from screener import study_daily, study_progress as sp  # noqa: E402


@pytest.fixture(scope="module")
def study():
    return json.loads((ROOT / "content" / "study.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bank():
    return json.loads((ROOT / "content" / "study" / "quiz_bank.json").read_text(encoding="utf-8"))


def _tmp_root(tmp_path: Path) -> Path:
    (tmp_path / "content" / "study").mkdir(parents=True)
    shutil.copy(ROOT / "content" / "study.json", tmp_path / "content" / "study.json")
    for f in ("quiz_bank.json", "srs.json"):
        shutil.copy(ROOT / "content" / "study" / f, tmp_path / "content" / "study" / f)
    return tmp_path


# ── 이슈 파싱 ──
def test_parse_issue_title_and_body():
    p = sp.parse_issue("study H2 done", "quiz H2-b4 1\nmin 15\n")
    assert p["id"] == "H2" and p["quiz"] == [("H2-b4", 1)] and p["min"] == 15 and p["bad"] == []


def test_parse_issue_variants():
    assert sp.parse_issue("Study 0-3 Done", None)["id"] == "0-3"
    assert sp.parse_issue("study R1 done", "min=20\nquiz R1-b1 3")["quiz"] == [("R1-b1", 3)]
    assert sp.parse_issue("study R1 done", "quiz R1-b1 <0~3>")["bad"] == ["quiz R1-b1 <0~3>"]   # 번호 안 바꾼 줄
    assert sp.parse_issue("study R1 done", "quiz R1-b1 4")["quiz"] == []                          # 범위 밖
    assert sp.parse_issue("pick 2026-10-20", "") is None
    assert sp.parse_issue("study H2", "") is None


def test_issue_url_pattern():
    u = sp.issue_url_study("H2", "quiz H2-b4 <0~3>\nmin 15")
    assert u.startswith(f"https://github.com/{sp.REPO}/issues/new?title=study%20H2%20done&body=")
    assert "누나" not in u


# ── 채점 ──
def test_grade_against_bank(bank):
    it = bank["items"][0]
    g = sp.grade(bank, it["id"], it["answer"])
    assert g["ok"] and g["module"] == it["module"] and len(g["choices"]) == 4
    wrong = (it["answer"] + 1) % 4
    assert sp.grade(bank, it["id"], wrong)["ok"] is False
    assert sp.grade(bank, "NOPE-b9", 0) is None


def test_quiz_desk_from_src():
    assert sp.quiz_desk({"module": "R1", "src": ["kb:frm#1"]}) == "frm"
    assert sp.quiz_desk({"module": "D1", "src": ["consult:derivs#q3"]}) == "derivs"
    assert sp.quiz_desk({"module": "H2", "src": ["consult:pb_learner#L3"]}) == "behavior"   # 학습자 자문은 데스크 아님 → 트랙
    assert sp.quiz_desk({"module": "M1", "src": []}) == "cio"


# ── 출석 ──
def test_streak_weekday_rule():
    assert sp.streak([]) == 0
    assert sp.streak(["2026-10-19", "2026-10-20", "2026-10-21"]) == 3
    assert sp.streak(["2026-10-16", "2026-10-19"]) == 2            # 금 → 월 (주말 건너뜀)
    assert sp.streak(["2026-10-19", "2026-10-21"]) == 1            # 화요일 결손 → 끊김
    assert sp.streak(["2026-10-19", "2026-10-19", "2026-10-20"]) == 2   # 같은 날 2개 = 1일


# ── SRS 파생 ──
def test_derive_modules_srs():
    done = [{"id": "H2", "date": "2026-10-20", "min": 15}]
    quiz = [{"qid": "H2-b1", "module": "H2", "ok": True, "date": "2026-10-21"},    # due(10/21) 통과 → stage 1, 10/24
            {"qid": "H2-b2", "module": "H2", "ok": False, "date": "2026-10-24"}]   # 실패 → stage 0, 10/25
    m = sp.derive_modules(done, quiz)["H2"]
    assert m["done"] == ["2026-10-20"] and m["stage"] == 0 and m["next_due"] == "2026-10-25"
    m2 = sp.derive_modules(done, quiz[:1])["H2"]
    assert m2["stage"] == 1 and m2["next_due"] == "2026-10-24"


# ── 적용 + 오답 피드백 큐 ──
def test_apply_issue_records_and_feeds_back(tmp_path, bank, study):
    root = _tmp_root(tmp_path)
    it = next(q for q in bank["items"] if q["module"] == "H2")
    wrong = (it["answer"] + 1) % 4
    msg = sp.apply_issue("study H2 done", f"quiz {it['id']} {wrong}\nmin 15", "2026-10-19T22:30:00Z", root=root)
    assert "H2" in msg and "오답" in msg and "출석 1일 연속" in msg and "누나" not in msg
    p = json.loads((root / "reports" / "study_progress.json").read_text(encoding="utf-8"))
    assert p["done"] == [{"id": "H2", "date": "2026-10-20", "min": 15}]          # 22:30Z = KST 다음날
    assert p["quiz"][0]["qid"] == it["id"] and p["quiz"][0]["ok"] is False
    assert p["streak"] == 1 and p["last"] == "2026-10-20" and p["modules"]["H2"]["next_due"] == "2026-10-21"
    w = json.loads((root / "reports" / "study_wrong.json").read_text(encoding="utf-8"))
    assert w["items"][0]["qid"] == it["id"] and w["items"][0]["desk"] == sp.quiz_desk(it)
    fb = (root / "docs" / "desk_kb" / "_quiz_feedback.md").read_text(encoding="utf-8")
    assert "흔한 오해" in fb and f"| H2 | {sp.quiz_desk(it)} | {it['id']} |" in fb and it["choices"][wrong] in fb
    # 같은 이슈 재적용(워크플로 재시도) → 중복 없음
    sp.apply_issue("study H2 done", f"quiz {it['id']} {wrong}", "2026-10-19T22:30:00Z", root=root)
    p2 = json.loads((root / "reports" / "study_progress.json").read_text(encoding="utf-8"))
    assert len(p2["done"]) == 1 and len(p2["quiz"]) == 1
    assert (root / "docs" / "desk_kb" / "_quiz_feedback.md").read_text(encoding="utf-8").count(it["id"]) == 1


def test_apply_correct_answer_no_feedback(tmp_path, bank):
    root = _tmp_root(tmp_path)
    it = next(q for q in bank["items"] if q["module"] == "R1")
    msg = sp.apply_issue("study R1 done", f"quiz {it['id']} {it['answer']}", "2026-10-20T01:00:00Z", root=root)
    assert "정답" in msg and not (root / "reports" / "study_wrong.json").exists()
    assert not (root / "docs" / "desk_kb" / "_quiz_feedback.md").exists()


def test_apply_unknown_module(tmp_path):
    root = _tmp_root(tmp_path)
    msg = sp.apply_issue("study ZZ9 done", "", None, root=root)
    assert "없습니다" in msg
    p = json.loads((root / "reports" / "study_progress.json").read_text(encoding="utf-8"))
    assert p["done"] == []


def test_bad_format_message():
    assert "형식" in sp.apply_issue("study", "", None, root=Path("/nonexistent"))


# ── 2주 게이트 ──
def test_two_week_gate_15_open(study):
    g = study["gate"]
    assert len(g["open"]) == 15 and len(g["locked"]) == 52 and g["unlock_rule"] == "앞 모듈 done 이슈"
    assert g["open"][:10] == study["roadmap"]["first_two_weeks"] and g["open"][0] == "H2"
    mods = {m["id"]: m for t in study["tracks"] for m in t["modules"]}
    assert sum(1 for m in mods.values() if not m["locked"]) == 15
    assert all(m["unlock_rule"] == "앞 모듈 done 이슈" and m["open_until"] is None for m in mods.values() if m["locked"])
    assert all(m["open_until"] == g["open_until"] for m in mods.values() if not m["locked"])


def test_gate_check_rejects_wrong_count():
    S = scc.load_sources()
    S["index"]["gate"]["open"] = S["index"]["gate"]["open"][:-1]
    S["index"]["gate"]["locked"] = S["index"]["gate"]["locked"] + [S["index"]["gate"]["open"][-1]]
    assert any("정확히 15" in e for e in scc.check_all(S).errors)


def test_unlock_next_on_done(study):
    p = {"unlocked": []}
    nxt = sp.unlock_next(p, study, "H2")
    order = study["roadmap"]["order"]
    assert nxt in study["gate"]["locked"] and order.index(nxt) > order.index("H2") and p["unlocked"] == [nxt]
    assert sp.unlock_next(p, study, "H2") != nxt          # 이미 열린 건 건너뛰고 그 다음
    assert sp.unlock_next({"unlocked": []}, study, "NOPE") is None


# ── study_daily 연동 ──
def test_daily_picks_only_open_modules(study, bank):
    srs = json.loads((ROOT / "content" / "study" / "srs.json").read_text(encoding="utf-8"))
    g = study["gate"]
    progress = {"done": [{"id": i, "date": "2026-10-20", "min": 10} for i in g["open"]], "quiz": [], "streak": 15, "unlocked": [], "modules": {}}
    o = study_daily.build(date(2026, 10, 21), study, bank, srs, progress, None)
    assert o["new"] is None and o["gate"]["next_locked"] in g["locked"]
    txt = study_daily.telegram_text(o)
    assert "잠김" in txt and "앞 모듈 done 이슈" in txt
    progress["unlocked"] = [g["locked"][0]]
    o2 = study_daily.build(date(2026, 10, 21), study, bank, srs, progress, None)
    assert o2["new"]["id"] == g["locked"][0]


def test_daily_message_two_blocks_with_issue_link_and_streak(study, bank):
    srs = json.loads((ROOT / "content" / "study" / "srs.json").read_text(encoding="utf-8"))
    progress = {"done": [{"id": "H2", "date": "2026-10-20", "min": 15}], "quiz": [], "streak": 1, "unlocked": [], "modules": {}}
    o = study_daily.build(date(2026, 10, 21), study, bank, srs, progress, {"title": "x"})
    txt = study_daily.telegram_text(o)
    lines = txt.splitlines()
    assert len(lines) == 2 and lines[0].startswith("📚 오늘 공부:") and o["new"]["id"] == "R1"
    assert f"issues/new?title=study%20{o['new']['id']}%20done" in txt and "출석 1일 연속" in txt and "누나" not in txt


def test_daily_quiz_skips_answered(study, bank):
    srs = json.loads((ROOT / "content" / "study" / "srs.json").read_text(encoding="utf-8"))
    ids = [q["id"] for q in bank["items"] if q["module"] == "H2"]
    progress = {"done": [], "quiz": [{"qid": i, "module": "H2", "ok": True, "date": "2026-10-20"} for i in ids[:-1]], "unlocked": [], "modules": {}}
    o = study_daily.build(date(2026, 10, 21), study, bank, srs, progress, None)
    assert o["quiz"]["id"] == ids[-1]
