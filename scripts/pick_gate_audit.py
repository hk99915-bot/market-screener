"""대결 '나' 게이트 소급 점검 — 겸이 10/24 결재(appr-pick-gate-start): PICK_GATE_FROM(10/23 19:00 KST) 이후 제출분.

  python3 scripts/pick_gate_audit.py            # 표만 출력
  python3 scripts/pick_gate_audit.py --apply    # 위반 픽에 'gate_audit' 표시만 추가(칸 이동·삭제 없음 — 채점 그대로)
네트워크 없음(ops/cooldown.json·decisions.json 만). 행동 데스크 소관.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screener import decisions, pick_gate  # noqa: E402
from screener.defs import PICK_GATE_FROM  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    data = decisions.load()
    items = data.get("items") or []
    from screener.ticket import cooldown_file_events
    rows = pick_gate.audit(items, events=cooldown_file_events())
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    print(f"게이트 소급 점검 {today} · 대상 = 제출 {PICK_GATE_FROM} KST 이후 '나'·'나🔥' · {len(rows)}건")
    for r in rows:
        print(f"  {r['id']} {r['slot']} {r['submitted']} {r['status']}" + (" — " + " · ".join(r["reasons"]) if r["reasons"] else ""))
    bad = [r for r in rows if r["status"] == "위반"]
    print(f"위반 {len(bad)}건")
    if a.apply and bad:
        byid = {x["id"]: x for x in items}
        for r in bad:
            byid[r["id"]]["picks"][r["slot"]]["gate_audit"] = f"소급 점검 {today}: 게이트 위반 — " + " · ".join(r["reasons"]) + " (표시만, 채점 그대로)"
        decisions.OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"표시 {len(bad)}건 기록 → {decisions.OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
