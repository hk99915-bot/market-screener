"""신호등 보정 검증 — 과거 회의판에 새 🟡 규칙을 재적용해 전·후 분포를 출력 (10/20 dev: light-calibration).

입력: reports/archive/committee*/*.json + git 이력의 reports/committee.json·committee_us.json (같은 asof 는 1판).
전 = 그 판에 게시된 light. 후 = 같은 판의 저장된 clock·내재 범위로 새 규칙(us_committee.light_yellow) 재계산.
🔴 조건(판정·결론·레짐 전환·신규 실행 후보)은 바뀌지 않았으므로 게시본이 🔴 이면 그대로 🔴.
고중요 이벤트 판정: 저장된 clock 이름 → calendar.json 으로 type·ticker 복원, 관심 종목 = 그 판의 ideas_top(+후보).
출력은 콘솔 표만(화면·산출물에 넣지 않음 — PB 보고 검증용).  실행: python3 scripts/light_calibration.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener.us_committee import high_event, light_yellow  # noqa: E402


def _boards(kind: str, path: str) -> list[dict]:
    out = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((ROOT / "reports" / "archive" / kind).glob("20*.json"))]
    hs = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%h", "--", path], capture_output=True, text=True).stdout.split()
    for h in hs:
        try:
            out.append(json.loads(subprocess.run(["git", "-C", str(ROOT), "show", f"{h}:{path}"], capture_output=True, text=True).stdout))
        except Exception:  # noqa: BLE001
            continue
    seen, uniq = set(), []
    for o in out:
        bl = o.get("bottom_line") or {}
        key = (o.get("asof"), o.get("session"))
        if not bl.get("light") or key in seen:
            continue
        seen.add(key)
        uniq.append(o)
    return uniq


def relight(o: dict, cal_by_name: dict, us: bool) -> str:
    bl = o["bottom_line"]
    if bl["light"] == "red":
        return "red"
    it = o.get("ideas_top") or {}
    watch = {str(x.get("s")) for x in (it.get("items") or []) + (it.get("candidates") or [])}
    if us:
        watch |= {x.get("s") for x in (o.get("ideas") or {}).get("long", [])}
    clock = []
    for c in bl.get("clock") or []:
        c = dict(c)
        if c.get("kind") == "이벤트":
            nm = re.sub(r"\s*★$", "", str(c.get("what", "")))
            e = cal_by_name.get(nm) or {"name": nm}
            c["hi"] = high_event(e, watch)
        clock.append(c)
    if us:
        rg = next((c["what"] for c in clock if c.get("t") == "범위"), "")
        m = re.search(r"±([\d.]+)%", rg)
        band = float(m.group(1)) / 100 if m else 0.01
    else:
        band = ((o.get("positioning") or {}).get("implied") or {}).get("pct") or 0.01
    near, hi = light_yellow(clock, band)
    return "yellow" if (near or hi) else "green"


def main() -> int:
    cal = json.loads((ROOT / "reports" / "calendar.json").read_text(encoding="utf-8")).get("events", [])
    by_name = {e["name"]: e for e in cal}
    print("| 시장 | 판 수 | 전 🔴/🟡/🟢 | 후 🔴/🟡/🟢 |")
    print("|---|---|---|---|")
    for kind, path, us in (("committee", "reports/committee.json", False), ("committee_us", "reports/committee_us.json", True)):
        bs = _boards(kind, path)
        pre = Counter(o["bottom_line"]["light"] for o in bs)
        post = Counter(relight(o, by_name, us) for o in bs)
        f = lambda c: f"{c['red']}/{c['yellow']}/{c['green']}"  # noqa: E731
        print(f"| {'국장' if not us else '미장'} | {len(bs)} | {f(pre)} | {f(post)} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
