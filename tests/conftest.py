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


# 외부 소켓 차단 기본값 (감사 D3, 10/21 CI 빨강: 로컬은 네트워크가 되고 CI 는 막혀 "로컬 통과·CI 실패" 가 났다 — 네이버 API 호출).
# 로컬 = CI 조건: 루프백·유닉스 소켓만 허용, 그 밖의 DNS 조회·connect 는 즉시 실패. 일부러 외부를 쓰는 테스트는
# `@pytest.mark.net` 또는 환경변수 TESTS_ALLOW_NET=1 (예: 수동 재현). monkeypatch 가 아니라 모듈 교체라 테스트 안의 mock 은 그대로 동작.
import socket as _socket  # noqa: E402

_LOCAL = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}
_real_connect = _socket.socket.connect
_real_gai = _socket.getaddrinfo


def _is_local(host) -> bool:
    return host in _LOCAL or (isinstance(host, str) and host.startswith("127."))


@pytest.fixture(autouse=True)
def _block_external_sockets(request, monkeypatch):
    if os.environ.get("TESTS_ALLOW_NET") == "1" or request.node.get_closest_marker("net"):
        return

    def connect(self, address):
        if self.family == getattr(_socket, "AF_UNIX", None) or (isinstance(address, tuple) and _is_local(address[0])):
            return _real_connect(self, address)
        raise RuntimeError(f"외부 네트워크 차단(tests/conftest.py): connect {address!r} — 테스트에서 mock 하거나 @pytest.mark.net")

    def gai(host, *a, **k):
        if _is_local(host):
            return _real_gai(host, *a, **k)
        raise RuntimeError(f"외부 네트워크 차단(tests/conftest.py): DNS {host!r} — 테스트에서 mock 하거나 @pytest.mark.net")

    monkeypatch.setattr(_socket.socket, "connect", connect)
    monkeypatch.setattr(_socket, "getaddrinfo", gai)


def pytest_configure(config):
    config.addinivalue_line("markers", "net: 일부러 외부 네트워크를 쓰는 테스트(소켓 차단 해제)")
