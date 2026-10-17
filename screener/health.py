"""주간 자가점검 — 조용한 고장(숫자는 떠 있는데 틀리거나 멈춘 것)을 찾아 이상할 때만 텔레그램.

점검 항목
1. 정합성: 지수·매크로(상단 시세 / 매크로 시계열 / 매크로 표), 운용회의·데일리 코스피, 종목 상세 표본(가격=차트=1년차트=비교표)
2. 신선도: 주요 파일 마지막 날짜가 거래일 기준으로 밀렸는지
3. 결측: 매크로 지표가 빠졌는지, 종목 상세 수가 급감했는지
4. 만료 임박: 매크로 일정표 남은 기간, (선택) 토큰·계정 만료일 메모(reports/health_expiry.json)
5. 예약 실패: 최근 7일 GitHub Actions 실패 횟수 (GITHUB_TOKEN 있을 때)
결과: reports/health.json, 이상 있으면 텔레그램 "🔧 점검 필요"
"""
from __future__ import annotations

import json
import logging
import os
import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "health.json"


def _j(p: str):
    return json.loads((REPORT_DIR / p).read_text(encoding="utf-8"))


def _bdays_between(a: date, b: date) -> int:
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _close(vals: dict, tol: float) -> bool:
    v = [x for x in vals.values() if x is not None]
    if len(v) < 2:
        return True
    hi, lo = max(v), min(v)
    return hi == 0 or (hi - lo) / abs(hi) <= tol


def check() -> dict:
    issues, ok = [], []
    today = datetime.now(KST).date()
    # 1) 지수·매크로 정합성
    try:
        live = {i["key"]: i for i in _j("live.json")["items"]}
        ms = _j("macro_series.json")["series"]
        mv = {r["key"]: r for r in _j("macro_view.json")["rows"]}
        for k in ("KOSPI", "KOSDAQ", "SPX", "NASDAQ", "USDKRW", "US10Y", "VIX", "USDJPY", "WTI", "DXY", "GOLD"):
            s = ms.get(k) or []
            if not s:
                issues.append(f"매크로 {k} 시계열 없음 (수집 실패가 이어지는 중)")
                continue
            vals = {"상단 시세": (live.get(k) or {}).get("last"), "시계열": s[-1][4], "매크로 표": (mv.get(k) or {}).get("last")}
            if not _close(vals, 0.003):
                issues.append(f"{k} 값 불일치 " + " / ".join(f"{a} {b:,.2f}" for a, b in vals.items() if b is not None))
        ok.append("지수·매크로 정합성")
    except Exception as e:  # noqa: BLE001
        issues.append(f"지수·매크로 점검 실패: {type(e).__name__}")
    # 운용회의·데일리 코스피
    try:
        import re
        ms = _j("macro_series.json")["series"]["KOSPI"]
        cm = _j("committee.json")
        m = re.search(r"코스피 ([\d,\.]+)", cm["head"][0])
        if m and cm.get("date") == ms[-1][0] and not _close({"a": float(m.group(1).replace(",", "")), "b": ms[-1][4]}, 0.002):
            issues.append(f"운용회의 코스피 {m.group(1)} ≠ 시계열 {ms[-1][4]:,.2f}")
    except Exception:  # noqa: BLE001
        pass
    # 종목 상세 표본
    for mk in ("KR", "US"):
        try:
            idx = _j(f"detail/{mk}/_index.json")
            peers = {r["s"]: r for r in _j(f"peers_{mk}.json")["rows"]}
            syms = idx.get("symbols") or []
            if len(syms) < (1000 if mk == "KR" else 400):
                issues.append(f"{mk} 종목 상세 {len(syms)}개로 급감")
            random.seed(today.toordinal())
            bad = []
            for s in random.sample(syms, min(40, len(syms))):
                d = _j(f"detail/{mk}/{s}.json")
                ch = d.get("chart") or []
                c = d.get("close")
                cl = ch[-1]["c"] if ch else None
                c1 = (d.get("c1y") or [None])[-1]
                c1 = c1[1] if isinstance(c1, list) else c1
                r1, pr = (d.get("stats") or {}).get("ret1"), (peers.get(s) or {}).get("r1")
                if (cl and c and abs(cl / c - 1) > 1e-6) or (c1 and c and abs(c1 / c - 1) > 1e-6) \
                        or (r1 is not None and pr is not None and abs(r1 - pr) > 1e-6) or (ch and ch[-1].get("t") != d.get("asof")):
                    bad.append(s)
            if bad:
                issues.append(f"{mk} 종목 상세 표본 40개 중 {len(bad)}개 값 불일치 (예: {', '.join(bad[:5])})")
            # 신선도
            a = date.fromisoformat(str(idx.get("asof"))[:10])
            lag = _bdays_between(a, today)
            lim = 1 if mk == "KR" else 2
            if lag > lim:
                issues.append(f"{mk} 종목 상세가 {lag}거래일 밀림 (asof {a})")
            ok.append(f"{mk} 종목 상세")
        except Exception as e:  # noqa: BLE001
            issues.append(f"{mk} 종목 상세 점검 실패: {type(e).__name__}")
    # 2) 파일 신선도
    for p, key, lim in (("macro_series.json", "asof_kr", 2), ("committee.json", "date", 2), ("daily_brief.json", "asof", 2),
                        ("calendar.json", "asof", 3), ("derivs.json", "date", 3), ("signal_scores.json", "asof", 7)):
        try:
            o = _j(p)
            v = o.get(key)
            if v is None and key == "asof_kr":   # 감사 M3: KR 날짜 = KOSPI 끝 행 (옛 파일엔 asof_kr 없음)
                v = (o.get("series", {}).get("KOSPI") or [[None]])[-1][0]
            a = date.fromisoformat(str(v)[:10])
            lag = _bdays_between(a, today)
            if lag > lim:
                issues.append(f"{p} 가 {lag}거래일 멈춤 (마지막 {a})")
        except Exception:  # noqa: BLE001
            issues.append(f"{p} 날짜 확인 불가")
    # 3) 만료 임박
    try:
        from .calendar_ev import MACRO
        last = max(date.fromisoformat(d) for d, *_ in MACRO)
        left = (last - today).days
        if left < 45:
            issues.append(f"매크로 일정표가 {last} 까지만 있음 ({left}일 남음) — 다음 해 FOMC·CPI·고용 일정 입력 필요")
    except Exception:  # noqa: BLE001
        pass
    try:
        exp = _j("health_expiry.json")   # {"items":[{"name":"깃허브 읽기 토큰","date":"2027-01-15"}]}
        for it in exp.get("items", []):
            d = date.fromisoformat(it["date"])
            if (d - today).days <= 14:
                issues.append(f"{it['name']} 만료 {d} ({(d - today).days}일 남음)")
    except Exception:  # noqa: BLE001
        pass
    # 4) 예약 실패 (최근 7일)
    fails = {}
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if tok and repo:
        try:
            import requests
            since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
            r = requests.get(f"https://api.github.com/repos/{repo}/actions/runs", params={"per_page": 100, "created": f">={since}"},
                             headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}, timeout=20)
            for run in r.json().get("workflow_runs", []):
                if run.get("conclusion") in ("failure", "timed_out"):
                    fails[run["name"]] = fails.get(run["name"], 0) + 1
            for k, v in fails.items():
                if v >= 3:
                    issues.append(f"예약 작업 '{k}' 최근 7일 실패 {v}회")
        except Exception as e:  # noqa: BLE001
            log.info("Actions 실패 집계 실패: %s", e)
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "issues": issues, "ok": ok, "fails7d": fails}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def run(send: bool = True) -> dict:
    o = check()
    if o["issues"] and send:
        from .report import send_telegram
        send_telegram("🔧 <b>터미널 점검 필요</b> · " + o["asof"] + "\n" + "\n".join(f"• {x}" for x in o["issues"][:15]))
    log.info("자가점검: 이상 %d건", len(o["issues"]))
    return o
