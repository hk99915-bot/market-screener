"""장중 '오늘 일봉' 오버레이 → reports/intraday_last.json (보드 intraday-bar, 2026-10-24 겸이 "1y 그 차트에 오늘 데이터가 일봉으로 없으니 보기 어려움"·
"갭하락인지 갭상인지 등등").

왜 따로 파일인가: 종목 상세(reports/detail/<시장>/<코드>.json)의 chart(OHLC 260봉)·c1y([날짜, 종가])는 EOD(전 거래일까지)다.
장중에 2천 개 파일을 5분마다 다시 쓰면 커밋이 폭증한다. 그래서 live 루프의 히트맵 수집(같은 시세 호출)을 재사용해
'오늘 일봉 하나'만 시장별로 모아 두고, 화면이 상세 차트 끝에 잠정 봉으로 붙인다. 마감 뒤 EOD 상세가 그날 봉을 가지면 화면은 무시한다.

출처: KR = 네이버 1차(polling: 현재가·당일 시가·고가·저가·누적 거래량·전일 종가 — 정규장 KRX 값, NXT·시간외 미포함, x=1),
네이버가 못 준 종목만 토스(정규장 중·신선할 때, 시가 필드 없음 → x=0 관측 근사·갭 없음). 10/24 측정(req-dev-a4d03413)으로 토스 1차 보류.
US = 야후 일봉(정규장만 — 프리·애프터 미포함)의 그날 Open·High·Low·Volume, 전일 종가 = 직전 일봉 Close(x=1).

계약 (schema 2 — 화면은 이것만 읽는다; 바꾸면 tests/test_intraday_last.py · 프런트 장부 같이):
{
  "schema": 2, "asof": "YYYY-MM-DD HH:MM KST",          # 두 시장 중 최신 갱신 시각
  "fields": ["o","h","l","c","v","pc","r1","src","x","gap","gk","gf"],   # q 배열 순서
  "gap_band": 0.005,                                    # 갭 판정 문턱 ±0.5%
  "KR": {"trade_date": "YYYY-MM-DD", "session": "LIVE|CLOSE", "asof": "...KST", "n": 1261,
         "src": {"naver": 1250, "toss": 11}, "exact": 1250,      # exact = x=1(출처 당일 필드) 종목 수
         "provisional": true,                                    # (있을 때만) KR 15:30~15:45 KRX 종가 확정 전 → 화면 '잠정'

         "q": {"005930": [o, h, l, c, v, pc, r1, "t"|"n"|"y", x, gap, gk, gf]}},
  "US": {...같은 꼴, 키 = 티커...}
}
  o·h·l·c = 당일 시가·고가·저가·현재가, v = 누적 거래량(없으면 null), pc = 전일 종가(없으면 null), r1 = 전일 대비 등락(소수)
  src 한 글자 = 현재가 출처(n 네이버 · t 토스 폴백 · y 야후), x = 1 시가·고저가 출처 필드 / 0 5분 관측 근사(시가 = 첫 관측)
  gap = o ÷ pc − 1 (x=1 이고 pc 있을 때만, 아니면 null — 추정 금지), gk = "U" 갭상승(gap ≥ +0.5%) · "D" 갭하락(≤ −0.5%) · "0" 보합 · null
  gf = 갭 메움 1/0 (U: 저가 ≤ 전일 종가, D: 고가 ≥ 전일 종가) · 보합·null 이면 null
  [가정: 문턱 ±0.5% = 시가 단일가 잡음·호가 단위(국장 대형주 0.05~0.1%/틱)보다 충분히 큰 값으로 둔 관례값, 검증전 — 바꾸면 gap_band 하나]

화면 규칙(프런트 장부 req-front-75d54530):
 ① 상세 chart 마지막 t < trade_date 일 때만 붙인다(마감 뒤 EOD 오면 자동으로 사라짐). c1y 끝에도 [trade_date, c].
 ② 이동평균 s20·s50·s200 은 오늘 c 를 넣어 화면에서 다시 계산(오늘 값 = (직전 N−1개 EOD 종가 + c) ÷ N). 거래량 막대도 v.
 ③ 잠정 표시(점선 테두리 등) + 라벨 '장중 HH:MM 토스/네이버/야후'(asof 시각 · src). x=0 이면 '고저 관측 근사(5분)' 툴팁.
 ④ 갭 배지(오늘 봉 옆): gk U → '갭상 +1.8%', D → '갭하 −1.2%', gf=1 이면 '· 메움'. 양봉/음봉 = c ≥ o / c < o. gap null 이면 배지 없음.
 ⑤ session=LIVE 인데 asof 가 20분 넘게 지났으면 붙이지 않음(멈춘 값을 장중처럼 — toss_live.MAX_AGE_MIN 과 같은 값).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import REPORT_DIR
from .json_safe import dumps

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
NAME = "intraday_last.json"
FIELDS = ["o", "h", "l", "c", "v", "pc", "r1", "src", "x", "gap", "gk", "gf"]
GAP_BAND = 0.005
SRC1 = {"toss": "t", "naver": "n", "yahoo": "y"}


def _r(x, mk: str):
    if x is None:
        return None
    return round(float(x), 0 if mk == "KR" and float(x) >= 1000 else 4)


def gap_info(o: float | None, h: float, l: float, pc: float | None, exact: bool) -> tuple:
    """(gap, gk, gf). 시가가 출처 필드가 아니거나 전일 종가가 없으면 (None, None, None) — 추정 금지."""
    if not exact or not o or not pc:
        return None, None, None
    g = o / pc - 1
    if g >= GAP_BAND:
        return round(g, 5), "U", int(l <= pc)
    if g <= -GAP_BAND:
        return round(g, 5), "D", int(h >= pc)
    return round(g, 5), "0", None


def merge(prev: dict | None, rows: list[dict], market: str, trade_date: str, session: str, asof: str) -> dict:
    """시장 블록 하나. rows = [{s, close, r1, src?, o?, h?, l?, v?, pc?}] — o·h·l 이 있으면 출처 당일 필드(x=1),
    없으면 같은 거래일 이전 블록과 관측 누적(x=0, 시가 = 첫 관측). 거래일이 바뀌면 새로 시작."""
    old = (prev or {}).get("q") if (prev or {}).get("trade_date") == trade_date else None
    old = old or {}
    q: dict = {}
    cnt: dict = {}
    nx = 0
    for r in rows:
        s, c = str(r["s"]), r.get("close")
        if c is None or not c > 0 or r.get("r1") is None:
            continue
        src = r.get("src") or ("yahoo" if market == "US" else "naver")
        cnt[src] = cnt.get(src, 0) + 1
        exact = r.get("o") is not None and r.get("h") is not None and r.get("l") is not None
        if exact:
            o, h, l = r["o"], max(r["h"], c), min(r["l"], c)
            nx += 1
        elif s in old:
            o, h, l = old[s][0], max(old[s][1], c), min(old[s][2], c)
        else:
            o = h = l = c
        pc = r.get("pc")
        if pc is None and r["r1"] > -1:
            pc = c / (1 + r["r1"])
        g, gk, gf = gap_info(o, h, l, r.get("pc") if r.get("pc") else (pc if exact else None), exact)
        q[s] = [_r(o, market), _r(h, market), _r(l, market), _r(c, market), int(r["v"]) if r.get("v") else None,
                _r(pc, market), round(float(r["r1"]), 5), SRC1.get(src, src[:1]), int(exact), g, gk, gf]
    return {"trade_date": trade_date, "session": session, "asof": asof, "n": len(q), "src": cnt, "exact": nx, "q": q}


def update(market: str, rows: list[dict], trade_date: str, session: str, now: datetime, root: Path = REPORT_DIR,
           provisional: bool = False) -> dict | None:
    """reports/intraday_last.json 의 market 블록을 갱신. 같은 시장의 더 새 asof 가 이미 있으면 안 씀(역행 금지)."""
    f = root / NAME
    try:
        doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, json.JSONDecodeError):
        doc = {}
    asof = now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    prev = doc.get(market) or {}
    if str(prev.get("asof", "")) > asof:
        log.warning("intraday_last %s: 기존 %s 가 더 새로움 — 안 씀", market, prev.get("asof"))
        return None
    doc[market] = merge(prev, rows, market, trade_date, session, asof)
    if provisional:
        doc[market]["provisional"] = True   # KR 15:30~15:45 KRX 종가 확정 전 — 화면 '잠정'(heatmap_kr.build 와 같은 창)
    doc.update(schema=2, fields=FIELDS, gap_band=GAP_BAND, asof=max(str((doc.get(m) or {}).get("asof", "")) for m in ("KR", "US")),
               note="장중 오늘 일봉(잠정) — 상세 차트 마지막 날짜 < trade_date 일 때만 화면이 붙인다. x=0 은 5분 관측 근사, gap 은 x=1 일 때만. screener/intraday_last.py")
    f.write_text(dumps(doc, ensure_ascii=False), encoding="utf-8")
    log.info("intraday_last %s %s %s: %d종목 %s exact %d", market, trade_date, session, doc[market]["n"], doc[market]["src"], doc[market]["exact"])
    return doc
