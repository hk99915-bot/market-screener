"""데스크 10년차 드릴 채점 (G1, 10/24 겸이 결재) — KB 엔 문제만, 답·키는 content/drills, round_collect 가 채점. 네트워크 없음."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import drill_grade as G  # noqa: E402
import round_collect as rc  # noqa: E402


def test_kb_has_no_answers_and_every_drill_has_key():
    assert G.check() == []
    keys = G.load_keys()
    assert len(keys) >= 27 and all(k.endswith("-d1") or "-d" in k for k in keys)


def test_each_key_answer_passes_itself_and_empty_answer_fails():
    for did, it in G.load_keys().items():
        assert G.grade(it, it["answer"])["score"] == 1.0, did
        assert not G.grade(it, "잘 모르겠다, 상황 봐서 적용 판단")["pass"], did


def test_grade_numbers_terms_and_partial():
    it = G.load_keys()["frm-d1"]
    g = G.grade(it, "기대 2.5회인데 7회면 황. 레짐 변화면 60일 창, 아니면 ES·스트레스")
    assert g["pass"] and g["score"] == 1.0
    g2 = G.grade(it, "기대 2.5회, 상황 지켜봄")                    # '상황'의 '황'은 신호등이 아님
    assert not g2["pass"] and "2.5" in g2["hit"]
    b = G.load_keys()["bonds-d1"]
    assert "-1.4" in G.grade(b, "가격 약 1.4% 하락")["hit"]           # 부호 무시 일치


def test_check_catches_answer_left_in_kb(tmp_path):
    kb, keys = tmp_path / "kb", tmp_path / "keys"
    kb.mkdir(); keys.mkdir()
    (keys / "zz.json").write_text('{"desk":"zz","items":[{"id":"zz-d1","q":"q","answer":"a","keys":[{"n":1}]}]}', encoding="utf-8")
    (kb / "zz.md").write_text("- 드릴 [zz-d1]: 문제? **답:** 1\n- 드릴: 두 번째 **답:** 2\n", encoding="utf-8")
    errs = G.check(kb, keys)
    assert any("답이 문제 줄에 남음" in e for e in errs) and any("id 없음" in e for e in errs)


def test_round_collect_adds_drill_table(tmp_path):
    rd = tmp_path / "rounds" / "2026-10-27"
    rd.mkdir(parents=True)
    (rd / "frm.md").write_text("## 배움\n- x\n드릴: frm-d1 기대 2.5회, 황 — 레짐이면 60일, ES 보완\nVOC: 없음\n", encoding="utf-8")
    (rd / "quant.md").write_text("## 배움\n- x\n드릴: quant-d9 모름\n", encoding="utf-8")
    sb = tmp_path / "sb.md"
    sb.write_text("# 스코어보드\n", encoding="utf-8")
    board = tmp_path / "board.json"
    board.write_text('{"tasks": []}', encoding="utf-8")
    ledger = tmp_path / "req.json"
    out = []
    assert rc.run("2026-10-27", tmp_path / "rounds", sb, board, ledger, apply=True, out=out.append, audit_dir=tmp_path) == 0
    text = sb.read_text(encoding="utf-8")
    assert G.DRILL_HEAD in text and "| 2026-10-27 | frm | frm-d1 | 100% | 통과 | — |" in text
    assert "| 2026-10-27 | quant | quant-d9 | — | id 없음 |" in text
    rc.run("2026-10-27", tmp_path / "rounds", sb, board, ledger, apply=True, out=out.append, audit_dir=tmp_path)
    assert sb.read_text(encoding="utf-8").count("frm-d1 |") == 1          # 재수집해도 중복 없음


def test_required_keys_and_weak_key_reverse_checks():
    """평가 키 역검사(10/27 eval.md §2) 재현 — 틀린 판단이 부수 키로 통과하던 3건이 이제 불통과."""
    onb = G.load_onboarding()
    # posrisk-q2: 사용률을 50%·녹으로 틀려도 0.13·컴플·FRM 으로 0.6 통과하던 것 → 필수 키(99.1·적) 누락으로 불통과
    r = G.grade(onb["posrisk-q2"], "사용률 50% 녹. 0.13%p 남음, 넘으면 컴플이 판정, 시나리오는 FRM")
    assert r["score"] >= 0.6 and not r["pass"] and r["req_miss"]
    # '적' 한 글자가 '목적·적절' 에 걸리지 않는다
    assert not G.grade(onb["posrisk-q2"], "사용률 99.1% 목적상 적절, 0.13%p, 컴플, FRM")["pass"]
    assert G.grade(onb["posrisk-q2"], "사용률 99.1% 적, 0.13%p 남음, 컴플, FRM")["pass"]
    # compliance-q1: 기호를 하나도 안 쓴 답은 불통과
    assert not G.grade(onb["compliance-q1"], "시행 중, 결정 대기, 22시 이후 합의, 07시 이후 맞아 확인, 규칙 변경에만 걸린다")["pass"]
    # compliance-q3: '리스크' 만으로는 FRM 키를 못 맞힌다
    assert "FRM" in G.grade(onb["compliance-q3"], "리스크본부가 본다")["miss"]
    assert G.check_onboarding() == []
