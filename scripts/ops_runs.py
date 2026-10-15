"""최근 24시간 GitHub Actions 실행 통계 → reports/ops/runs.json

워크플로별: 실행 수 · 성공 · 실패 · 취소 · 예약(schedule) vs 수동(workflow_dispatch) · 예약 지연(cron 시각 대비, 추정) · 예약 누락 추정.
백업 예약기(apps-script/Scheduler.gs) 시간표 슬롯별로 dispatch 가 도착했는지·몇 분 늦었는지도 본다.

  GITHUB_TOKEN=… GITHUB_REPOSITORY=hk99915-bot/market-screener python scripts/ops_runs.py [--hours 24]
토큰 없으면 비인증 호출(공개 저장소, 시간당 60회 한도).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "ops" / "runs.json"
KST = timezone(timedelta(hours=9))
UTC = timezone.utc
FAIL = {"failure", "timed_out", "startup_failure", "action_required"}


def api(url: str) -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "market-screener-ops"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = "Bearer " + tok
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
        return json.load(r)


def fetch_runs(repo: str, since: datetime) -> list[dict]:
    out, page = [], 1
    q = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    while page <= 10:
        d = api(f"https://api.github.com/repos/{repo}/actions/runs?created=%3E%3D{q}&per_page=100&page={page}")
        rs = d.get("workflow_runs", [])
        out += rs
        if len(rs) < 100:
            break
        page += 1
    return out


# ── cron ────────────────────────────────────────────────────────────
def _field(spec: str, lo: int, hi: int) -> set[int]:
    vals = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/"); step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = map(int, part.split("-"))
        else:
            a = b = int(part)
            if step > 1:
                b = hi
        vals |= set(range(a, b + 1, step))
    return vals


def cron_fires(expr: str, start: datetime, end: datetime) -> list[datetime]:
    """UTC cron 이 [start, end] 사이에 울리는 시각들."""
    m, h, dom, mon, dow = expr.split()
    M, H, D, MO = _field(m, 0, 59), _field(h, 0, 23), _field(dom, 1, 31), _field(mon, 1, 12)
    W = {x % 7 for x in _field(dow, 0, 7)}
    out, t = [], start.replace(second=0, microsecond=0)
    while t <= end:
        if t.minute in M and t.hour in H and t.month in MO:
            dw = (t.weekday() + 1) % 7   # 0=일
            dom_ok, dow_ok = t.day in D, dw in W
            if (dom == "*" or dow == "*") and dom_ok and dow_ok or (dom != "*" and dow != "*" and (dom_ok or dow_ok)):
                out.append(t)
        t += timedelta(minutes=1)
    return out


def workflow_crons() -> dict[str, list[str]]:
    out = {}
    for p in (ROOT / ".github" / "workflows").glob("*.yml"):
        out[f".github/workflows/{p.name}"] = re.findall(r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']", p.read_text(encoding="utf-8"), re.M)
    return out


def gas_schedule() -> list[dict]:
    p = ROOT / "apps-script" / "Scheduler.gs"
    if not p.exists():
        return []
    s = p.read_text(encoding="utf-8")
    consts = {k: [int(x) for x in v.split(",") if x.strip()] for k, v in re.findall(r"const\s+(\w+)\s*=\s*\[([\d,\s]+)\]", s)}
    out = []
    for hm, wf, days in re.findall(r"\[\s*'(\d\d:\d\d)'\s*,\s*'([\w.-]+)'\s*,\s*\{[^}]*\}\s*,\s*(\w+)\s*\]", s):
        out.append({"time": hm, "workflow": wf, "days": consts.get(days, list(range(7)))})
    return out


def parse_t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    a = ap.parse_args()
    repo = os.environ.get("GITHUB_REPOSITORY", "hk99915-bot/market-screener")
    now = datetime.now(UTC)
    since = now - timedelta(hours=a.hours)
    runs = fetch_runs(repo, since)
    crons = workflow_crons()

    by = defaultdict(list)
    for r in runs:
        by[r.get("path", "").split("@")[0] or r.get("name")].append(r)

    wfs = []
    for path, rs in sorted(by.items()):
        rs.sort(key=lambda r: r["created_at"])
        st = {"runs": len(rs), "success": 0, "failure": 0, "cancelled": 0, "skipped": 0, "in_progress": 0, "schedule": 0, "dispatch": 0, "other": 0}
        delays, fails = [], []
        cr = crons.get(path, [])
        for r in rs:
            c = r.get("conclusion")
            if r.get("status") != "completed":
                st["in_progress"] += 1
            elif c == "success":
                st["success"] += 1
            elif c in FAIL:
                st["failure"] += 1
                fails.append({"at": parse_t(r["created_at"]).astimezone(KST).strftime("%m-%d %H:%M"), "event": r["event"], "url": r.get("html_url"), "title": (r.get("display_title") or "")[:80]})
            elif c == "cancelled":
                st["cancelled"] += 1
            elif c == "skipped":
                st["skipped"] += 1
            ev = r.get("event")
            if ev == "schedule":
                st["schedule"] += 1
                t = parse_t(r["created_at"])
                fires = [f for e in cr for f in cron_fires(e, t - timedelta(hours=6), t)]
                if fires:
                    delays.append(round((t - max(fires)).total_seconds() / 60))
            elif ev == "workflow_dispatch":
                st["dispatch"] += 1
            else:
                st["other"] += 1
        expected = len([f for e in cr for f in cron_fires(e, since, now - timedelta(minutes=20))])
        last = rs[-1]
        wfs.append({
            "path": path, "name": last.get("name") or path, **st,
            "max_delay_min": max(delays) if delays else None,
            "avg_delay_min": round(sum(delays) / len(delays)) if delays else None,
            "cron_expected": expected,
            "cron_missed_est": max(0, expected - st["schedule"]) if cr else None,
            "last": {"at": parse_t(last["created_at"]).astimezone(KST).strftime("%m-%d %H:%M"), "event": last["event"],
                     "status": last.get("status"), "conclusion": last.get("conclusion"), "url": last.get("html_url")},
            "failures": fails[-5:],
        })
    # 예약 정의는 있는데 24h 동안 한 번도 안 돈 워크플로
    for path, cr in crons.items():
        if path not in by and cr:
            exp = len([f for e in cr for f in cron_fires(e, since, now - timedelta(minutes=20))])
            if exp:
                wfs.append({"path": path, "name": Path(path).stem, "runs": 0, "success": 0, "failure": 0, "cancelled": 0, "skipped": 0,
                            "in_progress": 0, "schedule": 0, "dispatch": 0, "other": 0, "max_delay_min": None, "avg_delay_min": None,
                            "cron_expected": exp, "cron_missed_est": exp, "last": None, "failures": []})

    # 백업 예약기(GAS) 슬롯별 도착 확인
    gas = []
    nowk = now.astimezone(KST)
    for slot in gas_schedule():
        hh, mm = map(int, slot["time"].split(":"))
        for back in (1, 0):
            day = (nowk - timedelta(days=back)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            if not (since <= day <= now - timedelta(minutes=10)):
                continue
            if (day.weekday() + 1) % 7 not in slot["days"]:
                continue
            wpath = f".github/workflows/{slot['workflow']}"
            disp = [parse_t(r["created_at"]) for r in by.get(wpath, []) if r["event"] == "workflow_dispatch"]
            hit = [t for t in disp if day <= t.astimezone(KST) <= day + timedelta(minutes=30)]
            gas.append({"slot": day.strftime("%m-%d %H:%M"), "workflow": slot["workflow"],
                        "arrived": bool(hit), "delay_min": round((min(hit).astimezone(KST) - day).total_seconds() / 60) if hit else None})
    gas.sort(key=lambda g: g["slot"])

    tot = {k: sum(w[k] for w in wfs) for k in ("runs", "success", "failure", "cancelled", "schedule", "dispatch")}
    out = {
        "asof": nowk.strftime("%Y-%m-%d %H:%M KST"),
        "window_h": a.hours,
        "repo": repo,
        "note": "지연 = 실행 생성 시각 − 직전 cron 시각(추정, 여러 cron 이 가까우면 과소추정). 누락 추정 = 예정 횟수 − 예약 실행 수.",
        "total": tot,
        "workflows": sorted(wfs, key=lambda w: (-w["failure"], -w["runs"])),
        "gas": gas,
        "gas_summary": {"slots": len(gas), "arrived": sum(g["arrived"] for g in gas),
                        "max_delay_min": max((g["delay_min"] for g in gas if g["delay_min"] is not None), default=None)},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"runs.json: {tot['runs']}회 (실패 {tot['failure']}) · 워크플로 {len(wfs)}개 · GAS 슬롯 {out['gas_summary']['arrived']}/{len(gas)} 도착")


if __name__ == "__main__":
    main()
