"""tests/conftest.py 외부 소켓 차단 기본값 (감사 D3) — 로컬=CI 조건."""
import socket

import pytest


def test_external_dns_blocked():
    with pytest.raises(RuntimeError, match="외부 네트워크 차단"):
        socket.getaddrinfo("example.org", 443)


def test_external_connect_blocked():
    s = socket.socket()
    try:
        with pytest.raises(RuntimeError, match="외부 네트워크 차단"):
            s.connect(("93.184.216.34", 443))
    finally:
        s.close()


def test_loopback_allowed():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    c = socket.socket()
    c.connect(srv.getsockname())
    c.close()
    srv.close()


@pytest.mark.net
def test_net_marker_lifts_block():
    assert socket.getaddrinfo("localhost", 80)
    assert socket.socket.connect.__name__ == "connect" and "차단" not in (socket.socket.connect.__doc__ or "")
    # 마커가 있으면 패치가 없다 = 모듈 원본 함수
    assert socket.getaddrinfo.__module__ in ("socket", "_socket")
