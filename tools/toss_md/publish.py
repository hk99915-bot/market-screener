"""토스 수집분 → 공개용 요약 publish (겸이 노트북 → 저장소). 2026-10-21 겸이 "지금부터 시작해" · 약관 '허용'(재배포·자동수집).

    python tools/toss_md/collect.py --group intraday --publish        # 수집 끝에 자동 호출(작업 스케줄러)
    python tools/toss_md/publish.py                                   # 단독 실행(오늘 수집분)
    python tools/toss_md/publish.py --dry-run                         # _dryrun 수집분으로 미리보기(저장소·git 안 건드림)
    python tools/toss_md/publish.py --shape                           # 수집 파일의 '키 구조'만 출력(값 없음) — 파서 고칠 때 PB 에 전달

만드는 것 — 전용 데이터 브랜치 `toss-live` 루트에 두 파일만 (main 엔 커밋 안 함, 10/21 PB 설계 변경):
- live.json       현재값(market-indicators/prices: KOSPI·KOSDAQ·국채 2~30Y % 수익률) · KOSPI·KOSDAQ 당일 1분봉 OHLC(압축,
                  키 = 봉 **시작** 시각 HH:MM) · 시장 투자자별 순매수(개인·외국인·기관·기타법인 합계만) · USDKRW midRate(매매기준율)
                  · 휴장 달력 요약 · asof/generated_at/published_at/source='toss'
- crosscheck.json 최근 7거래일 토스 vs 기존 소스 괴리(괴리율·판정만, 원값 없음)
- sectors.json    토스 섹터 계층 + 종목→말단 섹터(다중) — 하루 1회(10/21)
- daily_bars.json 지수·국채·미장 지표 ETF 일봉 과거분(마지막 봉 제외, ≤520봉) — 새 날짜가 생길 때만 바뀜(10/21)
- daily_today.json 키별 마지막 일봉 1개 — 10분 회차마다(10/21)
넣지 않는 것: 원시 호가·체결·종목 시세, 계좌·토큰·키, 토스 rate(고객 매수환율), API 주소.
터미널은 raw.githubusercontent.com/<저장소>/toss-live/live.json 을 직접 읽는다(screener/toss_live.py · 화면 tab_market/tab_detail).

커밋 규칙 (겸이 "최대한 최신" + PM 저장소 용량 경고 10/21):
- 수집 회차마다(10분) publish, 내용 서명이 직전과 같으면 커밋 안 함. --min-interval 로 간격을 둘 수 있음(기본 0).
- 커밋은 작업 트리·main 을 건드리지 않는 plumbing(hash-object→mktree→commit-tree, 부모 = 원격 끝) → **일반 push** 만.
  force push·이력 재작성 없음. 거절되면 다시 받아 1회 재시도, 그래도 실패면 heartbeat publish.pending → 다음 회차.
- 정렬·고정 포맷(봉 1줄 1개)이라 회차 diff 는 몇 줄. live.json 은 당일분만, 200KB 상한(넘으면 봉 솎기).
- 커밋 신원은 봇(toss-md) — 노트북 git 설정(겸이 개인 이메일)을 쓰지 않는다. 메시지 접두 'toss:'.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screener import contracts, guard, tradecal  # noqa: E402
from tools.toss_md import collect, crosscheck  # noqa: E402

KST = collect.KST
BRANCH = "toss-live"
REMOTE_REF = f"refs/remotes/origin/{BRANCH}"
CONTRACT_PATH = "toss_md/live.json"   # screener/contracts.py 계약 키 (브랜치 파일이지만 같은 계약으로 검사)
MIN_INTERVAL_MIN = 0            # 최소 publish 간격(분). 0 = 수집 회차마다(변화 있을 때만)
SLACK_SEC = 90                  # 작업 스케줄러 지터 허용
MAX_BYTES = 200_000             # live.json 크기 상한
XC_DAYS = 7                     # crosscheck 요약 거래일 수
XC_AFTER = time(16, 0)          # 이 시각 이후 그날 crosscheck 자동 계산 (macro_series 종가가 16:20~ 갱신 → 18:30 회차가 실질)
KR_OPEN, KR_FINAL = time(9, 0), time(15, 40)   # 장중 판정 창 (15:30 마감 + 동시호가·마지막 봉 10분)
BOT_NAME, BOT_EMAIL = "toss-md", "toss-md-bot@users.noreply.github.com"

# 공개 파일 금지 키 — 원시 호가·체결·계좌·토큰·토스 rate(매수환율)
FORBIDDEN_KEYS = {"orderbook", "bids", "asks", "bid", "ask", "trades", "account", "accountno", "accountnumber",
                  "access_token", "token", "client_id", "client_secret", "holdings", "rate", "buyrate", "sellrate",
                  "endpoint", "params"}

log = logging.getLogger("toss_md.publish")

_OPEN_K, _HIGH_K, _LOW_K = ("open", "openPrice"), ("high", "highPrice"), ("low", "lowPrice")
_PREV_K = ("prevClose", "previousClose", "prevClosePrice", "previousClosePrice", "basePrice")
_DATE_K = ("baseDate", "date", "tradeDate", "businessDate")
_LABEL_K = ("investor", "investorType", "investorCode", "type", "name", "category")
_VALUE_K = ("netBuyValue", "netValue", "netBuyAmount", "netTradingValue", "netAmount", "netBuy")
INVESTORS = {   # 출력 4칸 ← 라벨(정규화: 대문자·공백/하이픈→_) — 기관 세부(금융투자·연기금 …)는 일부러 안 받는다
    "개인": {"INDIVIDUAL", "INDIVIDUALS", "RETAIL", "PERSONAL", "개인"},
    "외국인": {"FOREIGN", "FOREIGNER", "FOREIGNERS", "FOREIGN_INVESTOR", "외국인"},
    "기관": {"INSTITUTION", "INSTITUTIONS", "INSTITUTIONAL", "INSTITUTION_TOTAL", "기관", "기관계", "기관합계"},
    "기타법인": {"OTHER_CORPORATION", "OTHER_CORPORATIONS", "OTHER_CORP", "CORPORATION", "기타법인"},
}
_FIELD_P = {"개인": ("individual", "retail", "personal"), "외국인": ("foreign", "foreigner"),
            "기관": ("institution", "institutional"), "기타법인": ("othercorporation", "othercorp")}
_BUY_K, _SELL_K = ("buyAmount", "buyValue", "buyTradingAmount"), ("sellAmount", "sellValue", "sellTradingAmount")
_FIELD_S = ("netbuyvalue", "netvalue", "netbuyamount", "nettradingvalue", "netbuy")


# ── 파싱 (응답 구조를 다 모르므로 키 후보로 찾는다 — 실제 구조는 --shape 로 확인) ─────────────────
def to_kst(v) -> datetime | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        sec = v / 1000 if v > 1e11 else v
        try:
            return datetime.fromtimestamp(sec, KST)
        except (OverflowError, OSError, ValueError):
            return None
    return guard.stamp(v) if isinstance(v, str) else None


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def bars(data, day: str) -> list[list]:
    """그날(KST) 1분봉 → [["HH:MM", o, h, l, c], …] (분 단위 중복 제거, 시각순)."""
    by = {}
    for d in crosscheck._dicts(data):
        k = collect._row_key(d)
        if not k:
            continue
        t = to_kst(d.get(k))
        c = crosscheck._num(d, crosscheck._CLOSE_KEYS)
        if t is None or c is None or t.strftime("%Y-%m-%d") != day:
            continue
        o, h, lo = (crosscheck._num(d, ks) for ks in (_OPEN_K, _HIGH_K, _LOW_K))
        by[t.strftime("%H:%M")] = [t.strftime("%H:%M"), _r(o if o is not None else c), _r(h if h is not None else c),
                                   _r(lo if lo is not None else c), _r(c)]
    return [by[k] for k in sorted(by)]


def prev_close(data) -> float | None:
    for d in crosscheck._dicts(data):
        if collect._row_key(d) and crosscheck._num(d, crosscheck._CLOSE_KEYS) is not None:
            continue   # 봉 행은 건너뜀
        v = crosscheck._num(d, _PREV_K)
        if v is not None:
            return v
    return None


def _norm(s) -> str:
    return re.sub(r"[\s\-]+", "_", str(s).strip()).upper()


def _date_of(d: dict) -> str | None:
    for k in _DATE_K:
        v = d.get(k)
        if isinstance(v, str) and guard.day(v):
            return guard.kst_day(v)
    return None


def flows(data) -> dict | None:
    """시장 투자자별 순매수 최신 1일 → {date, status, 개인, 외국인, 기관, 기타법인 (억원), unit_basis}. 해석 못 하면 None.
    두 꼴 허용: ① OpenAPI 원문 result.records[]{date, individual{buyAmount,sellAmount}, foreigner, institution{…,breakdown}, otherCorporation}
    (net = buy−sell, 기관 breakdown 세부는 안 받음) ② 라벨+netBuyValue 행 / <투자자>NetBuyValue 필드 (예전 추정 꼴)."""
    if data is None:
        return None
    dated = [(dt, d) for d in crosscheck._dicts(data) if (dt := _date_of(d))]
    latest = max((dt for dt, _ in dated), default=None)
    scope = [d for dt, d in dated if dt == latest] if latest else [data]
    raw: dict[str, float] = {}
    status = None
    for root in scope:
        for d in crosscheck._dicts(root):
            if status is None and isinstance(d.get("status"), str):
                status = d["status"]
            lab = next((d[k] for k in _LABEL_K if isinstance(d.get(k), str)), None)
            if lab is not None:
                cat = next((c for c, labs in INVESTORS.items() if _norm(lab) in labs), None)
                v = crosscheck._num(d, _VALUE_K)
                if cat and v is not None:
                    raw.setdefault(cat, v)
            for key, val in d.items():
                kl = str(key).lower()
                for cat, pre in _FIELD_P.items():
                    if any(kl == p + s for p in pre for s in _FIELD_S):
                        v = crosscheck._num(d, (key,))
                        if v is not None:
                            raw.setdefault(cat, v)
                    elif kl in pre and isinstance(val, dict):
                        v = crosscheck._num(val, _VALUE_K)
                        if v is None:   # OpenAPI 원문: {buyAmount, sellAmount} KRW 정수 문자열, net 없음 → buy−sell (10/21 PB)
                            b, s_ = crosscheck._num(val, _BUY_K), crosscheck._num(val, _SELL_K)
                            v = b - s_ if b is not None and s_ is not None else None
                        if v is not None:
                            raw.setdefault(cat, v)
    if not raw:
        return None
    mx = max(abs(v) for v in raw.values())
    # 단위 추정 [검증전 — 첫 실데이터를 pykrx 확정치와 대조해 확정, 10/24까지]: 시장 하루 순매수는 수백~수만 억원
    div, basis = (1e8, "원→억원") if mx >= 1e8 else (1e2, "백만원→억원") if mx >= 1e4 else (1.0, "억원 그대로")
    out = {c: (_r(raw[c] / div, 1) if c in raw else None) for c in INVESTORS}
    out.update({"date": latest, "status": status, "unit": "억원", "unit_basis": basis})
    return out


_SYM_K = ("symbol", "code", "indicator", "symbolCode")
_PRICE_K = ("price", "lastPrice", "currentPrice", "close", "closePrice", "value")


def quotes(data) -> dict:
    """market-indicators/prices → {심볼: {last, asof}} (국채는 % 수익률). 해석 못 하면 빈 dict."""
    out = {}
    for d in crosscheck._dicts(data):
        sym = next((d[k] for k in _SYM_K if isinstance(d.get(k), str)), None)
        v = crosscheck._num(d, _PRICE_K)
        if not sym or v is None or sym in out:
            continue
        t = to_kst(collect.find_asof(d))
        out[sym] = {"last": _r(v, 4 if "BOND" in sym.upper() else 2), "asof": t.isoformat(timespec="seconds") if t else None}
    return out


def fx_mid(data) -> dict | None:
    m = crosscheck.fx_rate(data)   # midRate 만 (crosscheck._RATE_KEYS)
    if m is None:
        return None
    vf = next((d.get("validFrom") for d in crosscheck._dicts(data) if isinstance(d.get("validFrom"), str)), None)
    return {"mid": _r(m, 2), "asof": vf or collect.find_asof(data)}   # validFrom = 환율 고시 시각(원문) — 10/21 asof null 수정


def calendar(data, today: str) -> dict | None:
    days = crosscheck.calendar_days(data)
    if not days:
        return None
    return {"today_open": days.get(today), "closed_next": [d for d in sorted(days) if d >= today and not days[d]][:5]}


# ── 요약 만들기 ──────────────────────────────────────────────────────────
def _load(day_dir: Path, name: str):
    f = day_dir / f"{name}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("data")
    except Exception:  # noqa: BLE001
        return None


def bar_days(data) -> set[str]:
    out = set()
    for d in crosscheck._dicts(data):
        k = collect._row_key(d)
        t = to_kst(d.get(k)) if k else None
        if t and crosscheck._num(d, crosscheck._CLOSE_KEYS) is not None:
            out.add(t.strftime("%Y-%m-%d"))
    return out


def _bar_src(base: Path, today: date) -> tuple[Path | None, str | None]:
    """1분봉이 있는 가장 최근 (폴더, 봉 날짜). 개장 전 오늘 폴더엔 전 거래일 봉만 있다(200봉) → 그 날짜를 그대로 쓴다."""
    for i in range(8):
        folder = base / (today - timedelta(days=i)).isoformat()
        ds = bar_days(_load(folder, "kospi_1m")) | bar_days(_load(folder, "kosdaq_1m"))
        ds = {d for d in ds if d <= today.isoformat()}
        if ds:
            return folder, max(ds)
    return None, None


def build(base: Path, now: datetime) -> dict:
    today = now.astimezone(KST).date()
    tday = today.isoformat()
    bdir, bday = _bar_src(base, today)
    missing, asofs = [], []
    doc: dict = {"source": "toss", "date": bday or tday, "generated_at": now.isoformat(timespec="seconds"),
                 "indices": {}, "flows": {}, "fx": {}, "calendar": {},
                 "note": "토스증권 Open API 시세 요약(공개용). 원시 호가·체결·계좌 없음. 환율=매매기준율(mid)."}
    for key, name in (("KOSPI", "kospi_1m"), ("KOSDAQ", "kosdaq_1m")):
        data = _load(bdir, name) if bdir else None
        b = bars(data, bday) if bday else []
        if not b:
            missing.append(f"{key} 1분봉 없음")
            continue
        pc = prev_close(data)
        ts = f"{bday}T{b[-1][0]}:00+09:00"
        asofs.append(ts)
        doc["indices"][key] = {"asof": ts, "last": b[-1][4], "open": b[0][1], "high": max(x[2] for x in b),
                               "low": min(x[3] for x in b), "prev_close": _r(pc), "chg": _r(b[-1][4] / pc - 1, 5) if pc else None,
                               "n": len(b), "bars": b}
    q = {}
    for i in range(4):
        folder = base / (today - timedelta(days=i)).isoformat()
        q = quotes(_load(folder, "indicator_prices"))
        if q:   # 10/21 실측: indicator prices 의 timestamp 가 None → asof = 수집 시각(generated_at)
            try:
                gen = json.loads((folder / "indicator_prices.json").read_text(encoding="utf-8")).get("generated_at")
            except Exception:  # noqa: BLE001
                gen = None
            g = to_kst(gen) if gen else None
            for v in q.values():
                if not v.get("asof") and g:
                    v["asof"], v["asof_src"] = g.isoformat(timespec="seconds"), "수집 시각"
        if q:
            break
    doc["quotes"] = q
    if not q:
        missing.append("현재값(market-indicators/prices) 없음/해석 실패")
    for key, v in q.items():
        if key in doc["indices"] and v.get("asof") and v["asof"] >= doc["indices"][key]["asof"]:
            doc["indices"][key]["last"] = v["last"]   # 현재값은 prices 가 캔들보다 빠르다(원문 10/21)
            doc["indices"][key]["asof"] = v["asof"]
            pc = doc["indices"][key]["prev_close"]
            doc["indices"][key]["chg"] = _r(v["last"] / pc - 1, 5) if pc else None
        if key in ("KOSPI", "KOSDAQ") and v.get("asof"):
            asofs.append(v["asof"])
    for key, name in (("KOSPI", "investor_value"), ("KOSDAQ", "investor_value_kq")):
        f = flows(_load(base / tday, name)) or (flows(_load(bdir, name)) if bdir and bdir.name != tday else None)
        if f:
            doc["flows"][key] = f
        else:
            missing.append(f"{key} 투자자별 매매대금 없음/해석 실패")
    fx = None
    for i in range(4):   # 자정 뒤·개장 전 첫 수집 전엔 최근 폴더 값(asof 가 그대로라 신선도 판정은 화면·서버가 한다)
        fx = fx_mid(_load(base / (today - timedelta(days=i)).isoformat(), "usdkrw"))
        if fx:
            break
    if fx:
        doc["fx"]["USDKRW"] = fx
        if fx.get("asof"):
            t = to_kst(fx["asof"])
            if t:
                fx["asof"] = t.isoformat(timespec="seconds")
                asofs.append(fx["asof"])
    else:
        missing.append("USDKRW midRate 없음")
    for mk, name in (("KR", "calendar_kr"), ("US", "calendar_us")):
        c = None
        for i in range(8):   # 달력은 하루 2번만 받으므로 최근 폴더
            c = calendar(_load(base / (today - timedelta(days=i)).isoformat(), name), tday)
            if c:
                break
        if c:
            doc["calendar"][mk] = c
    krp = None
    for i in range(4):
        krp = _load(base / (today - timedelta(days=i)).isoformat(), "kr_prices")
        if krp:
            break
    if krp:   # 국장 종목·ETF 현재가 (10/21 "ETF도 트래킹되지?")
        kq, ku, kw = quote_block(krp, "KR", load_bases(base, today))
        doc["kr_quotes"] = {s: v for s, v in kq.items() if len(s) == 6 or s.startswith("A")}
        doc["kr_meta"] = {"chg_unit": {"raw": ku, "basis": kw}, "_keys": keys_of(krp), "etfs": list(collect.KR_ETFS)}
    us = build_us(base, now)
    if us:
        doc["us"] = us
    doc["missing"] = missing
    ts_all = [t for t in (to_kst(a) for a in asofs) if t]
    doc["asof"] = max(ts_all).isoformat(timespec="seconds") if ts_all else doc["generated_at"]
    return doc


# ── 미장 블록 (10/21 'us' 그룹) ───────────────────────────────────────────
US_TOP = 20   # 랭킹·섹터 랭킹 상위 몇 개를 공개하나
_CHG_K = ("changeRate", "changePercent", "fluctuationRate")
_AMT_K = ("tradingAmount", "tradingValue", "amount")
_NAME_K = ("name", "stockName", "displayName", "koreanName", "symbolName", "companyName", "englishName")
# 10/21 01:19 첫 실데이터: us.quotes 200개 chg_pct 전부 null · rank 의 n·last·chg null(키 이름 불일치) → 키 이름을 정규식으로 찾고
# 중첩 dict(예: price{…})도 본다. 실제 키 이름은 live.json us._keys 에 '이름만' 남긴다(값 없음, --shape 대용).
_RE_CHG = re.compile(r"(chang|fluct).*(rate|ratio|percent|pct)|(rate|ratio|percent|pct).*(chang|fluct)", re.I)
_RE_PREV = re.compile(r"(prev|previous|base|yesterday|before|reference).*(close|price)|^(basePrice|prevClose|previousClose)$", re.I)
_RE_DIFF = re.compile(r"^(change|changeAmount|changePrice|priceChange|netChange|compareToPreviousClosePrice|diff|difference)$", re.I)
_RE_PRICE = re.compile(r"^(price|lastPrice|currentPrice|close|closePrice|tradePrice|last|value)$", re.I)
_RE_NAME = re.compile(r"name$", re.I)
# 등락률 단위: 응답에서 (등락률, 현재가, 전일가)가 같이 있으면 판정, 없으면 기본 'ratio'
# [추정 근거: 10/21 01:19 섹터 '상승 상위' 1·2위 값 0.04·0.04 — %라면 상위 섹터가 +0.04% 라는 뜻이라 비현실적. --shape·대조로 확정, 10/24까지]
DEFAULT_CHG_UNIT = "ratio"


def _flat(d: dict, depth: int = 2) -> dict:
    """행 dict + 중첩 dict 의 잎 키(같은 이름이면 바깥 우선)."""
    out = {}
    if depth < 0 or not isinstance(d, dict):
        return out
    for k, v in d.items():
        if not isinstance(v, (dict, list)):
            out.setdefault(k, v)
    for k, v in d.items():
        if isinstance(v, dict):
            for k2, v2 in _flat(v, depth - 1).items():
                out.setdefault(k2, v2)
    return out


def _numv(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return None
    return None


def _find(f: dict, rx, exclude=None):
    for k, v in f.items():
        if rx.search(str(k)) and not (exclude and exclude.search(str(k))):
            x = _numv(v)
            if x is not None:
                return x
    return None


def row_fields(d: dict) -> dict:
    """한 행 → {name, last, chg_raw, prev, diff, amt} (값 못 찾으면 None)."""
    f = _flat(d)
    last = next((x for x in (_numv(f.get(k)) for k in _PRICE_K) if x is not None), None)
    if last is None:
        last = _find(f, _RE_PRICE)
    nm = next((f[k] for k in _NAME_K if isinstance(f.get(k), str) and f[k].strip()), None)
    if nm is None:
        nm = next((v for k, v in f.items() if _RE_NAME.search(str(k)) and isinstance(v, str) and v.strip() and not str(k).lower().startswith("sector")), None)
    return {"name": nm, "last": last, "chg_raw": _find(f, _RE_CHG), "prev": _find(f, _RE_PREV),
            "diff": _find(f, _RE_DIFF), "amt": next((x for x in (_numv(f.get(k)) for k in _AMT_K) if x is not None), None)}


def chg_unit(rows: list[dict]) -> tuple[str, str]:
    """(단위 'ratio'|'pct', 근거). 현재가·전일가가 같이 있는 행으로 다수결."""
    votes = {"ratio": 0, "pct": 0}
    for r in rows:
        c, last, prev = r.get("chg_raw"), r.get("last"), r.get("prev")
        if prev is None and last is not None and r.get("diff") is not None:
            prev = last - r["diff"]
        if c is None or not last or not prev:
            continue
        x = last / prev - 1
        if abs(x) < 1e-6 and abs(c) < 1e-6:
            continue
        votes["ratio" if abs(c - x) <= abs(c - x * 100) else "pct"] += 1
    if votes["ratio"] or votes["pct"]:
        u = "ratio" if votes["ratio"] >= votes["pct"] else "pct"
        return u, f"응답 판정({votes['ratio']}:{votes['pct']})"
    return DEFAULT_CHG_UNIT, "기본값(추정)"


def chg_pct(r: dict, unit: str) -> float | None:
    """등락률(%) — 등락률 키 → 없으면 전일가/변동폭으로 계산."""
    if r.get("chg_raw") is not None:
        return _r(r["chg_raw"] * (100 if unit == "ratio" else 1), 3)
    last, prev = r.get("last"), r.get("prev")
    if prev is None and last is not None and r.get("diff") is not None:
        prev = last - r["diff"]
    return _r((last / prev - 1) * 100, 3) if last and prev else None


def keys_of(data, want: str = "symbol") -> list[str]:
    """진단용: want 키가 있는 첫 행의 키 이름(중첩은 a.b) — 값은 없음."""
    for d in crosscheck._dicts(data):
        if want in d:
            ks = []
            for k, v in d.items():
                ks += [f"{k}.{k2}" for k2 in v] if isinstance(v, dict) else [k]
            return sorted(ks)[:40]
    return []


def price_rows(data) -> dict[str, dict]:
    """/api/v1/prices → {심볼: row_fields}."""
    out = {}
    for d in crosscheck._dicts(data) if data is not None else []:
        sym = next((d[k] for k in _SYM_K if isinstance(d.get(k), str)), None)
        if not sym or sym in out:
            continue
        r = row_fields(d)
        if r["last"] is None:
            continue
        t = to_kst(collect.find_asof(d))
        r["asof"] = t.isoformat(timespec="seconds") if t else None
        out[sym] = r
    return out


def session_day(mk: str, asof: str | None) -> str | None:
    """시세 시각 → 그 시세가 속한 거래 세션 날짜. KR = KST 날짜, US = ET 날짜(20:00 ET 이후 데이마켓은 다음 날 세션)."""
    t = to_kst(asof) if asof else None
    if t is None:
        return None
    if mk == "KR" or collect.ET is None:
        return t.astimezone(KST).date().isoformat()
    e = t.astimezone(collect.ET)
    return (e.date() + timedelta(days=1)).isoformat() if (e.hour, e.minute) >= collect.US_DAY_START_ET else e.date().isoformat()


def base_from_cache(closes: list | None, sday: str | None) -> float | None:
    """[[날짜, 종가], …] 에서 세션 날짜보다 앞선 마지막 종가 = 기준가(전일 종가)."""
    if not closes or not sday:
        return None
    prev = [c for d, c in closes if d < sday]
    return float(prev[-1]) if prev else None


def quote_block(data, mk: str = "US", bases: dict | None = None, ref: dict | None = None,
                unit_hint: str | None = None) -> tuple[dict, str, str]:
    """prices → ({심볼: {last, chg_pct, base_src, asof}}, 단위, 근거).
    /prices 에는 등락률·기준가가 없다(10/21 실측) → 기준가 = 랭킹 price.basePrice(ref, 같은 회차) → 일봉 캐시(bases.json) 순."""
    rows = price_rows(data)
    unit, why = chg_unit(list(rows.values()) + list((ref or {}).values()))
    if unit_hint and why.startswith("기본값"):
        unit = unit_hint
    out = {}
    for s_, r in rows.items():
        src = "응답"
        if r["chg_raw"] is None and r["prev"] is None and r["diff"] is None:
            rr = (ref or {}).get(s_) or {}
            if rr.get("prev"):
                r = {**r, "prev": rr["prev"]}
                src = "랭킹 basePrice"
            else:
                b = base_from_cache(((bases or {}).get(mk) or {}).get(s_), session_day(mk, r["asof"]))
                r = {**r, "prev": b}
                src = "일봉 캐시" if b else None
        out[s_] = {"last": _r(r["last"], 4), "chg_pct": chg_pct(r, unit), "base_src": src if chg_pct(r, unit) is not None else None,
                   "asof": r["asof"]}
    return out, unit, why


def rank_ref(*datas) -> dict:
    """랭킹 응답들 → {심볼: row_fields} (기준가·단위 판정용)."""
    out = {}
    for data in datas:
        for d in crosscheck._dicts(data) if data is not None else []:
            sym = next((d[k] for k in _SYM_K if isinstance(d.get(k), str)), None)
            if sym and sym not in out:
                r = row_fields(d)
                if r["last"] is not None or r["prev"] is not None:
                    out[sym] = r
    return out


def load_bases(base: Path, today: date) -> dict | None:
    for i in range(4):
        b = _load(base / (today - timedelta(days=i)).isoformat(), "bases")
        if b:
            return b
    return None


def _latest(base: Path, today: date, name: str, days: int = 2):
    """오늘·어제 폴더 중 asof 가 늦은 수집분의 data (미장은 KST 자정을 넘긴다)."""
    best, best_t = None, ""
    for i in range(days):
        f = base / (today - timedelta(days=i)).isoformat() / f"{name}.json"
        if not f.exists():
            continue
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        t = str(rec.get("generated_at") or "")
        if t > best_t:
            best, best_t = rec.get("data"), t
    return best


def us_bars(datas: list) -> tuple[str | None, list[list]]:
    """미장 1분봉 여러 수집분 → (ET 날짜, [["HH:MM"(ET, 봉 종료 시각), o, h, l, c], …]) 가장 늦은 ET 거래일만."""
    by: dict[str, dict] = {}
    for data in datas:
        for d in crosscheck._dicts(data):
            k = collect._row_key(d)
            t = to_kst(d.get(k)) if k else None
            c = crosscheck._num(d, crosscheck._CLOSE_KEYS)
            if t is None or c is None or collect.ET is None:
                continue
            e = t.astimezone(collect.ET)
            o, h, lo = (crosscheck._num(d, ks) for ks in (_OPEN_K, _HIGH_K, _LOW_K))
            by.setdefault(e.date().isoformat(), {})[e.strftime("%H:%M")] = [
                e.strftime("%H:%M"), _r(o if o is not None else c), _r(h if h is not None else c), _r(lo if lo is not None else c), _r(c)]
    if not by:
        return None, []
    day = max(by)
    return day, [by[day][k] for k in sorted(by[day])]


def _rank_rows(data, n: int = US_TOP, unit: str = DEFAULT_CHG_UNIT, quotes: dict | None = None) -> list[dict]:
    """랭킹 행 → [{s, n, last, chg_pct, amt}]. 랭킹 응답에 가격·등락이 없으면 같은 회차 prices(quotes)로 채운다."""
    out, seen = [], set()
    for d in crosscheck._dicts(data):
        sym = next((d[k] for k in _SYM_K if isinstance(d.get(k), str)), None)
        if not sym or sym in seen:
            continue
        r = row_fields(d)
        if r["last"] is None and r["chg_raw"] is None and r["amt"] is None:
            continue
        seen.add(sym)
        q = (quotes or {}).get(sym) or {}
        last = r["last"] if r["last"] is not None else q.get("last")
        c = chg_pct(r, unit)
        out.append({"s": sym, "n": r["name"], "last": _r(last), "chg_pct": c if c is not None else q.get("chg_pct"),
                    "amt": _r(r["amt"], 0)})
        if len(out) >= n:
            break
    return out


def _sector_rank(data, n: int = US_TOP, unit: str = DEFAULT_CHG_UNIT) -> list[dict]:
    out, seen = [], set()
    for d in crosscheck._dicts(data):
        sid = d.get("sectorId")
        if sid is None or str(sid) in seen:
            continue
        seen.add(str(sid))
        r = row_fields(d)
        out.append({"id": str(sid), "name": d.get("name") or d.get("sectorName"), "chg_pct": chg_pct(r, unit)})
        if len(out) >= n:
            break
    return out


def build_us(base: Path, now: datetime) -> dict | None:
    """live.json 'us' 블록: 지표 ETF·대형주 현재가 · SPY/QQQ/SOXX 1분봉 · 랭킹 상위 20 · 섹터 랭킹. 수집분이 하나도 없으면 None."""
    today = now.astimezone(KST).date()
    missing, asofs = [], []
    pr = _latest(base, today, "us_prices")
    rk = {k: _latest(base, today, n) for k, n in (("amount", "us_rank_amount"), ("gainers", "us_rank_gainers"), ("losers", "us_rank_losers"))}
    q, unit, unit_why = quote_block(pr, "US", load_bases(base, today), rank_ref(*rk.values()))
    asofs += [t for t in (to_kst(v["asof"]) for v in q.values()) if t]
    if not q:
        missing.append("미장 현재가(prices) 없음/해석 실패")
    spark = {}
    for sym in collect.US_SPARK:
        datas = [x for x in (_latest(base, today - timedelta(days=i), f"us_{sym.lower()}_1m", 1) for i in range(2)) if x is not None]
        day, b = us_bars(datas)
        if b:
            spark[sym] = {"date": day, "n": len(b), "bars": b, "tz": "ET", "stamp": "봉 종료 시각"}
        else:
            missing.append(f"{sym} 1분봉 없음")
    ranks = {}
    for key, name in (("amount", "us_rank_amount"), ("gainers", "us_rank_gainers"), ("losers", "us_rank_losers")):
        rows = _rank_rows(rk[key], unit=unit, quotes=q)
        if rows:
            ranks[key] = rows
        else:
            missing.append(f"랭킹 {key} 없음")
    srank_data = _latest(base, today, "us_sector_rank")
    srank = _sector_rank(srank_data, unit=unit)
    if not srank:
        missing.append("섹터 랭킹 없음")
    if not (q or spark or ranks or srank):
        return None
    sess = None
    cal = None
    for i in range(8):
        cal = _load(base / (today - timedelta(days=i)).isoformat(), "calendar_us")
        if cal:
            break
    if cal and collect.ET is not None:
        d0 = now.astimezone(collect.ET).date()
        for dd in (d0, d0 + timedelta(days=1)):
            w = collect.calendar_window(cal, dd.isoformat())
            if w and now <= w[1]:
                sess = {"start": w[0].astimezone(KST).isoformat(timespec="seconds"), "end": w[1].astimezone(KST).isoformat(timespec="seconds")}
                break
    asof = max(asofs).isoformat(timespec="seconds") if asofs else None
    return {"asof": asof, "quotes": q, "spark": spark, "rank": ranks, "sector_rank": srank, "session": sess,
            "chg_unit": {"raw": unit, "basis": unit_why},
            "_keys": {"prices": keys_of(pr), "rank": keys_of(_latest(base, today, "us_rank_amount")),
                      "sector_rank": keys_of(srank_data, "sectorId")},
            "missing": missing, "note": "chg_pct = 등락률(%, 응답 단위를 % 로 환산) · amt = 거래대금(USD) · 1분봉 시각은 ET 봉 종료 시각 · _keys = 응답 키 이름(진단)"}


# ── 토스 섹터 (보드 toss-sectors) — sectors.json: 섹터 계층 + 종목→말단 섹터 다중 매핑. 시세·금액 필드 없음 ──
def build_sectors(base: Path, now: datetime) -> dict | None:
    today = now.astimezone(KST).date()
    for i in range(8):
        f = base / (today - timedelta(days=i)).isoformat() / "sectors.json"
        if not f.exists():
            continue
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        data = rec.get("data") or {}
        secs = collect.parse_sectors(data.get("sectors"))
        if not secs:
            continue
        members: dict[str, dict[str, list[str]]] = {}
        for mk, by in (data.get("stocks") or {}).items():
            m: dict[str, set] = {}
            for sid, resp in (by or {}).items():
                for d in crosscheck._dicts(resp):
                    sym = d.get("symbol")
                    if isinstance(sym, str) and sym:
                        m.setdefault(sym, set()).add(str(sid))
            members[mk] = {k: sorted(v) for k, v in sorted(m.items())}
        return {"source": "toss", "asof": rec.get("generated_at"), "date": f.parent.name,
                "sectors": secs, "members": members, "failed": len(data.get("failed") or []),
                "note": "토스 섹터 3단계(depth 0~2, parent 로 상위). members = 종목 → 말단 섹터 id 목록(다중 소속). 시세·금액 없음."}
    return None


# ── 일봉 (10/21 겸이 "일봉도 토스데이터로 … 10분마다 최신화") — 커밋 크기 때문에 두 파일로 나눈다 ──────────────
# daily_bars.json  = 키별 과거 봉(마지막 봉 제외) — 새 날짜가 생길 때만 바뀜(하루 1~2회 커밋)
# daily_today.json = 키별 마지막 봉 1개 — 10분 회차마다 바뀜(수백 바이트)
# 화면은 두 파일을 합쳐 쓴다(같은 날짜면 today 가 이김).
def build_daily(base: Path, now: datetime) -> tuple[dict | None, dict | None]:
    keys = list(collect.DAILY_IND) + list(collect.DAILY_US)
    hist, today = {}, {}
    for k in keys:
        c = collect.daily_cache(base, k)
        bars = sorted((c.get("bars") or {}).items())
        if not bars:
            continue
        rows = [[d, *[_r(x, 4) if x is not None else None for x in v]] for d, v in bars]
        mk = c.get("mk") or ("KR" if k in collect.DAILY_IND else "US")
        hist[k] = {"mk": mk, "tz": "KST" if mk == "KR" else "ET", "n": len(rows) - 1, "bars": rows[:-1]}
        today[k] = {"bar": rows[-1], "updated": c.get("updated")}
    if not today:
        return None, None
    last_hist = max((v["bars"][-1][0] for v in hist.values() if v["bars"]), default=None)
    h = {"source": "toss", "date": last_hist, "keys": hist,
         "note": "토스 일봉 과거분(키별 마지막 봉 제외). bars = [날짜, 시, 고, 저, 종, 거래량]. 오늘 봉은 daily_today.json. 국채는 % 수익률."}
    t = {"source": "toss", "asof": max((v["updated"] for v in today.values() if v.get("updated")), default=None), "keys": today,
         "note": "키별 마지막 일봉 1개(10분 갱신: KOSPI·KOSDAQ 국장 창, SPY·QQQ·DIA·IWM·SOXX 미장 창). bar = [날짜, 시, 고, 저, 종, 거래량]."}
    return h, t


def build_crosscheck(base: Path, now: datetime, reports: Path | None = None) -> dict:
    """최근 XC_DAYS 거래일 crosscheck.json → 괴리율·판정만. 16:00 이후면 오늘 것을 먼저 계산해 로컬에 저장."""
    loc = now.astimezone(KST)
    today = loc.date()
    tdir = base / today.isoformat()
    if tradecal.is_session("KR", today) and loc.time() >= XC_AFTER and tdir.exists():
        try:
            res = crosscheck.compare(today.isoformat(), tdir, reports)
            (tdir / "crosscheck.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("crosscheck 계산 실패: %s", type(e).__name__)
    days, d = [], tradecal.session_on_or_before("KR", today)
    for _ in range(XC_DAYS):
        days.append(d)
        d = tradecal.prev_session("KR", d)
    out = []
    for d in sorted(days):
        f = base / d.isoformat() / "crosscheck.json"
        if not f.exists():
            continue
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        rows = []
        for x in r.get("rows", []):
            y = {"item": x.get("item"), "status": x.get("status")}
            for k in ("diff_pct", "tol_pct", "tol", "checked"):
                if k in x:
                    y[k] = x[k]
            if "mismatch" in x:
                y["mismatch_n"] = len(x["mismatch"])
            rows.append(y)
        out.append({"date": d.isoformat(), "breach": r.get("breach", 0), "no_data": r.get("no_data", 0), "rows": rows})
    return {"source": "toss", "asof": out[-1]["date"] if out else None, "days": out,
            "tolerances": {"INDEX_CLOSE_TOL_PCT": crosscheck.INDEX_CLOSE_TOL_PCT, "FX_TOL_PCT": crosscheck.FX_TOL_PCT,
                           "CALENDAR_MISMATCH_MAX": crosscheck.CALENDAR_MISMATCH_MAX},
            "note": "토스 수집분 vs 기존 소스(macro_series·tradecal) 괴리율·판정만. 원값 미포함."}


# ── 공개 안전·포맷 ───────────────────────────────────────────────────────
def assert_public(obj, path: str = "") -> None:
    """금지 키·토큰 흔적·API 도메인이 있으면 ValueError (쓰기 전)."""
    needle = "toss" + "invest"
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_KEYS:
                raise ValueError(f"공개 금지 키: {path}.{k}")
            assert_public(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_public(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        low = obj.lower()
        if needle in low or "bearer " in low or "://" in low:
            raise ValueError(f"공개 금지 문자열: {path}")


_SCALAR_LIST = re.compile(r"\[\n([^\[\]{}]*?)\n\s*\]")


def render(obj) -> str:
    """정렬·고정 포맷: 키 정렬 indent=1, 숫자 리스트(봉 1개)는 한 줄 → 새 봉이 붙어도 diff 는 몇 줄."""
    s = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)
    return _SCALAR_LIST.sub(lambda m: "[" + " ".join(x.strip() for x in m.group(1).splitlines()) + "]", s) + "\n"


def fit_size(doc: dict, cap: int = MAX_BYTES) -> dict:
    """render 크기가 cap 을 넘으면 봉을 2배씩 솎는다(마지막 봉 유지)."""
    k = 1
    groups = lambda: list(doc["indices"].values()) + list(((doc.get("us") or {}).get("spark") or {}).values())  # noqa: E731
    while len(render(doc).encode("utf-8")) > cap and any(len(v.get("bars", [])) > 2 for v in groups()):
        k *= 2
        for v in groups():
            b = v["bars"]
            v["bars"] = b[:-1][::2] + b[-1:] if len(b) > 2 else b
            v["thinned"] = k
    return doc


def signature(doc: dict, drop: tuple = ()) -> str:
    x = {k: v for k, v in doc.items() if k not in ("generated_at", "published_at", "schema_version") + drop}
    return hashlib.sha256(render(x).encode("utf-8")).hexdigest()[:16]


def in_kr_window(now: datetime) -> bool:
    loc = now.astimezone(KST)
    return tradecal.is_session("KR", loc.date()) and KR_OPEN <= loc.time() < KR_FINAL


def decide(state: dict, sig_full: str, sig_xc: str, now: datetime,
           min_interval_min: int = MIN_INTERVAL_MIN) -> tuple[bool, str]:
    """(커밋할지, 사유). 바뀐 게 없으면 안 함(실패 재시도는 예외), 간격이 정해져 있으면 그 안에서는 미룸."""
    changed = sig_full != state.get("last_full") or sig_xc != state.get("last_xc")
    if not changed:
        return (True, "retry_push") if state.get("pending") else (False, "no_change")
    last = to_kst(state.get("last_publish_at"))
    if min_interval_min and last and not state.get("pending") \
            and (now - last).total_seconds() < min_interval_min * 60 - SLACK_SEC:
        return False, "interval"
    if in_kr_window(now):
        return True, "intraday"
    us = us_session(now)
    return True, f"us_{us}" if us else "off_session"


def us_session(now: datetime) -> str | None:
    """미장 4세션 이름(ET 기준 — 토스 세션: 데이 20:00~04:00 · 프리 04:00~09:30 · 정규 09:30~16:00 · 애프터 16:00~18:00 ET). 밖이면 None."""
    if collect.ET is None or not collect.in_window("us", now, None)[0]:
        return None
    e = now.astimezone(collect.ET)
    m = e.hour * 60 + e.minute
    return "day" if m >= 20 * 60 or m < 4 * 60 else "pre" if m < 9 * 60 + 30 else "regular" if m < 16 * 60 else "after"


# ── git (전용 브랜치 toss-live — 작업 트리·main 을 건드리지 않는 plumbing 커밋, 일반 push 만) ─────────────
Runner = Callable[..., tuple[int, str, str]]


_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")


def clean_git_env() -> dict:
    """git 훅 안에서 불려도(GIT_DIR 등 상속) cwd 저장소만 쓰게 — 10/21 pre-push 훅 → pytest 가 실제 저장소를
    core.bare=true 로 바꾸고 't init' 커밋을 끼운 사고 재발 방지."""
    import os
    return {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARS}


def git_runner(args: list[str], cwd: Path, data: str | None = None) -> tuple[int, str, str]:
    """봇 신원으로 git 실행 (노트북 git 설정 무시). 반환: (코드, stdout, stderr 마지막 줄 — URL 자격 증명 가림).
    stdin 은 바이트(UTF-8, LF 그대로)로 넘긴다 — Windows 텍스트 모드 CRLF 변환 방지."""
    cmd = ["git", "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}", *args]
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=180, env=clean_git_env(),
                           input=data.encode("utf-8") if data is not None else None)
    except Exception as e:  # noqa: BLE001
        return 1, "", type(e).__name__
    err = p.stderr.decode("utf-8", "replace").strip().splitlines()
    msg = re.sub(r"https?://[^@\s/]+@", "https://***@", err[-1] if err else "")[:200]
    return p.returncode, p.stdout.decode("utf-8", "replace").strip(), msg


def remote_file(repo: Path, name: str, run: Runner = git_runner) -> str | None:
    rc, out, _ = run(["show", f"{REMOTE_REF}:{name}"], repo)
    return out if rc == 0 else None


def fetch_branch(repo: Path, run: Runner = git_runner) -> bool:
    """origin/toss-live 원격 추적 참조 갱신 (브랜치가 아직 없으면 False — 첫 커밋은 부모 없이)."""
    rc, _, _ = run(["fetch", "-q", "origin", f"+refs/heads/{BRANCH}:{REMOTE_REF}"], repo)
    return rc == 0


def git_publish(repo: Path, files: dict[str, str], message: str, run: Runner = git_runner) -> tuple[bool, str]:
    """files{이름: 내용} 만 담은 트리로 toss-live 에 커밋 1개(부모 = 원격 끝) → 일반 push. 거절되면 다시 받아 1회 재시도."""
    m = ""
    for attempt in range(2):
        if attempt:
            fetch_branch(repo, run)
        rc, parent, _ = run(["rev-parse", "-q", "--verify", f"{REMOTE_REF}^{{commit}}"], repo)
        parent = parent if rc == 0 and parent else None
        entries = []
        for name, text in sorted(files.items()):
            rc, sha, m = run(["hash-object", "-w", "--stdin"], repo, text)
            if rc:
                return False, f"hash-object: {m}"
            entries.append(f"100644 blob {sha}\t{name}")
        rc, tree, m = run(["mktree"], repo, "\n".join(entries) + "\n")
        if rc:
            return False, f"mktree: {m}"
        if parent:
            rc, ptree, _ = run(["rev-parse", f"{parent}^{{tree}}"], repo)
            if rc == 0 and ptree == tree:
                return True, "unchanged"
        rc, commit, m = run(["commit-tree", tree, *(["-p", parent] if parent else []), "-m", message], repo)
        if rc:
            return False, f"commit-tree: {m}"
        rc, _, m = run(["push", "-q", "origin", f"{commit}:refs/heads/{BRANCH}"], repo)
        if rc == 0:
            run(["update-ref", REMOTE_REF, commit], repo)
            return True, "pushed"
    return False, f"push: {m}"


# ── 실행 ─────────────────────────────────────────────────────────────────
def _hb(base: Path) -> dict:
    try:
        return json.loads((base / "heartbeat.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(base: Path, st: dict) -> None:
    hb = _hb(base)
    hb["publish"] = st
    base.mkdir(parents=True, exist_ok=True)
    (base / "heartbeat.json").write_text(json.dumps(hb, ensure_ascii=False, indent=2), encoding="utf-8")


def check_doc(doc: dict, remote_text: str | None) -> list[str]:
    """계약(contracts 'toss_md/live.json') + asof 역행(원격 live.json 보다 과거면 거부 — guard.not_older 와 같은 기준)."""
    errs = contracts.check(Path("reports") / CONTRACT_PATH, doc)
    if remote_text:
        try:
            old = json.loads(remote_text).get("asof")
        except Exception:  # noqa: BLE001
            old = None
        if old and doc.get("asof") and not guard.not_older(old, doc["asof"]):
            errs.append(f"asof 역행: 원격 {old} → 새 {doc['asof']}")
    return errs


def run(base: Path | None = None, now: datetime | None = None, repo: Path = ROOT, dry_run: bool = False,
        push: bool = True, min_interval_min: int = MIN_INTERVAL_MIN, git: Runner = git_runner,
        reports: Path | None = None) -> dict:
    base = base or collect.DATA_DIR
    if dry_run:
        base = base / "_dryrun"
    now = now or datetime.now(KST)
    st = dict(_hb(base).get("publish") or {})
    loc = now.astimezone(KST)
    if push and not dry_run and tradecal.is_session("KR", loc.date()) and loc.time() >= XC_AFTER:
        git(["pull", "-q", "--ff-only", "origin", "main"], repo)   # 대조 전에 main 의 macro_series 최신화(실패해도 진행)
    doc = fit_size(build(base, now))
    xc = build_crosscheck(base, now, reports or repo / "reports")
    sec = build_sectors(base, now)
    dh, dt = build_daily(base, now)
    extra = {n: x for n, x in (("sectors.json", sec), ("daily_bars.json", dh), ("daily_today.json", dt)) if x}
    assert_public(doc)
    assert_public(xc)
    for x in extra.values():
        assert_public(x)
    sig_full, sig_xc = signature(doc), signature(xc) + "".join(signature(extra[n]) for n in sorted(extra))
    go, why = decide(st, sig_full, sig_xc, now, min_interval_min)
    st.update({"at": now.isoformat(timespec="seconds"), "decision": why})
    if dry_run:
        out = base / "publish_preview"
        out.mkdir(parents=True, exist_ok=True)
        (out / "live.json").write_text(render(doc), encoding="utf-8")
        (out / "crosscheck.json").write_text(render(xc), encoding="utf-8")
        for n, x in extra.items():
            (out / n).write_text(render(x), encoding="utf-8")
        return {"status": "dry_run", "decision": why, "go": go, "dir": str(out), "bytes": len(render(doc).encode())}
    if not go:
        st["status"] = f"skipped:{why}"
        _save_state(base, st)
        return {"status": st["status"], "decision": why}
    doc["published_at"] = now.isoformat(timespec="seconds")
    have_remote = fetch_branch(repo, git) if push else False
    errs = check_doc(doc, remote_file(repo, "live.json", git) if have_remote else None)
    if errs:
        st.update({"status": "fail", "error": "; ".join(errs)[:200], "pending": False})
        _save_state(base, st)
        log.error("publish 거부: %s", st["error"])
        return {"status": "fail", "decision": why, "error": st["error"]}
    contracts.stamp(Path("reports") / CONTRACT_PATH, doc)
    files = {"live.json": render(doc), "crosscheck.json": render(xc)}
    for n in ("sectors.json", "daily_bars.json", "daily_today.json"):
        if n in extra:
            files[n] = render(extra[n])
        elif have_remote:   # 트리를 통째로 새로 만들므로, 이번에 못 만들면 원격 파일을 그대로 실어야 지워지지 않는다
            old = remote_file(repo, n, git)
            if old:
                files[n] = old if old.endswith("\n") else old + "\n"
    if not push:
        out = base / "publish_preview"
        out.mkdir(parents=True, exist_ok=True)
        for n, t in files.items():
            (out / n).write_text(t, encoding="utf-8")
        st.update({"status": "written(no-push)"})
        _save_state(base, st)
        return {"status": "written", "decision": why}
    good, msg = git_publish(repo, files, f"toss: published {loc:%Y-%m-%dT%H:%M} (asof {doc['date']}, {why})", git)
    st.update({"status": msg if good else "fail", "error": None if good else msg, "pending": not good})
    if good:
        st.update({"last_publish_at": now.isoformat(timespec="seconds"), "last_full": sig_full, "last_xc": sig_xc})
    _save_state(base, st)
    return {"status": st["status"], "decision": why, "error": st.get("error")}


def shape(x, depth: int = 0, key: str = "") -> list[str]:
    """값 없이 키 구조만 (리스트는 첫 원소만)."""
    pad = "  " * depth
    if isinstance(x, dict):
        out = [f"{pad}{key}{{}}"]
        for k, v in x.items():
            out += shape(v, depth + 1, f"{k}: ")
        return out
    if isinstance(x, list):
        return [f"{pad}{key}[{len(x)}]"] + (shape(x[0], depth + 1) if x else [])
    return [f"{pad}{key}<{type(x).__name__}>"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="토스 수집분 → reports/toss_md 공개 요약 publish")
    ap.add_argument("--data", type=Path, default=None, help="수집 폴더(기본 ~/toss_md_data)")
    ap.add_argument("--dry-run", action="store_true", help="_dryrun 수집분 → publish_preview/ (git 안 함)")
    ap.add_argument("--no-push", action="store_true", help="파일만 쓰고 커밋·push 안 함")
    ap.add_argument("--min-interval", type=int, default=MIN_INTERVAL_MIN, help="장중 최소 publish 간격(분)")
    ap.add_argument("--shape", action="store_true", help="오늘 수집 파일의 키 구조만 출력(값 없음)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.shape:
        d = (a.data or collect.DATA_DIR) / ("_dryrun" if a.dry_run else "") / datetime.now(KST).strftime("%Y-%m-%d")
        for f in sorted(d.glob("*.json")):
            if f.name.startswith("stocks_all"):
                continue
            print(f"== {f.name}")
            print("\n".join(shape(json.loads(f.read_text(encoding="utf-8")).get("data"))[:60]))
        return 0
    s = run(a.data, dry_run=a.dry_run, push=not a.no_push, min_interval_min=a.min_interval)
    print(f"toss_md publish: {s['status']} ({s['decision']})" + (f" — {s['error']}" if s.get("error") else ""))
    return 1 if s["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
