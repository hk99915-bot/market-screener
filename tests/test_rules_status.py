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
    return {r.no: r for r in RS.build_rows(LEDGER, RULES, TODAY)}


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
    for ln in body:                             # '# #n  [k]  상태  7-3' 만 — 원장 문구 유출 없음
        assert ln.split()[1].startswith("#")
        assert "백스톱" not in ln and "밴드" not in ln and "쿨다운" not in ln


def test_no_section_means_empty(tmp_path):
    assert RS.build_rows("# 원장\n- ✅ 결재 #2 [5]\n", RULES, TODAY) == []
    unapproved = LEDGER.replace("(✅ 10/17", "(🗳️ 10/17")
    assert RS.build_rows(unapproved, RULES, TODAY) == []


def test_cli_write_and_check(tmp_path):
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "agreements.md").write_text(LEDGER, encoding="utf-8")
    (tmp_path / "rules.txt").write_text(RULES, encoding="utf-8")
    assert RS.main(["--pb", str(tmp_path), "--write", "--today", "2026-10-26"]) == 0
    txt = (tmp_path / "rules.txt").read_text(encoding="utf-8")
    assert txt.startswith(RS.BLOCK_START) and RS.strip_block(txt) == RULES
    assert RS.main(["--pb", str(tmp_path), "--check", "--today", "2026-10-26"]) == 1   # #2 치명
    assert RS.main(["--pb", str(tmp_path / "없음"), "--check"]) == 2
