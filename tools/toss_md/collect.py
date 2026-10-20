"""토스 시세 파일럿 수집기 — **겸이 노트북 전용** (수집 주체 1개, 공개 산출물 없음).

    python tools/toss_md/collect.py --group intraday           # 지수 1분·투자자별 매매대금·USDKRW
    python tools/toss_md/collect.py --group daily              # KR/US 휴장 달력 (+ --stocks-all 이면 종목 목록 일1회)
    python tools/toss_md/collect.py --group all --dry-run      # 네트워크 없이 픽스처로 전 과정 점검

출력: 저장소 **밖** ~/toss_md_data/YYYY-MM-DD/<이름>.json  {generated_at, asof, asof_src, endpoint, data}
      ~/toss_md_data/heartbeat.json  {last_success, last_attempt, last_error, ok, fail}
      dry-run 은 ~/toss_md_data/_dryrun/ 아래.
- 원시 수집분은 저장소 밖에만(출력 폴더가 저장소 안이면 거부). 공개는 --publish → tools/toss_md/publish.py 가 요약만
  toss-live 브랜치로 (10/20 겸이 약관 확인 '허용', 10/21 "지금부터 시작해").
- 응답 원문은 화면·로그에 찍지 않는다(파일에만 저장). 에러는 상태·code 만.
- 동시 실행 금지: ~/.config/toss_md/collector.lock (토큰 재발급 시 이전 토큰이 무효가 되므로).

경로·파라미터는 겸이가 10/20 채팅에 준 OpenAPI 3.1 원문(v1.2.24)과 PB가 대조해 맞춤(10/20 23:5x). 404/400 이면 이 표만 고친다.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screener import toss_md  # noqa: E402

try:
    KST = ZoneInfo("Asia/Seoul")
except Exception:  # Windows 는 시스템 tz DB 가 없어 tzdata 패키지 필요 — 없으면 고정 +09:00 (한국은 서머타임 없음)
    KST = timezone(timedelta(hours=9), "KST")
DATA_DIR = Path(os.environ.get("TOSS_MD_DATA_DIR", Path.home() / "toss_md_data"))
FIXTURES = Path(__file__).resolve().parent / "fixtures"
LOCK_STALE_SEC = 15 * 60

# (이름, 그룹, 경로, 파라미터) — 1단계 파일럿 대상
# 시장지표 캔들 timestamp = 봉 **시작** 시각(10/20 실측 KOSPI 마지막 봉 15:30:00 = 종가 단일가), 종목 캔들(/api/v1/candles) 1m 은 봉 **종료** 시각([t-1분, t)) — OpenAPI 원문 v1.2.24.
# 현재값은 가벼운 prices(MARKET_INDICATOR 그룹, 최대 200개, 국채는 % 수익률·일봉만) — 차트는 캔들. 국채 심볼 2·5·20·30Y 는 3Y·10Y 이름 꼴에서 [추정 — 첫 실행 응답으로 확인].
INDICATOR_SYMBOLS = ("KOSPI", "KOSDAQ", "KR_BOND_2Y", "KR_BOND_3Y", "KR_BOND_5Y", "KR_BOND_10Y", "KR_BOND_20Y", "KR_BOND_30Y")
PILOT: list[tuple[str, str, str, dict]] = [
    ("indicator_prices", "intraday", "/api/v1/market-indicators/prices", {"symbols": ",".join(INDICATOR_SYMBOLS)}),
    ("kospi_1m", "intraday", "/api/v1/market-indicators/KOSPI/candles", {"interval": "1m", "count": 200}),
    ("kosdaq_1m", "intraday", "/api/v1/market-indicators/KOSDAQ/candles", {"interval": "1m", "count": 200}),
    ("investor_value", "intraday", "/api/v1/market-indicators/KOSPI/investor-trading", {"interval": "1d", "count": 5}),
    ("investor_value_kq", "intraday", "/api/v1/market-indicators/KOSDAQ/investor-trading", {"interval": "1d", "count": 5}),
    ("usdkrw", "intraday", "/api/v1/exchange-rate", {"baseCurrency": "USD", "quoteCurrency": "KRW"}),
    ("calendar_kr", "daily", "/api/v1/market-calendar/KR", {}),
    ("calendar_us", "daily", "/api/v1/market-calendar/US", {}),
]
# /stocks/all 은 market 이 필수 파라미터(OpenAPI 원문) — 시장별 1회씩. 10/21 첫 실제 실행에서 market 없이 불러 실패(LastTaskResult 1).
STOCKS_ALL = [(f"stocks_all_{m.lower()}", "daily", "/api/v1/stocks/all", {"market": m})
              for m in ("KOSPI", "KOSDAQ", "KR_ETC", "NYSE", "NASDAQ", "AMEX", "US_ETC")]

log = logging.getLogger("toss_md.collect")

_TIME_KEYS = ("timestamp", "asOf", "asof", "baseDateTime", "dateTime", "tradedAt", "time", "baseDate", "date")


def find_asof(data) -> str | None:
    """응답 안에서 가장 늦은 시각 문자열(ISO 비교) — 없으면 None. 구조를 몰라도 되게 재귀."""
    best = None

    def walk(x, depth=0):
        nonlocal best
        if depth > 6:
            return
        if isinstance(x, dict):
            for k in _TIME_KEYS:
                v = x.get(k)
                if isinstance(v, str) and len(v) >= 8 and (best is None or v > best):
                    best = v
            for v in x.values():
                walk(v, depth + 1)
        elif isinstance(x, list):
            for v in x:
                walk(v, depth + 1)

    walk(data)
    return best


def _row_key(r: dict):
    for k in _TIME_KEYS:
        if k in r:
            return k
    return None


def merge_rows(old, new):
    """1분봉처럼 '시각 키가 있는 dict 리스트'면 시각으로 합친다(200봉 상한을 넘는 하루치 보존). 아니면 새 값."""
    def rows(x):
        if isinstance(x, list):
            return x, None
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v, k
        return None, None

    o, ok = rows(old)
    n, nk = rows(new)
    if not o or not n or ok != nk or not isinstance(n[0], dict) or _row_key(n[0]) is None:
        return new
    key = _row_key(n[0])
    merged = {r.get(key): r for r in o if isinstance(r, dict)}
    merged.update({r.get(key): r for r in n if isinstance(r, dict)})
    out = [merged[k] for k in sorted(merged, key=lambda z: str(z))]
    if nk is None:
        return out
    res = dict(new)
    res[nk] = out
    return res


def _refuse_repo(p: Path) -> None:
    try:
        p.resolve().relative_to(ROOT)
    except ValueError:
        return
    raise SystemExit("출력 폴더가 저장소 안 — 약관 미확인이라 저장소 밖에만 쓴다 (TOSS_MD_DATA_DIR 확인)")


class Lock:
    """수집 주체 1개 — 동시 실행 방지 잠금(O_EXCL). 15분 넘은 잠금은 죽은 것으로 보고 치운다."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.write(fd, f"{os.getpid()} {time.time():.0f}".encode())
                os.close(fd)
                return self
            except FileExistsError:
                if time.time() - self.path.stat().st_mtime > LOCK_STALE_SEC:
                    self.path.unlink(missing_ok=True)
                    continue
                raise SystemExit("다른 수집기가 실행 중(잠금 있음) — 수집 주체는 1개")
        raise SystemExit("잠금 획득 실패")

    def __exit__(self, *a):
        self.path.unlink(missing_ok=True)


def fixture_transport(method: str, url: str, headers: dict, data: bytes | None) -> toss_md.Resp:
    """dry-run: 네트워크 대신 tools/toss_md/fixtures/*.json 을 돌려준다(정책 검사는 실제와 같이 거친다)."""
    path = "/" + url.split("://", 1)[-1].split("/", 1)[-1].split("?", 1)[0]
    if path == toss_md.TOKEN_PATH:
        return toss_md.Resp(200, {}, json.dumps({"access_token": "dry-run", "expires_in": 86400}).encode())
    name = path.strip("/").replace("/", "__")
    f = FIXTURES / f"{name}.json"
    if not f.exists():
        return toss_md.Resp(404, {}, b'{"code":"fixture_missing"}')
    return toss_md.Resp(200, {}, f.read_bytes())


def write_heartbeat(base: Path, ok: int, fail: int, last_error: str | None, now: datetime,
                    rate_limits: dict | None = None) -> None:
    hb = base / "heartbeat.json"
    prev = {}
    if hb.exists():
        try:
            prev = json.loads(hb.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    cur = {"last_attempt": now.isoformat(timespec="seconds"),
           "last_success": now.isoformat(timespec="seconds") if ok and not fail else prev.get("last_success"),
           "ok": ok, "fail": fail, "last_error": last_error,
           # 그룹별 마지막 X-RateLimit-Remaining (한도 여유) — 이번 회차에 안 부른 그룹은 이전 값 유지
           "rate_limit": {**(prev.get("rate_limit") or {}),
                          **{g: {**v, "at": now.isoformat(timespec="seconds")} for g, v in (rate_limits or {}).items()}}}
    if prev.get("publish"):
        cur["publish"] = prev["publish"]   # publish.py 상태(마지막 push·실패 사유) 보존
    base.mkdir(parents=True, exist_ok=True)
    hb.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


def run(group: str = "all", dry_run: bool = False, stocks_all: bool = False, out: Path | None = None,
        now: datetime | None = None, client: toss_md.TossMD | None = None) -> dict:
    base = (out or DATA_DIR)
    if dry_run:
        base = base / "_dryrun"
    _refuse_repo(base)
    now = now or datetime.now(KST)
    day = base / now.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)

    targets = [t for t in PILOT if group in ("all", t[1])]
    if stocks_all and group in ("all", "daily"):
        targets += [t for t in STOCKS_ALL if not (day / f"{t[0]}.json").exists()]  # 시장별 일 1회

    if client is None:
        if dry_run:
            cfg = {"client_id": "dry-run-id", "client_secret": "dry-run", "base_url": "https://dry-run.invalid"}
            client = toss_md.TossMD(cfg, transport=fixture_transport, token_cache=base / ".token_dryrun.json")
        else:
            client = toss_md.TossMD()

    ok, fail, last_err = 0, 0, None
    lock = (base if dry_run else toss_md.CONFIG_DIR) / "collector.lock"
    with Lock(lock):
        for name, _g, path, params in targets:
            try:
                data = client.get(path, params)
            except (toss_md.TossMDError, toss_md.ForbiddenRequest) as e:
                fail += 1
                last_err = f"{name}: {e}"
                log.error("수집 실패 %s", last_err)
                continue
            f = day / f"{name}.json"
            if f.exists() and name.endswith("_1m"):   # 분봉만 시각으로 합침(prices 는 여러 심볼이 같은 시각이라 합치면 안 됨)
                try:
                    data = merge_rows(json.loads(f.read_text(encoding="utf-8")).get("data"), data)
                except Exception:
                    pass
            asof = find_asof(data)
            rec = {"generated_at": datetime.now(KST).isoformat(timespec="seconds") if not dry_run else now.isoformat(timespec="seconds"),
                   "asof": asof or now.isoformat(timespec="seconds"),
                   "asof_src": "response" if asof else "generated_at",
                   "endpoint": path, "params": params, "dry_run": dry_run, "data": data}
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            tmp.replace(f)
            ok += 1
    write_heartbeat(base, ok, fail, last_err, now, getattr(client, "rate_limits", None))
    summary = {"dir": str(day), "ok": ok, "fail": fail, "host": socket.gethostname() if not dry_run else "dry-run"}
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--group", choices=["intraday", "daily", "all"], default="all")
    ap.add_argument("--dry-run", action="store_true", help="네트워크 없이 픽스처로")
    ap.add_argument("--stocks-all", action="store_true", help="/stocks/all 일 1회 포함")
    ap.add_argument("--out", type=Path, default=None, help="출력 폴더(기본 ~/toss_md_data, 저장소 밖만)")
    ap.add_argument("--publish", action="store_true", help="수집 뒤 공개 요약을 toss-live 브랜치로 publish (tools/toss_md/publish.py)")
    ap.add_argument("--min-interval", type=int, default=0, help="publish 최소 간격(분, 기본 0 = 수집 회차마다·변화 있을 때만)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = run(a.group, a.dry_run, a.stocks_all, a.out)
    # 요약만 출력(응답 원문 금지)
    print(f"toss_md collect: ok={s['ok']} fail={s['fail']} → {s['dir']}")
    if a.publish:   # 수집 일부 실패여도 있는 것으로 publish (빠진 항목은 live.json missing 에 적힘)
        from tools.toss_md import publish
        try:
            p = publish.run(a.out, dry_run=a.dry_run, min_interval_min=a.min_interval)
            print(f"toss_md publish: {p['status']} ({p['decision']})" + (f" — {p['error']}" if p.get("error") else ""))
        except Exception as e:  # noqa: BLE001 — publish 실패가 수집 결과를 막지 않게(heartbeat 에 남김)
            log.error("publish 예외: %s", type(e).__name__)
    return 0 if s["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
