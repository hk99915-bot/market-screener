"""pytest 공통 설정 — 저장소 루트를 import 경로에 올려 `screener` 패키지를 바로 쓴다 (네트워크 없이 도는 순수 로직만 검사)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_health_write(tmp_path, monkeypatch):
    """alerts.secret_health 가 테스트 중 실제 reports/freshness.json 에 '알림 비활성' 을 쓰지 않게 (시크릿 없는 테스트 환경)."""
    from screener import alerts
    monkeypatch.setattr(alerts, "HEALTH_FILE", tmp_path / "_health_freshness.json")
