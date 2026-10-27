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


# 감사 짝 검수 10/28(req-audit-5c11f8ac, rounds/2026-10-28/audit_compliance_peer_appendix.md) — 역검수 12줄 원문 + 컴플 추가 변형·오답 1개씩.
# 결함: d2 는 질문 속 🌙·08:10 을 베끼면 점수, 건수 키 없음, '13' 부분 문자열 / d3 는 숫자 키가 자리 무관, '없음'이 '문제없음'에 걸림.
D2_OK = [
    "결정·구현 모두 22~07시 창 안이라 원장 🌙 기록은 맞지만 시행은 07시 이후 확인(08:10)부터. 06:30 주문표는 확인 전 시행 = [13] 위반 1건, 능동, 사후 발견. 그 주문표를 옛 값으로 재판정.",
    "밤 결정은 아침에 겸이가 맞다고 해야 효력이 생긴다. 06:30 주문표는 아직 승인 안 된 값으로 돌았으니 거버넌스 조항(밤 규칙 변경 금지) 위반 1건, 사람이 만든 변경이라 active. 그 주문표를 이전 값으로 다시 판정한다.",
    "야간 변경 금지 조항 위반 1건이다. 아침 확인 전에 바뀐 값이 쓰였고(06:30), 수동이 아니라 능동이다. 조치는 원래 값 기준으로 주문표 재평가, 로그는 남기고 종결 시각만.",
    # 컴플 추가: 조항을 시간 창으로만, 건수를 한글로
    "22∼07 규칙 변경 금지 창에서 확인 전 시행 한 건. 바꾼 건 사람이니 능동. 06:30 주문표는 옛 값으로 다시 돌린다.",
]
D2_BAD = [
    "원장에 🌙 줄이 있고 08:10 맞아 확인도 있으니 절차대로라 위반 아님 — 능동 매매도 아니고 [13] 해당 없음. 0건.",
    "🌙 기록은 있으나 07시 이후 확인 전이라 문제. [13] 위반 2건(커밋 1·주문표 1), 수동 위반.",
    "쿨다운 [6] 위반 1건, 능동. 🌙 있으니 08:10 이후로 재판정 필요 없음.",
    # 컴플 추가: 건수만 틀림('13' 이 '3건' 옆에 붙어도 1건으로 읽지 않는지)
    "[13] 위반 3건(결정·커밋·주문표), 능동. 확인 전 시행이니 옛 값으로 재판정.",
]
D3_OK = [
    "엄격 1/7 ≈ 14%, 부분 포함 4/7 ≈ 57%. [6][7]은 담당·시각이 없으니 '없음'. 부분은 주문표를 거칠 때만.",
    "완전 자동 1/7(14.3%), 부분 포함 4/7(57.1%). [6][7]은 누가·언제가 없어 미커버로 분류 — 수동으로 치지 않는다. 부분은 OMS를 거칠 때만 걸린다.",
    "엄격 0.14, 부분 0.57. [6][7]은 '없음'. 부분 조건 = 앱 직접 주문은 통과.",
    # 컴플 추가: 숫자를 이름 앞에, [6]·[7] 가운뎃점 표기
    "1/7(엄격, 14%)과 4/7(부분 포함, 57%)을 같이 보고. [6]·[7]은 담당·시각 미지정이라 없음 — 주문표를 안 거치면 부분도 안 걸린다.",
]
D3_BAD = [
    "엄격 14%, 부분 57%(주문표 경유). [6][7]은 수동.",
    "엄격 1/7≈14%, 수동 포함 7/7=100%, [6][7]은 수동으로 친다. 문제없음.",
    "엄격 4/7 ≈ 57%, 부분 포함 5/7 ≈ 71%. [6][7]은 없음, 주문표 경유 조건.",
    # 컴플 추가: 숫자·자리 맞고 [6][7] 을 [9] 와 같은 수동으로 오분류, 문장 뒤 '문제 없음'
    "엄격 1/7 ≈ 14%, 부분 포함 4/7 ≈ 57%. [6][7]은 [9]처럼 수동으로 분류, 주문표 경유. 문제 없음.",
]


def test_compliance_d2_d3_keys_audit_reverse_check():
    """변형 4/4 통과 · 오답 4/4 불통과(감사 12줄 + 컴플 4줄) — 키 문장 그대로만 통과하던 키 결함 고정."""
    keys = G.load_keys()
    for did, ok, bad in (("compliance-d2", D2_OK, D2_BAD), ("compliance-d3", D3_OK, D3_BAD)):
        it = keys[did]
        for a in ok:
            r = G.grade(it, a)
            assert r["pass"] and not r["req_miss"], (did, a, r)
        for a in bad:
            r = G.grade(it, a)
            assert not r["pass"] and r["req_miss"], (did, a, r)
        assert G.grade(it, it["answer"])["score"] == 1.0, did
    # 질문 문장을 그대로 베껴도(🌙·08:10·13 포함) 통과하지 않는다
    for did in ("compliance-d2", "compliance-d3"):
        assert not G.grade(keys[did], keys[did]["q"])["pass"], did


def test_negation_context_blocks_required_keys_audit_recheck():
    """감사 재검수 10/28(audit_compliance_peer_recheck.md, req-audit-5c11f8ac) — 부정문 오답 3줄 불통과, 표기 변형 맞는 답 통과."""
    keys = G.load_keys()
    d2, d3 = keys["compliance-d2"], keys["compliance-d3"]
    for it, a in ((d2, "[13] 위반 1건, 능동이 아니라 수동(값이 자동 반영). 확인 전 시행이니 옛 값으로 재판정."),
                  (d2, "위반 1건도 없다. 🌙 기록이 있어 [13] 해당 없음, 능동 변경도 아님. 재판정 불필요."),
                  (d3, "엄격 1/7≈14%, 부분 4/7≈57%. [6][7]은 '없음'이 아니라 수동(담당 PB).")):
        r = G.grade(it, a)
        assert not r["pass"] and r["req_miss"], (a, r)
    for it, a in ((d2, "밤 22시~07시 창 규칙(13조) 위반 한 건, 능동. 확인 전 시행이라 06:30 주문표는 이전 값으로 다시 본다."),
                  (d2, "위반이다. [13] 1건, 능동 위반 — 08:10 확인 전 06:30 주문표가 새 값으로 통과했으니 옛 값으로 재판정."),
                  (d3, "엄격 기준 1/7(약 14%), 부분 포함 시 4/7(약 57%). [6]과 [7]은 미커버(없음), 부분은 주문표 경유 때만."),
                  (d3, "완전 자동만 치면 14%, 부분까지 57%. [6][7]: 담당·시각 없음. 주문표 안 거치면 부분도 안 걸림.")):
        r = G.grade(it, a)
        assert r["pass"] and not r["req_miss"], (a, r)


def test_negation_context_negative_keys_and_options():
    """부정 개념 키(negative / 키에 '없음' 등)는 반대로 — 부재 표지는 무시, 바로 붙은 '…이 아니라' 만 무효. 비필수·negcheck:false 는 그대로."""
    pos = {"id": "x-d1", "keys": [{"t": ["능동"], "req": True}, {"t": ["옛 값"]}]}
    assert G.grade(pos, "능동 위반, 옛 값으로")["pass"]
    assert not G.grade(pos, "능동이 아니라 수동, 옛 값으로")["pass"]
    assert not G.grade(pos, "능동 변경도 아님, 옛 값으로")["pass"]
    assert not G.grade(pos, "능동하지 않음, 옛 값으로")["pass"]
    assert not G.grade(pos, "not 능동, 옛 값으로")["pass"]
    assert G.grade(pos, "수동이 아니라 능동, 옛 값으로")["pass"]           # 'A가 아니라 B' 의 B 는 긍정
    assert G.grade(pos, "능동, 다만 기록은 없다. 옛 값으로")["pass"]       # 절이 바뀌면 부정이 키에 안 걸림
    assert G.grade(pos, "능동 맞음, 옛 값이 아니라 새 값")["score"] == 1.0   # 비필수 키는 부정 판정 안 함
    off = {"id": "x-d2", "keys": [{"t": ["능동"], "req": True, "negcheck": False}]}
    assert G.grade(off, "능동이 아니라 수동")["pass"]
    neg = {"id": "x-d3", "keys": [{"t": ["없음"], "req": True}]}            # 키 문자열에 부정어 → 자동 부정 개념
    assert G.grade(neg, "담당 없음")["pass"]
    assert G.grade(neg, "미커버(없음)이고 담당도 없다")["pass"]
    assert not G.grade(neg, "'없음'이 아니라 수동")["pass"]
    ban = {"id": "x-d4", "keys": [{"t": ["완화 금지"], "req": True, "negative": True}]}   # 명시 표시
    assert G.grade(ban, "위반 중 완화 금지라 받을 수 없다")["pass"]
    assert not G.grade(ban, "완화 금지가 아니라 허용")["pass"]
    assert not G.grade({**ban, "keys": [{"t": ["완화 금지"], "req": True}]}, "위반 중 완화 금지라 받을 수 없다")["pass"]


def test_all_model_answers_pass_with_negation_check():
    """회귀: content/drills/*.json + content/onboarding/*.json 의 모범답 전부가 부정 문맥 판정 뒤에도 자기 키를 다 맞힌다."""
    fails = []
    for d in (G.KEYS_DIR, G.ONB_KEYS_DIR):
        for qid, it in G.load_keys(d).items():
            r = G.grade(it, it["answer"])
            if r["score"] < 1.0 or not r["pass"]:
                fails.append((qid, r["miss"]))
    assert fails == []
    assert len(G.load_keys()) + len(G.load_onboarding()) >= 60
