"""감사 10/24 M3(req-dev-218c8448): gas_deploy.yml 이 예약 실행기 파일(Scheduler.gs·TelegramHook.gs)을 웹앱 프로젝트에 섞어 넣지 않는지."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "gas_deploy.yml"


def _run():
    steps = yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["deploy"]["steps"]
    return next(s for s in steps if "clasp" in s.get("name", ""))["run"]


def test_no_glob_copy_of_all_gs():
    assert not re.search(r"apps-script/?\*\.gs", _run())      # 전엔 cp apps-script/*.gs → 웹앱에 doPost·tick 혼입


def test_web_gets_code_only_unless_same_project():
    run = _run()
    assert 'WEB_FILES="Code.gs"' in run and 'SCHED_FILES="Scheduler.gs TelegramHook.gs"' in run
    assert '[ "$GAS_SCHED_SCRIPT_ID" = "$GAS_SCRIPT_ID" ] && WEB_FILES=' in run
    web = run.index('push_to "$GAS_SCRIPT_ID"'); dep = run.index("clasp deploy"); sched = run.index('push_to "$GAS_SCHED_SCRIPT_ID"')
    assert web < dep < sched                                      # 웹앱만 배포(새 버전), 예약 실행기는 push 만
    assert "clasp deploy" not in run[sched:]


def test_every_listed_gs_exists():
    run = _run()
    for f in re.findall(r"[A-Za-z]+\.gs", run):
        assert (ROOT / "apps-script" / f).exists(), f
