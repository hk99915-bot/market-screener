"""asof 단조 가드 — 산출물을 '더 과거 날짜'로 덮어쓰지 않는다 (refactor_plan 결정 B 1단계, 보드 detail-us-regress).

사용
    from .guard import write_json, write_text, allow
    write_json(REPORT_DIR / "momentum_US.json", data)                 # obj["asof"|"date"] 와 기존 파일 비교
    write_json(OUT, cur, key="date")                                    # 비교 키 지정 (derivs: asof 는 실행 시각, date 가 데이터일)
    write_text(REPORT_DIR / "latest_US.md", md, asof="2026-10-16")      # 텍스트: 기존 파일 첫 줄들의 YYYY-MM-DD 와 비교
    if not allow(d / "_index.json", new_asof): return                   # 폴더 통째(상세 2,000파일)는 색인 1개로 판정

규칙
- 날짜 비교는 **일 단위**(앞 10자 YYYY-MM-DD). 같은 날은 허용(장중→마감 갱신), 새 값이 더 과거면 차단.
- 장중 산출물(live.json·dashboard_state 조각): 양쪽 값에 **시각**이 있으면 분 단위로 비교(같은 날 더 이른 시각 = 역행 차단,
  같은 시각·더 늦은 시각 = 허용). 시간대 표기(Z·+09:00)는 KST 로 바꿔 비교 — UTC 자정 근처 값이 '하루 전'으로 읽혀
  정상 장중 갱신이 막히던 일 단위 비교 문제(guard-rest, 10/17) 방지. 한쪽이라도 시각이 없으면 KST 날짜로 비교.
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


_T = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?")


def stamp(v) -> datetime | None:
    """'2026-10-17 09:47' (KST 가정) · '2026-10-17T00:47:00Z' · '…+09:00' → KST datetime. 시각이 없으면 None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=KST) if v.tzinfo is None else v.astimezone(KST)
    m = _T.search(str(v))
    d0 = _D.search(str(v))
    if not m or (d0 and d0.start() != m.start()):   # 첫 날짜에 시각이 붙은 경우만 (머리글 '… 2026-10-16 …\n생성 2026-10-17 09:47' 은 날짜 10-16)
        return None
    y, mo, d, h, mi, sec, tz = m.groups()
    try:
        t = datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec or 0))
        if tz:
            t = datetime.fromisoformat(f"{t.isoformat()}{'+00:00' if tz == 'Z' else tz if ':' in tz else tz[:3] + ':' + tz[3:]}")
            return t.astimezone(KST)
    except ValueError:
        return None
    return t.replace(tzinfo=KST)


def kst_day(v) -> str | None:
    """시각+시간대가 있으면 KST 날짜, 아니면 day()."""
    t = stamp(v)
    return t.strftime("%Y-%m-%d") if t else day(v)


def not_older(old, new) -> bool:
    """new 가 old 보다 과거가 아니면 True. 둘 다 시각이 있으면 분 단위, 아니면 KST 날짜 단위. 비교 불가(None)면 True."""
    to, tn = stamp(old), stamp(new)
    if to and tn:
        return tn.replace(second=0, microsecond=0) >= to.replace(second=0, microsecond=0)
    do, dn = kst_day(old), kst_day(new)
    return do is None or dn is None or dn >= do


def _get(obj, key: str):
    """점 경로. 리스트는 정수 조각으로 인덱스 ('series.KOSPI.-1.0' = KOSPI 끝 행 날짜)."""
    cur = obj
    for k in key.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(k)]
            except (ValueError, IndexError):
                return None
            continue
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def json_value(obj, key: str | None = None):
    """비교에 쓸 원값 (시각 포함 가능). key 없으면 asof → date 순."""
    if key:
        return _get(obj, key)
    for k in ("asof", "date"):
        if isinstance(obj, dict) and obj.get(k) is not None:
            return obj[k]
    return None


def json_day(obj, key: str | None = None) -> str | None:
    return day(json_value(obj, key))


def text_day(text: str, head_lines: int = 3) -> str | None:
    return day("\n".join(text.splitlines()[:head_lines]))


def existing_value(path: Path, key: str | None = None):
    """기존 파일의 비교 원값 (json: key 값, 텍스트: 머리 3줄). 없거나 못 읽으면 None."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None
    if path.suffix == ".json":
        try:
            return json_value(json.loads(raw), key)
        except Exception:  # noqa: BLE001
            return None
    return text_day(raw)   # 텍스트는 일 단위 그대로 (머리 3줄의 첫 날짜)


def existing_day(path: Path, key: str | None = None) -> str | None:
    return day(existing_value(path, key))


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


def record_fill(path: str, what: str, info: dict) -> None:
    """목표 날짜를 다른 출처로 채운 경우(조용한 대체 금지 — stale 대신 출처 기록) reports/freshness.json 의 `filled` 에 남김.
    info = {src, date, filled, total, pct, label} (screener.data.fill_last_day)."""
    fp = _report_dir() / "freshness.json"
    try:
        cur = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}
    except Exception:  # noqa: BLE001
        cur = {}
    item = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "path": str(path), "what": what, **info}
    rows = [r for r in (cur.get("filled") or []) if not (r.get("path") == item["path"] and r.get("date") == item.get("date"))]
    cur["filled"] = (rows + [item])[-KEEP:]
    log.info("보충 기록: %s %s %s", path, what, info.get("label"))
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")


def _label(v) -> str | None:
    t = stamp(v)
    return t.strftime("%Y-%m-%d %H:%M") if t else day(v)


def allow(path: Path, new_value, key: str | None = None) -> bool:
    """path 의 기존 값보다 new_value 가 과거가 아니면 True. 과거면 기록하고 False. 시각이 양쪽에 있으면 분 단위(not_older)."""
    if day(new_value) is None:
        log.info("asof 가드: %s 새 값에 날짜 없음 — 비교 생략", path)
        return True
    old_v = existing_value(Path(path), key)
    if day(old_v) is None or not_older(old_v, new_value):
        return True
    old, new = _label(old_v), _label(new_value)
    if os.environ.get("SCREENER_ALLOW_REGRESS") == "1":
        log.warning("asof 가드 우회(SCREENER_ALLOW_REGRESS=1): %s %s → %s", path, old, new)
        return True
    log.warning("⛔ asof 역행 차단: %s 기존 %s → 새 %s (쓰지 않음)", path, old, new)
    try:
        record_block(Path(path), old, new)
    except Exception as e:  # noqa: BLE001
        log.warning("역행 기록 실패: %s", e)
    return False


def record_contract(path: Path, errs: list[str]) -> None:
    fp = _report_dir() / "freshness.json"
    try:
        cur = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}
    except Exception:  # noqa: BLE001
        cur = {}
    rows = (cur.get("contract_violation") or []) + [{"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "path": Path(path).name,
                                                       "errors": errs[:5], "mode": os.environ.get("SCREENER_MODE") or ""}]
    cur["contract_violation"] = rows[-KEEP:]
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")


def write_json(path: Path, obj, *, key: str | None = None, **dumps_kw) -> bool:
    """json.dumps(obj) 를 path 에 쓰되 ① 데이터 계약(screener/contracts.py) 위반 ② asof 역행이면 쓰지 않는다. 쓴 경우 True."""
    from . import contracts
    path = Path(path)
    errs = contracts.check(path, obj)
    if errs:
        log.warning("⛔ 데이터 계약 위반 — %s 쓰지 않음: %s", path, "; ".join(errs[:3]))
        try:
            record_contract(path, errs)
        except Exception as e:  # noqa: BLE001
            log.warning("계약 위반 기록 실패: %s", e)
        return False
    if not allow(path, json_value(obj, key), key):
        return False
    contracts.stamp(path, obj)
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
