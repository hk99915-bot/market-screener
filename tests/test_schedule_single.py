"""결정 C 예약 일원화 — 산출물 하나 = 실행 주체 하나 (docs/schedule_table.md, scripts/slot_guard.py).

워크플로 YAML + apps-script/Scheduler.gs 를 파싱해
- 이중 실행 슬롯(GAS + 가드 없는 cron) 0,
- 수동 dispatch 기본 읽기 전용(commit 입력·조건),
- GAS 가 보내는 inputs 가 워크플로에 정의돼 있음(아니면 GitHub 가 422 로 거부),
- 월요일 08:50 장전 알림 실행 주체 정확히 1
을 확인한다.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import slot_guard as g  # noqa: E402

KST = timezone(timedelta(hours=9))
WFS = g.load_workflows()
GAS = g.parse_gas()


def kst(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=KST).astimezone(timezone.utc)


def test_workflows_valid_yaml():
    for name, text in WFS.items():
        d = g._yaml(text)
        assert "jobs" in d and "on" in d, name


def test_gas_parse_nonempty_and_comment_skipped():
    assert len(GAS["slots"]) >= 15
    assert not any(s["wf"] == "briefing.yml" and s["inputs"].get("mode") == "valuation" for s in GAS["slots"])  # 주석 줄


def test_double_executor_slots_zero():
    res = g.analyze()
    assert res["double_slots"] == [], f"이중 실행 슬롯: {res['double_slots']}"


def test_detector_catches_unguarded_cron():
    """가드를 빼면 탐지기가 이중 슬롯을 잡아야 한다(탐지기 자체 검증)."""
    wfs = dict(WFS)
    wfs["briefing.yml"] = wfs["briefing.yml"].replace("scripts/slot_guard.py --wf briefing.yml", "true")
    res = g.analyze(GAS, wfs)
    assert ("briefing.yml", "premarket_kr", "08:50") in res["double_slots"]


# 다른 데스크가 잠금 중이라 아직 못 고친 워크플로 — 고쳐지면 아래 두 번째 테스트가 목록에서 빼라고 실패한다.
# accum.yml: 퀀트 잠금(accum-scan, 10/17 13:52) — backfill 수동 실행은 commit=true 로 바꿔야 함. 보드 schedule-single-accum.
PENDING = {"accum.yml"}


def test_manual_dispatch_read_only_by_default():
    bad = [v for v in g.manual_gate_violations() if v.split(":")[0] not in PENDING]
    assert bad == [], bad


def test_pending_list_is_honest():
    still = {v.split(":")[0] for v in g.manual_gate_violations()}
    fixed = PENDING - still
    assert not fixed, f"{fixed} 는 이제 commit 조건이 있음 → PENDING 에서 빼기"


def test_gas_inputs_defined_in_workflow_and_commit_true():
    for s in GAS["slots"]:
        assert s["wf"] in WFS, f"Scheduler.gs 가 없는 워크플로를 부름: {s['wf']}"
        on = g._yaml(WFS[s["wf"]])["on"]
        inputs = set(((on.get("workflow_dispatch") or {}).get("inputs") or {}))
        extra = set(s["inputs"]) - inputs
        assert not extra, f"{s['time']} {s['wf']}: 워크플로에 없는 입력 {extra} → GitHub 422"
        assert s["inputs"].get("commit") == "true", f"{s['time']} {s['wf']}: commit 'true' 없음 → 읽기 전용으로 돌아 산출물 미저장"
        assert g.guarded(s["wf"], WFS[s["wf"]]), f"{s['wf']}: slot_guard 단계 없음"


def test_run_name_carries_key():
    """가드는 display_title 의 '[키]' 와 'commit=' 로 GAS 실행을 찾는다."""
    for wf in {s["wf"] for s in GAS["slots"]}:
        d = g._yaml(WFS[wf])
        rn = d.get("run-name", "")
        assert "commit=" in rn, wf
        if wf in g.KEY_FIELD:
            assert "[{0}]" in rn and f"inputs.{g.KEY_FIELD[wf]}" in rn, wf


def test_gas_window_shorter_than_fallback_wait():
    assert GAS["window_min"] is not None
    assert GAS["window_min"] + 2 <= g.FALLBACK_WAIT_MIN


def test_every_gas_slot_has_cron_fallback_mapping():
    """GAS 슬롯과 같은 시각 cron 이 있으면 가드가 그 cron 을 대기로 인식해야 한다 (요일 변환 포함)."""
    for wf, text in WFS.items():
        for item in g._yaml(text)["on"].get("schedule") or []:
            cron = item["cron"]
            key = g.cron_key(wf, text, cron)
            for kmin, days in g.cron_kst(cron):
                for d in days:
                    s = g.find_gas_slot(GAS, wf, key, kmin, d)
                    if not s:
                        continue
                    # d 요일의 해당 KST 시각 → fallback_plan 이 같은 슬롯을 찾아야 함
                    base = datetime(2026, 10, 18, tzinfo=KST)   # 일요일
                    t = base + timedelta(days=d, minutes=kmin + 1)
                    plan = g.fallback_plan(GAS, wf, key, cron, t.astimezone(timezone.utc))
                    assert plan and plan["slot"] is s, (wf, cron, d)


def test_briefing_case_covers_all_crons():
    text = WFS["briefing.yml"]
    modes = g.briefing_cron_modes(text)
    for item in g._yaml(text)["on"]["schedule"]:
        assert item["cron"] in modes, f"briefing cron {item['cron']} 이 모드 case 문에 없음"


# ── 월요일 08:50 장전 알림: 실행 주체 정확히 1 ─────────────────────────
def test_monday_premarket_single_executor():
    rows = [r for r in g.analyze()["rows"] if r["wf"] == "briefing.yml" and r["key"] == "premarket_kr"
            and r["time"] == "08:50" and r["dow"] == 1]
    assert len(rows) == 1
    ex = rows[0]["executors"]
    assert ex.count("GAS") == 1 and [e for e in ex if not e.endswith("(대기)")] == ["GAS"], ex


def _run(title, at_utc, event="workflow_dispatch", conclusion=None):
    return {"id": 1, "event": event, "display_title": title, "conclusion": conclusion,
            "created_at": at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_monday_cron_skips_when_gas_ran():
    now = kst(2026, 10, 19, 8, 50)   # 월 08:50 cron 정시 발화
    slept = []
    runs = [_run("briefing [premarket_kr] commit=true", kst(2026, 10, 19, 8, 51))]
    d = g.decide("briefing.yml", "premarket_kr", "schedule", "50 23 * * 0-4", "", now=now,
                 runs_fn=lambda wf, since: runs, sleep_fn=slept.append, gas=GAS)
    assert d["go"] is False and slept and abs(slept[0] - 12 * 60) < 1


def test_monday_cron_runs_when_gas_dead():
    now = kst(2026, 10, 19, 9, 5)    # GitHub 지연 15분, GAS 미실행
    d = g.decide("briefing.yml", "premarket_kr", "schedule", "50 23 * * 0-4", "", now=now,
                 runs_fn=lambda wf, since: [], sleep_fn=lambda s: None, gas=GAS)
    assert d == {"go": True, "commit": True, "reason": d["reason"]}


def test_cron_ignores_other_mode_and_read_only_dispatch():
    now = kst(2026, 10, 19, 9, 5)
    runs = [_run("briefing [detail_us] commit=true", kst(2026, 10, 19, 8, 52)),
            _run("briefing [premarket_kr] commit=false", kst(2026, 10, 19, 8, 53)),
            _run("briefing [premarket_kr] commit=true", kst(2026, 10, 19, 8, 54), conclusion="cancelled")]
    d = g.decide("briefing.yml", "premarket_kr", "schedule", "50 23 * * 0-4", "", now=now,
                 runs_fn=lambda wf, since: runs, sleep_fn=lambda s: None, gas=GAS)
    assert d["go"] is True


def test_api_failure_fails_open():
    def boom(wf, since):
        raise OSError("rate limit")
    d = g.decide("briefing.yml", "premarket_kr", "schedule", "50 23 * * 0-4", "", now=kst(2026, 10, 19, 9, 5),
                 runs_fn=boom, sleep_fn=lambda s: None, gas=GAS)
    assert d["go"] is True


def test_dispatch_commit_rules():
    # 새 GAS (commit=true) → 커밋
    assert g.decide("briefing.yml", "premarket_kr", "workflow_dispatch", "", "true", now=kst(2026, 10, 19, 8, 51), gas=GAS)["commit"]
    # 구버전 GAS (commit 입력 없음 = auto) 슬롯 시각 → 커밋 (붙여넣기 전 호환)
    assert g.decide("briefing.yml", "premarket_kr", "workflow_dispatch", "", "auto", now=kst(2026, 10, 19, 9, 2), gas=GAS)["commit"]
    # 10/17 사고 재현: 토 09:46 수동 detail_us → 읽기 전용
    assert not g.decide("briefing.yml", "detail_us", "workflow_dispatch", "", "auto", now=kst(2026, 10, 17, 9, 46), gas=GAS)["commit"]
    # 슬롯 모드라도 시각 밖 수동 → 읽기 전용
    assert not g.decide("briefing.yml", "screen_us", "workflow_dispatch", "", "", now=kst(2026, 10, 17, 14, 0), gas=GAS)["commit"]
    # 슬롯 요일이 아니면(일요일 08:50) 읽기 전용
    assert not g.decide("briefing.yml", "premarket_kr", "workflow_dispatch", "", "auto", now=kst(2026, 10, 18, 8, 51), gas=GAS)["commit"]
    # 명시 false 는 슬롯 시각이어도 읽기 전용
    assert not g.decide("briefing.yml", "premarket_kr", "workflow_dispatch", "", "false", now=kst(2026, 10, 19, 8, 51), gas=GAS)["commit"]


def test_non_gas_cron_runs_immediately():
    slept = []
    d = g.decide("briefing.yml", "valuation", "schedule", "10 22 * * 1-5", "", now=kst(2026, 10, 20, 7, 10),
                 runs_fn=lambda wf, since: pytest.fail("조회 불필요"), sleep_fn=slept.append, gas=GAS)
    assert d["go"] and d["commit"] and not slept


def test_us_slot_day_shift():
    """03:52 KST 화~토 = UTC 18:52 월~금 — 요일 변환이 맞아야 대기로 인식."""
    plan = g.fallback_plan(GAS, "briefing.yml", "intraday_us", "52 18 * * 1-5", kst(2026, 10, 17, 4, 0))   # 토 04:00
    assert plan and plan["slot"]["time"] == "03:52"
    assert g.fallback_plan(GAS, "briefing.yml", "intraday_us", "52 18 * * 1-5", kst(2026, 10, 19, 4, 0)) is None   # 월 04:00 (일 UTC 발화 없음)
