"""토스 파일럿 수집분 vs 기존 소스 괴리 기록 (겸이 노트북에서 실행, 결과는 저장소 밖).

    python tools/toss_md/crosscheck.py                    # 오늘(KST)
    python tools/toss_md/crosscheck.py --date 2026-10-20 [--dry-run]

비교 대상(기존 소스, 저장소 reports/ 와 screener/tradecal.py — git pull 로 최신화 후 실행):
- 지수 종가: 토스 kospi_1m·kosdaq_1m 의 마지막 봉 close  vs  reports/macro_series.json series KOSPI·KOSDAQ 그날 종가
- 환율:     토스 usdkrw midRate(매매기준율, rate=매수환율은 안 씀) vs  reports/macro_series.json USDKRW 그날 종가(야후, 없으면 reports/live.json)
- 휴장 달력: 토스 calendar_kr·calendar_us 의 날짜별 개장 여부 vs  screener.tradecal.is_session
출력: ~/toss_md_data/YYYY-MM-DD/crosscheck.json (저장소 밖). 화면엔 항목별 괴리율·판정만.

허용오차는 아래 상수로 **사전에** 정한다(결과를 보고 고치지 않는다 — 고치면 변경 기록에 사유).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screener import tradecal  # noqa: E402
from tools.toss_md import collect  # noqa: E402

# ── 허용오차 (사전 명시, 2026-10-20 개발) ──────────────────────────────────
INDEX_CLOSE_TOL_PCT = 0.05   # 지수 종가: 같은 거래소 확정치라 0.05% 안이어야 정상(소수점·반올림 차이만 허용)
FX_TOL_PCT = 0.50            # USDKRW: 토스는 참고 환율(1분 갱신), 야후는 다른 시각·출처 → 0.5% 까지 정상
CALENDAR_MISMATCH_MAX = 0    # 휴장일 판정 불일치는 1건도 허용 안 함
# 근거: 지수 종가는 KRX 단일 원천이라 차이가 나면 시각(장중 값 비교)이나 파싱 오류. 환율은 기준 시각이 달라 일중 변동(통상 0.3% 안팎) 만큼 허용.

try:
    KST = ZoneInfo("Asia/Seoul")
except Exception:  # Windows 는 시스템 tz DB 가 없어 tzdata 패키지 필요 — 없으면 고정 +09:00 (한국은 서머타임 없음)
    KST = timezone(timedelta(hours=9), "KST")
_CLOSE_KEYS = ("close", "closePrice", "lastPrice", "price")
# 환율은 매매기준율(mid)만 — 토스 rate 는 고객 매수환율(스프레드 포함)이라 야후 mid 와 비교·공개 불가 (10/21 PB). 없으면 None(no_data).
_RATE_KEYS = ("midRate", "mid_rate", "midPrice")
_OPEN_KEYS = ("isOpen", "open", "isTradingDay")
_HOLI_KEYS = ("isHoliday", "holiday", "closed")


def _dicts(x, depth=0):
    if depth > 6:
        return
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from _dicts(v, depth + 1)
    elif isinstance(x, list):
        for v in x:
            yield from _dicts(v, depth + 1)


def _num(d: dict, keys) -> float | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace(",", ""))
            except ValueError:
                pass
    return None


def last_close(data, day: str) -> float | None:
    """그날 날짜로 시작하는 시각 키를 가진 봉 중 가장 늦은 봉의 close."""
    best = None
    for d in _dicts(data):
        k = collect._row_key(d)
        if not k or not str(d.get(k, "")).startswith(day):
            continue
        c = _num(d, _CLOSE_KEYS)
        if c is not None and (best is None or str(d[k]) > best[0]):
            best = (str(d[k]), c)
    return best[1] if best else None


def fx_rate(data) -> float | None:
    for d in _dicts(data):
        r = _num(d, _RATE_KEYS)
        if r is not None:
            return r
    return None


def calendar_days(data) -> dict[str, bool]:
    """{날짜: 개장 여부}. 해석 못 하면 빈 dict."""
    out = {}
    for d in _dicts(data):
        ds = d.get("date") or d.get("baseDate")
        if not isinstance(ds, str) or len(ds) < 10:
            continue
        for k in _OPEN_KEYS:
            if isinstance(d.get(k), bool):
                out[ds[:10]] = d[k]
                break
        else:
            for k in _HOLI_KEYS:
                if isinstance(d.get(k), bool):
                    out[ds[:10]] = not d[k]
                    break
            else:   # 10/21 실측 꼴: {today|previousBusinessDay|nextBusinessDay: {date, (integrated:){preMarket…}{startTime,endTime}}} — 개장 플래그 없음
                if _has_session(d):
                    out[ds[:10]] = True
                elif any(k in d for k in ("integrated", "regularMarket", "dayMarket")):
                    out[ds[:10]] = False
    _fill_between(data, out)
    return out


def _has_session(d: dict) -> bool:
    for k, v in d.items():
        if isinstance(v, dict) and ("market" in k.lower() or k == "integrated"):
            if v.get("startTime") or _has_session(v):
                return True
    return False


def _fill_between(data, out: dict) -> None:
    """previousBusinessDay·nextBusinessDay 사이(오늘 제외) 날짜는 휴장."""
    from datetime import date as _d, timedelta as _td
    r = data.get("result") if isinstance(data, dict) else None
    if not isinstance(r, dict) or not all(isinstance(r.get(k), dict) for k in ("previousBusinessDay", "nextBusinessDay")):
        return
    try:
        a, b = (_d.fromisoformat(str(r[k].get("date"))[:10]) for k in ("previousBusinessDay", "nextBusinessDay"))
    except ValueError:
        return
    x = a + _td(days=1)
    while x < b:
        out.setdefault(x.isoformat(), False)
        x += _td(days=1)


def _series_close(ms: dict, key: str, day: str) -> float | None:
    for row in (ms.get("series") or {}).get(key) or []:
        if row and row[0] == day:
            return float(row[4])  # fmt dohlcv → close
    return None


def _pct(a: float, b: float) -> float:
    return abs(a - b) / abs(b) * 100.0


def compare(day: str, toss_dir: Path, reports: Path | None = None) -> dict:
    reports = reports or ROOT / "reports"

    def load(name):
        f = toss_dir / f"{name}.json"
        return json.loads(f.read_text(encoding="utf-8")).get("data") if f.exists() else None

    try:
        ms = json.loads((reports / "macro_series.json").read_text(encoding="utf-8"))
    except Exception:
        ms = {}
    rows = []

    def add(item, toss, ref, tol, ref_src):
        if toss is None or ref is None:
            rows.append({"item": item, "status": "no_data", "toss": toss, "ref": ref, "ref_src": ref_src,
                         "note": "토스 값 해석 실패" if toss is None else "기존 소스에 그날 값 없음"})
            return
        diff = _pct(toss, ref)
        rows.append({"item": item, "status": "ok" if diff <= tol else "breach", "toss": toss, "ref": ref,
                     "diff_pct": round(diff, 4), "tol_pct": tol, "ref_src": ref_src})

    for name, key in (("kospi_1m", "KOSPI"), ("kosdaq_1m", "KOSDAQ")):
        add(f"{key} 종가", last_close(load(name), day), _series_close(ms, key, day), INDEX_CLOSE_TOL_PCT,
            "reports/macro_series.json")
    fx_ref, fx_src = _series_close(ms, "USDKRW", day), "reports/macro_series.json(야후)"
    if fx_ref is None:  # 시계열에 그날 행이 아직 없으면 live.json 의 같은 날짜 값
        try:
            lv = json.loads((reports / "live.json").read_text(encoding="utf-8"))
            it = next((i for i in lv.get("items", []) if i.get("key") == "USDKRW" and i.get("date") == day
                       and i.get("src") != "toss"), None)   # live.json 이 토스로 덮였으면 자기 대조가 되므로 제외
            if it and isinstance(it.get("last"), (int, float)):
                fx_ref, fx_src = float(it["last"]), "reports/live.json(야후)"
        except Exception:
            pass
    add("USDKRW", fx_rate(load("usdkrw")), fx_ref, FX_TOL_PCT, fx_src)

    for name, mkt in (("calendar_kr", "KR"), ("calendar_us", "US")):
        days = calendar_days(load(name))
        if not days:
            rows.append({"item": f"{mkt} 달력", "status": "no_data", "note": "토스 달력 해석 실패", "ref_src": "screener/tradecal.py"})
            continue
        mism = [ds for ds, op in sorted(days.items()) if tradecal.is_session(mkt, date.fromisoformat(ds)) != op]
        rows.append({"item": f"{mkt} 달력", "status": "ok" if len(mism) <= CALENDAR_MISMATCH_MAX else "breach",
                     "checked": len(days), "mismatch": mism[:20], "tol": CALENDAR_MISMATCH_MAX, "ref_src": "screener/tradecal.py"})

    return {"date": day, "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "tolerances": {"INDEX_CLOSE_TOL_PCT": INDEX_CLOSE_TOL_PCT, "FX_TOL_PCT": FX_TOL_PCT,
                           "CALENDAR_MISMATCH_MAX": CALENDAR_MISMATCH_MAX},
            "rows": rows,
            "breach": sum(r["status"] == "breach" for r in rows),
            "no_data": sum(r["status"] == "no_data" for r in rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="토스 수집분 vs 기존 소스 괴리")
    ap.add_argument("--date", default=datetime.now(KST).strftime("%Y-%m-%d"))
    ap.add_argument("--dry-run", action="store_true", help="_dryrun 수집분과 비교")
    ap.add_argument("--data", type=Path, default=None, help="수집 폴더(기본 ~/toss_md_data)")
    a = ap.parse_args(argv)
    base = a.data or collect.DATA_DIR
    if a.dry_run:
        base = base / "_dryrun"
    collect._refuse_repo(base)
    d = base / a.date
    res = compare(a.date, d)
    d.mkdir(parents=True, exist_ok=True)
    (d / "crosscheck.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in res["rows"]:
        extra = f" 괴리 {r['diff_pct']}% (허용 {r['tol_pct']}%)" if "diff_pct" in r else \
            (f" 불일치 {len(r.get('mismatch', []))}/{r.get('checked')}" if "checked" in r else f" {r.get('note', '')}")
        print(f"[{r['status']}] {r['item']}:{extra}")
    print(f"crosscheck {a.date}: breach={res['breach']} no_data={res['no_data']} → {d / 'crosscheck.json'}")
    return 1 if res["breach"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
