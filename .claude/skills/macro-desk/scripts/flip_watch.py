#!/usr/bin/env python3
"""매크로 뒤집힘·관찰 조건 점검 — 매크로 스킬 시범(2026-10-31). 표시 전용: 규칙·문턱·파일을 바꾸지 않는다.

  python3 .claude/skills/macro-desk/scripts/flip_watch.py            # 저장소 reports/ 기준 표
  python3 .claude/skills/macro-desk/scripts/flip_watch.py --json     # 같은 내용 json
  python3 .claude/skills/macro-desk/scripts/flip_watch.py --reports <dir>

조건 정의 = references/flip_conditions.md F1–F6 (라운드 10/28~10/31 원문, 전부 관찰용·검증전).
입력: macro_series.json(US10Y·SPX·DXY·KOSPI 종가) · bonds.json(credit_us.r20·us.curve now/m1) ·
      macro_view.json(glance 'FF상단 x.xx%') · commodities.json(BRENT). 없는 입력은 '데이터 없음(원인)'으로 적고 계속.
20일 변화 = 종가[-1]/종가[-21]−1 (macroview chg20 과 같은 창). 2s30s 1개월 = (30Y−2Y)now − (30Y−2Y)m1.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def closes(series: dict, key: str) -> list[tuple[str, float]]:
    rows = (series or {}).get(key) or []
    return [(r[0], float(r[4])) for r in rows if isinstance(r, list) and len(r) >= 5 and r[4] is not None]


def chg(c: list[tuple[str, float]], n: int = 20):
    return c[-1][1] / c[-1 - n][1] - 1 if len(c) > n and c[-1 - n][1] else None


def streak_below(c: list[tuple[str, float]], lvl: float) -> int:
    k = 0
    for _, v in reversed(c):
        if v < lvl:
            k += 1
        else:
            break
    return k


def ff_upper(view: dict | None):
    for g in (view or {}).get("glance") or []:
        m = re.search(r"FF상단\s*([0-9.]+)%", g.get("line", "") + " " + g.get("short", ""))
        if m:
            return float(m.group(1))
    return None


def evaluate(rep: Path) -> dict:
    ms, bd = _load(rep / "macro_series.json"), _load(rep / "bonds.json")
    view, cm = _load(rep / "macro_view.json"), _load(rep / "commodities.json")
    s = (ms or {}).get("series") or {}
    t10, spx, dxy, ksp = (closes(s, k) for k in ("US10Y", "SPX", "DXY", "KOSPI"))
    cr = (bd or {}).get("credit_us") or {}
    hyg20 = cr.get("r20")
    cv = ((bd or {}).get("us") or {}).get("curve") or {}
    now, m1 = cv.get("now") or {}, cv.get("m1") or {}
    y10 = t10[-1][1] if t10 else None
    out = {"asof": {"macro_series": (ms or {}).get("asof"), "bonds": (bd or {}).get("asof"),
                    "macro_view": (view or {}).get("asof"), "commodities": (cm or {}).get("asof")}, "rows": []}

    def row(cid, name, hit, value, need, src):
        out["rows"].append({"id": cid, "name": name, "hit": hit, "value": value, "need": need, "src": src})

    nodata = "데이터 없음({})"
    # F1
    if t10:
        k = streak_below(t10, 4.90)
        row("F1", "미10Y 4.90% 하회 연속", f"{min(k, 2)}/2", f"{y10:.3f}% ({t10[-1][0]}) · {k}일차", "종가 <4.90 2일", "macro_fomc 10/29")
    else:
        row("F1", "미10Y 4.90% 하회 연속", None, nodata.format("macro_series US10Y"), "종가 <4.90 2일", "macro_fomc 10/29")
    # F2
    if y10 is not None and hyg20 is not None:
        n = int(hyg20 <= -0.03) + int(y10 >= 5.25)
        row("F2", "크레딧 경로(HYG/IEF·10Y)", f"{n}/2", f"HYG/IEF 20일 {hyg20*100:+.1f}% · 10Y {y10:.3f}%", "−3%↓ 와 5.25%↑ 동시", "macro_rates_ai 10/29")
    else:
        row("F2", "크레딧 경로(HYG/IEF·10Y)", None, nodata.format("bonds credit_us 또는 US10Y"), "−3%↓ 와 5.25%↑ 동시", "macro_rates_ai 10/29")
    # F3
    ff, y2 = ff_upper(view), now.get("2Y")
    if t10 and hyg20 is not None and ff is not None and y2 is not None:
        gap = (y2 - ff) * 100
        ok = (streak_below(t10, 4.90) >= 2 or gap <= 50) and hyg20 > -0.03
        row("F3", "'금리 안전판' 문장 허용", "충족" if ok else "미충족",
            f"2Y−FF상단 {gap:+.0f}bp(≈{gap/25:.1f}회) · 10Y 하회 {streak_below(t10, 4.90)}일 · HYG/IEF {hyg20*100:+.1f}%",
            "(4.90 2일 또는 ≤+50bp) 그리고 HYG/IEF >−3%", "macro_ds_1101 10/31")
    else:
        row("F3", "'금리 안전판' 문장 허용", None, nodata.format("FF상단·2Y·HYG/IEF 중 일부"), "(4.90 2일 또는 ≤+50bp) 그리고 HYG/IEF >−3%", "macro_ds_1101 10/31")
    # F4
    d10 = (t10[-1][1] - t10[-21][1]) * 100 if len(t10) > 20 else None
    sp20, dx20 = chg(spx), chg(dxy)
    s230 = ((now["30Y"] - now["2Y"]) - (m1["30Y"] - m1["2Y"])) * 100 if all(k in d for d in (now, m1) for k in ("2Y", "30Y")) else None
    if None not in (y10, d10, sp20, dx20, s230):
        n4 = int(y10 >= 5.25) + int(s230 >= 15) + int(dx20 <= -0.02) + int(sp20 < 0)
        n3 = int(d10 > 0) + int(sp20 < 0) + int(dx20 < 0)
        row("F4", "재정·달러('자경단') 경로", f"{n4}/4 · 2025-04형 {n3}/3",
            f"10Y {y10:.3f}%(20일 {d10:+.0f}bp) · 2s30s 1M {s230:+.0f}bp · DXY 20일 {dx20*100:+.1f}% · S&P 20일 {sp20*100:+.1f}%",
            "5.25%↑+2s30s +15bp↑+DXY −2%↓+S&P 하락[가정: S&P 20일<0]", "macro_curve 10/31")
    else:
        row("F4", "재정·달러('자경단') 경로", None, nodata.format("US10Y·SPX·DXY 21일 또는 곡선 2Y/30Y"), "4조건 동시", "macro_curve 10/31")
    # F5
    k20, s20 = chg(ksp), sp20
    if k20 is not None and s20 is not None:
        gap = (k20 - s20) * 100
        lab = "한국 고유(<−8%p)" if gap < -8 else ("한국 강함(>+8%p)" if gap > 8 else "±8%p 안")
        row("F5", "코스피−S&P 20일 격차", lab, f"{gap:+.1f}%p (코스피 {k20*100:+.1f}% · S&P {s20*100:+.1f}%)", "±8%p", "kb:macro#5")
    else:
        row("F5", "코스피−S&P 20일 격차", None, nodata.format("KOSPI·SPX 21일"), "±8%p", "kb:macro#5")
    # F6
    br = next((r for r in (cm or {}).get("rows") or [] if r.get("key") == "BRENT"), None)
    if br and br.get("last") is not None:
        b = float(br["last"])
        lab = "차질 지속 쪽($126↑)" if b >= 126 else ("해소 후보($90↓, 통항 합의는 별도 확인)" if b < 90 else "$90~126 안")
        row("F6", "브렌트 오일 시나리오", lab, f"${b:.2f} ({br.get('date')}) · 1M {float(br.get('chg1m') or 0)*100:+.1f}%", "$126↑ 또는 통항 합의+$90↓", "macro_oil_battery 10/29")
    else:
        row("F6", "브렌트 오일 시나리오", None, nodata.format("commodities BRENT"), "$126↑ 또는 통항 합의+$90↓", "macro_oil_battery 10/29")
    return out


def render(res: dict) -> str:
    a = res["asof"]
    lines = [f"기준: macro_series {a['macro_series']} · bonds {a['bonds']} · macro_view {a['macro_view']} · commodities {a['commodities']} (관찰용·검증전, 규칙 아님)"]
    for r in res["rows"]:
        lines.append(f"- {r['id']} {r['name']}: {r['hit'] if r['hit'] is not None else '판정 불가'} · {r['value']} · 문턱 {r['need']} · 출처 {r['src']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reports", default=str(ROOT / "reports"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = evaluate(Path(a.reports))
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
