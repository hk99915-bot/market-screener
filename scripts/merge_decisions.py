"""decisions.json 병합 — pick·pb_call·live 저장 단계 공용 (감사 10/21 #1: live 가 통째로 덮어써 직전 pick 이 사라질 수 있었음).

워크플로가 원격 최신(reset --hard origin/main) 위에서 실행:
  python scripts/merge_decisions.py {pick|pb|live} /tmp/dec.json   → reports/decisions.json 에 병합
- pick : 겸이 슬롯(나·나🔥) 병합, ticket 은 통째로 교체, exit 은 PB 판정 전이면 picks 교체 (기존 pick.yml 규칙 그대로)
- pb   : pb_view 있는 항목의 PB·PB🔥·규칙 슬롯과 pb_view 만 반영 (기존 pb_call.yml 규칙 그대로)
- live : 원격에 이미 있는 슬롯·필드는 유지하고 없는 것만 추가 (duel 이 새로 쓴 '규칙' 판정만 얹힘)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DEC = Path(__file__).resolve().parents[1] / "reports" / "decisions.json"


def merge(cur: dict, new: dict, mode: str) -> dict:
    if mode not in ("pick", "pb", "live"):
        raise SystemExit(f"알 수 없는 mode: {mode}")
    ids = {x["id"]: x for x in cur["items"]}
    for v in new["items"]:
        if mode == "pb" and not v.get("pb_view"):
            continue
        x = ids.get(v["id"])
        if x is None:
            cur["items"].append(v)
            ids[v["id"]] = v
        elif mode == "pick":
            if v.get("kind") == "ticket":
                x.clear(); x.update(v)
            elif v.get("kind") != "exit" or "PB" in x["picks"] and x["picks"]["PB"].get("by"):
                x["picks"] = {**x["picks"], **{s: v["picks"][s] for s in ("나", "나🔥") if s in v["picks"]}}
            else:
                x["picks"] = v["picks"]
        elif mode == "pb":
            for k in ("PB", "PB🔥", "규칙"):
                if k in v["picks"]:
                    x["picks"][k] = v["picks"][k]
            x["pb_view"] = v["pb_view"]
        else:   # live
            for k, p in v.get("picks", {}).items():
                if k not in x.setdefault("picks", {}) or x["picks"][k].get("pending") and not p.get("pending"):
                    x["picks"][k] = p
            if "규칙:" in v.get("note", "") and "규칙:" not in x.get("note", ""):
                x["note"] = (x.get("note", "") + " · " + v["note"][v["note"].index("규칙:"):]).strip(" ·")
            for k, val in v.items():
                x.setdefault(k, val)
    return cur


if __name__ == "__main__":
    mode, src = sys.argv[1], sys.argv[2]
    new = json.loads(Path(src).read_text(encoding="utf-8"))
    cur = json.loads(DEC.read_text(encoding="utf-8")) if DEC.exists() else {"items": []}
    DEC.write_text(json.dumps(merge(cur, new, mode), ensure_ascii=False, indent=1), encoding="utf-8")
