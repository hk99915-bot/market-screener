"""신선도 감시 — ops/freshness.json 계약대로 '지금 있어야 할 날짜'와 실제 파일 날짜를 비교 (재발방지대책 C, 2026-10-17).

python -m screener.main --mode freshness          # 점검만 → reports/freshness.json (briefing 모든 모드 끝, 텔레그램 없음)
python -m screener.main --mode freshness_alert    # 점검 + 늦은 게 있으면 텔레그램 ⛔ 소리 1통 (health.yml 08:20·20:10 KST)

같은 문제(항목 id + 기대일)는 하루 1회만 알림 — reports/freshness_alert_state.json.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import guard, tradecal
from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
ROOT = REPORT_DIR.parent
CONTRACT = ROOT / "ops" / "freshness.json"
OUT = REPORT_DIR / "freshness.json"
STATE = REPORT_DIR / "freshness_alert_state.json"
_TS = re.compile(r"(?:(\d{4})-)?(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})")
TEAM_IGNORE = ("reports", "data", "ops/team.json", "index.html")   # team.yml paths-ignore 와 같게


def load_contract(path: Path | None = None) -> list[dict]:
    return json.loads(Path(path or CONTRACT).read_text(encoding="utf-8"))["items"]


def parse_ts(v, now: datetime) -> datetime | None:
    """'2026-10-17 09:47', '10-17 09:47 KST', '2026-10-17T10:47+09:00' → KST datetime (연도 없으면 now 의 연도)."""
    if v is None:
        return None
    s = str(v)
    try:
        if "T" in s and ("+" in s[10:] or s.endswith("Z")):
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(KST)
    except ValueError:
        pass
    m = _TS.search(s)
    if not m:
        return None
    y = int(m.group(1)) if m.group(1) else now.astimezone(KST).year
    return datetime(y, int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), tzinfo=KST)


def _read_value(root: Path, it: dict):
    p = root / it["path"]
    if not p.exists():
        return None, "파일 없음"
    raw = p.read_text(encoding="utf-8")
    if p.suffix != ".json":
        return guard.text_day(raw), None
    try:
        obj = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None, "JSON 깨짐"
    if not it.get("key"):
        return guard.json_day(obj), None
    v = guard._get(obj, it["key"])
    if v is None and it.get("key_fallback"):   # 새 키(예: macro_series asof_kr)가 아직 없는 옛 파일
        v = guard._get(obj, it["key_fallback"])
    return v, None


def last_human_commit(root: Path = ROOT) -> datetime | None:
    """봇이 아닌 마지막 커밋 시각 (team.yml 이 무시하는 경로만 바꾼 커밋은 제외). 얕은 복제면 못 찾을 수 있음 → None."""
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "-40", "--format=%an|%cI", "--", "."]
                             + [f":!{x}" for x in TEAM_IGNORE], capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        return None
    for line in out.splitlines():
        an, _, ts = line.partition("|")
        if "bot" not in an.lower() and ts:
            return datetime.fromisoformat(ts).astimezone(KST).replace(second=0, microsecond=0)   # 비교는 분 단위
    return None


def _ready_today(now: datetime, hm: str, tz: str) -> datetime:
    loc = now.astimezone(ZoneInfo(tz))
    h, m = hm.split(":")
    return loc.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def check_item(it: dict, now: datetime, root: Path = ROOT, last_commit: datetime | None = None) -> dict | None:
    """늦었으면 {id, path, expected, actual, mode, fix, desc} 반환, 정상이면 None."""
    kind = it.get("kind", "session")
    if kind == "toss_md":   # 원격 브랜치 파일(toss-live/live.json) — 노트북 수집기가 멈추면 여기서 걸린다 (10/21)
        from . import toss_live
        val, err = toss_live.read_value(it.get("url") or toss_live.RAW_URL, it.get("key") or "published_at")
    else:
        val, err = _read_value(root, it)
    late = None
    if kind == "toss_md":
        from . import toss_live
        late = toss_live.check_late(val, now, it)
    elif kind == "session":
        exp = tradecal.expected_session(it["market"], now, it.get("ready"), it.get("tz"),
                                        int(it.get("day_offset") or 0), int(it.get("grace_min") or 0))
        act = guard.day(val)
        if act is None or act < exp.isoformat():
            late = (exp.isoformat(), act)
    elif kind == "intraday":
        if tradecal.in_session(it["market"], now):
            o = tradecal.SESSION[it["market"]][0]
            opened = datetime.combine(now.astimezone(tradecal.TZ[it["market"]]).date(), o, tzinfo=tradecal.TZ[it["market"]])
            age = int(it.get("max_age_min") or 120)
            ts = parse_ts(val, now)
            if now - opened >= timedelta(minutes=age) and (ts is None or now - ts > timedelta(minutes=age)):
                late = (f"{(now - timedelta(minutes=age)).astimezone(KST):%Y-%m-%d %H:%M} 이후", ts.strftime("%Y-%m-%d %H:%M") if ts else None)
    elif kind == "team":
        ts = parse_ts(val, now)
        g = timedelta(minutes=int(it.get("grace_min") or 30))
        need = None
        r = _ready_today(now, it.get("ready") or "00:07", it.get("tz") or "Asia/Seoul")
        if now >= r + g:
            need = r.replace(hour=0, minute=0)
        if last_commit and now >= last_commit + g:
            need = max(need, last_commit) if need else last_commit
        if need and (ts is None or ts < need):
            late = (f"{need.astimezone(KST):%Y-%m-%d %H:%M} 이후", ts.strftime("%Y-%m-%d %H:%M") if ts else None)
    if not late:
        return None
    return {"id": it["id"], "path": it["path"], "expected": late[0], "actual": late[1] or (err or "날짜 없음"),
            "mode": it.get("mode", ""), "fix": it.get("fix", ""), "desc": it.get("desc", "")}


def check(now: datetime | None = None, root: Path = ROOT, items: list[dict] | None = None,
          last_commit: datetime | None = None, write: bool = True) -> dict:
    now = now or datetime.now(KST)
    items = items if items is not None else load_contract(root / "ops" / "freshness.json")
    if last_commit is None and any(i.get("kind") == "team" for i in items):
        last_commit = last_human_commit(root)
    late = []
    for it in items:
        try:
            r = check_item(it, now, root, last_commit)
        except Exception as e:  # noqa: BLE001
            r = {"id": it.get("id"), "path": it.get("path"), "expected": "?", "actual": f"점검 실패 {type(e).__name__}",
                 "mode": it.get("mode", ""), "fix": it.get("fix", ""), "desc": it.get("desc", "")}
        if r:
            late.append(r)
    for mk in ("KR", "US"):   # 휴장일 표 만료 임박
        left = (tradecal.covered_until(mk) - now.astimezone(KST).date()).days
        if left < 45:
            late.append({"id": f"calendar_{mk}", "path": "screener/tradecal.py", "expected": "휴장일 표 갱신",
                         "actual": f"{tradecal.covered_until(mk)} 까지 ({left}일)", "mode": "개발", "fix": "HOLIDAYS 에 다음 해 추가",
                         "desc": f"{mk} 휴장일 표 만료 임박"})
    out_p = root / "reports" / "freshness.json"
    try:
        prev = json.loads(out_p.read_text(encoding="utf-8")) if out_p.exists() else {}
    except Exception:  # noqa: BLE001
        prev = {}
    blocked = prev.get("regress_blocked") or []
    stale = prev.get("stale") or []
    today = now.astimezone(KST).strftime("%Y-%m-%d")
    out = {"checked_at": now.astimezone(KST).strftime("%Y-%m-%d %H:%M"), "n": len(items), "late": late,
           "regress_today": [b for b in blocked if str(b.get("at", "")).startswith(today)],
           "regress_blocked": blocked, "stale_today": [x for x in stale if str(x.get("at", "")).startswith(today)],
           "stale": stale, "contract": "ops/freshness.json",
           "health": prev.get("health") or []}   # 시크릿 부재 등 '알림 비활성' (alerts.secret_health 가 씀) — 덮어쓰지 않고 보존
    if write:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("신선도: %d항목 중 늦음 %d · 오늘 역행 차단 %d", len(items), len(late), len(out["regress_today"]))
    return out


def alert_text(o: dict, keys_sent: set[str]) -> tuple[str | None, list[str]]:
    """새로 알릴 것만 골라 텔레그램 본문(≤8줄). 반환: (본문 또는 None, 이번에 보낸 키)."""
    new, keys = [], []
    for x in o["late"]:
        k = f"late:{x['id']}:{x['expected']}"
        if k not in keys_sent:
            new.append(f"• {x['path']} · 기대 {x['expected']} · 실제 {x['actual']} · {x['mode']} · 복구 <code>{x['fix']}</code>")
            keys.append(k)
    for b in o.get("regress_today") or []:
        k = f"regress:{b['path']}:{b['new']}"
        if k not in keys_sent:
            new.append(f"• 역행 차단 {b['path']} · 기존 {b['existing']} → 새 {b['new']} ({b.get('mode') or '?'})")
            keys.append(k)
    for x in o.get("stale_today") or []:
        k = f"stale:{x['path']}:{x['what']}:{x.get('got')}"
        if k not in keys_sent:
            new.append(f"• 대체 사용 {x['path']} {x['what']} · 목표 {x.get('want')} · 사용 {x.get('got')} ({x.get('mode') or '?'})")
            keys.append(k)
    if not new:
        return None, []
    head = f"⛔ <b>데이터 늦음 {len(new)}건</b> · {o['checked_at']} KST"
    body = new[:6] + ([f"… 외 {len(new) - 6}건 (화면 상단 ⚠ 배지)"] if len(new) > 6 else [])
    return "\n".join([head] + body), keys


def item_of(key: str) -> str:
    """알림 키 'late:<id>:<기대>' · 'regress:<경로>:<새>' · 'stale:<경로>:…' → 항목(id 또는 경로). 소리 하루 1회 판정 단위."""
    parts = str(key).split(":")
    return parts[1] if len(parts) > 1 else str(key)


def run(send: bool = False, now: datetime | None = None, root: Path = ROOT) -> dict:
    o = check(now, root)
    if not send:
        return o
    now = now or datetime.now(KST)
    today = now.astimezone(KST).strftime("%Y-%m-%d")
    sp = root / "reports" / STATE.name
    try:
        st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    except Exception:  # noqa: BLE001
        st = {}
    same = st.get("date") == today
    sent = set(st.get("keys") or []) if same else set()
    rang = set(st.get("rang") or []) if same else set()
    text, keys = alert_text(o, sent)
    if text:
        try:
            from .alerts import silent
            from .report import send_telegram
            new_items = sorted({item_of(k) for k in keys} - rang)
            # 결재 #9: 데이터 신선도 ⛔ 는 소리 — 단 항목당 하루 1회. 같은 항목이 같은 날 다시 걸리면(기대일 변경 등) 무음.
            send_telegram(text, disable_notification=silent(f"fresh:{i}" for i in new_items))
            sent |= set(keys)
            rang |= set(new_items)
            sp.write_text(json.dumps({"date": today, "keys": sorted(sent), "rang": sorted(rang)}, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("신선도 알림 실패: %s", e)
    o["alerted"] = keys if text else []
    return o
