"""신호 전달 지연 — 슬롯 → 계산(전송) → main 커밋 (data_eng 2026-11-06, ⚡ 급락 신호 15:08 실행·아무도 못 본 날).

reports/alerts_state.json 의 오늘 `sent` 키(예: '2026-11-06:crash' → '2026-11-06 15:09')를 읽어
  slot_lag  = 계산(전송) 시각 − 예약 슬롯(docs/schedule_table.md)   ← GAS 디스패치 지연 + 실행 시간
  commit_lag = main 커밋 시각 − 계산 시각                          ← 저장 단계 (git 이력이 얕으면 None = 미확인)
  margin    = 마감(동시호가 등) − 계산 시각                         ← 사람이 행동할 수 있는 남은 시간
을 reports/freshness.json 의 `latency` 칸에 적는다. Pages 반영(커밋→배포 ≈1분)은 Actions API 가 필요해 여기선 재지 않는다.

SLA (데이터엔지니어 제안, 검증전 — 11/6 실측 1건 기준): 슬롯→계산 ≤5분 · 계산→커밋 ≤1분 · 커밋→Pages ≤2분,
그리고 마감까지 ≥10분 남을 것. 어기면 `ok=False` — 경보는 하지 않는다(소리 등급은 결재 #9 소관).
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
STATE = "reports/alerts_state.json"
# 종류 → (예약 슬롯, 마감). 출처 docs/schedule_table.md 65·66행, screener/alerts.py (d) 15:20 동시호가.
SLOTS = {"crash": ("15:05", "15:20"), "dl": ("14:25", None)}
SLA = {"slot_lag_s": 300, "commit_lag_s": 60, "pages_lag_s": 120, "margin_s": 600}


def _kind(key: str) -> str:
    """'2026-11-06:crash' → 'crash' · '2026-10-20:dl2' → 'dl' · 'stop1' → 'stop'."""
    k = key.split(":", 1)[-1]
    return k.rstrip("0123456789") or k


def _at(day: str, hm: str | None) -> datetime | None:
    return datetime.fromisoformat(f"{day} {hm}").replace(tzinfo=KST) if hm else None


def commit_time(key: str, root: Path) -> datetime | None:
    """그 키를 alerts_state.json 에 처음 넣은 커밋 시각. 얕은 복제(Actions depth 1)면 못 찾음 → None."""
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%cI", f"-S\"{key}\"", "--", STATE],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return datetime.fromisoformat(out).astimezone(KST) if out else None
    except Exception:  # noqa: BLE001
        return None


def measure(sent: dict, day: str, commits: dict | None = None) -> list[dict]:
    """sent = alerts_state['sent'], commits = {키: 커밋 datetime} (없으면 commit_lag None). 순수 함수 — 테스트용."""
    commits = commits or {}
    rows = []
    for key, ts in sorted(sent.items()):
        if not key.startswith(day):
            continue
        sent_at = datetime.fromisoformat(str(ts)).replace(tzinfo=KST)
        slot, deadline = SLOTS.get(_kind(key), (None, None))
        slot_at, dl_at, c_at = _at(day, slot), _at(day, deadline), commits.get(key)
        r = {"key": key, "slot": slot, "sent": str(ts), "deadline": deadline,
             "committed": c_at.strftime("%Y-%m-%d %H:%M:%S") if c_at else None,
             "slot_lag_s": int((sent_at - slot_at).total_seconds()) if slot_at else None,
             # 전송 시각은 분 단위라 커밋이 같은 분이면 음수가 나올 수 있다 → 0 바닥
             "commit_lag_s": max(0, int((c_at - sent_at).total_seconds())) if c_at else None,
             "margin_s": int((dl_at - sent_at).total_seconds()) if dl_at else None}
        bad = [n for n in ("slot_lag_s", "commit_lag_s") if r[n] is not None and r[n] > SLA[n]]
        if r["margin_s"] is not None and r["margin_s"] < SLA["margin_s"]:
            bad.append("margin_s")
        r["ok"], r["breach"] = not bad, bad
        rows.append(r)
    return rows


def run(root: Path, now: datetime, prev: list | None = None) -> dict:
    """freshness.check 가 부른다. 같은 날 이전 실행에서 찾은 커밋 시각은 보존(이번 복제가 얕아도 지우지 않음)."""
    day = now.astimezone(KST).strftime("%Y-%m-%d")
    try:
        sent = json.loads((root / STATE).read_text(encoding="utf-8")).get("sent") or {}
    except Exception:  # noqa: BLE001
        sent = {}
    old = {r["key"]: r for r in (prev or []) if isinstance(r, dict) and str(r.get("key", "")).startswith(day)}
    commits = {}
    for k in sent:
        if not k.startswith(day):
            continue
        c = commit_time(k, root)
        if c is None and (old.get(k) or {}).get("committed"):
            c = datetime.fromisoformat(old[k]["committed"]).replace(tzinfo=KST)
        if c:
            commits[k] = c
    return {"day": day, "sla": SLA, "rows": measure(sent, day, commits)}
