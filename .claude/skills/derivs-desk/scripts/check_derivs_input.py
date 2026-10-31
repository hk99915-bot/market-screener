#!/usr/bin/env python3
"""파생 입력 sanity 검사 — 파생 스킬 시범(2026-10-31). 지표를 읽기 전에 입력부터 본다(kb:derivs 복기 10/16·10년차 ③).

  python3 .claude/skills/derivs-desk/scripts/check_derivs_input.py            # reports/derivs.json + data/deriv/daily.csv·vkospi.csv
  python3 .claude/skills/derivs-desk/scripts/check_derivs_input.py --json X --daily Y --vkospi Z

실패(종료코드 1): 미결제 프로파일이 현물을 못 덮음 · 현물×1.1 ≥ 1,000 인데 1,000 이상 행사가 없음(쉼표 파서 누락, 복기 10/16)
               · call_oi/put_oi ≤ 0 · atm_iv 5~200% 밖(iv_flow_design A-1) · pcr_oi ≠ put_oi/call_oi(±1%).
경고(통과는 함): gex_top 부호가 한쪽뿐(한쪽으로만 극단 → 입력 누락 의심) · derivs.json 날짜 ≠ daily.csv 마지막 날짜
               · VKOSPI 마지막 값 10~90 밖(10/26 오매핑 사례) · 터미널 fut.basis 와 daily.csv basis 차이(스냅 시점 차 — 통계엔 daily.csv).
정보: 1σ = atm_iv ÷ √252(68% 구간, 상한 아님) · basis − basis_theo 괴리(daily.csv 확정치). 방향 해석은 하지 않는다 — 검사만.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _last_row(path: Path) -> dict | None:
    if not path.exists():
        return None
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    return rows[-1] if rows else None


def check(d: dict, daily: dict | None = None, vk: dict | None = None):
    fail, warn, info = [], [], []
    spot = _f(d.get("spot"))
    ks = sorted(_f(x.get("k")) for x in d.get("oi_profile") or [] if _f(x.get("k")) is not None)
    if not ks or spot is None:
        fail.append("oi_profile 또는 spot 없음")
    else:
        if not ks[0] <= spot <= ks[-1]:
            fail.append(f"행사가 범위 {ks[0]:g}~{ks[-1]:g} 가 현물 {spot:g} 를 못 덮음")
        if spot * 1.1 >= 1000 and ks[-1] < 1000:
            fail.append(f"현물 {spot:g}×1.1 ≥ 1,000 인데 최고 행사가 {ks[-1]:g} — 쉼표 표기 파싱 누락 의심(복기 10/16)")
        info.append(f"행사가 {len(ks)}개 · {ks[0]:g}~{ks[-1]:g} (현물 대비 {ks[0]/spot-1:+.0%}~{ks[-1]/spot-1:+.0%})")
    c, p = _f(d.get("call_oi")), _f(d.get("put_oi"))
    if not c or not p or c <= 0 or p <= 0:
        fail.append(f"call_oi/put_oi 비정상: {c}/{p}")
    else:
        pcr = _f(d.get("pcr_oi"))
        if pcr is None or abs(pcr - p / c) > 0.01 * (p / c):
            fail.append(f"pcr_oi {pcr} ≠ put_oi/call_oi {p / c:.3f}")
    iv = _f(d.get("atm_iv"))
    if iv is None or not 0.05 <= iv <= 2.0:
        fail.append(f"atm_iv {iv} — 5~200% 밖(소수 표기 기준)")
    else:
        info.append(f"1σ = {iv:.1%} ÷ √252 = {iv / math.sqrt(252):.2%}/일 (68% 구간, 상한 아님)")
    signs = {(_f(g.get("g_bn")) or 0) > 0 for g in d.get("gex_top") or []}
    if len(signs) == 1:
        warn.append("gex_top 부호가 한쪽뿐 — 지표가 한쪽으로만 극단이면 입력 누락부터 의심(복기 10/16)")
    if daily:
        if daily.get("date") != d.get("date"):
            warn.append(f"derivs.json {d.get('date')} ≠ daily.csv 마지막 {daily.get('date')}")
        b, bt = _f(daily.get("basis")), _f(daily.get("basis_theo"))
        fb = _f((d.get("fut") or {}).get("basis"))
        if b is not None and bt is not None:
            info.append(f"daily.csv {daily.get('date')} 베이시스 {b:+.2f} − 이론 {bt:.2f} = 괴리 {b - bt:+.2f}pt")
        if b is not None and fb is not None and daily.get("date") == d.get("date") and abs(fb - b) > 0.5:
            warn.append(f"터미널 fut.basis {fb:+.2f} vs daily.csv basis {b:+.2f} — 스냅 시점 차, 통계엔 daily.csv")
    if vk:
        v = _f(vk.get("close"))
        if v is None or not 10 <= v <= 90:
            warn.append(f"VKOSPI {vk.get('date')} {v} — 정상 범위 10~90 밖(오매핑 의심, 미확인 표기)")
    return fail, warn, info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "reports" / "derivs.json"))
    ap.add_argument("--daily", default=str(ROOT / "data" / "deriv" / "daily.csv"))
    ap.add_argument("--vkospi", default=str(ROOT / "data" / "deriv" / "vkospi.csv"))
    a = ap.parse_args(argv)
    d = json.loads(Path(a.json).read_text(encoding="utf-8"))
    fail, warn, info = check(d, _last_row(Path(a.daily)), _last_row(Path(a.vkospi)))
    print(f"derivs 입력 검사 · {d.get('date')} (asof {d.get('asof')})")
    for tag, xs in (("실패", fail), ("경고", warn), ("정보", info)):
        for x in xs:
            print(f"  [{tag}] {x}")
    print(f"결과: 실패 {len(fail)} · 경고 {len(warn)}" + (" — 실패 0 이어야 지표 인용 가능" if fail else ""))
    return 1 if fail else 0


# --- pytest: python3 -m pytest .claude/skills/derivs-desk/scripts/check_derivs_input.py ---
_GOOD = {"date": "2026-10-30", "spot": 899.78, "call_oi": 100.0, "put_oi": 117.6, "pcr_oi": 1.176, "atm_iv": 0.53,
         "fut": {"basis": -0.33}, "oi_profile": [{"k": 800.0}, {"k": 900.0}, {"k": 1007.5}],
         "gex_top": [{"g_bn": -10}, {"g_bn": 5}]}


def test_good_passes():
    f, w, i = check(_GOOD, {"date": "2026-10-30", "basis": "-0.33", "basis_theo": "3.26"}, {"date": "x", "close": "51.4"})
    assert f == [] and w == [] and any("괴리 -3.59" in x for x in i) and any("3.34%" in x for x in i)


def test_comma_strike_missing_and_bad_inputs():
    bad = dict(_GOOD, spot=920.0, oi_profile=[{"k": 800.0}, {"k": 997.5}], pcr_oi=1.5, atm_iv=53.0,
               gex_top=[{"g_bn": -1}, {"g_bn": -2}])
    f, w, _ = check(bad, {"date": "2026-10-29"}, {"date": "x", "close": "787.27"})
    assert any("쉼표" in x for x in f) and any("pcr_oi" in x for x in f) and any("atm_iv" in x for x in f)
    assert any("한쪽" in x for x in w) and any("≠ daily" in x for x in w) and any("VKOSPI" in x for x in w)


def test_spot_outside_profile():
    f, _, _ = check(dict(_GOOD, spot=780.0))
    assert any("못 덮음" in x for x in f)


if __name__ == "__main__":
    sys.exit(main())
