#!/usr/bin/env python3
"""국장 새 추세 진입(hi52·gcv·sqz) '편입 대기' 전진 추적 판정 — 겸이 결재 10/24 (req-quant-d5d2f400, 보드 appr-trend-events-adopt).

  python3 scripts/trend_adopt_judge.py            # 드라이런 — 요약 출력만
  python3 scripts/trend_adopt_judge.py --apply    # reports/trend_adopt.json 쓰기 + 판정일 이후 보드에 결재 항목 1회 추가 (ops.yml 00:07 KST)

원천: reports/signal_tracking/<YYYY-MM>.json 의 src 'disc_kr', 태그 'adopt:<전략>'(화면 '편입 대기' 목록과 같은 모집단 — ETF·유동성 미달·추격 제외)
  이벤트 h20 초과(신호일 종가 → 20거래일, 시장 중앙값 대비). 'new:<전략>'(필터 전 전체)은 참고로 같이 집계.
판정(판정일 JUDGE_DATE 이후, 사전 고정 — reports/studies/2026-10-24_trend_events.md §4):
  n(h20 평가된 이벤트) ≥ 30 · 평균 초과 > 0  → '정식 후보'(연구 OOS 와 같은 방향)
  n ≥ 30 · 평균 초과 ≤ 0                     → '폐기 후보'
  n < 30                                       → '보류'(표본 부족 — 매월 20일 이후 재판정, 보류가 남는 동안 달마다 결재 항목 1건)
  주의: 10/23 신호의 h20 은 11/20 무렵에야 채워지므로 첫 판정은 '보류'가 될 가능성이 크다(표본 누적 시간).
**자동 승격 없음**: 판정은 보드 결재 항목(appr-trend-adopt-judge)으로만 올리고, 화면 라벨 변경·정식 편입은 겸이 결재 뒤 별도 커밋.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
OUT = ROOT / "reports" / "trend_adopt.json"
JUDGE_DATE = "2026-11-20"
MIN_N = 30
STRATS = ("hi52", "gcv", "sqz")
TASK_PREFIX = "appr-trend-adopt-judge-"   # + YYYY-MM — 판정일 뒤 매월 20일 이후 1회(보류가 남아 있는 동안)


def collect(root: Path = ROOT, layer: str = "adopt") -> dict[str, list[float]]:
    xs: dict[str, list[float]] = {k: [] for k in STRATS}
    for f in sorted((root / "reports" / "signal_tracking").glob("20*.json")):
        try:
            evs = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for e in evs:
            if e.get("src") != "disc_kr" or not str(e.get("tag", "")).startswith(layer + ":"):
                continue
            k = e["tag"].split(":", 1)[1]
            h = ((e.get("fwd") or {}).get("h20") or {})
            if k in xs and h.get("ex") is not None:
                xs[k].append(float(h["ex"]))
    return xs


def verdict(x: list[float]) -> str:
    if len(x) < MIN_N:
        return "보류"
    return "정식 후보" if sum(x) / len(x) > 0 else "폐기 후보"


def judge(today: str, root: Path = ROOT) -> dict:
    xs = collect(root)
    due = today >= JUDGE_DATE
    rows = {}
    for k, x in xs.items():
        x2 = sorted(x)
        rows[k] = {"n": len(x), "avg_ex": round(sum(x) / len(x), 5) if x else None,
                   "med_ex": round(x2[len(x2) // 2], 5) if x2 else None,
                   "hit": round(sum(v > 0 for v in x) / len(x), 3) if x else None,
                   "status": verdict(x) if due else "전진 추적 중"}
    ref = {k: {"n": len(x), "avg_ex": round(sum(x) / len(x), 5) if x else None} for k, x in collect(root, "new").items()}
    return {"asof": today, "judge_date": JUDGE_DATE, "due": due, "min_n": MIN_N, "strategies": rows, "ref_new_all": ref,
            "rule": f"판정일 {JUDGE_DATE} 이후: n(h20) ≥ {MIN_N}·평균 초과 > 0 → 정식 후보 / ≤ 0 → 폐기 후보 / n < {MIN_N} → 보류",
            "auto_promote": False,
            "note": "표시만 — 판정은 보드 결재 항목으로 올리고, 정식 편입·라벨 변경은 겸이 결재 뒤. 원천 signal_tracking disc_kr adopt:*(ref_new_all = new:* 필터 전)",
            "schema_version": 1}


def board_add(res: dict, root: Path = ROOT) -> bool:
    """판정일 이후 1회: 보드에 결재 항목 추가(이미 있으면 안 함)."""
    if not res["due"] or res["asof"][8:10] < "20" and res["asof"] != JUDGE_DATE:
        return False
    task_id = TASK_PREFIX + res["asof"][:7]
    sys.path.insert(0, str(root / "scripts"))
    import board as B
    bp = root / "ops" / "board.json"
    b = json.loads(bp.read_text(encoding="utf-8"))
    mine = [t for t in b.get("tasks", []) if str(t.get("id", "")).startswith(TASK_PREFIX)]
    if any(t["id"] == task_id for t in mine):
        return False
    if mine and "보류" not in max(mine, key=lambda t: t["id"]).get("notes", ""):
        return False   # 지난 판정에 보류 없음 = 판정 끝(결재 대상 이미 올라감)
    pc = lambda x: "—" if x is None else f"{x * 100:+.2f}%"  # noqa: E731
    s = " · ".join(f"{k} {v['status']}(n {v['n']}, 평균 {pc(v['avg_ex'])})" for k, v in res["strategies"].items())
    task = {"id": task_id, "title": "겸이 결재 필요: 국장 새 추세 진입 전진 추적 판정 — 정식 편입 여부", "owner": "퀀트",
            "priority": "P2", "status": "대기", "started": None, "due": (datetime.fromisoformat(res["asof"]) + timedelta(days=7)).date().isoformat(),
            "files": ["reports/trend_adopt.json", "reports/studies/2026-10-24_trend_events.md"], "depends_on": [],
            "notes": f"scripts/trend_adopt_judge.py 자동 생성({res['asof']}). {s}. 자동 승격 없음 — 결재 뒤 퀀트가 표시 변경.",
            "approval": "겸이"}
    errs = B.add_task(b, task)
    if errs:
        print("✗ 보드 추가 실패:", errs, file=sys.stderr)
        return False
    bp.write_text(json.dumps(b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--today", help="테스트용 기준일 YYYY-MM-DD")
    a = ap.parse_args(argv)
    today = a.today or datetime.now(KST).date().isoformat()
    res = judge(today)
    print(json.dumps({k: res[k] for k in ("asof", "due", "strategies")}, ensure_ascii=False))
    if a.apply:
        OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if board_add(res):
            print("보드 결재 항목 추가:", TASK_PREFIX + res["asof"][:7])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
