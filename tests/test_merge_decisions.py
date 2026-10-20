"""감사 10/21 #1: live 저장 직전에 원격에 새 pick 이 있으면 보존."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("merge_decisions", Path(__file__).resolve().parents[1] / "scripts" / "merge_decisions.py")
md = importlib.util.module_from_spec(spec); spec.loader.exec_module(md)


def test_live_keeps_remote_pick():
    remote = {"items": [{"id": "2026-10-21-entry", "kind": "entry", "note": "",
                         "picks": {"나": {"code": "069500", "amt": 1000000}, "PB": {"pending": True}}}]}
    live = {"items": [{"id": "2026-10-21-entry", "kind": "entry", "note": "규칙: 추세 유지",
                       "picks": {"나": {"pending": True}, "PB": {"pending": True}, "규칙": {"code": "122630"}}, "basis": {"at": "x"}}]}
    it = md.merge(remote, live, "live")["items"][0]
    assert it["picks"]["나"] == {"code": "069500", "amt": 1000000}   # 원격 pick 보존
    assert it["picks"]["규칙"] == {"code": "122630"} and it["basis"] == {"at": "x"} and "규칙:" in it["note"]
