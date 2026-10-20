"""토스증권 Open API — **시세 전용** 클라이언트 (파일럿, 2026-10-20 겸이 결정).

왜 이렇게 좁게 만드나:
- 토스 Open API 는 스코프 구분이 없다(스펙 `scopes: {}`). 키가 새면 그 키로 **주문도 가능**하다.
  허용 IP 등록제가 1차 방어이고, 이 모듈은 2차 방어 — 코드 경로에서 주문·계좌 호출을 **요청 전에** 막는다.
- 매매는 미래에셋에서 한다. 토스 계좌·주문 기능은 쓰지 않는다.

지키는 것 (테스트: tests/test_toss_md.py):
1. 메서드는 GET 만. 예외는 토큰 발급 `POST /oauth2/token` 하나.
2. 경로는 화이트리스트(ALLOWED)에 맞아야 하고, 금지어(FORBIDDEN_SEGMENTS: orders·accounts·holdings …)가
   경로 어디에든 있으면 거부. `..`·`//`·`%`·`?`·`#`·절대 URL 도 거부.
3. 헤더 `X-Tossinvest-Account`(대소문자 무관)가 있으면 거부.
4. 키는 환경변수(TOSS_MD_CLIENT_ID/TOSS_MD_CLIENT_SECRET) 또는 ~/.config/toss_md/env 에서만.
   파일은 권한 600 이 아니면(그룹·기타 권한 있으면) 거부, 저장소 안에 있으면 거부.
5. 응답 원문·토큰·키는 로그에도 예외 메시지에도 넣지 않는다. 에러는 HTTP 상태 + 응답의 code 필드만.
6. 토큰은 24시간 — 파일 캐시(~/.config/toss_md/token.json, 600)로 재사용하고 만료 5분 전이면 재발급.
   토스는 클라이언트당 유효 토큰 1개(재발급 시 이전 토큰 즉시 무효) → **수집 주체는 노트북 1대뿐**.
7. 429 는 Retry-After(초) 를 지킨다(최대 RETRY_MAX 회, 1회 대기 상한 RETRY_SLEEP_CAP 초).

REST 기본 주소는 OpenAPI 원문 servers.url(https://openapi.tossinvest.com) 기준. 바뀌면 env 의 TOSS_MD_BASE_URL 로 덮는다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

log = logging.getLogger("toss_md")

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://openapi.tossinvest.com"  # OpenAPI servers.url
CONFIG_DIR = Path(os.environ.get("TOSS_MD_CONFIG_DIR", Path.home() / ".config" / "toss_md"))
TOKEN_PATH = "/oauth2/token"
TOKEN_MARGIN_SEC = 300          # 만료 5분 전이면 새로 받는다
TOKEN_DEFAULT_TTL = 24 * 3600   # 응답에 expires_in 이 없으면 24h 로 본다(스펙: 24h, refresh 없음)
RETRY_MAX = 3                   # 429 재시도 횟수
RETRY_SLEEP_CAP = 60.0          # Retry-After 가 이보다 길면 이 값까지만 기다리고 실패로 끝낸다
TIMEOUT = 15.0

ACCOUNT_HEADER = "x-tossinvest-account"

# 경로 어디에든 이 조각이 있으면 거부 (주문·계좌 계열 — 스펙 '계좌 필요' 절 전부)
FORBIDDEN_SEGMENTS = (
    "orders", "conditional-orders", "accounts", "holdings",
    "buying-power", "sellable-quantity", "commissions",
)

_SYM = r"[A-Za-z0-9._\-]+"
# 시세 전용 화이트리스트 (/api/v1/ 아래). 정규식은 경로 전체와 일치해야 한다.
ALLOWED = tuple(re.compile(p) for p in (
    r"/api/v1/prices",
    r"/api/v1/orderbook",
    r"/api/v1/trades",
    r"/api/v1/price-limits",
    r"/api/v1/candles",
    r"/api/v1/stocks",
    r"/api/v1/stocks/all",
    rf"/api/v1/stocks/{_SYM}/(?:warnings|investor-trading|program-trades|short-selling|credit-trades|securities-lending)",
    r"/api/v1/exchange-rate",
    r"/api/v1/market-calendar/(?:KR|US)",
    r"/api/v1/rankings",
    rf"/api/v1/sectors(?:/{_SYM})*",
    rf"/api/v1/market-indicators(?:/{_SYM})+",
))


class TossMDError(RuntimeError):
    """API 오류. 메시지엔 상태·code 만 — 응답 원문은 절대 담지 않는다."""

    def __init__(self, status: int | None, code: str | None, what: str = ""):
        self.status, self.code = status, code
        super().__init__(f"toss_md {what} 실패: status={status} code={code}")


class ForbiddenRequest(ValueError):
    """시세 전용 정책 위반 — 네트워크로 나가기 전에 던진다."""


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    body: bytes


# Transport = (method, url, headers, data) -> Resp. 기본은 requests, 테스트·dry-run 은 가짜를 넣는다.
Transport = Callable[[str, str, dict[str, str], bytes | None], Resp]


def _requests_transport(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Resp:
    import requests  # 지연 import — 테스트·dry-run 은 requests 없이 돈다

    r = requests.request(method, url, headers=headers, data=data, timeout=TIMEOUT, allow_redirects=False)
    return Resp(r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.content)


# ── 정책 검사 ───────────────────────────────────────────────────────────
def check_request(method: str, path: str, headers: dict[str, str] | None = None) -> None:
    """정책 위반이면 ForbiddenRequest. 통과하면 None. (네트워크 전 단계)"""
    m = (method or "").upper()
    if not isinstance(path, str) or not path.startswith("/") or "://" in path:
        raise ForbiddenRequest("경로는 '/'로 시작하는 상대 경로만")
    if any(ch in path for ch in ("?", "#", "%", "\\", " ")) or ".." in path or "//" in path:
        raise ForbiddenRequest("경로에 허용되지 않는 문자")
    low = path.lower()
    for k in (headers or {}):
        if k.strip().lower() == ACCOUNT_HEADER:
            raise ForbiddenRequest("계좌 헤더 금지(시세 전용)")
    segs = [s for s in low.split("/") if s]
    for bad in FORBIDDEN_SEGMENTS:
        if any(bad in s for s in segs):
            raise ForbiddenRequest(f"금지 경로(주문·계좌): {bad}")
    if path == TOKEN_PATH:
        if m != "POST":
            raise ForbiddenRequest("토큰 경로는 POST 만")
        return
    if m != "GET":
        raise ForbiddenRequest("시세 전용: GET 만 허용")
    if not any(p.fullmatch(path) for p in ALLOWED):
        raise ForbiddenRequest("화이트리스트 밖 경로")


# ── 키·설정 읽기 ─────────────────────────────────────────────────────────
def _inside_repo(p: Path) -> bool:
    try:
        p.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def check_private_file(p: Path) -> None:
    """키 파일 검사: 저장소 밖 + (POSIX) 그룹·기타 권한 없음. 위반이면 PermissionError."""
    if _inside_repo(p):
        raise PermissionError("키 파일이 저장소 안에 있음 — 저장소 밖(~/.config/toss_md/env)으로 옮길 것")
    if os.name == "nt":
        wide = windows_wide_principals(p)
        if wide:
            raise PermissionError(f"키 파일 권한이 넓음({', '.join(wide)}) — icacls 로 본인만 남길 것(설정 가이드 ③)")
    elif os.name == "posix":
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & 0o077:
            raise PermissionError(f"키 파일 권한이 넓음({oct(mode)}) — chmod 600 필요")


# Windows: 본인 외에 읽을 수 있는 넓은 그룹 (icacls 출력에서 찾는다, 영문·한글 표기 모두)
WIDE_PRINCIPALS = ("Everyone", "BUILTIN\\Users", "Authenticated Users", "NT AUTHORITY\\Authenticated Users",
                   "모든 사용자", "BUILTIN\\사용자", "Guests")


def _icacls(args: list[str]) -> str:
    import subprocess

    r = subprocess.run(["icacls", *args], capture_output=True, text=True, timeout=15)
    return r.stdout or ""


def windows_wide_principals(p: Path, runner: Callable[[list[str]], str] | None = None) -> list[str]:
    """Windows 키 파일 ACL 에 넓은 그룹이 있으면 그 이름들. (POSIX chmod 600 에 해당하는 검사)"""
    out = (runner or _icacls)([str(p)])
    if not out.strip():
        return ["icacls 출력 없음(검사 불가)"]
    return [w for w in WIDE_PRINCIPALS if w.lower() in out.lower()]


def restrict_windows(p: Path, runner: Callable[[list[str]], str] | None = None) -> None:
    """Windows: 상속 끊고 현재 사용자만 전체 권한 (토큰 캐시 파일에 사용)."""
    user = os.environ.get("USERNAME", "")
    if user:
        (runner or _icacls)([str(p), "/inheritance:r", "/grant:r", f"{user}:F"])


def _parse_env(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_config(env_path: Path | None = None) -> dict[str, str]:
    """client_id·client_secret·base_url. 환경변수 우선, 없으면 env 파일(권한 검사)."""
    cfg = {"client_id": os.environ.get("TOSS_MD_CLIENT_ID", ""),
           "client_secret": os.environ.get("TOSS_MD_CLIENT_SECRET", ""),
           "base_url": os.environ.get("TOSS_MD_BASE_URL", "")}
    p = env_path or (CONFIG_DIR / "env")
    if (not cfg["client_id"] or not cfg["client_secret"]) and p.exists():
        check_private_file(p)
        f = _parse_env(p.read_text(encoding="utf-8"))
        cfg["client_id"] = cfg["client_id"] or f.get("TOSS_MD_CLIENT_ID", "")
        cfg["client_secret"] = cfg["client_secret"] or f.get("TOSS_MD_CLIENT_SECRET", "")
        cfg["base_url"] = cfg["base_url"] or f.get("TOSS_MD_BASE_URL", "")
    cfg["base_url"] = (cfg["base_url"] or DEFAULT_BASE_URL).rstrip("/")
    if not cfg["base_url"].startswith("https://"):
        raise ValueError("TOSS_MD_BASE_URL 은 https:// 만")
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise RuntimeError("키 없음: 환경변수 또는 ~/.config/toss_md/env (docs/toss_md_laptop_setup.md ③)")
    return cfg


def _write_private(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    if os.name == "posix":
        os.chmod(p, 0o600)
    elif os.name == "nt":
        restrict_windows(p)


def _err_code(body: bytes) -> str | None:
    """응답에서 code 필드만 꺼낸다(원문은 버린다)."""
    try:
        j = json.loads(body.decode("utf-8"))
    except Exception:
        return None
    if isinstance(j, dict):
        for k in ("code", "error", "errorCode"):
            v = j.get(k)
            if isinstance(v, (str, int)):
                return str(v)[:64]
            if isinstance(v, dict) and isinstance(v.get("code"), (str, int)):
                return str(v["code"])[:64]
    return None


def _retry_after(h: dict[str, str]) -> float:
    v = (h or {}).get("retry-after", "")
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return 1.0  # HTTP-date 형식 등은 1초로 보수 처리


# 레이트리밋 그룹 (OpenAPI 원문 v1.2.24, 10/21 PB: X-RateLimit-Limit/Remaining/Reset 은 그룹별).
# MARKET_INDICATOR·MARKET_INDICATOR_CHART·MARKET_INFO 는 원문 이름, 경로→그룹 대응 중 investor-trading·stocks 는 [추정 — 첫 실데이터 Remaining 이 같이 줄면 같은 그룹].
def rate_group(path: str) -> str:
    if path == "/api/v1/market-indicators/prices":
        return "MARKET_INDICATOR"
    if path.startswith("/api/v1/market-indicators/") and path.endswith("/candles"):
        return "MARKET_INDICATOR_CHART"
    if path.startswith("/api/v1/market-indicators/"):
        return "MARKET_INDICATOR"
    if path.startswith(("/api/v1/exchange-rate", "/api/v1/market-calendar", "/api/v1/stocks")):
        return "MARKET_INFO"
    # 10/21 us·sectors 그룹 — 이름은 heartbeat 표시용 [추정 — 첫 실행 Remaining 이 같이 줄면 같은 그룹]
    if path == "/api/v1/candles":
        return "CHART"
    if path.startswith("/api/v1/rankings") or path == "/api/v1/sectors/rankings":
        return "RANKING"
    if path.startswith("/api/v1/sectors"):
        return "SECTOR"
    if path.startswith(("/api/v1/prices", "/api/v1/orderbook", "/api/v1/trades", "/api/v1/price-limits")):
        return "PRICE"
    return "OTHER"


def _rate_headers(h: dict[str, str]) -> dict | None:
    h = {k.lower(): v for k, v in (h or {}).items()}
    out = {}
    for k in ("limit", "remaining", "reset"):
        v = h.get(f"x-ratelimit-{k}")
        if v is not None:
            try:
                out[k] = int(float(v))
            except (TypeError, ValueError):
                out[k] = str(v)[:32]
    return out or None


# ── 클라이언트 ───────────────────────────────────────────────────────────
class TossMD:
    def __init__(self, cfg: dict[str, str] | None = None, transport: Transport | None = None,
                 token_cache: Path | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time):
        self._cfg = cfg if cfg is not None else load_config()
        self._t = transport or _requests_transport
        self._cache = token_cache if token_cache is not None else CONFIG_DIR / "token.json"
        self._sleep, self._clock = sleep, clock
        self._token: str | None = None
        self._exp: float = 0.0
        self.rate_limits: dict[str, dict] = {}   # 그룹 → 마지막 {limit, remaining, reset} (heartbeat 기록용, 값은 숫자뿐)

    def __repr__(self) -> str:  # 키·토큰이 repr 로 새지 않게
        return "TossMD(<redacted>)"

    # 저수준: 모든 요청은 여기를 지난다
    def _send(self, method: str, path: str, headers: dict[str, str], data: bytes | None = None,
              query: str = "") -> Resp:
        check_request(method, path, headers)
        url = self._cfg["base_url"] + path + query
        for attempt in range(RETRY_MAX + 1):
            r = self._t(method, url, headers, data)
            rl = _rate_headers(r.headers)
            if rl and path != TOKEN_PATH:
                self.rate_limits[rate_group(path)] = rl
            if r.status != 429:
                return r
            wait = _retry_after(r.headers)
            if attempt == RETRY_MAX or wait > RETRY_SLEEP_CAP:
                break
            log.warning("toss_md 429 path=%s retry_after=%.0fs", path, wait)
            self._sleep(wait)
        raise TossMDError(429, _err_code(r.body), "rate-limit")

    # 토큰
    def _load_cached(self) -> bool:
        try:
            if not self._cache.exists():
                return False
            check_private_file(self._cache)
            j = json.loads(self._cache.read_text(encoding="utf-8"))
            if j.get("client_id_tail") != self._cfg["client_id"][-4:]:
                return False
            self._token, self._exp = j["access_token"], float(j["expires_at"])
            return True
        except Exception:
            return False

    def _issue(self) -> None:
        body = urlencode({"grant_type": "client_credentials", "client_id": self._cfg["client_id"],
                          "client_secret": self._cfg["client_secret"]}).encode()
        r = self._send("POST", TOKEN_PATH, {"Content-Type": "application/x-www-form-urlencoded",
                                            "Accept": "application/json"}, body)
        if r.status != 200:
            raise TossMDError(r.status, _err_code(r.body), "토큰 발급")
        try:
            j = json.loads(r.body.decode("utf-8"))
            tok = j["access_token"]
            ttl = float(j.get("expires_in") or TOKEN_DEFAULT_TTL)
        except Exception:
            raise TossMDError(r.status, "bad_token_payload", "토큰 발급") from None
        self._token, self._exp = tok, self._clock() + ttl
        try:
            _write_private(self._cache, json.dumps({"access_token": tok, "expires_at": self._exp,
                                                    "client_id_tail": self._cfg["client_id"][-4:]}))
        except OSError:
            log.warning("toss_md 토큰 캐시 저장 실패(메모리로만 사용)")
        log.info("toss_md 토큰 발급(만료 %.0f시간 뒤)", ttl / 3600)

    def token(self) -> str:
        now = self._clock()
        if self._token and now < self._exp - TOKEN_MARGIN_SEC:
            return self._token
        if self._load_cached() and now < self._exp - TOKEN_MARGIN_SEC:
            return self._token  # type: ignore[return-value]
        self._issue()
        return self._token  # type: ignore[return-value]

    # 공개 API: GET 하나뿐
    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        check_request("GET", path, {})  # 토큰 발급 전에 먼저 막는다
        q = ("?" + urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)) if params else ""
        for again in (False, True):
            h = {"Authorization": f"Bearer {self.token()}", "Accept": "application/json"}
            r = self._send("GET", path, h, None, q)
            if r.status == 401 and not again:  # 다른 곳에서 재발급돼 무효가 된 경우 1회만 재발급
                log.warning("toss_md 401 — 토큰 재발급 1회 (다른 수집 주체가 있는지 확인)")
                self._token, self._exp = None, 0.0
                try:
                    self._cache.unlink()
                except OSError:
                    pass
                continue
            break
        if r.status != 200:
            raise TossMDError(r.status, _err_code(r.body), f"GET {path}")
        try:
            return json.loads(r.body.decode("utf-8"))
        except Exception:
            raise TossMDError(r.status, "bad_json", f"GET {path}") from None
