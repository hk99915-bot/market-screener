#!/usr/bin/env python3
"""S4 페이드 전진 추적 — 국장 '거래량 ≥ 직전 20일 평균×3 + 종가 = 20일 최고' 신호를 2026-10-22 부터 실시간 기록만 한다(진입 없음).

  python3 scripts/hf_forward.py        # KR 장후(15:55 HF 회차)마다 — reports/studies/2026-10-21_hf_desk_signals_forward.json 갱신

왜: 4차 연구(reports/studies/2026-10-21_hf_desk_signals.md) S4 추격 롱 = 10일 유니버스 대비 −1.3~−1.7%(t −7.4/−6.2).
반대(페이드 = 숏)는 결과를 본 뒤 정의라 사후 착안 → 같은 데이터 재검정 금지, 앞으로 생기는 신호로만 판정.
정의(4차 S4 그대로): 신호일 다음 날 시가 진입, 신호일 +10거래일 종가 청산, 유니버스 = 같은 날 유동(20일 거래대금 ≥ 10억·≥1,000원) 종목 동일가중 같은 창.
페이드 초과 = −(종목 − 유니버스) − 0.25%(왕복 비용) − 대차 연 3% × 10/252.
판정: 신호일 ≥ 30 · 사건 ≥ 100 → 페이드 초과 평균 > 0 · t ≥ 2.0 이면 '전진 통과(재량 북 숏 후보, 대형주·종목선물 한정)', 아니면 '전진 탈락'.
한계: 유니버스 = reports/detail/KR 수록 종목(전 종목 아님).
"""
from __future__ import annotations

import glob
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "studies" / "2026-10-21_hf_desk_signals_forward.json"
KST = timezone(timedelta(hours=9))
START = "2026-10-22"
HOLD = 10
COST = 0.0025 + 0.03 * HOLD / 252
MIN_DATES, MIN_EVENTS, T_PASS = 30, 100, 2.0


def _charts(root: Path) -> dict:
    out = {}
    for f in sorted(glob.glob(str(root / "reports" / "detail" / "KR" / "*.json"))):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        ch = [b for b in (d.get("chart") or []) if b.get("t") and b.get("c") and b.get("o")]
        if len(ch) >= 25:
            out[Path(f).stem] = (d.get("name") or Path(f).stem, ch)
    return out


def _liquid(ch, i) -> bool:
    w = ch[max(0, i - 19):i + 1]
    return sum(float(b["c"]) * float(b.get("v") or 0) for b in w) / len(w) >= 1e9 and float(ch[i]["c"]) >= 1000


def is_s4(ch, i) -> bool:
    if i < 20:
        return False
    v20 = sum(float(b.get("v") or 0) for b in ch[i - 20:i]) / 20
    return v20 > 0 and float(ch[i].get("v") or 0) >= 3 * v20 and float(ch[i]["c"]) >= max(float(b["c"]) for b in ch[i - 19:i + 1])


def update(state: dict | None = None, root: Path = ROOT) -> dict:
    st = state or (json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"v": 1, "start": START, "events": []})
    charts = _charts(root)
    seen = {(e["d"], e["code"]) for e in st["events"]}
    for code, (nm, ch) in charts.items():
        for i in range(20, len(ch)):                 # 시작일 이후 전부(회차를 건너뛰어도 빠짐없이)
            d = ch[i]["t"][:10]
            if d < st["start"] or (d, code) in seen or not _liquid(ch, i) or not is_s4(ch, i):
                continue
            st["events"].append({"d": d, "code": code, "name": nm, "status": "대기"})
            seen.add((d, code))
    idx = {code: {b["t"][:10]: k for k, b in enumerate(ch)} for code, (_, ch) in charts.items()}
    uni_cache = {}
    for e in st["events"]:
        if e["status"] != "대기" or e["code"] not in charts:
            continue
        ch = charts[e["code"]][1]
        i = idx[e["code"]].get(e["d"])
        if i is None or i + HOLD >= len(ch):
            continue
        ent, ex = float(ch[i + 1]["o"]), float(ch[i + HOLD]["c"])
        if e["d"] not in uni_cache:
            rs = []
            for c2, (_, ch2) in charts.items():
                j = idx[c2].get(e["d"])
                if j is None or j + HOLD >= len(ch2) or not _liquid(ch2, j):
                    continue
                o2 = float(ch2[j + 1]["o"])
                if o2 > 0:
                    rs.append(float(ch2[j + HOLD]["c"]) / o2 - 1)
            uni_cache[e["d"]] = sum(rs) / len(rs) if len(rs) >= 30 else None
        uni = uni_cache[e["d"]]
        if uni is None or ent <= 0:
            continue
        r = ex / ent - 1
        e.update(entry=ent, exit=ex, ret=round(r, 4), uni=round(uni, 4), excess=round(r - uni, 4),
                 fade=round(-(r - uni) - COST, 4), exit_d=ch[i + HOLD]["t"][:10], status="완료")
    done = [e for e in st["events"] if e["status"] == "완료"]
    by_d = {}
    for e in done:
        by_d.setdefault(e["d"], []).append(e["fade"])
    xs = [sum(v) / len(v) for v in by_d.values()]
    summ = {"events": len(st["events"]), "done": len(done), "dates": len(by_d)}
    if len(xs) >= 2:
        m = sum(xs) / len(xs)
        sd = (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5
        summ.update(mean_fade=round(m, 5), t=round(m / (sd / len(xs) ** 0.5), 2) if sd > 0 else None)
    if summ["dates"] >= MIN_DATES and summ["done"] >= MIN_EVENTS:
        summ["verdict"] = "전진 통과(재량 북 숏 후보 — 대형주·종목선물 한정)" if (summ.get("mean_fade") or 0) > 0 and (summ.get("t") or 0) >= T_PASS else "전진 탈락"
    else:
        summ["verdict"] = f"추적 중 — 신호일 {summ['dates']}/{MIN_DATES} · 완료 {summ['done']}/{MIN_EVENTS}"
    st["summary"] = summ
    st["updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    st["rule"] = "scripts/hf_forward.py 머리말 — 진입 없음, 기록만"
    return st


def main():
    st = update()
    OUT.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    s = st["summary"]
    print(f"S4 페이드 전진 추적: 사건 {s['events']} · 완료 {s['done']} · 신호일 {s['dates']}"
          + (f" · 페이드 초과 평균 {s['mean_fade'] * 100:+.2f}% (t {s['t']})" if s.get("mean_fade") is not None else "") + f" · {s['verdict']}")


if __name__ == "__main__":
    main()
