"""asof 단조 가드 — 산출물을 '더 과거 날짜'로 덮어쓰지 않는다 (refactor_plan 결정 B 1단계, 보드 detail-us-regress).

사용
    from .guard import write_json, write_text, allow
    write_json(REPORT_DIR / "momentum_US.json", data)                 # obj["asof"|"date"] 와 기존 파일 비교
    write_json(OUT, cur, key="date")                                    # 비교 키 지정 (derivs: asof 는 실행 시각, date 가 데이터일)
    write_text(REPORT_DIR / "latest_US.md", md, asof="2026-10-16")      # 텍스트: 기존 파일 첫 줄들의 YYYY-MM-DD 와 비교
    if not allow(d / "_index.json", new_asof): return                   # 폴더 통째(상세 2,000파일)는 색인 1개로 판정

규칙
- 날짜 비교는 **일 단위**(앞 10자 YYYY-MM-DD). 같은 날은 허용(장중→마감 갱신), 새 값이 더 과거면 차단.
- 차단 시: 쓰지 않음 + WARNING 로그 + reports/freshness.json 의 `regress_blocked` 에 기록(화면 배지·텔레그램이 읽음).
- 기존 파일이 없거나 날짜를 못 읽으면 허용(신규 파일). 새 값에 날짜가 없으면 허용(비교 불가 — 로그만).
- 의도적 과거 재생성(백필)은 환경변수 `SCREENER_ALLOW_REGRESS=1` 로만 우회.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
_D = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")
KEEP = 40   # regress_blocked 최근 기록 수


def day(v) -> str | None:
    """'2026-10-16', '2026-10-16 19:44', '20261016', date → '2026-10-16'. 못 읽으면 None."""
    if v is None:
        return None
    m = _D.search(str(v))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _get(obj, key: str):
    cur = obj
    for k in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def json_day(obj, key: str | None = None) -> str | None:
    if key:
        return day(_get(obj, key))
    for k in ("asof", "date"):
        if isinstance(obj, dict) and obj.get(k) is not None:
            return day(obj[k])
    return None


def text_day(text: str, head_lines: int = 3) -> str | None:
    return day("\n".join(text.splitlines()[:head_lines]))


def existing_day(path: Path, key: str | None = None) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None
    if path.suffix == ".json":
        try:
            return json_day(json.loads(raw), key)
        except Exception:  # noqa: BLE001
            return None
    return text_day(raw)


def _report_dir() -> Path:
    from .config import REPORT_DIR
    return REPORT_DIR


def record_block(path: Path, existing: str, new: str) -> None:
    """reports/freshness.json 의 regress_blocked 에 1줄 추가 (같은 파일·같은 날짜 쌍은 1회)."""
    fp = _report_dir() / "freshness.json"
    try:
        cur = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}
    except Exception:  # noqa: BLE001
        cur = {}
    try:
        rel = str(Path(path).resolve().relative_to(_report_dir().resolve().parent))
    except Exception:  # noqa: BLE001
        rel = str(path)
    rows = cur.get("regress_blocked") or []
    item = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "path": rel, "existing": existing, "new": new,
            "mode": os.environ.get("SCREENER_MODE") or ""}
    rows = [r for r in rows if not (r.get("path") == rel and r.get("new") == new and r.get("existing") == existing)] + [item]
    cur["regress_blocked"] = rows[-KEEP:]
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")


def record_stale(path: str, what: str, want, got) -> None:
    """조용한 대체 금지: 목표 날짜를 못 얻어 이전 값을 쓴 경우 reports/freshness.json 의 `stale` 에 기록 (화면 배지·알림이 읽음)."""
    fp = _report_dir() / "freshness.json"
    try:
        cur = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}
    except Exception:  # noqa: BLE001
        cur = {}
    rows = cur.get("stale") or []
    item = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "path": str(path), "what": what,
            "want": None if want is None else str(want), "got": None if got is None else str(got),
            "mode": os.environ.get("SCREENER_MODE") or ""}
    rows = [r for r in rows if not (r.get("path") == item["path"] and r.get("what") == what and r.get("got") == item["got"])] + [item]
    cur["stale"] = rows[-KEEP:]
    log.warning("stale 기록: %s %s (목표 %s · 사용 %s)", path, what, want, got)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")


def allow(path: Path, new_value, key: str | None = None) -> bool:
    """path 의 기존 날짜보다 new_value 가 과거가 아니면 True. 과거면 기록하고 False."""
    new = day(new_value)
    if new is None:
        log.info("asof 가드: %s 새 값에 날짜 없음 — 비교 생략", path)
        return True
    old = existing_day(Path(path), key)
    if old is None or new >= old:
        return True
    if os.environ.get("SCREENER_ALLOW_REGRESS") == "1":
        log.warning("asof 가드 우회(SCREENER_ALLOW_REGRESS=1): %s %s → %s", path, old, new)
        return True
    log.warning("⛔ asof 역행 차단: %s 기존 %s → 새 %s (쓰지 않음)", path, old, new)
    try:
        record_block(Path(path), old, new)
    except Exception as e:  # noqa: BLE001
        log.warning("역행 기록 실패: %s", e)
    return False


def write_json(path: Path, obj, *, key: str | None = None, **dumps_kw) -> bool:
    """json.dumps(obj) 를 path 에 쓰되 asof 역행이면 쓰지 않는다. 쓴 경우 True."""
    path = Path(path)
    if not allow(path, json_day(obj, key), key):
        return False
    dumps_kw.setdefault("ensure_ascii", False)
    path.write_text(json.dumps(obj, **dumps_kw), encoding="utf-8")
    return True


def write_text(path: Path, text: str, *, asof=None) -> bool:
    """텍스트 산출물(md). asof 를 안 주면 text 머리 3줄의 첫 날짜로 비교."""
    path = Path(path)
    if not allow(path, asof if asof is not None else text_day(text)):
        return False
    path.write_text(text, encoding="utf-8")
    return True
