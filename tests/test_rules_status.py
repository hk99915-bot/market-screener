"""결재 ✅ → rules.txt 반영 현황 (감사 P0-2) — 가짜 원장·가짜 규정으로만 검사(비공개 파일 불필요)."""
from datetime import date

from scripts import rules_status as RS

TODAY = date(2026, 10, 26)

LEDGER = """# 합의 원장
## 7. 기록·운영
- ✅ 다른 절 줄 결재 #4 [13] 도장 (10/17)
### 7-2. 다른 절
- #9 [5] 여기 토큰은 7-3 밖이라 무시
### 7-3. 일요일 결재 일괄 도장 (✅ 10/17 토 14:09)
- 결재 이슈 #1·#2·#3·#4·#8·#9·#10·#14 → 도장. 통합(#1→#4, #8 쿨다운→#14·나머지 11/15)
- #2 백스톱 예외 [5] · #3 밴드 레짐 연동 [3],[11]
- #4 [13]: 정의 먼저
- #9 소리 알림 (규정 무관)
- #10 보존 규칙
- #14 쿨다운 [12] (10/25 발효)
- 🗳️→✅ 규칙 [7] 위반 = A
### 7-4. 다음 절
- #10 [6] 여기도 무시
"""

RULES = """# 규정 v0
[3. 사이징]
- 테마 한도 (결재 #3 반영 10/20)
[5. 보유·청산]
- 백스톱
[11. 정량 한도]
- 한도
[12. 하락장 특칙]
- 특칙
"""


def rows():
    return {r.no: r for r in RS.build_rows(LEDGER, RULES, TODAY) if r.line is None}


def test_parse_approvals_and_mapping():
    r = rows()
    assert sorted(r) == [1, 2, 3, 4, 8, 9, 10, 14]
    assert r[2].clauses == [5] and r[3].clauses == [3, 11]
    assert r[4].clauses == [13]                 # 7-3 줄 + 원장 다른 ✅ 줄의 '결재 #4 [13]'
    assert r[10].clauses == []                  # 7-4 의 [6] 은 무시
    assert r[9].clauses == []                   # 7-2 의 [5] 는 무시
    assert 7 not in r                           # '#' 없는 '규칙 [7]' 줄은 결재 아님


def test_states():
    r = rows()
    assert r[1].state == "통합→#4" and r[8].state == "통합→#14"
    assert r[2].state == "미반영"
    assert r[3].state == "일부 반영" and r[3].tagged == [3]
    assert r[4].state == "조항 없음"
    assert r[9].state == "규정 무관"
    assert r[10].state == "미지정"
    assert r[14].effective == date(2026, 10, 25)
    full = RULES.replace("- 한도", "- 한도 (결재 #3 반영 10/20)")
    assert {x.no: x for x in RS.build_rows(LEDGER, full, TODAY)}[3].state == "반영"


def test_findings_severity_and_grace():
    fs = RS.findings(LEDGER, RULES, TODAY)
    by = {w.split("결재 ")[-1]: (s, m) for s, w, m in fs if "결재 #" in w}
    assert by["#2"][0] == "치명"                # [5] = 예약 PB 가 읽는 조항, 10/17+7 경과
    assert by["#3"][0] == "중"                  # 일부 반영, [3]·[11]
    assert by["#4"][0] == "중"                  # 조항 없음
    assert by["#10"][0] == "경"                 # 미지정
    assert "#14" not in by                      # [12] 지만 10/25 발효 → 7일 안 지남
    late = RS.findings(LEDGER, RULES, date(2026, 11, 2))
    assert any(s == "치명" and w.endswith("#14") for s, w, _ in late)
    early = RS.findings(LEDGER, RULES, date(2026, 10, 20))
    assert not any(s in ("치명", "중") for s, _, _ in early)
    assert any(w == "rules.txt" and "블록 없음" in m for _, w, m in fs)


def test_write_block_keeps_body_and_is_idempotent():
    block = RS.render_block(RS.build_rows(LEDGER, RULES, TODAY), "2026-10-26 09:00")
    once = RS.apply_block(RULES, block)
    assert once.startswith(RS.BLOCK_START) and once.endswith(RULES)
    assert RS.strip_block(once) == RULES
    twice = RS.apply_block(once, block)
    assert twice == once                        # 다시 써도 블록 하나
    # 블록 안의 문구가 꼬리표·조항으로 오인되지 않음
    assert RS.parse_rules(once) == RS.parse_rules(RULES)
    # 최신 블록이면 낡음 경보 없음(스탬프만 달라도 같음)
    assert not any(w == "rules.txt" for _, w, _ in RS.findings(LEDGER, once, TODAY))
    stale = RS.apply_block(RULES, RS.render_block([], "x"))
    assert any(w == "rules.txt" and "낡음" in m for _, w, m in RS.findings(LEDGER, stale, TODAY))


def test_block_has_ids_only():
    block = RS.render_block(RS.build_rows(LEDGER, RULES, TODAY), "2026-10-26")
    body = [ln for ln in block.splitlines()[3:-1]]
    for ln in body:                             # '# #n|Ln  [k]  상태  m/d  D+n  키' 만 — 원장 문구 유출 없음
        assert ln.split()[1][0] in "#L"
        assert "백스톱" not in ln and "밴드" not in ln and "쿨다운" not in ln


def test_no_section_means_empty(tmp_path):
    assert RS.build_rows("# 원장\n- ✅ 결재 #2 [5]\n", RULES, TODAY) == []
    unapproved = LEDGER.replace("(✅ 10/17", "(🗳️ 10/17")
    assert [r for r in RS.build_rows(unapproved, RULES, TODAY) if r.line is None] == []


def test_cli_write_and_check(tmp_path):
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "agreements.md").write_text(LEDGER, encoding="utf-8")
    (tmp_path / "rules.txt").write_text(RULES, encoding="utf-8")
    assert RS.main(["--pb", str(tmp_path), "--write", "--today", "2026-10-26"]) == 0
    txt = (tmp_path / "rules.txt").read_text(encoding="utf-8")
    assert txt.startswith(RS.BLOCK_START) and RS.strip_block(txt) == RULES
    assert RS.main(["--pb", str(tmp_path), "--check", "--today", "2026-10-26"]) == 1   # #2 치명
    assert RS.main(["--pb", str(tmp_path / "없음"), "--check"]) == 2


# ── 감사 R01 (11/11): 원장 전체 ✅ 규칙·한도 결재 줄 추적 + 11/5 꼬리표 형식 + 경과일 ─────────────
# 가짜 원장 — 행 번호가 테스트의 기준이므로 줄 순서를 바꾸지 말 것.
LEDGER2 = """# 합의 원장 (가짜)
## 1. 규칙
- ✅ (10/20 09:00 오너 결정) 규칙 [3] 테마 비중 상한 문구 변경
- ✅ (10/21 10:00 오너) 대시보드 색상 변경 — 규칙 변경 아님 [3]
- ✅ (10/22 오너) 위원회 개설 (규정 무관) 규칙 [9]
- 🗳️ (10/23) 규칙 [6] 손실 한도 개정 제안 — 결재 대기
- ☑️ 규칙 [4] 진입 필터 → 다음 회의
- ✅ 사전등록 (10/24) 규칙 [5] 개정안 — 도장 전 미발효
- ✅ 집행(10/24) 규칙 [5] 백스톱대로 매도 완료
> ✅ 인용 줄 규칙 [2] 은 무시
- ✅ (10/25 오너) 텔레그램 버튼 문구 정리, 결재 처리 완료
## 11월
- ✅ (11/1 오너) 규칙 [7] 회전율 한도 정의 개정 결재
- ✅ (11/6 10:00 오너 「ㅇㅇ」 = 결재) A·B 일괄 결재 — [6] 종료 정의·분모 명시, rules.txt 문언은 컴플 대조 후 반영
- ✅ (11/6 15:00 오너 결재) 후속안 ② [5] 반등일형 백스톱 정리 시각 고정
- ✅ (11/6 16:00 오너 결재) 구속 스트레스 한도 −15% 재계산 구간 고정
- ✅ (11/7 오너) 회의록 양식 통일, 한도 감시 화면 정리
"""

RULES2 = """# 규정 (가짜)
- 머리말 (결재: agreements 3행, 10/21 반영)
[3. 사이징]
- 테마 비중 상한 (결재: agreements 3행, 10/21 반영)
[5. 보유·청산]
- 백스톱
[6. 손실 한도]
- 종료 정의
[7. 회전율]
- 회전율 (결재: agreements 13행, 11/5 반영 — 설명 꼬리)
"""


def _lines(ledger=LEDGER2, rules=RULES2, today=date(2026, 11, 11)):
    return {r.line: r for r in RS.build_rows(ledger, rules, today) if r.line is not None}


def test_row_tag_format_parsed():
    """11/5 형식 '(결재: agreements N·M~K행, m/d 반영 …)' — 목록·범위·꼬리 설명 모두."""
    t = RS.parse_row_tags("[3. x]\n- a (결재: agreements 22·26·134행, 11/5 반영)\n"
                          "[5. y]\n- b (결재: agreements 24·102~103·134행, 11/5 반영 — 꼬리)\n")
    assert t == {22: [3], 26: [3], 134: [3, 5], 24: [5], 102: [5], 103: [5]}
    assert RS.parse_row_tags("- 머리말 (결재: agreements 7행, 11/5 반영)\n") == {7: [-1]}
    # 옛 형식은 번호 결재 쪽 parse_rules 가 그대로 본다
    assert RS.parse_rules("[3. x]\n- a (결재 #3 반영 10/20)\n") == ({3}, {3: [3]})


def test_line_candidates_conservative():
    """판별 기준 ①~④ — 오탐 방지: 비변경·무관·대기·사전등록·집행·인용·규칙 표지 없는 결재는 빠진다."""
    got = _lines()
    assert sorted(got) == [3, 13, 14, 15, 16]
    # 4: '규칙 변경 아님' · 5: '(규정 무관)' · 6: 🗳️ · 7: ☑️ · 8: 사전등록 · 9: 집행 · 10: 인용 ·
    # 11: '결재'만 있고 규칙·한도 표지 없음 · 12: 헤더 · 17: 한도 낱말은 있으나 % 수치·조항 없음
    for n in (4, 5, 6, 7, 8, 9, 10, 11, 12, 17):
        assert n not in got


def test_both_tag_formats_mark_reflected():
    got = _lines()
    assert got[3].state == "반영" and got[3].tagged == [3]     # 머리말 꼬리표(-1)는 조항 목록에서 빠짐
    assert got[13].state == "반영" and got[13].tagged == [7]   # 꼬리 설명 붙은 11/5 형식
    # 번호 결재: 옛 형식 '(결재 #2 반영 m/d)' 와 11/5 형식(§7-3 정의 행 번호) 둘 다 반영으로 센다
    ledger = LEDGER.splitlines()
    n2 = next(i for i, ln in enumerate(ledger, 1) if ln.startswith("- #2 "))
    old = RULES.replace("- 백스톱", "- 백스톱 (결재 #2 반영 10/20)")
    new = RULES.replace("- 백스톱", f"- 백스톱 (결재: agreements {n2}행, 11/5 반영)")
    for rules in (old, new):
        r = {x.no: x for x in RS.build_rows(LEDGER, rules, TODAY) if x.line is None}
        assert r[2].state == "반영", rules
    # 같은 행(#2 [5] · #3 [3],[11])을 가리켜도 다른 조항에 붙은 꼬리표는 #3 을 반영으로 만들지 않는다
    r = {x.no: x for x in RS.build_rows(LEDGER, new, TODAY) if x.line is None}
    assert r[3].state == "일부 반영" and r[3].tagged == [3]


def test_unreflected_nov6_approvals_and_elapsed():
    """11/6 결재(가짜) — 꼬리표 없음 → 미반영, 경과일 = 결재일 대비 날짜 수, 7일 지나면 경보."""
    got = _lines()
    for n in (14, 15, 16):
        assert got[n].state == "미반영" and got[n].approved == date(2026, 11, 6)
        assert got[n].elapsed == 5
    assert got[14].clauses == [6] and got[15].clauses == [5]
    early = RS.findings(LEDGER2, RULES2, date(2026, 11, 11))
    assert not any(w.startswith(RS.LEDGER_REL + ":") for _, w, _ in early)     # 7일 유예 안
    late = {w: (s, m) for s, w, m in RS.findings(LEDGER2, RULES2, date(2026, 11, 14))}
    assert late[f"{RS.LEDGER_REL}:14"][0] == "중"
    assert late[f"{RS.LEDGER_REL}:15"][0] == "치명"            # [5] = 예약 PB 가 읽는 조항
    assert late[f"{RS.LEDGER_REL}:16"][0] == "중"              # '결재 + 한도 −15%'
    assert "8일" in late[f"{RS.LEDGER_REL}:14"][1]
    assert f"{RS.LEDGER_REL}:3" not in late and f"{RS.LEDGER_REL}:13" not in late
    # 반영 꼬리표를 달면 경보가 사라진다
    fixed = RULES2.replace("- 종료 정의", "- 종료 정의 (결재: agreements 14·15~16행, 11/8 반영)")
    assert not any(w.startswith(RS.LEDGER_REL + ":") for _, w, _ in RS.findings(LEDGER2, fixed, date(2026, 11, 14)))


def test_numbered_lines_not_double_tracked_and_section_date():
    """§7-3 번호 결재 정의 행·'결재 #n [k]' 행은 원장 행으로 다시 세지 않고, 절 안 줄의 결재일은 절 헤더 날짜."""
    got = {r.line: r for r in RS.build_rows(LEDGER, RULES, TODAY) if r.line is not None}
    ledger = LEDGER.splitlines()
    adj = next(i for i, ln in enumerate(ledger, 1) if "결재 #4 [13]" in ln)
    a7 = next(i for i, ln in enumerate(ledger, 1) if "규칙 [7]" in ln)
    assert adj not in got
    assert list(got) == [a7] and got[a7].approved == date(2026, 10, 17)


def test_block_elapsed_does_not_make_block_stale():
    rows_ = RS.build_rows(LEDGER2, RULES2, date(2026, 11, 11))
    block = RS.render_block(rows_, "x")
    assert "# L14" in block and "D+5" in block
    once = RS.apply_block(RULES2, block)
    assert RS.parse_row_tags(once) == RS.parse_row_tags(RULES2)      # 블록 안 안내 문구는 꼬리표가 아님
    next_day = RS.findings(LEDGER2, once, date(2026, 11, 12))
    assert not any(w == "rules.txt" for _, w, _ in next_day)          # 하루 지나 D+n 만 바뀌면 낡음 아님
