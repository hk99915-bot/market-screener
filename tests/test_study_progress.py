"""STUDY 진행 기록 — 이슈 파싱·채점·오답 피드백 큐·2주 게이트·출석·study_daily 연동 (네트워크 없음)."""
import copy
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
    mods = {m["id"]: m for t in study["tracks"] for m in t["modules"]}
    # locked = 전체 − 15 (10/24 트랙 J 추가로 52 → 58; 모듈 수 하드코딩 대신 파생)
    assert len(g["open"]) == 15 and len(g["locked"]) == len(mods) - 15 and g["unlock_rule"] == "앞 모듈 done 이슈"
    assert g["open"][:10] == study["roadmap"]["first_two_weeks"] and g["open"][0] == "H2"
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


# ── STUDY 탭 내보내기 (v1 UTC · v2 KST) ──
V1 = {"v": 1, "sent": "2026-10-23", "issue": 17,
      "done": {"0-1": "2026-10-15", "0-4": "2026-10-18"},
      "apt": [["E2026-10-23-0", 0, None, "2026-10-22"],     # 출제일 = UTC+1 → KST 10/23 확정
              ["E2026-10-16-1", 1, 4, "2026-10-18"],        # 출제일보다 늦게 풂 → KST 10/18 또는 10/19 (U)
              ["N7", 0, 30, "2026-10-18"]],
      "eng": [["2026-10-22", "r", 0, 1], ["2026-10-22", "q", 1, 0], ["2026-10-23", "q", 0, 1]],
      "op": []}


def test_apply_export_v1_merge_and_idempotent(study):
    p, it = sp.merge_export({}, V1, study)
    assert [(d["id"], d["date"], d["tz"]) for d in p["done"]] == [("0-1", "2026-10-15", "U"), ("0-4", "2026-10-18", "U")]
    assert it["apt"]["E2026-10-23-0"] == {"ok": 0, "sec": None, "date": "2026-10-23", "tz": "K"}
    assert it["apt"]["E2026-10-16-1"]["tz"] == "U" and it["apt"]["N7"]["sec"] == 30
    assert it["eng"]["2026-10-22|q|1"] == {"ok": 0, "date": "2026-10-22", "tz": "C"}
    s = p["summary"]
    assert s["apt"] == {"n": 3, "ok": 1, "rate": 0.333} and s["eng_quiz"]["n"] == 2
    # 10/22 복습(r) = 정답 노출 버그 수정(9842e63e, 10/26) 전 응답 → 원응답 보존, 집계 제외(req-dev-1a14cbe5 ①)
    assert s["eng_review"] == {"n": 0, "ok": 0, "rate": None, "tainted": 1}
    assert it["eng"]["2026-10-22|r|0"] == {"ok": 1, "date": "2026-10-22", "tz": "C", "tainted": 1}
    assert s["apt_by"]["오늘의 인적성"] == {"n": 2, "ok": 1, "rate": 0.5} and s["apt_by"]["유형 대응"]["n"] == 1
    assert s["done_modules"] == 2 and p["last"] == "2026-10-23" and p["exports"] == [{"v": 1, "sent": "2026-10-23", "issue": 17}]
    assert p["streak"] == 2                                   # 10/18(일) 뒤 10/19~21 평일 결손 → 10/22~23
    assert p["modules"]["0-4"]["next_due"] == "2026-10-19"
    assert sp.merge_export(p, V1, study, it) == (p, it)       # 같은 내보내기 재적용 → 동일(멱등)


def test_public_file_has_no_item_level_records(study):
    """피어리뷰 E2(10/24): 공개 진행 파일엔 문항 id·정답 여부·초가 없다 — 영역·유형별 비율·횟수·모듈 id·streak 만."""
    p = sp.apply_export({}, V1, study)
    blob = json.dumps(p, ensure_ascii=False)
    assert "apt" not in {k for k in p if k != "summary"} and "eng" not in p
    assert "E2026-10-23-0" not in blob and "N7" not in blob and "2026-10-22|q|1" not in blob
    # 옛 공개 파일(apt·eng 포함)은 1회 이전: 비공개 상태로 옮기고 공개에서 지운다
    legacy = {"apt": {"N7": {"ok": 0, "sec": 30, "date": "2026-10-18", "tz": "U"}}, "eng": {}}
    q, it = sp.merge_export(legacy, {"v": 2, "tz": "KST", "apt": [], "eng": []}, study)
    assert "apt" not in q and it["apt"]["N7"]["ok"] == 0 and q["summary"]["apt"]["n"] == 1 and "2026-10-18" in q["days"]


def test_apply_export_first_response_fixed_and_v2_kst(study):
    """피어리뷰 E1(10/24): 같은 문항은 첫 응답 고정(kb:eval#8) — 나중에 다시 풀어 맞혀도 첫 오답이 남는다."""
    p, it = sp.merge_export({}, V1, study)
    v2 = {"v": 2, "tz": "KST", "sent": "2026-10-24",
          "done": {"0-4": "2026-10-24"},
          "apt": [["N7", 1, 20, "2026-10-24", "K"], ["E2026-10-16-1", 0, 9, "2026-10-17", "U"]],   # 더 이른 날짜 행은 첫 응답으로 대체
          "eng": [["2026-10-22", "q", 1, 1, "2026-10-24"]], "op": [["2026-10-24", 0, "IM3", "2026-10-24"]]}
    q, it2 = sp.merge_export(p, v2, study, it)
    assert it2["apt"]["N7"] == {"ok": 0, "sec": 30, "date": "2026-10-18", "tz": "U"}              # 첫 오답 유지
    assert it2["apt"]["E2026-10-16-1"] == {"ok": 0, "sec": 9, "date": "2026-10-17", "tz": "U"}    # 더 이른 응답이 첫 응답
    assert it2["eng"]["2026-10-22|q|1"]["ok"] == 0
    assert [d["date"] for d in q["done"] if d["id"] == "0-4"] == ["2026-10-24"]          # 체크박스 = 모듈당 1행, 최신
    assert q["op_count"] == 1 and "IM3" not in json.dumps(q, ensure_ascii=False)          # OPIc 자기평가 내용은 공개 파일에 안 남김
    assert q["last"] == "2026-10-24" and len(q["exports"]) == 2


def test_same_day_exports_order_independent(study):
    """같은 날짜 내보내기 두 개를 어느 순서로 넣어도 결과가 같다(피어리뷰 채점 S1)."""
    a = {"v": 2, "tz": "KST", "sent": "2026-10-24", "apt": [["N7", 1, 20, "2026-10-24", "K"]], "eng": [["2026-10-24", "q", 0, 1, "2026-10-24"]]}
    b = {"v": 2, "tz": "KST", "sent": "2026-10-24", "apt": [["N7", 0, 35, "2026-10-24", "K"]], "eng": [["2026-10-24", "q", 0, 0, "2026-10-24"]]}
    pa, ia = sp.merge_export({}, a, study)
    pab, iab = sp.merge_export(pa, b, study, ia)
    pb_, ib = sp.merge_export({}, b, study)
    pba, iba = sp.merge_export(pb_, a, study, ib)
    assert iab["apt"] == iba["apt"] and iab["eng"] == iba["eng"]
    assert pab["summary"] == pba["summary"] and iab["apt"]["N7"]["ok"] == 0                 # 같은 날이면 오답 먼저(보수)


def test_apply_export_keeps_issue_records_and_reads_issue_body(tmp_path, study):
    root = _tmp_root(tmp_path)
    sp.apply_issue("study H2 done", "min 10", "2026-10-21T01:00:00Z", root=root)
    body = "학습 기록\n\n```json\n" + json.dumps(V1) + "\n```\n"
    (tmp_path / "body.md").write_text(body, encoding="utf-8")
    priv = tmp_path / "priv"
    s = sp.apply_export_file(str(tmp_path / "body.md"), root=root, priv=priv)
    p = json.loads((root / "reports" / "study_progress.json").read_text(encoding="utf-8"))
    items = json.loads((priv / "items.json").read_text(encoding="utf-8"))
    assert "apt" not in p and items["apt"]["N7"]["ok"] == 0          # 문항 단위는 비공개 쪽에만
    assert {"H2", "0-1", "0-4"} <= {d["id"] for d in p["done"]} and s["done_modules"] == 3
    assert p["streak"] == 3                                   # 10/21(H2 이슈)·10/22·10/23


def test_apply_export_unknown_module_skipped(study):
    p = sp.apply_export({}, {"v": 2, "tz": "KST", "done": {"ZZ9": "2026-10-23"}, "apt": [], "eng": []}, study)
    assert p["done"] == [] and p["summary"]["done_modules"] == 0


# ── G3(10/24 겸이 결재): 퀴즈 응답 텔레그램 수집 — 문장 답·퀴즈만 이슈 ──
def test_g3_text_answer_resolves_by_choice_text(bank):
    it = bank["items"][0]
    right = it["choices"][it["answer"]]
    p = sp.parse_issue("study quiz", f"quiz {it['id']} {right[:6]}\nquiz {it['id']} 2\nquiz {it['id']} <0~3>")
    assert p["quiz_only"] and p["id"] is None and p["quiz"][0] == (it["id"], right[:6]) and p["quiz"][1] == (it["id"], 2)
    assert p["bad"] == [f"quiz {it['id']} <0~3>"]
    g = sp.grade(bank, it["id"], right[:6])
    assert g["ok"] and g["answer"] == it["answer"]
    assert sp.resolve_choice(["손익분기 승률", "손익비", "손절"], "손") is None          # 1자 → 모호
    assert sp.resolve_choice(["손익분기 승률", "손익비", "손절"], "손익") is None        # 앞부분 2개 일치 → 모호
    assert sp.resolve_choice(["손익분기 승률", "손익비", "손절"], "손익비") == 1
    assert sp.resolve_choice(["+42.9%", "+30%", "+60%"], "42.9") == 0                     # 포함 일치


def test_g3_text_answer_survives_choice_reorder(bank):
    it = copy.deepcopy(bank["items"][0])
    right = it["choices"][it["answer"]]
    it["choices"] = it["choices"][::-1]
    it["answer"] = it["choices"].index(right)
    g = sp.grade({"items": [it]}, it["id"], right)
    assert g["ok"]


def test_g3_quiz_only_issue_records_without_done(tmp_path, bank):
    root = _tmp_root(tmp_path)
    it = next(q for q in bank["items"] if q["module"] == "R1")
    right = it["choices"][it["answer"]]
    msg = sp.apply_issue("study quiz", f"quiz {it['id']} {right}", "2026-10-24T12:00:00Z", root=root)
    assert "퀴즈 1문항 기록" in msg and "정답" in msg
    p = json.loads((root / "reports" / "study_progress.json").read_text(encoding="utf-8"))
    assert p["done"] == [] and p["quiz"][0]["ok"] is True and p["quiz"][0]["answer"] == it["answer"]
    msg2 = sp.apply_issue("study quiz", f"quiz {it['id']} 아무말대잔치", "2026-10-24T12:00:00Z", root=root)
    assert "안 정해짐" in msg2


def test_g3_index_forms_and_out_of_range_not_silently_dropped():
    """평가 검수(req-eval-305a74f8 ②): '3)'·'3번'은 번호, '4'·'10' 같은 범위 밖 번호는 bad 로 알린다(전엔 아무 데도 안 남음)."""
    p = sp.parse_issue("study quiz", "quiz H2-b2 3)\nquiz H2-b2 2번\nquiz H2-b2 4\nquiz H2-b2 10")
    assert p["quiz"] == [("H2-b2", 3), ("H2-b2", 2)]
    assert p["bad"] == ["quiz H2-b2 4", "quiz H2-b2 10"]


def test_v2_module_quiz_first_response_and_committed_rate(study):
    """v2 quiz(모듈 확인문제) — 첫 응답 고정, 보기 고른 것만 committed 점수, 공개 파일엔 비율만."""
    x = {"v": 2, "tz": "KST", "sent": "2026-10-27", "apt": [], "eng": [],
         "quiz": [["2026-10-24", "0-6", 0, 1, 0, 0], ["2026-10-24", "0-6", 1, 0, None, 1], ["2026-10-24", "0-6", 2, 0, 3, 0]]}
    p, it = sp.merge_export({}, x, study)
    mq = p["summary"]["mod_quiz"]
    assert (mq["n"], mq["ok"], mq["self_n"]) == (3, 1, 1)
    assert (mq["committed"]["n"], mq["committed"]["ok"]) == (2, 1)
    assert "0-6|0" in it["mq"] and "mq" not in p
    again = {**x, "quiz": [["2026-10-26", "0-6", 2, 1, 1, 0]]}       # 나중에 다시 맞혀도 첫 응답 유지
    p2, _ = sp.merge_export(p, again, study, it)
    assert p2["summary"]["mod_quiz"]["ok"] == 1


def test_eng_review_after_fix_counts(study):
    x = {"v": 2, "tz": "KST", "sent": "2026-10-27", "eng": [["2026-10-24", "r", 0, 1, "2026-10-26"], ["2026-10-24", "r", 1, 0, "2026-10-25"]]}
    p, it = sp.merge_export({}, x, study)
    assert p["summary"]["eng_review"] == {"n": 1, "ok": 1, "rate": 1.0, "tainted": 1}
    assert "tainted" not in it["eng"]["2026-10-24|r|0"] and it["eng"]["2026-10-24|r|1"]["tainted"] == 1
    assert "2026-10-25" not in p["days"]                      # tainted 응답일은 활동일 집계에서도 뺌


def test_apt_choice_column_kept(study):
    # 내보내기 apt 6번째 칸 = 고른 보기 번호 c (req-dev-826c4bf0 ②)
    x = {"v": 2, "tz": "KST", "apt": [["N7", 0, 30, "2026-10-28", "K", 2], ["N8", 1, None, "2026-10-28", "K"]], "eng": []}
    _, it = sp.merge_export({}, x, study)
    assert it["apt"]["N7"]["c"] == 2 and "c" not in it["apt"]["N8"]


def test_streak_rest_day_keeps_chain():
    from screener.study_progress import streak
    # 10/27(화)·10/28(수) 학습, 10/29(목) 쉼 신청, 10/30(금) 학습 → 끊기지 않고 3(쉼일은 +1 안 함)
    assert streak(["2026-10-27", "2026-10-28", "2026-10-30"], ["2026-10-29"]) == 3
    assert streak(["2026-10-27", "2026-10-28", "2026-10-30"]) == 1
