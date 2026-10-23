"""보드 결재 필드(approval) — req-pm-47712fe7 · 피어 2026-10-24 U1·U2 (docs/peer_reviews/2026-10-24_uxui_home_board.md).
- board.py: approval 은 '겸이' | null, 'appr-*'·'겸이 결재 필요' 미완료 작업은 approval 필수
- 화면 tab_system sysApprOpen 은 필드만 센다 (글자 규칙 오탐·놓침 재현 사례로 확인)
- 화면 tab_home homePendDuel 은 제출 마감 지난 판을 빼고 센다 (duel.py 마감과 같은 기준)"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import board  # noqa: E402


def _t(**kw):
    base = {"id": "x", "title": "t", "owner": "개발", "priority": "P2", "status": "대기",
            "started": None, "due": None, "files": [], "depends_on": [], "notes": ""}
    return base | kw


def test_validate_approval_values():
    assert board.validate({"tasks": [_t(approval="겸이")]}) == []
    assert board.validate({"tasks": [_t(approval=None)]}) == []
    assert board.validate({"tasks": [_t()]}) == []
    assert any("approval" in e for e in board.validate({"tasks": [_t(approval="PB")]}))


def test_appr_prefix_requires_field():
    assert any("approval 없음" in e for e in board.validate({"tasks": [_t(id="appr-a")]}))
    assert any("approval 없음" in e for e in board.validate({"tasks": [_t(title="겸이 결재 필요: 키 발급")]}))
    assert board.validate({"tasks": [_t(id="appr-a", approval="겸이")]}) == []
    assert board.validate({"tasks": [_t(id="appr-a", status="완료")]}) == []   # 끝난 결재는 필드 없어도 됨


def test_live_board_valid_and_counts_field_only():
    b = json.loads((ROOT / "ops" / "board.json").read_text(encoding="utf-8"))
    assert board.validate(b) == []
    ids = {t["id"] for t in board.approval_open(b["tasks"])}
    assert all(t.get("approval") for t in b["tasks"] if t["id"] in ids)
    for fp in ("uxui-audit", "hf-alphabook"):   # 피어 U1 오탐 사례 — 글자만 있고 결재 대기 아님
        assert fp not in ids


def test_board_md_lists_approvals():
    md = board.render({"tasks": [_t(id="appr-a", approval="겸이"), _t(id="b", status="보류", approval="겸이"), _t(id="c")]})
    assert "**결재 대기 2:**" in md and "`appr-a` (겸이)" in md and "`b` (겸이 · 보류)" in md


def _js(path: str, *names: str) -> str:
    src = (ROOT / "apps-script" / path).read_text(encoding="utf-8")
    out = []
    for n in names:
        m = re.search(rf"^function {n}\(.*?(?=^\S)", src, re.S | re.M)
        assert m, n
        out.append(m.group(0))
    return "\n".join(out)


def _node(code: str):
    if not shutil.which("node"):
        pytest.skip("node 없음")
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_sys_appr_counts_field_not_text():
    T = [_t(id="a", approval="겸이"),
         _t(id="b", status="보류", approval="겸이"),
         _t(id="c", status="완료", approval="겸이"),
         _t(id="uxui-audit", notes="Top 10 → 겸이 결재 → 개발 구현"),   # 글자 규칙이면 오탐
         _t(id="o", owner="사용자")]
    got = _node(_js("tab_system.html", "sysApprOpen") + f"\nconsole.log(JSON.stringify(sysApprOpen({json.dumps(T, ensure_ascii=False)}).map(t=>t.id)))")
    assert got == ["a", "b"]


def test_home_pend_duel_respects_deadline():
    pend = {"나": {"pending": True}}
    items = [{"id": "kr", "date": "2026-10-23", "kind": "entry", "picks": pend},
             {"id": "us", "date": "2026-10-23", "market": "US", "kind": "entry", "picks": pend},
             {"id": "done", "date": "2026-10-23", "kind": "entry", "picks": pend, "result": {"void": "x"}}]
    js = _js("tab_home.html", "duelDeadlineMs", "homePendDuel")
    utc = lambda s: f"Date.parse('{s}')"
    cases = {
        "kr_1530": utc("2026-10-23T06:30:59Z"),   # 15:30:59 KST — 국장 아직 받음(duel.py '>1530' 거부)
        "kr_1531": utc("2026-10-23T06:31:00Z"),   # 15:31 KST — 국장 마감, 미장(22:30 KST, EDT)만
        "us_2229": utc("2026-10-23T13:29:00Z"),
        "us_2230": utc("2026-10-23T13:30:00Z"),   # 09:30 ET(EDT) — 둘 다 마감
        "next_day": utc("2026-10-23T15:10:00Z"),  # 10/24 00:10 KST (피어 재현 시각) → 0
    }
    code = js + "\nconst I=" + json.dumps(items) + ";console.log(JSON.stringify({" + ",".join(f"{k}:homePendDuel(I,{v})" for k, v in cases.items()) + \
        ",dl_us_winter:new Date(duelDeadlineMs({date:'2026-12-01',market:'US'})).toISOString()}))"
    got = _node(code)
    assert got["kr_1530"] == 2 and got["kr_1531"] == 1 and got["us_2229"] == 1
    assert got["us_2230"] == 0 and got["next_day"] == 0
    assert got["dl_us_winter"] == "2026-12-01T14:30:00.000Z"   # EST → 23:30 KST
