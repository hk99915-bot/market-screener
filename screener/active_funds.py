"""국내 주식형 액티브 ETF 편입·편출 트래킹 (데이터 데스크, 2026-10-17 오너 지시 "국내 주요 액티브펀드 편입편출 트래킹도").

원리: 국내 ETF 는 매 영업일 PDF(구성종목·1CU 당 수량)를 공시한다 → 전일 스냅샷과 비교하면 일간 편입·편출이 보인다.
- PDF 수량은 **1CU(설정 단위) 기준**이라 투자자 자금 유입(설정 증가)으로는 바뀌지 않는다 → '1CU 당 주식 수' 변화 = 운용역의
  실질 매매. 비중(weight) 변화는 주가 변동이 섞이므로 판정에 쓰지 않고 참고로만 남긴다.
  [확인 필요: 운용사 홈페이지 PDF 는 펀드 전체 수량인 곳이 있음 → 그 소스를 쓰면 units(설정 CU 수)로 나눠야 함. `units` 인자 지원]
- 액면분할·무상증자는 수량이 정수배로 뛴다 → `split_suspect` 플래그(이벤트로 세지 않음).
- 수집 실패·빈 PDF 는 '전량 편출'이 아니라 '미수집'이다 → 그 ETF 는 이전 스냅샷 유지, diff 안 함, stale 기록.

저장(용량 규칙, refactor_plan 0단계): 최신 스냅샷 1개(reports/active_funds_snap.json) + 이벤트 로그(reports/active_funds.json,
최근 KEEP_DAYS 거래일). 전 스냅샷 누적 금지. 텔레그램 없음. 예약 편입은 보드 `active-flow-schedule`(오너 결재 전 실행 주체 없음).

  python -m screener.active_funds            # 오늘(KST) PDF 수집 → diff → 저장
  python -m screener.active_funds --date 20261016
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import REPORT_DIR, UNIVERSE_DIR

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

OUT = REPORT_DIR / "active_funds.json"
SNAP = REPORT_DIR / "active_funds_snap.json"
KEEP_DAYS = 60          # 이벤트 로그 보존 거래일
CONSENSUS_DAYS = 5      # 합의도 집계 창(거래일)
REAL_CHG = 0.05         # 1CU 당 주식 수 ±5% 이상 = 실질 증감 (그 아래는 반올림·현금 조정 잡음으로 봄) [가정]
MIN_WEIGHT_NEW = 0.002  # 신규 편입 중 비중 0.2% 미만은 '시범 편입'으로 표시만

# 대상 명단 — 코드 확인 출처: R = 저장소 reports/detail/KR (네이버 ETF 목록·KRX, asof 2026-10-16) / W = 웹 검색 2026-10-17
# (funetf·한경·investing 등 2곳 이상 일치). kind: equity = 국내 주식 순수 액티브 / overlay = 커버드콜(옵션 매도 섞임, 주식 부분만 비교)
TARGETS: list[dict] = [
    {"code": "385720", "name": "TIME 코스피액티브", "issuer": "타임폴리오", "kind": "equity", "src": "W"},
    {"code": "385710", "name": "TIME K이노베이션액티브", "issuer": "타임폴리오", "kind": "equity", "src": "W"},
    {"code": "441800", "name": "TIME Korea플러스배당액티브", "issuer": "타임폴리오", "kind": "equity", "src": "R"},
    {"code": "463050", "name": "TIME K바이오액티브", "issuer": "타임폴리오", "kind": "equity", "src": "W"},
    {"code": "495060", "name": "TIME 코리아밸류업액티브", "issuer": "타임폴리오", "kind": "equity", "src": "W",
     "note": "KIND 2026-01-21 '종목명 변경' 공시 있음 — 현재 이름 확인 필요"},
    {"code": "0163Y0", "name": "KoAct 코스닥액티브", "issuer": "삼성액티브", "kind": "equity", "src": "R"},
    {"code": "476850", "name": "KoAct 배당성장액티브", "issuer": "삼성액티브", "kind": "equity", "src": "W"},
    {"code": "462900", "name": "KoAct 바이오헬스케어액티브", "issuer": "삼성액티브", "kind": "equity", "src": "W"},
    {"code": "494890", "name": "KODEX 200액티브", "issuer": "삼성", "kind": "equity", "src": "R"},
    {"code": "445290", "name": "KODEX 로봇액티브", "issuer": "삼성", "kind": "equity", "src": "R"},
    {"code": "385510", "name": "KODEX 신재생에너지액티브", "issuer": "삼성", "kind": "equity", "src": "W"},
    {"code": "471780", "name": "TIGER 코리아테크액티브", "issuer": "미래에셋", "kind": "equity", "src": "W",
     "note": "웹 출처 1곳(시세 사이트)만 — 첫 수집 때 이름 대조"},
    {"code": "444200", "name": "SOL 코리아메가테크액티브", "issuer": "신한", "kind": "equity", "src": "R"},
    {"code": "494330", "name": "ACE 라이프자산주주가치액티브", "issuer": "한국투자", "kind": "equity", "src": "W"},
    {"code": "472720", "name": "TRUSTON 주주가치액티브", "issuer": "트러스톤", "kind": "equity", "src": "W"},
    {"code": "472150", "name": "TIGER 배당커버드콜액티브", "issuer": "미래에셋", "kind": "overlay", "src": "R"},
    {"code": "0219E0", "name": "KODEX 200커버드콜액티브", "issuer": "삼성", "kind": "overlay", "src": "R"},
    {"code": "0177R0", "name": "TIGER 반도체TOP10커버드콜액티브", "issuer": "미래에셋", "kind": "overlay", "src": "R"},
]


def is_stock(code: str) -> bool:
    """국내 상장 주식 코드(6자리, 신형 영숫자 포함). 현금(KRD…)·선물·옵션(12자리 표준코드) 등은 제외."""
    c = str(code or "").strip()
    return len(c) == 6 and c[:5].isalnum() and c[0].isdigit()


# ---------------------------------------------------------------- 수집
def fetch_pdf(code: str, ymd: str) -> list[dict]:
    """KRX PDF(pykrx) → [{code,name,shares,amount}] (1CU 기준). 실패·빈 결과 = []. KRX_ID/KRX_PW 환경 필요(pykrx 1.2.x)."""
    try:
        from pykrx import stock  # type: ignore
        df = stock.get_etf_portfolio_deposit_file(code, ymd)
    except Exception as e:  # noqa: BLE001
        log.info("PDF %s 실패: %s", code, e)
        return []
    if df is None or len(df) == 0:
        return []
    cols = list(df.columns)
    sh = "계약수" if "계약수" in cols else None
    am = "금액" if "금액" in cols else None
    out = []
    for k, r in df.iterrows():
        out.append({"code": str(k), "name": str(r.get("구성종목명", k)),
                    "shares": float(r[sh]) if sh and r[sh] == r[sh] else None,
                    "amount": float(r[am]) if am and r[am] == r[am] else None})
    return out


def normalize(rows: list[dict], units: float = 1.0) -> dict:
    """PDF 행 → {종목코드: {n: 이름, s: 1CU당 주식 수, w: 주식 내 비중}}. 주식만, 수량 0 제외."""
    st = [r for r in rows if is_stock(r.get("code")) and (r.get("shares") or 0) > 0]
    tot = sum(r.get("amount") or 0 for r in st) or 0.0
    u = units or 1.0
    return {r["code"]: {"n": r.get("name") or r["code"], "s": round(r["shares"] / u, 4),
                        "w": round((r.get("amount") or 0) / tot, 5) if tot else None} for r in st}


# ---------------------------------------------------------------- diff
def diff(prev: dict, cur: dict, *, real_chg: float = REAL_CHG) -> list[dict]:
    """한 ETF 의 전일·당일 정규화 보유 비교 → 이벤트. kind: new / exit / up / down. 1CU 당 주식 수 기준(자금 유입 효과 없음)."""
    ev = []
    for c, h in cur.items():
        p = prev.get(c)
        if p is None:
            ev.append({"stock": c, "name": h["n"], "kind": "new", "w": h.get("w"),
                       "trial": (h.get("w") or 0) < MIN_WEIGHT_NEW})
            continue
        s0, s1 = p.get("s") or 0, h.get("s") or 0
        if s0 <= 0:
            continue
        r = s1 / s0
        if abs(r - 1) < real_chg:
            continue
        e = {"stock": c, "name": h["n"], "kind": "up" if r > 1 else "down", "chg": round(r - 1, 4),
             "w0": p.get("w"), "w": h.get("w")}
        if _split_like(r):
            e["split_suspect"] = True
        ev.append(e)
    for c, p in prev.items():
        if c not in cur:
            ev.append({"stock": c, "name": p["n"], "kind": "exit", "w0": p.get("w")})
    return ev


def _split_like(r: float) -> bool:
    """수량 비율이 2·3·4·5·10배(또는 역수)에 1% 안으로 붙으면 액면분할·병합 의심."""
    for k in (2, 3, 4, 5, 10, 20, 50):
        if abs(r - k) / k < 0.01 or abs(r - 1 / k) * k < 0.01:
            return True
    return False


def consensus(events: list[dict], days: list[str], universe: set[str] | None = None) -> list[dict]:
    """최근 days(거래일) 안의 이벤트를 종목별로: 실질 매수(new·up) ETF 수 − 매도(down·exit) ETF 수. 분할 의심·시범 편입 제외."""
    dset = set(days)
    agg: dict[str, dict] = {}
    for e in events:
        if e.get("date") not in dset or e.get("split_suspect") or e.get("trial"):
            continue
        a = agg.setdefault(e["stock"], {"stock": e["stock"], "name": e.get("name"), "buy": set(), "sell": set()})
        (a["buy"] if e["kind"] in ("new", "up") else a["sell"]).add(e["etf"])
    out = []
    for a in agg.values():
        b, s = sorted(a["buy"]), sorted(a["sell"])
        out.append({"stock": a["stock"], "name": a["name"], "n_buy": len(b), "n_sell": len(s), "net": len(b) - len(s),
                    "buy_etfs": b, "sell_etfs": s, "in_universe": (a["stock"] in universe) if universe is not None else None})
    out.sort(key=lambda x: (-x["net"], -x["n_buy"], x["stock"]))
    return out


# ---------------------------------------------------------------- 실행
def _universe() -> set[str]:
    p = UNIVERSE_DIR / "kr.csv"
    try:
        with p.open(encoding="utf-8") as f:
            return {r["symbol"].zfill(6) for r in csv.DictReader(f) if r.get("symbol")}
    except Exception:  # noqa: BLE001
        return set()


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def step(snap: dict, log_obj: dict, fetched: dict[str, dict], asof: str, *, universe: set[str] | None = None,
         keep_days: int = KEEP_DAYS, cons_days: int = CONSENSUS_DAYS) -> tuple[dict, dict]:
    """순수 로직(네트워크 없음): 이전 스냅샷 + 이번 수집(fetched: ETF코드 → 정규화 보유, 실패는 키 없음) → (새 스냅샷, 새 로그).
    같은 asof 를 다시 돌리면 이벤트를 중복 추가하지 않는다(멱등)."""
    funds = dict(snap.get("funds") or {})
    events = list(log_obj.get("events") or [])
    status = {}
    for t in TARGETS:
        c = t["code"]
        cur = fetched.get(c)
        old = funds.get(c)
        if not cur:
            status[c] = "미수집(이전 유지)" if old else "미수집"
            continue
        if old and old.get("asof", "") >= asof:
            status[c] = "같은 날(기존 이벤트 유지)"   # 재실행 멱등: 다시 diff 하지 않음
            continue
        if old:
            for e in diff(old.get("h") or {}, cur):
                events.append({"date": asof, "etf": c, "etf_name": t["name"], "prev": old["asof"], **e})
            status[c] = "diff"
        else:
            status[c] = "첫 스냅샷"
        funds[c] = {"asof": asof, "h": cur}
    days = sorted({e["date"] for e in events}, reverse=True)[:keep_days]
    events = [e for e in events if e["date"] in set(days)]
    events.sort(key=lambda e: (e["date"], e["etf"], e["kind"], e["stock"]), reverse=True)
    cdays = days[:cons_days]
    ok = sum(1 for v in status.values() if not v.startswith("미수집"))
    new_snap = {"asof": asof, "funds": funds}
    out = {"asof": asof, "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
           "status": "ok" if ok == len(TARGETS) else ("partial" if ok else "fail"),
           "n_targets": len(TARGETS), "n_fetched": ok, "fund_status": status,
           "method": "1CU 당 주식 수 변화 ±%d%% = 실질 증감(자금 유입 무관), 신규 비중 %.1f%% 미만 = 시범 편입(합의 제외), 분할 의심 제외"
                     % (REAL_CHG * 100, MIN_WEIGHT_NEW * 100),
           "targets": [{k: t[k] for k in ("code", "name", "issuer", "kind")} for t in TARGETS],
           "consensus_days": cdays, "consensus": consensus(events, cdays, universe)[:50],
           "events": events}
    return new_snap, out


def run(ymd: str | None = None) -> dict:
    from . import guard
    ymd = ymd or datetime.now(KST).strftime("%Y%m%d")
    asof = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
    fetched = {}
    for t in TARGETS:
        rows = fetch_pdf(t["code"], ymd)
        h = normalize(rows)
        if h:
            fetched[t["code"]] = h
        time.sleep(0.3)
    snap, logo = _load(SNAP), _load(OUT)
    if not fetched:
        guard.record_stale(str(OUT), "액티브 ETF PDF 전부 미수집", asof, logo.get("asof"))
        log.warning("액티브 ETF PDF 0/%d — 저장 안 함", len(TARGETS))
        return {"status": "fail", "asof": asof, "n_fetched": 0}
    new_snap, out = step(snap, logo, fetched, asof, universe=_universe())
    if out["status"] != "ok":
        guard.record_stale(str(OUT), f"액티브 ETF PDF {out['n_fetched']}/{len(TARGETS)} 수집", asof, asof)
    if guard.write_json(OUT, out, key="asof", indent=1):
        guard.write_json(SNAP, new_snap, key="asof", separators=(",", ":"))
    log.info("액티브 ETF %s: %d/%d 수집, 이벤트 %d", asof, out["n_fetched"], len(TARGETS),
             sum(1 for e in out["events"] if e["date"] == asof))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYYMMDD (기본 오늘 KST)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    r = run(a.date)
    print(json.dumps({k: r.get(k) for k in ("asof", "status", "n_fetched")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
