#!/usr/bin/env python3
"""HF 아이디에이션 — 위원회 후보와 무관하게 KR·US 전 유니버스에서 매 회의 재량 후보를 뽑는다 (겸이 10/21 밤 "후보에만 있는 종목 말고 직접 아이디에이션·시그널 발굴·매크로").

  python3 scripts/hf_ideas.py          # reports/hf_ideas.json + 요약 출력

후보 5종(각 근거 경로·방향·검증 상태 표기 — 검증 상태가 F 면 '회피/반대 근거'로만 쓴다):
 ① 실적 7일 내 + 직전 5일 ±6% 이상(reports/calendar.json + 차트) — 검증전(event_driven H12~H14 결과 전)
 ② 거래량 급증(직전 20일 평균 2배+) + 방향 — 국장 '3배 + 20일 신고가'는 추격 금지(S4 F, t −7.4)라 '회피·페이드 전진 추적'으로만
 ③ 52주 종가 고점 돌파·저점 이탈 — 국장 고점 = B1 통과 소스(B), 미장 고점 = B2 F(참고), 저점 이탈 = 검증전
 ④ 업종 체인(detail drivers.chain) 점수 상·하위 — 검증전
 ⑤ 매크로 국면(미 10년·달러·WTI·VIX·원달러 20일 변화) → 수혜/피해 업종 — 검증전(정성 규칙)
유동성: KR 20일 평균 거래대금 ≥ 10억원, US ≥ $2천만. 데이터 = reports/detail/{KR,US}/*.json 차트(마지막 봉이 최신 5거래일 안).
"""
from __future__ import annotations

import glob
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "hf_ideas.json"
KST = timezone(timedelta(hours=9))
LIQ = {"KR": 1e9, "US": 2e7}
TOP, PER_TYPE = 10, 3
STATUS = {
    "earn": "검증전 — 실적 이벤트 연구(reports/studies/2026-10-21_event_driven.md H12~H14) 결과 전",
    "vol": "검증전 — 거래량 급증 + 방향",
    "s4": "회피 — 국장 거래량 3배+20일 신고가 추격 F(t −7.4/−6.2), 페이드는 전진 추적 중(scripts/hf_forward.py)",
    "hi_kr": "B — 국장 52주 고점 근접 소스 B1 통과(reports/studies/2026-10-21_alpha_sources.md)",
    "hi_us": "F 참고 — 미장 52주 고점 B2 탈락, 단독 근거 금지",
    "lo": "검증전 — 52주 저점 이탈",
    "chain": "검증전 — 업종 체인 점수(detail drivers)",
    "macro": "검증전 — 정성 매크로 규칙",
}


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def stock_feats(ch: list[dict]) -> dict | None:
    """차트 → 특징. 봉 60개 미만이면 None."""
    ch = [b for b in ch if b.get("c") and b.get("t")]
    if len(ch) < 60:
        return None
    c = [float(b["c"]) for b in ch]
    v = [float(b.get("v") or 0) for b in ch]
    v20 = sum(v[-21:-1]) / 20
    prior = c[-251:-1] if len(c) > 251 else c[:-1]
    return {
        "t": ch[-1]["t"][:10], "c": c[-1],
        "ret1": c[-1] / c[-2] - 1, "ret5": c[-1] / c[-6] - 1,
        "vr": (v[-1] / v20) if v20 > 0 else 0.0,
        "adv": sum(c[i] * v[i] for i in range(-20, 0)) / 20,
        "hi_break": c[-1] > max(prior), "lo_break": c[-1] < min(prior),
        "s4": v20 > 0 and v[-1] >= 3 * v20 and c[-1] >= max(c[-20:]),
        "n": len(prior),
        "ret20": c[-1] / c[-21] - 1,
        "below50": bool(ch[-1].get("s50")) and c[-1] < float(ch[-1]["s50"]),
    }


def macro_tilts(series: dict) -> list[dict]:
    def chg(k, n=20, diff=False):
        s = series.get(k) or []
        if len(s) <= n:
            return None
        a, b = s[-n - 1][4], s[-1][4]
        return (b - a) if diff else (b / a - 1)
    out = []
    r = chg("US10Y", diff=True)
    if r is not None and abs(r) >= 0.15:
        up = r > 0
        out.append({"driver": f"미 10년 금리 20일 {r * 100:+.0f}bp", "benefit": "은행·보험" if up else "고PER 성장·리츠·유틸리티",
                    "hurt": "고PER 성장·리츠·유틸리티" if up else "은행·보험"})
    x = chg("DXY")
    if x is not None and abs(x) >= 0.015:
        out.append({"driver": f"달러지수 20일 {x * 100:+.1f}%", "benefit": "국장 수출주(원화 약세)" if x > 0 else "신흥국·원자재",
                    "hurt": "신흥국·원자재" if x > 0 else "국장 수출주 마진"})
    w = chg("WTI")
    if w is not None and abs(w) >= 0.10:
        out.append({"driver": f"WTI 20일 {w * 100:+.1f}%", "benefit": "에너지·정유" if w > 0 else "항공·화학(원가)",
                    "hurt": "항공·화학(원가)" if w > 0 else "에너지·정유"})
    vx = chg("VIX")
    if vx is not None and vx >= 0.30:
        out.append({"driver": f"VIX 20일 {vx * 100:+.0f}%", "benefit": "필수소비·헬스케어(방어)", "hurt": "고베타·소형 성장"})
    k = chg("USDKRW")
    if k is not None and abs(k) >= 0.015:
        out.append({"driver": f"원달러 20일 {k * 100:+.1f}%", "benefit": "외국인 수급(국장 대형주)" if k < 0 else "국장 수출주",
                    "hurt": "국장 수출주 마진" if k < 0 else "외국인 수급"})
    for o in out:
        o["status"] = STATUS["macro"]
        o["src"] = "reports/macro_series.json"
    return out


def build(today: date | None = None, root: Path = ROOT) -> dict:
    today = today or datetime.now(KST).date()
    cal = (_load(root / "reports" / "calendar.json") or {}).get("events") or []
    earn = {}
    for e in cal:
        if e.get("type") == "실적" and e.get("ticker"):
            try:
                dd = date.fromisoformat(e["date"])
            except Exception:  # noqa: BLE001
                continue
            if 0 <= (dd - today).days <= 7:
                earn[(e.get("market") or "US", e["ticker"])] = e["date"]
    ideas, chains = [], {}
    latest = {}
    feats = {}
    for mk in ("KR", "US"):
        for f in sorted(glob.glob(str(root / "reports" / "detail" / mk / "*.json"))):
            d = _load(f)
            if not d:
                continue
            code = Path(f).stem
            ft = stock_feats(d.get("chart") or [])
            ch = (d.get("drivers") or {}).get("chain") or {}
            if ch.get("key") and ch.get("score") is not None:
                chains.setdefault((mk, ch["key"]), {"market": mk, "name": ch.get("name"), "score": ch["score"], "members": []})["members"].append(d.get("name") or code)
            if not ft or ft["adv"] < LIQ[mk]:
                continue
            ft["flow"] = _flow_both(d.get("flow_note") or "")
            feats[(mk, code)] = (d.get("name") or code, ft)
            latest[mk] = max(latest.get(mk, ""), ft["t"])
    for (mk, code), (nm, ft) in feats.items():
        if (date.fromisoformat(latest[mk]) - date.fromisoformat(ft["t"])).days > 7:
            continue
        src = f"reports/detail/{mk}/{code}.json chart"
        base = {"market": mk, "code": code, "name": nm, "asof": ft["t"], "close": ft["c"]}
        if (mk, code) in earn and abs(ft["ret5"]) >= 0.06:
            dn = ft["ret5"] < 0
            ideas.append({**base, "type": "실적 임박", "score": abs(ft["ret5"]),
                          "direction": "롱 후보(기대치 하향 뒤 실적)" if dn else "숏·회피 후보(실적 전 과열)",
                          "evidence": f"실적 {earn[(mk, code)]} · 직전 5일 {ft['ret5'] * 100:+.1f}%", "status": STATUS["earn"],
                          "src": f"reports/calendar.json · {src}"})
        if mk == "KR" and ft["s4"]:
            ideas.append({**base, "type": "거래량 돌파(추격 금지)", "score": min(ft["vr"], 10) / 10,
                          "direction": "회피(추격 롱 금지) · 페이드 전진 추적", "evidence": f"거래량 {ft['vr']:.1f}배 · 20일 신고가 · 1일 {ft['ret1'] * 100:+.1f}%",
                          "status": STATUS["s4"], "src": src})
        elif ft["vr"] >= 2 and abs(ft["ret1"]) >= 0.02:
            up = ft["ret1"] > 0
            chase = mk == "KR" and up and ft["vr"] >= 3          # S4 와 거의 같은 추격 패턴(20일 신고가만 아님)
            ideas.append({**base, "type": "거래량 급증", "score": math.log(ft["vr"]) * abs(ft["ret1"]) * 10,
                          "direction": ("추격 주의(S4 유사) — 롱은 눌림 확인 뒤" if chase else "롱 후보(수급 유입)") if up else "숏 후보(물량 출회)",
                          "evidence": f"거래량 {ft['vr']:.1f}배 · 1일 {ft['ret1'] * 100:+.1f}%",
                          "status": STATUS["vol"] + (" · S4 유사(국장 거래량 3배+상승 추격 = 반대 근거)" if chase else ""), "src": src})
        if mk == "KR" and ft["adv"] >= 1e10 and ft["ret20"] <= -0.10 and ft["below50"] and ft["flow"] and ft["flow"][0] < 0 and ft["flow"][1] < 0:
            ideas.append({**base, "type": "수급 이탈 숏", "score": 0.3 + abs(ft["ret20"]),
                          "direction": "숏 후보(종목선물·대차 가능 대형주만)", "evidence": f"외국인 {ft['flow'][0]:+d}억·기관 {ft['flow'][1]:+d}억 5일 동반 매도 · 20일 {ft['ret20'] * 100:+.1f}% · 50일선 아래",
                          "status": "검증전 — 수급 이탈 숏(매수 쪽 수급 지속 C1 은 F, 매도 쪽은 미검정)", "src": src + " · flow_note"})
        if ft["hi_break"] and not (mk == "KR" and ft["s4"]):      # 같은 날 S4 면 고점 돌파 롱 후보로 안 올림(추격 금지 우선)
            ideas.append({**base, "type": "52주 고점 돌파", "score": 0.5 + max(ft["ret5"], 0),
                          "direction": "롱 후보" if mk == "KR" else "참고(미장 B2 F)",
                          "evidence": f"종가 {ft['n']}일 최고 경신 · 5일 {ft['ret5'] * 100:+.1f}%", "status": STATUS["hi_kr" if mk == "KR" else "hi_us"], "src": src})
        elif ft["lo_break"]:
            ideas.append({**base, "type": "52주 저점 이탈", "score": 0.4 + max(-ft["ret5"], 0),
                          "direction": "숏 후보(검증전)", "evidence": f"종가 {ft['n']}일 최저 이탈 · 5일 {ft['ret5'] * 100:+.1f}%",
                          "status": STATUS["lo"], "src": src})
    ch_sorted = sorted(chains.values(), key=lambda x: -x["score"])
    for c in ch_sorted[:2] + ch_sorted[-2:]:
        if abs(c["score"]) < 0.15:
            continue
        ideas.append({"market": c["market"], "code": None, "name": c["name"], "type": "업종 체인", "score": abs(c["score"]),
                      "direction": "롱 후보 업종" if c["score"] > 0 else "숏 후보 업종",
                      "evidence": f"체인 점수 {c['score']:+.2f} · 구성 예: {', '.join(c['members'][:3])}", "status": STATUS["chain"],
                      "src": "reports/detail/*/<코드>.json drivers.chain"})
    by, top = {}, []
    for x in sorted(ideas, key=lambda x: -x["score"]):
        if by.get(x["type"], 0) >= PER_TYPE:
            continue
        by[x["type"]] = by.get(x["type"], 0) + 1
        top.append(x)
        if len(top) >= TOP:
            break
    for i, x in enumerate(top, 1):
        x["rank"] = i
        x["score"] = round(x["score"], 3)
    series = ((_load(root / "reports" / "macro_series.json") or {}).get("series")) or {}
    return {"v": 1, "asof": today.isoformat(), "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
            "note": "HF 아이디에이션 — 후보일 뿐 진입 아님. 진입은 scripts/hf_book.py 체크리스트 통과 후. 검증 상태 F 는 반대 근거로만.",
            "counts": {"total": len(ideas), **{k: v for k, v in by.items()}}, "ideas": top, "macro": macro_tilts(series)}


WATCH = ROOT / "reports" / "hf_watch.json"
DART_KEEP = ("수주·계약", "임원·주요주주 매매", "지분 5%", "자사주", "IR·공정공시", "실적", "타법인 투자", "정기보고서")


def _flow_both(fn: str) -> tuple[int, int] | None:
    import re
    m = re.search(r"외국인 ([+-]?\d+)억 · 기관 ([+-]?\d+)억", fn or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def watch_status(w: dict, root: Path = ROOT, today: date | None = None) -> dict:
    """감시 종목 선행 조건 점검 — 켜진 조건이 있으면 '체크리스트 재실행' (매수 신호 아님, 검증전)."""
    today = today or datetime.now(KST).date()
    d = _load(root / "reports" / "detail" / w["market"] / f"{w['code']}.json") or {}
    ch = [b for b in (d.get("chart") or []) if b.get("c")]
    on, off = [], []
    if len(ch) >= 30:
        c = [float(b["c"]) for b in ch]
        v = [float(b.get("v") or 0) for b in ch]
        v20 = sum(v[-21:-1]) / 20 if len(v) > 21 else 0
        s200 = ch[-1].get("s200")
        r1 = c[-1] / c[-2] - 1
        (on if v20 and v[-1] >= 2 * v20 and r1 > 0 and not (v[-1] >= 3 * v20 and c[-1] >= max(c[-20:])) else off).append(
            f"거래량 동반 상승일(2배+·추격 패턴 아님): 오늘 {v[-1] / v20 if v20 else 0:.1f}배 {r1 * 100:+.1f}%")
        if s200:
            (on if c[-1] >= float(s200) and min(c[-5:]) >= float(s200) * 0.98 else off).append(f"200일선 {float(s200):,.0f} 지지(5일 저점 −2% 안): 종가 {c[-1]:,.0f}")
    fb = _flow_both(d.get("flow_note") or "")
    if fb:
        (on if fb[0] > 0 and fb[1] > 0 else off).append(f"외국인·기관 5일 동반 순매수: 외국인 {fb[0]:+d}억 · 기관 {fb[1]:+d}억")
    peers = w.get("peers") or []
    if peers and len(ch) >= 21:
        def r20(code):
            dd = _load(root / "reports" / "detail" / w["market"] / f"{code}.json") or {}
            cc = [float(b["c"]) for b in (dd.get("chart") or []) if b.get("c")]
            return cc[-1] / cc[-6] - 1 if len(cc) >= 6 else None
        pr = [x for x in (r20(p) for p in peers) if x is not None]
        me = float(ch[-1]["c"]) / float(ch[-6]["c"]) - 1
        if pr:
            med = sorted(pr)[len(pr) // 2]
            (on if me > med else off).append(f"동종 대비 5일 상대강도: {me * 100:+.1f}% vs 동종 중앙 {med * 100:+.1f}%")
    try:
        import polars as pl
        dart = pl.read_parquet(root / "data" / "dart.parquet").filter(pl.col("code") == w["code"])
        dart = dart.filter(pl.col("category").is_in(list(DART_KEEP)))
        rec = [(str(r["date"]), r["category"], r["title"]) for r in dart.sort("date", descending=True).head(5).iter_rows(named=True)
               if (today - date.fromisoformat(str(r["date"])[:10])).days <= 7]
        (on if rec else off).append("DART 7일: " + ("; ".join(f"{x[0]} {x[1]} {x[2]}" for x in rec) if rec else "공급계약·임원매수·지분·자사주·IR 없음"))
    except Exception:  # noqa: BLE001
        off.append("DART: data/dart.parquet 없음")
    for x in w.get("industry") or []:
        off.append("업종 선행(수동 확인): " + x)
    return {"code": w["code"], "name": d.get("name") or w["code"], "on": on, "off": off,
            "action": "체크리스트 재실행" if (any(x.startswith(("외국인", "거래량", "DART")) for x in on) or len(on) >= 3) else "대기", "status": "검증전 — 감시 조건(매수 신호 아님)", "reason": w.get("reason")}


def watch_all(root: Path = ROOT) -> list[dict]:
    ws = (_load(root / "reports" / "hf_watch.json") or {}).get("watch") or []
    return [watch_status(w, root) for w in ws]


def lines(o: dict) -> list[str]:
    ls = [f"아이디어 {o['asof']}: 후보 {o['counts']['total']}개 중 상위 {len(o['ideas'])}"]
    for x in o["ideas"]:
        ls.append(f"{x['rank']:>2}. [{x['type']}] {x['market']} {x['name']}{' ' + x['code'] if x.get('code') else ''} — {x['direction']} · {x['evidence']} · {x['status'].split(' — ')[0]}")
    for m in o["macro"]:
        ls.append(f" 매크로: {m['driver']} → 수혜 {m['benefit']} / 피해 {m['hurt']}")
    for w in o.get("watch") or []:
        ls.append(f" 감시 {w['name']}: {w['action']} — 켜짐 {len(w['on'])}: " + (" / ".join(w["on"]) if w["on"] else "없음"))
    if not o["macro"]:
        ls.append(" 매크로: 임계 넘은 변화 없음(금리 ±15bp·달러 ±1.5%·WTI ±10%·VIX +30%·원달러 ±1.5%)")
    return ls


def main():
    o = build()
    o["watch"] = watch_all()
    OUT.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines(o)))


if __name__ == "__main__":
    main()
