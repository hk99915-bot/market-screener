"""토스 시세 파일럿 수집기 — **겸이 노트북 전용** (수집 주체 1개, 공개 산출물 없음).

    python tools/toss_md/collect.py --group intraday           # 지수 1분·투자자별 매매대금·USDKRW
    python tools/toss_md/collect.py --group daily              # KR/US 휴장 달력 (+ --stocks-all 이면 종목 목록 일1회)
    python tools/toss_md/collect.py --group intraday,us --publish   # 작업 스케줄러 'toss_md_live' (평일 08:00~다음날 07:10, 10분)
    python tools/toss_md/collect.py --group us                 # 미장 지표 ETF·대형주 현재가·1분봉(SPY·QQQ·SOXX)·랭킹·섹터 랭킹
    python tools/toss_md/collect.py --group sectors            # 토스 섹터 계층 + 섹터별 종목(KR·US) 일 1회 (호출 1 + 2×말단 섹터 수)
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
# ── 미장 'us' 그룹 (10/21 겸이 "미장데이터 지금부터" · "프리장 데이장도") ─────────────────────────
# 대상 심볼 = 지표 ETF 고정 20 + committee_us 아이디어 + universe/us_top.csv(5일 거래대금 순, 공개 목록) 로 200개까지.
# 개인 보유(MY 탭·MY_HOLDINGS)는 쓰지 않는다. 1분봉은 SPY·QQQ·SOXX 3개만.
US_ETFS = ("SPY", "QQQ", "DIA", "IWM", "SOXX", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU",
           "XLRE", "XLC", "TLT", "HYG", "GLD")
US_SPARK = ("SPY", "QQQ", "SOXX")
US_MAX_SYMBOLS = 200   # /api/v1/prices 한 번 최대 200개 (OpenAPI 원문)
US_RANKS = (("us_rank_amount", "MARKET_TRADING_AMOUNT", "realtime"),
            ("us_rank_gainers", "TOP_GAINERS", "1d"), ("us_rank_losers", "TOP_LOSERS", "1d"))


def us_symbols(root: Path = ROOT) -> list[str]:
    """공개 목록만으로 미장 심볼 200개 이하 — 순서: ETF → 운용회의 아이디어 → 거래대금 상위."""
    out: list[str] = list(US_ETFS)

    def add(xs):
        for x in xs:
            x = str(x or "").strip().upper()
            if x and x not in out and len(out) < US_MAX_SYMBOLS and all(c.isalnum() or c in ".-" for c in x):
                out.append(x)
    try:
        c = json.loads((root / "reports" / "committee_us.json").read_text(encoding="utf-8"))
        ideas = c.get("ideas") or {}
        add(r.get("s") for k in ("long", "short", "watch") for r in (ideas.get(k) or []) if isinstance(r, dict))
    except Exception:  # noqa: BLE001 — 없으면 건너뜀
        pass
    for f in ("us_top.csv", "us_index.csv"):
        try:
            lines = (root / "universe" / f).read_text(encoding="utf-8").splitlines()[1:]
            add(ln.split(",", 1)[0] for ln in lines)
        except Exception:  # noqa: BLE001
            pass
    return out


def us_targets(root: Path = ROOT) -> list[tuple[str, str, str, dict]]:
    t = [("us_prices", "us", "/api/v1/prices", {"symbols": ",".join(us_symbols(root))})]
    # 종목 캔들 파라미터 이름(symbol·interval·count)은 [추정 — 첫 실행 400 이면 원문 대조해 이 줄만 고침]
    t += [(f"us_{s.lower()}_1m", "us", "/api/v1/candles", {"symbol": s, "interval": "1m", "count": 200}) for s in US_SPARK]
    t += [(n, "us", "/api/v1/rankings", {"marketCountry": "US", "type": ty, "duration": du, "count": 50}) for n, ty, du in US_RANKS]
    t += [("us_sector_rank", "us", "/api/v1/sectors/rankings", {"marketCountry": "US", "type": "TOP_GAINERS", "duration": "1d"})]
    return t


STOCKS_ALL = [(f"stocks_all_{m.lower()}", "daily", "/api/v1/stocks/all", {"market": m})
              for m in ("KOSPI", "KOSDAQ", "KR_ETC", "NYSE", "NASDAQ", "AMEX", "US_ETC")]

log = logging.getLogger("toss_md.collect")

# ── 세션 창 (10/21 PB: 작업 스케줄러는 'toss_md_live' 하나 — 평일 08:00~다음날 07:10 — 이고, 그룹별 세션 밖이면 건너뜀) ──
# 1순위: 수집해 둔 토스 market-calendar 의 그날 세션 시각(ISO 시각이 있을 때만 — 응답 꼴은 [추정, 첫 --shape 로 확인]).
# 폴백: KR = 저장소 휴장표(tradecal) 거래일 08:00~20:00 KST(NXT 포함, 예전 intraday 작업 창) ·
#       US = 토스 미장 4세션(데이 20:00 ET 전날 ~ 애프터 18:00 ET) — ET 기준이라 서머타임(11/1 해제)이 자동 반영.
try:
    ET = ZoneInfo("America/New_York")
except Exception:  # tzdata 없음 → 세션 판정 불가(그룹을 막지 않고 돌린다)
    ET = None
KR_WIN = ((8, 0), (20, 0))
US_DAY_START_ET, US_AFTER_END_ET = (20, 0), (18, 0)
_SESSION_KEYS = ("market", "session")
_START_K = ("start", "startTime", "startAt", "open", "openTime", "openAt", "from", "begin")
_END_K = ("end", "endTime", "endAt", "close", "closeTime", "closeAt", "to", "finish")


def _iso(v):
    if not isinstance(v, str) or "T" not in v:
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def calendar_window(data, day: str):
    """market-calendar 응답에서 day 항목의 세션 시각 (가장 이른 시작, 가장 늦은 끝). ISO 시각이 없으면 None."""
    starts, ends = [], []

    def walk(x, depth=0, hit=False):
        if depth > 7:
            return
        if isinstance(x, dict):
            here = hit or any(str(x.get(k, ""))[:10] == day for k in ("date", "baseDate", "tradeDate"))
            for k, v in x.items():
                if here and isinstance(v, dict) and any(t in k.lower() for t in _SESSION_KEYS):
                    a = next((_iso(v.get(z)) for z in _START_K if _iso(v.get(z))), None)
                    b = next((_iso(v.get(z)) for z in _END_K if _iso(v.get(z))), None)
                    if a and b:
                        starts.append(a)
                        ends.append(b)
                walk(v, depth + 1, here)
        elif isinstance(x, list):
            for v in x:
                walk(v, depth + 1, hit)
    walk(data)
    return (min(starts), max(ends)) if starts else None


def _cached_calendar(base: Path, name: str, now: datetime):
    for i in range(8):
        f = base / (now.astimezone(KST).date() - timedelta(days=i)).isoformat() / f"{name}.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8")).get("data")
            except Exception:  # noqa: BLE001
                return None
    return None


def in_window(group: str, now: datetime, base: Path | None = None) -> tuple[bool, str]:
    """(지금 수집할지, 근거). intraday=KR, us=US 4세션. 그 밖의 그룹은 항상 True."""
    from screener import tradecal
    if group == "intraday":
        loc = now.astimezone(KST)
        cal = _cached_calendar(base, "calendar_kr", now) if base else None
        w = calendar_window(cal, loc.date().isoformat()) if cal else None
        if w:
            return w[0] <= now <= w[1], "calendar"
        if not tradecal.is_session("KR", loc.date()):
            return False, "KR 휴장"
        return time_between(loc, *KR_WIN), "fallback"
    if group == "us":
        if ET is None:
            return True, "tz 없음 — 판정 생략"
        et = now.astimezone(ET)
        d = et.date()
        cal = _cached_calendar(base, "calendar_us", now) if base else None
        for dd in (d, d + timedelta(days=1)):
            w = calendar_window(cal, dd.isoformat()) if cal else None
            if w and w[0] <= now <= w[1]:
                return True, "calendar"
        today = tradecal.is_session("US", d) and (et.hour, et.minute) < US_AFTER_END_ET
        eve = tradecal.is_session("US", d + timedelta(days=1)) and (et.hour, et.minute) >= US_DAY_START_ET
        return today or eve, "fallback"
    return True, "always"


def time_between(loc: datetime, a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a <= (loc.hour, loc.minute) < b

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

    def __init__(self, path: Path, wait_sec: float = 0.0):
        self.path, self.wait_sec = path, wait_sec

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.wait_sec
        tries = 0
        while True:
            tries += 1
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.write(fd, f"{os.getpid()} {time.time():.0f}".encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    stale = time.time() - self.path.stat().st_mtime > LOCK_STALE_SEC
                except FileNotFoundError:
                    continue
                if stale and tries < 3:
                    self.path.unlink(missing_ok=True)
                    continue
                if time.time() < deadline:   # 08:30·18:30 처럼 두 작업이 겹치면 잠깐 기다린다(10/21)
                    time.sleep(2)
                    continue
                raise SystemExit("다른 수집기가 실행 중(잠금 있음) — 수집 주체는 1개")

    def __exit__(self, *a):
        self.path.unlink(missing_ok=True)


def fixture_transport(method: str, url: str, headers: dict, data: bytes | None) -> toss_md.Resp:
    """dry-run: 네트워크 대신 tools/toss_md/fixtures/*.json 을 돌려준다(정책 검사는 실제와 같이 거친다)."""
    rest = url.split("://", 1)[-1].split("/", 1)[-1]
    path = "/" + rest.split("?", 1)[0]
    query = dict(kv.split("=", 1) for kv in rest.split("?", 1)[1].split("&") if "=" in kv) if "?" in rest else {}
    if path == toss_md.TOKEN_PATH:
        return toss_md.Resp(200, {}, json.dumps({"access_token": "dry-run", "expires_in": 86400}).encode())
    name = path.strip("/").replace("/", "__")
    if name.startswith("api__v1__sectors__") and name.endswith("__stocks"):
        name = "api__v1__sectors__ID__stocks"   # 섹터별 종목 픽스처 1개(시장별 @KR·@US)
    for cand in ([f"{name}@{query['marketCountry']}"] if query.get("marketCountry") else []) + [name]:
        f = FIXTURES / f"{cand}.json"
        if f.exists():
            return toss_md.Resp(200, {}, f.read_bytes())
    return toss_md.Resp(404, {}, b'{"code":"fixture_missing"}')


# ── 토스 섹터 (보드 toss-sectors, 10/21 겸이: 테마·순환매·히트맵 = 토스 섹터 3단계·다중 소속) ─────────
# 호출 수 = 1(/sectors) + 2 × 말단 섹터 수(KR·US 각 1회). 상위 섹터 소속은 parentSectorId 로 거슬러 올라가 만든다.
# 일 1회(별도 작업 'toss_md_sectors' 07:20 — 실시간 작업 창 07:10~08:00 사이라 잠금이 안 겹침). 간격 SECTOR_GAP_SEC + 429 는 Retry-After.
SECTOR_GAP_SEC = 0.5
SECTOR_MARKETS = ("KR", "US")


def parse_sectors(data) -> list[dict]:
    """/api/v1/sectors → [{id, name, depth, parent}] (OpenAPI 원문 Sector: sectorId·name·depth·parentSectorId)."""
    out, seen = [], set()
    for d in crosscheck_dicts(data):
        sid = d.get("sectorId")
        if sid is None or str(sid) in seen:
            continue
        seen.add(str(sid))
        par = d.get("parentSectorId")
        dep = d.get("depth")
        out.append({"id": str(sid), "name": str(d.get("name") or ""), "depth": int(dep) if isinstance(dep, (int, float)) or (isinstance(dep, str) and dep.isdigit()) else None,
                    "parent": None if par in (None, "", 0, "0") else str(par)})
    return out


def leaf_ids(sectors: list[dict]) -> list[str]:
    parents = {s["parent"] for s in sectors if s["parent"]}
    return [s["id"] for s in sectors if s["id"] not in parents]


def crosscheck_dicts(x, depth: int = 0):
    if depth > 6:
        return
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from crosscheck_dicts(v, depth + 1)
    elif isinstance(x, list):
        for v in x:
            yield from crosscheck_dicts(v, depth + 1)


def collect_sectors(client, day: Path, now: datetime, dry_run: bool = False,
                    sleep=time.sleep, gap: float = SECTOR_GAP_SEC) -> tuple[int, int, str | None]:
    """섹터 계층 + 말단 섹터별 종목(KR·US) → day/sectors.json. 반환 (성공 호출, 실패 호출, 마지막 오류)."""
    ok = fail = 0
    err = None
    try:
        tree = client.get("/api/v1/sectors")
        ok += 1
    except (toss_md.TossMDError, toss_md.ForbiddenRequest) as e:
        return 0, 1, f"sectors: {e}"
    secs = parse_sectors(tree)
    stocks: dict[str, dict] = {m: {} for m in SECTOR_MARKETS}
    failed = []
    for mk in SECTOR_MARKETS:
        for sid in leaf_ids(secs):
            if not dry_run:
                sleep(gap)
            try:
                stocks[mk][sid] = client.get(f"/api/v1/sectors/{sid}/stocks", {"marketCountry": mk})
                ok += 1
            except (toss_md.TossMDError, toss_md.ForbiddenRequest) as e:
                fail += 1
                failed.append(f"{mk}:{sid}")
                err = f"sector_stocks {mk}: {e}"
    rec = {"generated_at": now.isoformat(timespec="seconds"), "asof": now.isoformat(timespec="seconds"),
           "asof_src": "generated_at", "endpoint": "/api/v1/sectors", "dry_run": dry_run,
           "data": {"sectors": tree, "stocks": stocks, "failed": failed, "calls": ok + fail, "leaves": len(leaf_ids(secs))}}
    f = day / "sectors.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)
    return ok, fail, err


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


GROUPS = ("intraday", "daily", "us", "sectors")


def run(group: str = "all", dry_run: bool = False, stocks_all: bool = False, out: Path | None = None,
        now: datetime | None = None, client: toss_md.TossMD | None = None, gate: bool = False,
        lock_wait: float = 0.0) -> dict:
    """group: 'all'(intraday·daily·us) 또는 콤마 목록('intraday,us'). gate=True 면 세션 밖 그룹은 건너뜀(in_window)."""
    base = (out or DATA_DIR)
    if dry_run:
        base = base / "_dryrun"
    _refuse_repo(base)
    now = now or datetime.now(KST)
    day = base / now.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)

    want = {"intraday", "daily", "us"} if group == "all" else {g.strip() for g in group.split(",") if g.strip()}
    bad = want - set(GROUPS)
    if bad:
        raise SystemExit(f"모르는 그룹: {','.join(sorted(bad))}")
    skipped = {}
    if gate:
        for g in sorted(want & {"intraday", "us"}):
            go, why = in_window(g, now, base)
            if not go:
                want.discard(g)
                skipped[g] = why
    targets = [t for t in PILOT + us_targets() if t[1] in want]
    if stocks_all and "daily" in want:
        targets += [t for t in STOCKS_ALL if not (day / f"{t[0]}.json").exists()]  # 시장별 일 1회
    do_sectors = "sectors" in want and not (day / "sectors.json").exists()
    if not targets and not do_sectors:
        log.info("수집 대상 없음(세션 밖: %s)", skipped)
        return {"dir": str(day), "ok": 0, "fail": 0, "skipped": skipped, "host": "dry-run" if dry_run else socket.gethostname()}

    if client is None:
        if dry_run:
            cfg = {"client_id": "dry-run-id", "client_secret": "dry-run", "base_url": "https://dry-run.invalid"}
            client = toss_md.TossMD(cfg, transport=fixture_transport, token_cache=base / ".token_dryrun.json")
        else:
            client = toss_md.TossMD()

    ok, fail, last_err = 0, 0, None
    lock = (base if dry_run else toss_md.CONFIG_DIR) / "collector.lock"
    with Lock(lock, lock_wait):
        if do_sectors:
            o, f_, e = collect_sectors(client, day, now, dry_run)
            ok, fail, last_err = ok + o, fail + f_, e or last_err
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
    summary = {"dir": str(day), "ok": ok, "fail": fail, "skipped": skipped, "host": socket.gethostname() if not dry_run else "dry-run"}
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--group", default="all", help="all | intraday | daily | us | sectors | 콤마 목록(예: intraday,us)")
    ap.add_argument("--no-gate", action="store_true", help="세션 밖이어도 수집(점검용)")
    ap.add_argument("--dry-run", action="store_true", help="네트워크 없이 픽스처로")
    ap.add_argument("--stocks-all", action="store_true", help="/stocks/all 일 1회 포함")
    ap.add_argument("--out", type=Path, default=None, help="출력 폴더(기본 ~/toss_md_data, 저장소 밖만)")
    ap.add_argument("--publish", action="store_true", help="수집 뒤 공개 요약을 toss-live 브랜치로 publish (tools/toss_md/publish.py)")
    ap.add_argument("--min-interval", type=int, default=0, help="publish 최소 간격(분, 기본 0 = 수집 회차마다·변화 있을 때만)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = run(a.group, a.dry_run, a.stocks_all, a.out, gate=not a.no_gate and a.group != "all", lock_wait=240)
    # 요약만 출력(응답 원문 금지)
    print(f"toss_md collect: ok={s['ok']} fail={s['fail']}" + (f" skipped={s['skipped']}" if s.get("skipped") else "") + f" → {s['dir']}")
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
