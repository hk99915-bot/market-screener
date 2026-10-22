import copy
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("board", Path(__file__).resolve().parents[1] / "scripts" / "board.py")
board = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(board)


def _b():
    return {"tasks": [{"id": "a", "title": "t", "owner": "dev", "priority": "P1", "status": "대기",
                       "started": None, "due": None, "files": [], "depends_on": [], "notes": ""}]}


def test_add_fills_optional_fields():
    b = _b()
    assert board.add_task(b, {"id": "b", "title": "x", "owner": "dev", "priority": "P2", "status": "대기"}) == []
    assert [t["id"] for t in b["tasks"]] == ["a", "b"]
    assert b["tasks"][1]["files"] == [] and board.validate(b) == []


def test_invalid_add_leaves_board_untouched():
    for bad in ({"id": "a", "title": "x", "owner": "d", "priority": "P1", "status": "대기"},   # 중복 id
                {"id": "c", "title": "x", "owner": "d", "priority": "P9", "status": "대기"},   # 우선순위
                {"id": "c", "title": "x", "owner": "d", "priority": "P1", "status": "??"},     # 상태
                {"id": "c", "title": "x", "owner": "d", "priority": "P1", "status": "대기", "depends_on": ["zz"]},
                {"id": "c", "title": "x"}):                                                     # 필수 누락
        b = _b(); before = copy.deepcopy(b)
        assert board.add_task(b, bad)
        assert b == before
