"""US 상세가 기대 거래일보다 과거(STALE)인지 판정 — briefing.yml 08:52 KST detail_us_retry 슬롯의 문지기 (req-dev-fc677ec8).

종료코드 0 = STALE(재시도 필요), 1 = 최신(건너뜀). 야후가 마감 뒤 몇 시간 늦게 당일 봉을 주는 날(10/21: 10/20 봉이 5.5h 뒤 공급)
06:52 screen_us 가 [STALE] 로 끝난 것을 15:30 장중 잠금과 무관한 아침 08:52 에 한 번 더 받아 본다.
재시도 실행 자체는 `--market US --no-send` 이고 main.asof_decision 이 게시본보다 과거면 쓰지 않는다(역행 불가).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def is_stale(now: datetime | None = None, index: Path | None = None) -> tuple[bool, str]:
    from screener import guard, tradecal
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    index = index or ROOT / "reports" / "detail" / "US" / "_index.json"
    exp = tradecal.expected_session("US", now).isoformat()
    try:
        have = guard.day(json.loads(index.read_text(encoding="utf-8")).get("asof"))
    except (OSError, ValueError):
        have = None
    if not have:
        return True, f"US 상세 기준일 읽기 실패 — 기대 {exp}, 재시도"
    if have < exp:
        return True, f"US 상세 기준일 {have} < 기대 {exp} — STALE, 재시도"
    return False, f"US 상세 기준일 {have} >= 기대 {exp} — 최신, 건너뜀"


if __name__ == "__main__":
    stale, why = is_stale()
    print(why)
    sys.exit(0 if stale else 1)
