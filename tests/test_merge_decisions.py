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


def test_pick_exit_keeps_pb_slot_when_pb_judged():
    """포니테일 검수 10/21 #6: exit 항목에 PB 판정(by)이 이미 있으면 pick 은 나·나🔥만 얹고 PB 슬롯은 유지. by 없으면 picks 통째 교체."""
    pb = {"cash": True, "by": "pb_call"}
    remote = {"items": [{"id": "x-exit", "kind": "exit", "picks": {"나": {"pending": True}, "PB": pb}},
                        {"id": "y-exit", "kind": "exit", "picks": {"나": {"pending": True}, "PB": {"pending": True}}}]}
    new = {"items": [{"id": "x-exit", "kind": "exit", "picks": {"나": {"cash": True}, "PB": {"pending": True}}},
                     {"id": "y-exit", "kind": "exit", "picks": {"나": {"cash": False}, "PB": {"pending": True}}}]}
    x, y = md.merge(remote, new, "pick")["items"]
    assert x["picks"] == {"나": {"cash": True}, "PB": pb}                                # PB 판정 보존
    assert y["picks"] == {"나": {"cash": False}, "PB": {"pending": True}}                 # PB 판정 전 → 교체


def test_pick_entry_merges_only_my_slots():
    """pick 모드: entry 는 나·나🔥 슬롯만 병합(원격 규칙·PB 유지), 원격에 없는 항목은 추가."""
    remote = {"items": [{"id": "e1", "kind": "entry", "picks": {"나": {"pending": True}, "PB": {"code": "T00001"}, "규칙": {"code": "T00002"}}}]}
    new = {"items": [{"id": "e1", "kind": "entry", "picks": {"나": {"code": "T00003"}, "나🔥": {"code": "T00004"}, "PB": {"pending": True}}},
                     {"id": "e2", "kind": "entry", "picks": {"나": {"code": "T00005"}}}]}
    out = md.merge(remote, new, "pick")["items"]
    assert out[0]["picks"] == {"나": {"code": "T00003"}, "나🔥": {"code": "T00004"}, "PB": {"code": "T00001"}, "규칙": {"code": "T00002"}}
    assert [x["id"] for x in out] == ["e1", "e2"]
