"""미장 촉매 판정 — 미장 진입 후보의 '촉매' 칸을 저장소에 있는 미장 데이터로 채운다.

배경(2026-11-14 진단): 2026-10-21~11-13 미장 제안 18건이 전부 '대기 — 촉매 없음' 으로 미진입했다
(reports/idea_tracking.json, summary_by_market.US.no_entry 18/18). 촉매 정의가 calendar.json 의 '실적' 이벤트
하나였고, 그 목록은 calendar_ev.US_EARN 30종목(빅테크, 반도체)뿐이었다. 미장 후보 풀은 peers_US 626종목이라
목록 밖 종목은 구조적으로 촉매 0 → 대기 → 미진입이었다(docs/desk_kb/rounds/2026-11-01/quant_signal_review.md §4).

연결한 원천(전부 저장소 파일, 네트워크 없음). 기준일은 아래 두 파일의 `asof`(KST)다:
- us_earn   : 실적 예정일 US_EARN_DAYS(14)일 안 — calendar.json(US_EARN 30종목) 과 earnings_cal.json(야후 추정, 반도체 바스켓 49종목). 같은 날짜는 한 번만 센다.
- us_eps_up : 이익 추정(EPS) 컨센 상향 — reports/us_eps.json 의 chg30(30일 변화율) 이 defs.US_EPS_UP_30 이상이고,
              상향 리비전 수 > 하향, 올해와 내년 두 기간이 서로 엇갈리지 않을 것.
              국장 촉매 '목표가상향(research:tp_up)' 의 미장 대응물이다. 미장 애널 목표가 원천은 저장소에 없다
              (reports/detail/US/*.json 의 research.consensus_tp, tp_upside 가 전 종목 null) → EPS 추정으로 대신한다.

노후 기준: us_eps 스냅숏이 US_EPS_MAX_AGE_DAYS(7)일보다 낡으면 촉매로 쓰지 않는다(낡은 값을 새 근거로 쓰지 않기).
기준일이 없거나 형식이 틀린 파일도 촉매 0 으로 떨어뜨리고 사유를 남긴다.

넣지 않은 원천(데이터 없음 — 지어내지 않음):
- 미장 공시 : reports/disclosures.json 은 DART(국장) 전용이다(3,434건 전부 6자리 국장 코드, 링크 dart.fss.or.kr).
              미장 8-K, 10-Q 피드가 저장소에 없다.
- 미장 애널 목표가 : reports/analysts.json 은 국장 애널만, detail/US research 는 전 종목 비어 있다.

정책: 근거가 없으면 빈 목록 → 호출부(us_committee 의 미장 진입 후보 생성)는 기존대로 '대기 — 촉매 없음' 으로 남긴다.
촉매는 '자격'만 열고 점수와 가중은 건드리지 않는다(등급 검증전 — 상향 문턱은 사전 검증 전 값).
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from .config import REPORT_DIR
from .defs import US_EARN_DAYS, US_EPS_MAX_AGE_DAYS, US_EPS_UP_30

log = logging.getLogger(__name__)
EPS_FILE = "us_eps.json"
EARN_FILE = "earnings_cal.json"
CAL_FILE = "calendar.json"
_CACHE: dict[str, tuple[float, object]] = {}


def _num(x) -> float | None:
    try:
        v = float(x)
        return v if v == v else None   # NaN 제외
    except (TypeError, ValueError):
        return None


def _day(s) -> str:
    return str(s or "")[:10]


def _read_json(path: Path):
    """파일 한 개를 mtime 기준으로 캐시해 읽는다. 없거나 깨지면 None(경고만)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _CACHE.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        val = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # JSONDecodeError ⊂ ValueError
        log.warning("미장 촉매 원천 읽기 실패 %s: %s", path.name, e)
        return None
    _CACHE[str(path)] = (mtime, val)
    return val


def load_sources(report_dir: Path | None = None) -> dict:
    """{'eps': {ticker: rec}, 'eps_asof', 'earn_cal': [row], 'earn_asof', 'cal_asof'} — 실패는 빈 값."""
    d = Path(report_dir or REPORT_DIR)
    eps = _read_json(d / EPS_FILE)
    ecal = _read_json(d / EARN_FILE)
    cal = _read_json(d / CAL_FILE)
    return {"eps": (eps.get("data") or {}) if isinstance(eps, dict) else {},
            "eps_asof": eps.get("asof") if isinstance(eps, dict) else None,
            "earn_cal": (ecal.get("rows") or []) if isinstance(ecal, dict) else [],
            "earn_asof": ecal.get("asof") if isinstance(ecal, dict) else None,
            "cal_asof": cal.get("asof") if isinstance(cal, dict) else None}


def earnings(code: str, today: date, cal=None, earn_cal=None) -> list[dict]:
    """실적 예정일 US_EARN_DAYS 일 안. calendar.json(회사 확정 표시 유지) + earnings_cal.json(야후 추정일)."""
    last = str(today + timedelta(days=US_EARN_DAYS))
    out: list[dict] = []
    seen: set[str] = set()
    for e in cal or ():
        if e.get("type") != "실적" or str(e.get("ticker")) != code:
            continue
        d = _day(e.get("date"))
        if not d or d in seen or not (str(today) <= d <= last):
            continue
        seen.add(d)
        out.append({"date": d, "what": "실적 발표" + (" (회사 확정)" if e.get("confirmed") else " (예정일 추정)"),
                    "k": "us_earn", "src": "calendar.json"})
    for r in earn_cal or ():
        if str(r.get("sym")) != code or r.get("past"):
            continue
        d = _day(r.get("date"))
        if not d or d in seen or not (str(today) <= d <= last):
            continue
        seen.add(d)
        out.append({"date": d, "what": "실적 예정 (야후 추정일)", "k": "us_earn", "src": "earnings_cal.json"})
    return sorted(out, key=lambda c: c["date"])


def eps_up(code: str, rec: dict | None, asof, today: date) -> tuple[dict | None, str]:
    """EPS 컨센 상향 촉매 1건 또는 None + 판정 사유 한 줄(화면, 로그용). 기준일 = us_eps.json asof."""
    if not rec:
        return None, "EPS 추정 자료 없음"
    try:
        age = (today - date.fromisoformat(_day(asof))).days
    except ValueError:
        return None, "us_eps 기준일 없음"
    if abs(age) > US_EPS_MAX_AGE_DAYS:
        return None, f"us_eps 낡음({_day(asof)}, {age}일)"
    e = rec.get("eps") or {}
    f0, f1 = e.get("0y") or {}, e.get("+1y") or {}
    c0, c1 = _num(f0.get("chg30")), _num(f1.get("chg30"))
    vals = [x for x in (c0, c1) if x is not None]
    if not vals:
        return None, "EPS 30일 변화 값 없음"
    if max(vals) < US_EPS_UP_30:
        return None, f"EPS 30일 상향 {max(vals):+.1%} < 문턱 {US_EPS_UP_30:.0%}"
    if len(vals) == 2 and min(vals) < 0:
        return None, f"엇갈림(올해 {c0:+.1%}, 내년 {c1:+.1%})"
    up, dn = _num(rec.get("rev_up30")), _num(rec.get("rev_dn30"))
    if up is not None and dn is not None and not up > dn:
        return None, f"상향 {up:.0f} ≤ 하향 {dn:.0f}"
    body = ", ".join(f"{lab} {x:+.1%}" for lab, x in (("올해", c0), ("내년", c1)) if x is not None)
    what = f"EPS 추정 상향 {body}" + (f" (상향 {up:.0f}/하향 {dn:.0f})" if up is not None and dn is not None else "")
    return {"date": _day(asof), "what": what, "k": "us_eps_up", "src": EPS_FILE}, f"EPS 30일 상향 {body}"


def evaluate(code: str, today: date, cal=None, src: dict | None = None) -> dict:
    """촉매 목록 + 판정 사유(원천, 기준일 포함). 촉매 없으면 catalysts=[] (호출부는 '대기 — 촉매 없음')."""
    src = src or {}
    cats = earnings(code, today, cal, src.get("earn_cal"))
    cal_asof = _day(src.get("cal_asof") or src.get("earn_asof"))
    note = f"실적 {US_EARN_DAYS}일 안 " + (f"{len(cats)}건" if cats else "없음") + (f"(캘린더 {cal_asof})" if cal_asof else "")
    asof = src.get("eps_asof")
    one, why = eps_up(code, (src.get("eps") or {}).get(code), asof, today)
    if one:
        cats.append(one)
    # EPS 판정 사유에는 원천 기준일을 같이 적는다(낡음, 기준일 없음 사유는 날짜가 이미 들어 있다).
    stamp = f"(us_eps {_day(asof)})" if asof and not why.startswith("us_eps") else ""
    note += " / " + why + stamp
    return {"catalysts": sorted(cats, key=lambda c: c["date"]), "check": note}
