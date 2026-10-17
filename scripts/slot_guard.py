"""예약 일원화 가드 (결정 C, docs/schedule_table.md) — 산출물 하나 = 실행 주체 하나.

워크플로의 첫 단계에서 부른다. 결과는 GITHUB_OUTPUT 의 go(true/false)·commit(true/false)·reason.

  python scripts/slot_guard.py --wf briefing.yml --key premarket_kr

규칙
1) GAS 예약기(apps-script/Scheduler.gs SCHEDULE)에 같은 (워크플로·키·KST 시각·요일) 슬롯이 있으면
   → **GAS 가 주 실행 주체**, 같은 슬롯 GitHub cron 은 '대기(fallback)':
     예정 시각 + FALLBACK_WAIT_MIN 까지 기다린 뒤, 그 사이 같은 키의 workflow_dispatch 실행이 있으면 건너뜀.
     GAS 는 예정 시각 + WINDOW_MIN(10분) 안에만 보내므로 대기 뒤 확인하면 경쟁이 없다.
   → API 실패 시엔 실행(fail-open, ::warning) — 알림 누락이 중복보다 나쁘다.
2) GAS 슬롯이 아닌 cron·push·issues → 그대로 실행, 커밋.
3) workflow_dispatch(수동·GAS) → 실행은 하되 커밋은 입력 commit 으로:
     true → 커밋 · false → 읽기 전용 · auto(기본) → GAS 슬롯 시각 + AUTO_WINDOW_MIN 안이면 커밋(구버전 GAS 호환), 아니면 읽기 전용.
   10/17 detail_us 수동 실행이 US 상세 기준일을 10/16→10/15 로 되돌린 사고의 재발 방지.

실행 구분용 run-name: 수동은 '<이름> [<키>] commit=<값>', 예약은 '<이름> 예약 <cron>' — 가드가 display_title 로 찾는다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAS = ROOT / "apps-script" / "Scheduler.gs"
WF_DIR = ROOT / ".github" / "workflows"
KST = timezone(timedelta(hours=9))

FALLBACK_WAIT_MIN = 12   # cron 대기 — GAS WINDOW_MIN(10) + 여유 2분
AUTO_WINDOW_MIN = 25     # commit=auto 수동 실행을 GAS 슬롯으로 인정하는 폭 (구버전 GAS WINDOW_MIN 20 + 여유)
SINCE_PAD_MIN = 5        # 예정 시각보다 이만큼 이른 dispatch 도 같은 슬롯으로 본다

# GAS inputs 중 '어떤 작업인가'를 가르는 입력 — 없으면 워크플로 전체가 작업 하나
KEY_FIELD = {"briefing.yml": "mode", "screener.yml": "market", "deriv_hist.yml": "task", "backfill.yml": "market"}
# cron 실행일 때의 키 (briefing 은 cron 문자열 → 모드 case 문에서 정해 --key 로 넘긴다)
CRON_KEY = {"screener.yml": "KR", "deriv_hist.yml": "run", "backfill.yml": "ALL"}


# ── 파서 (테스트와 공용) ─────────────────────────────────────────────
def parse_gas(text: str | None = None) -> dict:
    """Scheduler.gs → {'slots': [{time, min, wf, inputs, days}], 'window_min': int}. 주석 처리된 줄은 제외."""
    text = GAS.read_text(encoding="utf-8") if text is None else text
    consts = {}
    for name, body in re.findall(r"^const (\w+) = \[([\d,\s]+)\];", text, re.M):
        consts[name] = [int(x) for x in body.replace(" ", "").split(",") if x]
    m = re.search(r"^const WINDOW_MIN = (\d+);", text, re.M)
    block = re.search(r"^const SCHEDULE = \[(.*?)^\];", text, re.M | re.S).group(1)
    slots = []
    for line in block.splitlines():
        s = line.strip()
        if not s.startswith("["):
            continue   # '//' 주석 줄·빈 줄
        mm = re.match(r"\['(\d\d):(\d\d)',\s*'([\w.]+)',\s*\{(.*?)\},\s*(\w+)\]", s)
        if not mm:
            raise ValueError(f"Scheduler.gs SCHEDULE 줄 해석 실패: {s}")
        h, mi, wf, inp, days = mm.groups()
        inputs = dict(re.findall(r"(\w+):\s*'([^']*)'", inp))
        slots.append({"time": f"{h}:{mi}", "min": int(h) * 60 + int(mi), "wf": wf, "inputs": inputs,
                      "days": consts[days]})
    return {"slots": slots, "window_min": int(m.group(1)) if m else None}


def _field(f: str, lo: int, hi: int) -> list[int]:
    if f == "*":
        return list(range(lo, hi + 1))
    out = []
    for part in f.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def cron_kst(cron: str) -> list[tuple[int, list[int]]]:
    """UTC cron → [(KST 분, KST 요일 목록 0=일)]. 분·시·요일만 해석(일·월은 * 가정)."""
    mi, h, _dom, _mon, dow = cron.split()
    out = []
    for hh in _field(h, 0, 23):
        for mm in _field(mi, 0, 59):
            k = hh * 60 + mm + 9 * 60
            shift = k // 1440
            out.append((k % 1440, sorted({(d % 7 + shift) % 7 for d in _field(dow, 0, 6)})))
    return out


def gas_key(slot: dict) -> str:
    return slot["inputs"].get(KEY_FIELD.get(slot["wf"], ""), "")


def find_gas_slot(gas: dict, wf: str, key: str, kst_min: int, dow: int) -> dict | None:
    for s in gas["slots"]:
        if s["wf"] == wf and gas_key(s) == key and s["min"] == kst_min and dow in s["days"]:
            return s
    return None


def gas_slot_near(gas: dict, wf: str, key: str, now_kst: datetime, width: int) -> dict | None:
    """now 가 GAS 슬롯 [예정, 예정+width) 안이면 그 슬롯 (commit=auto 판정용)."""
    nm = now_kst.hour * 60 + now_kst.minute
    for s in gas["slots"]:
        if s["wf"] != wf or gas_key(s) != key:
            continue
        late = (nm - s["min"]) % 1440
        day = now_kst - timedelta(minutes=late)
        if late < width and (day.isoweekday() % 7) in s["days"]:
            return s
    return None


# ── 판정 (순수 함수) ─────────────────────────────────────────────────
def dispatch_commit(commit_input: str, gas: dict, wf: str, key: str, now_utc: datetime) -> tuple[bool, str]:
    c = (commit_input or "auto").strip().lower()
    if c == "true":
        return True, "수동 commit=true"
    if c == "false":
        return False, "수동 commit=false — 읽기 전용"
    s = gas_slot_near(gas, wf, key, now_utc.astimezone(KST), AUTO_WINDOW_MIN)
    if s:
        return True, f"commit=auto, GAS 슬롯 {s['time']} 시각 안 → 커밋(구버전 GAS 호환)"
    return False, "commit=auto, 예약 슬롯 밖 수동 실행 → 읽기 전용 (커밋하려면 commit=true)"


def fallback_plan(gas: dict, wf: str, key: str, cron: str, now_utc: datetime) -> dict | None:
    """cron 실행이 GAS 슬롯의 대기(fallback)면 {slot, check_at(UTC), since(UTC)}; 아니면 None."""
    now_kst = now_utc.astimezone(KST)
    nm = now_kst.hour * 60 + now_kst.minute
    best = None
    for kmin, days in cron_kst(cron):
        late = (nm - kmin) % 1440
        sched = (now_kst - timedelta(minutes=late)).replace(second=0, microsecond=0)
        if (sched.isoweekday() % 7) not in days:
            continue
        s = find_gas_slot(gas, wf, key, kmin, sched.isoweekday() % 7)
        if s and (best is None or late < best[0]):
            best = (late, s, sched)
    if not best:
        return None
    _, s, sched = best
    return {"slot": s, "check_at": (sched + timedelta(minutes=FALLBACK_WAIT_MIN)).astimezone(timezone.utc),
            "since": (sched - timedelta(minutes=SINCE_PAD_MIN)).astimezone(timezone.utc)}


def primary_ran(runs: list[dict], key: str, since: datetime) -> list[dict]:
    """since 이후 같은 키의 workflow_dispatch(취소·건너뜀·commit=false 제외)."""
    out = []
    for r in runs:
        if r.get("event") != "workflow_dispatch":
            continue
        t = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        title = r.get("display_title") or ""
        if t < since or r.get("conclusion") in ("cancelled", "skipped") or "commit=false" in title:
            continue
        if key and f"[{key}]" not in title:
            continue
        out.append(r)
    return out


# ── 분석 (docs/schedule_table.md · tests/test_schedule_single.py) ─────
MANUAL_ONLY = {"flowq.yml", "pb_call.yml"}   # workflow_dispatch 가 유일한 실행 주체(요청형) — 읽기 전용 기본 대상 아님
DOW = "일월화수목금토"


def load_workflows() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WF_DIR.glob("*.yml"))}


def _yaml(text: str) -> dict:
    import yaml   # 지연 import — 워크플로 실행 경로(가드)는 표준 라이브러리만
    d = yaml.safe_load(text)
    if True in d and "on" not in d:   # PyYAML 은 'on' 을 True 로 읽는다
        d["on"] = d.pop(True)
    return d


def briefing_cron_modes(text: str) -> dict[str, str]:
    """briefing.yml 의 case 문 → {cron: mode}."""
    out = {}
    for crons, mode in re.findall(r'^\s*((?:"[^"]+"\|?)+)\) MODE=(\w+) ;;', text, re.M):
        for c in re.findall(r'"([^"]+)"', crons):
            out[c] = mode
    return out


def cron_key(wf: str, text: str, cron: str) -> str:
    if wf == "briefing.yml":
        return briefing_cron_modes(text).get(cron, "?")
    return CRON_KEY.get(wf, "")


def guarded(wf: str, text: str) -> bool:
    return f"scripts/slot_guard.py --wf {wf}" in text


def analyze(gas: dict | None = None, wfs: dict[str, str] | None = None) -> dict:
    """슬롯(워크플로·키·KST 시각·요일)별 실행 주체. double = GAS + 가드 없는 cron 이 2개 이상."""
    gas = parse_gas() if gas is None else gas
    wfs = load_workflows() if wfs is None else wfs
    slots: dict[tuple, list[str]] = {}
    for s in gas["slots"]:
        for d in s["days"]:
            slots.setdefault((s["wf"], gas_key(s), s["min"], d), []).append("GAS")
    for wf, text in wfs.items():
        on = _yaml(text).get("on") or {}
        for item in (on.get("schedule") or []) if isinstance(on, dict) else []:
            cron = item["cron"]
            key = cron_key(wf, text, cron)
            for kmin, days in cron_kst(cron):
                for d in days:
                    is_fb = guarded(wf, text) and find_gas_slot(gas, wf, key, kmin, d) is not None
                    slots.setdefault((wf, key, kmin, d), []).append(f"cron:{cron}" + ("(대기)" if is_fb else ""))
    rows = []
    for (wf, key, kmin, d), ex in sorted(slots.items(), key=lambda x: (x[0][2], x[0][0], x[0][3])):
        active = [e for e in ex if not e.endswith("(대기)")]
        rows.append({"wf": wf, "key": key, "time": f"{kmin // 60:02d}:{kmin % 60:02d}", "dow": d,
                     "executors": ex, "double": len(active) > 1})
    return {"rows": rows, "double_slots": sorted({(r["wf"], r["key"], r["time"]) for r in rows if r["double"]})}


def manual_gate_violations(wfs: dict[str, str] | None = None) -> list[str]:
    """수동 dispatch 가 기본값으로 커밋할 수 있는 워크플로 (자동 트리거가 따로 있는데 commit 입력·조건이 없음)."""
    wfs = load_workflows() if wfs is None else wfs
    bad = []
    for wf, text in wfs.items():
        on = _yaml(text).get("on") or {}
        if not isinstance(on, dict) or "workflow_dispatch" not in on or wf in MANUAL_ONLY:
            continue
        if not (set(on) - {"workflow_dispatch"}) or "git push" not in text:
            continue
        inputs = (on.get("workflow_dispatch") or {}).get("inputs") or {}
        dflt = str((inputs.get("commit") or {}).get("default", "")).lower()
        if "commit" not in inputs or dflt == "true":
            bad.append(f"{wf}: workflow_dispatch 입력 commit(기본 false/auto) 없음")
            continue
        for job in _yaml(text)["jobs"].values():
            for st in job.get("steps", []):
                run = st.get("run") or ""
                if "git push" in run and "commit" not in str(st.get("if", "")) and "COMMIT" not in run:
                    bad.append(f"{wf}: '{st.get('name')}' 단계가 commit 조건 없이 push")
    return bad


def table_md(res: dict | None = None) -> str:
    res = analyze() if res is None else res
    agg: dict[tuple, dict] = {}
    for r in res["rows"]:
        k = (r["time"], r["wf"], r["key"], tuple(r["executors"]))
        agg.setdefault(k, {"days": [], "double": r["double"]})["days"].append(r["dow"])
    lines = ["| KST | 워크플로 [키] | 요일 | 실행 주체 | 이중 |", "|---|---|---|---|---|"]
    for (t, wf, key, ex), v in sorted(agg.items()):
        days = "".join(DOW[d] for d in sorted(v["days"], key=lambda x: (x + 6) % 7))
        exs = " + ".join("GAS(주)" if e == "GAS" else e.replace("cron:", "cron ") for e in ex)
        lines.append(f"| {t} | {wf}{f' [{key}]' if key else ''} | {days} | {exs} | {'⛔' if v['double'] else '—'} |")
    return "\n".join(lines)


# ── 실행 ────────────────────────────────────────────────────────────
def list_runs(wf: str, since: datetime) -> list[dict]:
    repo, tok = os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_TOKEN", "")
    url = (f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?event=workflow_dispatch"
           f"&created=%3E%3D{since.strftime('%Y-%m-%dT%H:%M:%SZ')}&per_page=50")
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               **({"Authorization": f"Bearer {tok}"} if tok else {})})
    with urllib.request.urlopen(req, timeout=20) as f:
        return json.load(f).get("workflow_runs", [])


def decide(wf: str, key: str, event: str, cron: str, commit_input: str, now: datetime | None = None,
           runs_fn=list_runs, sleep_fn=time.sleep, gas: dict | None = None) -> dict:
    gas = parse_gas() if gas is None else gas
    now = now or datetime.now(timezone.utc)
    if event == "workflow_dispatch":
        c, why = dispatch_commit(commit_input, gas, wf, key, now)
        return {"go": True, "commit": c, "reason": why}
    if event != "schedule" or not cron:
        return {"go": True, "commit": True, "reason": f"{event} — 단독 실행 주체"}
    plan = fallback_plan(gas, wf, key, cron, now)
    if not plan:
        return {"go": True, "commit": True, "reason": f"cron {cron} — GAS 슬롯 아님, 단독 실행 주체"}
    wait = (plan["check_at"] - now).total_seconds()
    if wait > 0:
        print(f"GAS 슬롯 {plan['slot']['time']} 대기 실행 — {wait:.0f}초 기다린 뒤 GAS 실행 여부 확인")
        sleep_fn(wait)
    try:
        hit = primary_ran(runs_fn(wf, plan["since"]), key, plan["since"])
    except Exception as e:   # noqa: BLE001 — API 실패는 실행(fail-open) + 경고
        print(f"::warning::slot_guard 실행 목록 조회 실패({e}) — 대기 실행을 그대로 진행")
        return {"go": True, "commit": True, "reason": "API 실패 → fail-open"}
    if hit:
        return {"go": False, "commit": False,
                "reason": f"GAS 가 슬롯 {plan['slot']['time']} [{key}] 실행함(run {hit[0].get('id')}) — cron 건너뜀"}
    return {"go": True, "commit": True, "reason": f"GAS 슬롯 {plan['slot']['time']} 미실행 → cron 이 대신 실행"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wf")
    ap.add_argument("--table", action="store_true", help="슬롯 × 실행 주체 표(markdown)와 이중 슬롯 수 출력")
    ap.add_argument("--key", default=None, help="작업 키 (briefing=mode, screener=market …). 생략 시 입력/기본값")
    a = ap.parse_args()
    if a.table:
        res = analyze()
        print(table_md(res))
        print(f"\n이중 실행 슬롯 {len(res['double_slots'])}개 · 수동 덮어쓰기 경로 {len(manual_gate_violations())}개")
        return 0
    if not a.wf:
        ap.error("--wf 필요")
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    cron = os.environ.get("SCHEDULE", "")
    key = a.key
    if key is None:
        key = os.environ.get("KEY_INPUT", "") if event == "workflow_dispatch" else CRON_KEY.get(a.wf, "")
    d = decide(a.wf, key, event, cron, os.environ.get("COMMIT_INPUT", ""))
    print(f"slot_guard {a.wf} [{key}] {event} {cron} → go={d['go']} commit={d['commit']} · {d['reason']}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"go={'true' if d['go'] else 'false'}\ncommit={'true' if d['commit'] else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
