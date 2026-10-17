"""scripts/round_collect.py — 라운드 수집·스코어보드 라운드 표·요청 장부·P1 승격 (파일은 tmp_path 에서만)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import round_collect as rc  # noqa: E402
import board as board_mod  # noqa: E402

OPS = """# 운영 라운드 1
## 1. 읽기
LOOP.md·README·보드.
## 2. 배우기
- [규정] GitHub Actions schedule 문서: 정각 예약은 지연이 잦다.
## 3. 고치기
scripts/round_collect.py 신설 + 테스트.
## 4. 피어
개발: board.py 에 --add 가 있으면 승격 경로가 단순해진다.
## 5. 복기
틀림 → 왜 → 다음부터.
VOC: dev.md 가 없어 피어 읽기를 보드로 대신함
요청→개발: board.py 에 --add 서브커맨드
"""
DEV_EMPTY = """# 개발 라운드 1
**배움** — [교과서] 테스트 피라미드.
**고침** — tests/ 정리.
**피어** —
**복기** —
"""


def _round(tmp, rnd, files):
    d = tmp / "rounds" / rnd
    d.mkdir(parents=True, exist_ok=True)
    for k, v in files.items():
        (d / f"{k}.md").write_text(v, encoding="utf-8")
    return d


def test_parse_items_requests_responses():
    p = rc.parse_round_file(OPS, "ops")
    assert p["items"] == {"배움": True, "고침": True, "피어": True, "복기": True}
    assert p["requests"] == [("dev", "board.py 에 --add 서브커맨드")]
    assert p["voc"] == ["dev.md 가 없어 피어 읽기를 보드로 대신함"]
    q = rc.parse_round_file(DEV_EMPTY, "dev")
    assert q["items"]["배움"] and q["items"]["고침"] and not q["items"]["피어"] and not q["items"]["복기"]
    assert q["requests"] == []
    r = rc.parse_round_file("처리→ops: --add 넣음\n요청→quant: 재현 요청", "dev")
    assert r["responses"] == [("ops", "--add 넣음")] and r["requests"] == [("quant", "재현 요청")]


def test_scoreboard_append_idempotent_and_keeps_following_sections():
    base = "# 데스크 스코어보드\n\n| 채점일 | 데스크 | n |\n|---|---|---|\n"
    parsed = [rc.parse_round_file(OPS, "ops"), rc.parse_round_file(DEV_EMPTY, "dev")]
    t1, n1 = rc.append_scoreboard(base, "2026-10-17", parsed)
    assert n1 == 2 and rc.ROUND_HEAD in t1
    assert "| 2026-10-17 | ops | ✓ | ✓ | ✓ | ✓ | 1 | ✓ | — |" in t1
    assert "| 2026-10-17 | dev | ✓ | ✓ | — | — | 0 | — | — |" in t1
    assert "### VOC 2026-10-17" in t1 and "- ops: dev.md 가 없어 피어 읽기를 보드로 대신함" in t1
    t2, n2 = rc.append_scoreboard(t1, "2026-10-17", parsed)
    assert n2 == 0 and t2 == t1                                   # 같은 라운드 다시 돌려도 중복 없음
    t3, n3 = rc.append_scoreboard(t1 + "\n## 다른 절\n내용\n", "2026-10-18", parsed[:1])
    assert n3 == 1
    lines = t3.splitlines()
    assert lines.index("| 2026-10-18 | ops | ✓ | ✓ | ✓ | ✓ | 1 | ✓ | — |") < lines.index("### VOC 2026-10-17") < lines.index("### VOC 2026-10-18") < lines.index("## 다른 절")   # 표 안에 끼워지고 VOC 절은 표 뒤


def test_audit_column_both_formats():
    parsed = [rc.parse_round_file(OPS, "ops"), rc.parse_round_file(DEV_EMPTY, "dev")]
    a1 = {"by_desk": {"운영": {"치명": 0, "중": 1, "경": 2}}}
    a2 = {"findings": [{"desk": "ops", "severity": "critical"}, {"desk": "ops", "severity": "경"}, {"desk": "x", "severity": "?"}]}
    assert rc.audit_counts(a1) == {"ops": {"치명": 0, "중": 1, "경": 2}}
    assert rc.audit_counts(a2) == {"ops": {"치명": 1, "중": 0, "경": 1}}
    rows = rc.round_rows("2026-10-17", parsed, a1)
    assert rows[0].endswith("| 0/1/2 |") and rows[1].endswith("| — |")
    assert rc.round_rows("2026-10-17", parsed, None)[0].endswith("| — |")


def test_ledger_two_rounds_unprocessed_promotes_p1(tmp_path):
    board = {"tasks": []}
    r1 = [rc.parse_round_file(OPS, "ops"), rc.parse_round_file(DEV_EMPTY, "dev")]
    L = rc.update_ledger({}, "2026-10-17", r1)
    assert len(L["requests"]) == 1 and L["requests"][0]["pending_rounds"] == 1
    assert rc.promotions(L, "2026-10-17", board) == []                      # 1라운드는 승격 안 함
    L = rc.update_ledger(L, "2026-10-17", r1)                                # 같은 라운드 재실행 → 안 늘어남
    assert L["requests"][0]["pending_rounds"] == 1
    L2 = rc.update_ledger(L, "2026-10-20", r1)                               # 개발이 또 답 없음
    assert L2["requests"][0]["pending_rounds"] == 2 and L2["requests"][0]["seen"] == ["2026-10-17", "2026-10-20"]
    tasks = rc.promotions(L2, "2026-10-20", board)
    assert len(tasks) == 1
    t = tasks[0]
    assert t["priority"] == "P1" and t["status"] == "대기" and t["owner"] == "개발" and t["due"] == "2026-10-27"
    assert t["id"].startswith("req-dev-")
    L3, B3 = rc.apply_promotions(L2, board, tasks, "2026-10-20")
    assert B3["tasks"][0]["id"] == t["id"] and L3["requests"][0]["status"] == "promoted"
    assert board_mod.validate(B3) == []                                      # 보드 검증기 통과 필드
    assert rc.promotions(L3, "2026-10-20", B3) == []                         # 두 번 승격 안 함


def test_ledger_response_closes_request():
    r1 = [rc.parse_round_file(OPS, "ops")]
    L = rc.update_ledger({}, "2026-10-17", r1)
    r2 = [rc.parse_round_file(OPS, "ops"), rc.parse_round_file("## 고치기\n처리→운영: --add 추가함\n", "dev")]
    L2 = rc.update_ledger(L, "2026-10-20", r2)
    assert L2["requests"][0]["status"] == "done" and L2["requests"][0]["done"] == "2026-10-20"
    assert rc.promotions(L2, "2026-10-20", {"tasks": []}) == []


def test_run_dry_run_writes_nothing_and_apply_writes(tmp_path):
    _round(tmp_path, "2026-10-17", {"ops": OPS, "dev": DEV_EMPTY, "_note": "무시"})
    sb = tmp_path / "_scoreboard.md"; sb.write_text("# 스코어보드\n", encoding="utf-8")
    bd = tmp_path / "board.json"; bd.write_text('{"tasks": []}', encoding="utf-8")
    ledger = tmp_path / "rounds" / "_requests.json"
    msgs = []
    rc.run("2026-10-17", tmp_path / "rounds", sb, bd, ledger, apply=False, out=msgs.append)
    assert sb.read_text(encoding="utf-8") == "# 스코어보드\n" and not ledger.exists()
    assert any("DRY-RUN" in m for m in msgs) and any("데스크 2" in m for m in msgs)
    rc.run("2026-10-17", tmp_path / "rounds", sb, bd, ledger, apply=True, out=msgs.append)
    assert "| 2026-10-17 | ops |" in sb.read_text(encoding="utf-8")
    assert json.loads(ledger.read_text(encoding="utf-8"))["requests"][0]["to"] == "dev"
    assert json.loads(bd.read_text(encoding="utf-8")) == {"tasks": []}      # 1라운드엔 보드 안 건드림
    _round(tmp_path, "2026-10-20", {"ops": OPS, "dev": DEV_EMPTY})
    (tmp_path / "audit").mkdir(); (tmp_path / "audit" / "2026-10-20.json").write_text('{"findings": [{"desk": "ops", "severity": "중"}]}', encoding="utf-8")
    rc.run("2026-10-20", tmp_path / "rounds", sb, bd, ledger, apply=True, out=msgs.append, audit_dir=tmp_path / "audit")
    assert "| 2026-10-20 | ops | ✓ | ✓ | ✓ | ✓ | 1 | ✓ | 0/1/0 |" in sb.read_text(encoding="utf-8")
    B = json.loads(bd.read_text(encoding="utf-8"))
    assert len(B["tasks"]) == 1 and B["tasks"][0]["priority"] == "P1" and B["updated"] == "2026-10-20"
    assert rc.run("2026-10-21", tmp_path / "rounds", sb, bd, ledger, apply=False, out=msgs.append) == 1   # 폴더 없음
