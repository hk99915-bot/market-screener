"""pytest 공통 설정 — 저장소 루트를 import 경로에 올려 `screener` 패키지를 바로 쓴다 (네트워크 없이 도는 순수 로직만 검사)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# git 훅(pre-push → scripts/prepush_check.py → pytest) 안에서 돌면 GIT_DIR·GIT_INDEX_FILE 등 '저장소 위치' 변수가 상속돼
# 테스트가 tmp 에서 부르는 git(init --bare·commit·reset)이 **실제 저장소**를 건드린다. 10/21 01시 사고 3회:
# 메인 체크아웃 core.bare=true, 작업 브랜치에 author 't' 커밋('init'·'base 10/16') — test_toss_publish·test_freshness_guard.
# 테스트 프로세스 시작 시 위치 변수만 지운다(자격 증명·프록시용 GIT_CONFIG_* 는 그대로).
import os  # noqa: E402

for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR",
           "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX", "GIT_QUARANTINE_PATH"):
    os.environ.pop(_k, None)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_health_write(tmp_path, monkeypatch):
    """alerts.secret_health 가 테스트 중 실제 reports/freshness.json 에 '알림 비활성' 을 쓰지 않게 (시크릿 없는 테스트 환경)."""
    from screener import alerts
    monkeypatch.setattr(alerts, "HEALTH_FILE", tmp_path / "_health_freshness.json")
