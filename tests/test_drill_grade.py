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
    f = G.load_keys()["front-d1"]                                    # 필수 키(req) — 44 를 놓치면 다른 키를 다 맞혀도 불통과 (평가 10/27 반려 결함 2)
    g3 = G.grade(f, "36px 유지(AA 통과), 색은 토큰 --bg2, build_pages 후 ui_smoke·skin_audit xl, 엑셀 스킨 검정 글자")
    assert g3["score"] >= 0.6 and not g3["pass"] and "44" in g3["miss"]
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


def test_compliance_keys_reject_eval_wrong_answers():
    """평가 역검수 10/28(eval_track_k.md) — 0.88/0.67/0.83 로 통과하던 오답 3건이 필수 키로 불통과, 모범답·바른 요약은 통과."""
    onb = G.load_onboarding()
    q1, q3, q6 = onb["compliance-q1"], onb["compliance-q3"], onb["compliance-q6"]
    w1 = "✅ 시행 중, 🗳️ 결정 대기, 🔒 잠금 자동 약속, 🌙 22시 이후 합의. 밤 12시 변경은 즉시 시행하고 확인 불필요. 22시 금지는 규칙 변경 포함 모든 답변에 걸린다."
    r = G.grade(q1, w1)
    assert not r["pass"] and r["req_miss"]
    assert G.grade(q1, "✅ 시행 중, 🗳️ 결정 대기, 🔒 자동 약속, 🌙 22시 이후 합의. 🌙 로 적고 07시 이후 맞아 확인 뒤 시행, 22시 금지는 규칙 변경에만")["pass"]
    w3 = "능동 위반이라 즉시 매도, 크기 0.3%p. 위반 중 완화 금지, 시나리오는 FRM"
    r = G.grade(q3, w3)
    assert not r["pass"] and "수동/passive" in r["req_miss"]
    assert "re:매수[^.]{0,20}능동/re:능동[^.]{0,20}(원상|매수)" in r["miss"]   # 맨 '능동' 은 키를 못 맞힌다
    assert G.grade(q3, "수동 위반 0.3%p, 기한 정해 해소. 매수로 넘겼다면 능동. 위반 중 완화 금지, 시나리오는 FRM")["pass"]
    w6 = "쿨다운은 PB 말이니 바로 시행. 결재 없이 커밋됐고 새 숏 진입이라 손절·독립성 검사"
    r = G.grade(q6, w6)
    assert not r["pass"] and r["req_miss"]
    assert G.grade(q6, "결정 아님(결재 없이 바꿈), 부모 없는 헤지는 새 숏이라 손절·독립성 검사, 쿨다운도 규칙 변경이라 결재 필요")["pass"]
    for it in (q1, q3, q6):
        assert G.grade(it, it["answer"])["score"] == 1.0


def test_compliance_q1_accepts_correct_variants_and_still_rejects_wrong():
    """평가 반려 10/28(eval_riskhq_onboarding_appendix.md 근거 2) — 강화 키가 맞는 답(C1·C2·컴플 실제 답)을 0.88 로 떨어뜨리던 결함.
    정답 변형은 통과, 반려 오답(W1~W3)은 계속 불통과. 부정문(W4)은 키로 막지 않고 평가 판독(kb:eval#16)."""
    q1 = G.load_onboarding()["compliance-q1"]
    head = "✅ 시행 중, 🗳️ 결정 대기, 🔒 자동 약속, 🌙 22시 이후 합의. 밤 12시 변경은 🌙 로 적고 07시 이후 겸이 맞아 확인 뒤 시행. "
    correct = [
        head + "22시 금지는 규칙 변경(한도·금지·절차)에만 걸린다",                           # C1 괄호 열거
        head + "22시 금지의 대상은 규칙 변경뿐이다",                                         # C2 '대상…뿐'
        head + "금지 대상은 규칙 변경이고 운영·매매 질문 답변은 아니다",                       # '대상은 규칙 변경'
        head + "22시 금지는 규칙 변경 한정, 강화 루프·운영은 대상 아님",                       # '한정'
        # 컴플 실제 답(rounds/2026-10-27/compliance.md:6)
        "✅ 시행 중 · 🗳️ 결정 대기(일요일·11/15 리뷰) · 🔒 조건부 약속 · 🌙 22시 이후 합의. 밤 12시 한도 변경은 원장 🌙 기록 → "
        "다음 날 07시 이후 겸이 \"맞아\" 확인 시점부터 ✅ 시행. 22~07시 금지는 규칙 변경(한도·금지·판정 입력·절차·공개 기준)에만 — 루프·운영·버그 수정은 대상 아님.",
    ]
    for c in correct:
        r = G.grade(q1, c)
        assert r["pass"] and not r["req_miss"], (c, r)
    wrong = [
        # W1 10/28 반려 오답
        "✅ 시행 중, 🗳️ 결정 대기, 🔒 잠금 자동 약속, 🌙 22시 이후 합의. 밤 12시 변경은 즉시 시행하고 확인 불필요. 22시 금지는 규칙 변경 포함 모든 답변에 걸린다.",
        # W2 기호 없이 서술
        "시행 중, 결정 대기, 자동 약속, 22시 이후 합의. 즉시 시행. 금지는 전부에 걸린다.",
        # W3 변형(07시 이후 바로·확인 안 받아도 됨·전부)
        "✅ 시행 중, 🗳️ 결정 대기, 🔒 자동 약속, 🌙 22시 이후 합의. 07시 이후 바로 시행, 확인 안 받아도 됨. 22시 금지는 전부에 걸린다.",
        # 넓힌 간격이 '포함·뿐 아니라' 를 정답으로 읽지 않는지
        head + "22시 금지는 규칙 변경뿐 아니라 운영 답변에도 걸린다",
        head + "22시 금지 대상은 규칙 변경 포함 모든 답변",
    ]
    for w in wrong:
        r = G.grade(q1, w)
        assert not r["pass"], (w, r)
    assert G.grade(q1, q1["answer"])["score"] == 1.0


def test_retest_sheet_key_pending_and_private_keys_flag(tmp_path, capsys):
    """평행 재시험(10/28 평가 '답안 커밋 먼저 → 키 공개'): 키 비공개 표식이 있는 문제지는 키 없는 id 허용, 표식이 없으면 오류.
    평가는 공개 전 --keys 로 비공개 키를 더해 채점한다."""
    doc, keys = tmp_path / "doc", tmp_path / "keys"
    doc.mkdir(); keys.mkdir()
    (keys / "zz.json").write_text('{"desk":"zz","items":[{"id":"zz-q1","q":"q","answer":"a 1","keys":[{"n":1}]}]}', encoding="utf-8")
    (doc / "zz.md").write_text("- 퀴즈 [zz-q1]: 문제?\n", encoding="utf-8")
    (doc / "zz_retest.md").write_text(G.KEY_PENDING + "\n- 퀴즈 [zz-q2]: 평행 문제?\n", encoding="utf-8")
    assert G.check_onboarding(doc, keys) == []
    (doc / "zz_retest.md").write_text("- 퀴즈 [zz-q2]: 평행 문제?\n", encoding="utf-8")
    assert any("zz-q2 키 없음" in e for e in G.check_onboarding(doc, keys))
    priv = tmp_path / "priv.json"
    priv.write_text('{"desk":"zz","items":[{"id":"zz-q2","q":"q","answer":"b 2","keys":[{"n":2}]}]}', encoding="utf-8")
    sheet = tmp_path / "ans.md"
    sheet.write_text("퀴즈: zz-q2 답은 2\n", encoding="utf-8")
    assert G.load_key_file(priv)["zz-q2"]["desk"] == "zz"
    G.main(["--sheet", str(sheet), "--keys", str(priv)])
    assert "| zz-q2 | 100% | 통과 |" in capsys.readouterr().out
