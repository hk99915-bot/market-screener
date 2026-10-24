"""KR 장중 히트맵 등락률 → reports/heatmap_KR.json (보드 maint-heatmap, 2026-10-21 유지보수).

왜: MARKET › 히트맵 KR 은 peers_KR.json(16:20 스크리너 일 1회)만 써서 장중엔 전날 종가 등락이 그대로 보였다
(10/21 코스피 +4% 장중 겸이 "히트맵 업뎃 안 됨"). US 의 heatmap_US.json 과 같은 꼴로 1D 등락만 장중 갱신한다.
5D/20D·시총·분류는 그대로 peers_KR.json.

실행 주체: live.yml 국장 루프(5분 간격) 안에서 `python -m screener.heatmap_kr` — 별도 cron 없음(cron 누락 회피).
소스 순서 — 네이버 1차·토스 폴백(10/24 데이터 측정 req-dev-a4d03413: 토스는 노트북 10분 수집이라 시세 나이 중앙 5.1분·최악 12.6분,
장 마감 뒤 종목가는 NXT 통합가, 커버리지 200 vs 1,272 → 토스 1차 전환은 보류, 겸이 최종 결정 대기):
  네이버 모바일(이미 쓰는 것 재사용 — live.kr_naver·event_watch 와 같은 등락 부호 규칙):
  1) polling.finance.naver.com 다종목 실시간(100개씩, 약 13회) — 당일 시가·고가·저가·거래량까지(10/24 순서 변경: 오늘 봉·갭)
  2) 남은 종목은 /api/stocks/marketValue/{KOSPI,KOSDAQ} 시총순 목록(페이지 100종목)
  (네이버 전부 실패한 종목만) 토스 — toss-live 브랜치 live.json kr_quotes, 정규장 중·신선(20분)할 때만(장 마감 뒤 NXT 통합가 금지). 행에 src='toss'.
  3) 그래도 80% 미만이면 남은 종목만 /api/stock/{code}/basic(event_watch 와 같은 엔드포인트, 동시 8개·90초 상한)
커버리지 80% 미만이면 파일을 안 쓴다(이전 값 유지) — 화면은 기준 시각이 늦어져 STALE 배지, 신선도 계약(ops/freshness.json
heatmap_kr)이 late 로 잡는다. 조용한 대체 없음.
"""
from __future__ import annotations

import argparse
import json
import logging
import time as _time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from . import tradecal
from .config import REPORT_DIR
from .json_safe import dumps

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "Referer": "https://m.stock.naver.com/"}
MIN_COVER = 0.8
WINDOW = (time(9, 0), time(15, 50))   # 장 시작 ~ 동시호가 마감 반영까지 (08:40~09:00 은 전날 종가 = peers 와 같음)
LIST_URL = "https://m.stock.naver.com/api/stocks/marketValue/{mk}?page={page}&pageSize=100"
POLL_URL = "https://polling.finance.naver.com/api/realtime/domestic/stock/{codes}"
BASIC_URL = "https://m.stock.naver.com/api/stock/{code}/basic"


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def parse_item(j: dict) -> tuple[str, dict] | None:
    """네이버 종목 dict(목록·polling·basic 공통 키) → (코드, {r1, close, t}). 부호: compareToPreviousPrice.code 1·2 상승, 3 보합, 4·5 하락."""
    if not isinstance(j, dict):
        return None
    code = str(j.get("itemCode") or j.get("cd") or "").strip()
    last = _num(j.get("closePriceRaw") if j.get("closePriceRaw") is not None else j.get("closePrice"))
    ratio = _num(j.get("fluctuationsRatioRaw") if j.get("fluctuationsRatioRaw") is not None else j.get("fluctuationsRatio"))
    if len(code) != 6 or last is None or ratio is None or last <= 0:
        return None
    sign = str((j.get("compareToPreviousPrice") or {}).get("code", ""))
    r1 = ratio / 100
    if sign in ("4", "5"):
        r1 = -abs(r1)
    elif sign in ("1", "2"):
        r1 = abs(r1)
    elif sign == "3":
        r1 = 0.0
    out = {"r1": round(r1, 5), "close": last, "t": str(j.get("localTradedAt") or "")[:16]}
    # 당일 시가·고가·저가·누적 거래량(polling·basic 에 있음, 목록엔 없음) + 전일 종가(절대 변화로 복원 — 등락률 소수 2자리 반올림 오차 없음)
    # → 상세 차트 '오늘 봉'(screener/intraday_last.py). 정규장(KRX) 값 — 시간외·NXT 는 overMarketPriceInfo 에 따로 있어 안 섞임.
    for k, n in (("o", "openPrice"), ("h", "highPrice"), ("l", "lowPrice"), ("v", "accumulatedTradingVolume")):
        x = _num(j.get(n))
        if x is not None and x > 0:
            out[k] = x
    d = _num(j.get("compareToPreviousClosePrice"))
    if d is not None:
        pc = last - abs(d) if r1 > 0 else last + abs(d) if r1 < 0 else last
        if pc > 0 and abs(last / pc - 1 - r1) <= 0.0001:
            out["pc"] = pc
    return code, out


def _items(doc) -> list[dict]:
    """응답 안의 종목 dict 목록 (목록 = stocks, polling = datas, basic = 자기 자신)."""
    if isinstance(doc, list):
        return [x for x in doc if isinstance(x, dict)]
    if not isinstance(doc, dict):
        return []
    for k in ("stocks", "datas", "result", "items"):
        if isinstance(doc.get(k), list):
            return [x for x in doc[k] if isinstance(x, dict)]
    return [doc] if doc.get("itemCode") else []


def collect(codes: list[str], get, deadline_sec: float = 150) -> tuple[dict, list[str]]:
    """codes 의 등락. get(url) → JSON(실패 시 예외). 반환 ({코드: row}, 사용한 소스 이름들)."""
    want, out, used = set(codes), {}, []
    t0 = _time.monotonic()

    def take(doc) -> int:
        n = 0
        for it in _items(doc):
            p = parse_item(it)
            if p and p[0] in want and p[0] not in out:
                out[p[0]] = p[1]
                n += 1
        return n

    rest = list(codes)   # 1) 다종목 polling 먼저 — 당일 시가·고저·거래량이 있는 소스(10/24 오늘 봉·갭). 100개씩 ≈ 13회
    for i in range(0, len(rest), 100):
        if _time.monotonic() - t0 > deadline_sec / 2:
            break
        try:
            if take(get(POLL_URL.format(codes=",".join(rest[i:i + 100])))) and "polling" not in used:
                used.append("polling")
        except Exception as e:  # noqa: BLE001
            log.warning("KR 히트맵 polling 실패: %s", type(e).__name__)
            break
    for mk in ("KOSPI", "KOSDAQ"):   # 2) 시총순 목록 (polling 이 못 준 종목 — 시가·고저 없음)
        for page in range(1, 31):
            if want <= out.keys() or _time.monotonic() - t0 > deadline_sec * 0.75:
                break
            try:
                doc = get(LIST_URL.format(mk=mk, page=page))
            except Exception as e:  # noqa: BLE001
                log.warning("KR 히트맵 목록 %s p%d 실패: %s", mk, page, type(e).__name__)
                break
            if not _items(doc):
                break
            if take(doc) and "list" not in used:
                used.append("list")
    rest = [c for c in codes if c not in out]   # 3) 종목별 basic (모자랄 때만)
    if rest and len(out) < len(codes) * MIN_COVER:
        def one(c):
            if _time.monotonic() - t0 > deadline_sec:
                return None
            try:
                return get(BASIC_URL.format(code=c))
            except Exception:  # noqa: BLE001
                return None
        with ThreadPoolExecutor(8) as ex:
            for doc in ex.map(one, rest):
                if doc is not None and take(doc) and "basic" not in used:
                    used.append("basic")
    return out, used


def toss_quotes(doc: dict | None, codes: list[str], trade_date: str, now: datetime) -> dict:
    """토스 live.json kr_quotes → {코드: {r1, close, t, src:'toss'}} — 네이버 폴백용. 정규장 중(tradecal.in_session)이고 신선(20분)하며
    거래일이 trade_date 인 것만. 장 마감 뒤는 토스 종목가가 NXT 통합가로 보여(req-dev-a4d03413) 쓰지 않는다."""
    from . import toss_live
    if not doc or not tradecal.in_session("KR", now):
        return {}
    want, out = set(codes), {}
    for c, v in (doc.get("kr_quotes") or {}).items():
        if c not in want or not isinstance(v, dict):
            continue
        last, pct, asof = _num(v.get("last")), _num(v.get("chg_pct")), v.get("asof")
        if last is None or last <= 0 or pct is None or abs(pct) > 31 or not str(asof or "")[:10] == trade_date:
            continue
        ok, _ = toss_live.fresh_ts(asof, now)
        if ok:
            out[c] = {"r1": round(pct / 100, 5), "close": last, "t": str(asof)[:16].replace("T", " "), "src": "toss"}
    return out


def plan(now: datetime, once: bool = False) -> tuple[str, str] | None:
    """(거래일, LIVE|CLOSE) 또는 None(수집 안 함). 장중 = LIVE, 15:30~15:50 = CLOSE. --once 는 창 밖에서도 마지막 거래일."""
    loc = now.astimezone(KST)
    d = loc.date()
    if tradecal.is_session("KR", d) and WINDOW[0] <= loc.time() <= WINDOW[1]:
        return d.isoformat(), ("LIVE" if tradecal.in_session("KR", now) else "CLOSE")
    if not once:
        return None
    last = tradecal.session_on_or_before("KR", d)
    if last == d and loc.time() < WINDOW[0]:
        last = tradecal.prev_session("KR", d)
    return last.isoformat(), "CLOSE"


def build(peers: dict, quotes: dict, now: datetime, trade_date: str, status: str, used: list[str]) -> dict:
    codes = list(dict.fromkeys(str(r["s"]) for r in peers.get("rows") or []))
    rows = []
    for c in codes:
        q = quotes.get(c)
        if not q:
            continue
        if q["t"] and q["t"][:10] < trade_date:   # 오늘 체결 없는 종목(거래정지 등) — 전날 등락을 오늘로 섞지 않음
            continue
        rows.append({"s": c, "r1": q["r1"], "close": q["close"], **({"src": "toss"} if q.get("src") == "toss" else {})})
    nt = sum(1 for r in rows if r.get("src") == "toss")
    src = ([f"네이버 증권 모바일 현재가({'+'.join(u for u in used if u != 'toss') or '없음'}) {len(rows) - nt}"] if len(rows) > nt else []) + ([f"토스 폴백 {nt}"] if nt else [])
    loc = now.astimezone(KST)
    return {"asof": loc.strftime("%Y-%m-%d %H:%M KST"), "trade_date": trade_date, "session": status,
            # 15:30~15:45 = 장 마감 직후 KRX 종가 확정 전(동시호가 체결 반영 중) → 잠정 (req-dev-a4d03413 ①)
            **({"provisional": True} if status == "CLOSE" and "15:30" <= loc.strftime("%H:%M") < "15:45" else {}),
            "source": " + ".join(src) or "없음", "src_n": {"naver": len(rows) - nt, "toss": nt}, "base_asof": peers.get("asof"),
            "expected": len(codes), "collected": len(rows), "rows": rows}


def _get(url: str):
    import requests
    r = requests.get(url, headers=UA, timeout=8)
    r.raise_for_status()
    return r.json()


def _toss_doc():
    from . import toss_live
    return toss_live.fetch()


def run(once: bool = False, now: datetime | None = None, get=_get, root: Path = REPORT_DIR, toss=_toss_doc) -> dict | None:
    now = now or datetime.now(KST)
    p = plan(now, once)
    if p is None:
        print("KR heatmap: 국장 창(09:00~15:50) 밖 — 건너뜀")
        return None
    trade_date, status = p
    peers = json.loads((root / "peers_KR.json").read_text(encoding="utf-8"))
    codes = list(dict.fromkeys(str(r["s"]) for r in peers.get("rows") or []))
    quotes, used = collect(codes, get)   # 네이버 1차 — 현재가·등락 + 당일 시가·고저·거래량·전일 종가(polling)
    miss = [c for c in codes if c not in quotes]
    if miss:   # 네이버가 못 준 종목만 토스(정규장·신선할 때)
        try:
            tq = toss_quotes(toss(), miss, trade_date, now)
        except Exception as e:  # noqa: BLE001
            log.warning("KR 히트맵 토스 폴백 읽기 실패: %s", type(e).__name__)
            tq = {}
        quotes.update(tq)
        if tq:
            used = [*used, "toss"]
    out = build(peers, quotes, now, trade_date, status, used)
    if out["collected"] < len(codes) * MIN_COVER:
        raise RuntimeError(f"KR heatmap coverage {out['collected']}/{len(codes)} ({'+'.join(used) or '소스 전부 실패'}); 이전 파일 유지")
    f = root / "heatmap_KR.json"
    if f.exists():
        try:
            if json.loads(f.read_text(encoding="utf-8")).get("asof", "") > out["asof"]:
                raise RuntimeError("Refusing older KR heatmap")
        except json.JSONDecodeError:
            pass
    f.write_text(dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"KR heatmap {trade_date} {status}: {out['collected']}/{len(codes)} via {'+'.join(used)} (토스 폴백 {out['src_n']['toss']})")
    try:   # 종목 상세 차트 '오늘 봉' 오버레이 (screener/intraday_last.py)
        from . import intraday_last
        intraday_last.update("KR", [{"s": r["s"], **quotes[r["s"]]} for r in out["rows"]], trade_date, status, now, root,
                             provisional=bool(out.get("provisional")))
    except Exception as e:  # noqa: BLE001
        log.warning("intraday_last KR 실패: %s", e)
    return out


def put_newer(src: Path, dst: Path) -> bool:
    """src 의 asof 가 dst 보다 같거나 새로우면 dst 를 덮는다 (live 루프가 원격 최신 위에 얹을 때 — 다른 실행 주체가 먼저 쓴 더 새 값 보존)."""
    if not src.exists():
        return False
    new = json.loads(src.read_text(encoding="utf-8"))
    old = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {}
    if str(new.get("asof", "")) >= str(old.get("asof", "")):
        dst.write_bytes(src.read_bytes())
        return True
    return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="창 밖에서도 1회 (마지막 거래일 종가 기준)")
    ap.add_argument("--put", nargs=2, metavar=("SRC", "DST"), help="asof 가 같거나 새로울 때만 SRC → DST 복사")
    a = ap.parse_args()
    if a.put:
        print("put", a.put[1], put_newer(Path(a.put[0]), Path(a.put[1])))
    else:
        run(a.once)
