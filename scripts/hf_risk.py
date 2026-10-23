#!/usr/bin/env python3
"""HF 재량 북 포트폴리오 위험 보고 — 노출·테마 집중·달러 노출·스트레스 5종·지수 요인 VaR (scripts/hf_book.py show 에서 호출).

노출(장부 대비, 부호 있음): 주식·선물 = 방향 × 비중, 옵션 = 보유 계약의 기초 명목 × 델타(BS).
베타조정 = 노출 × 베타(국장 vs 코스피200, 미장 vs 나스닥 종합 — hf_book.beta_of).
스트레스 = 지수 충격 × 베타(종목 고유 충격 없음) + 옵션은 충격 뒤 기초·변동성 배수·5일 경과로 BS 재평가.
VaR = 과거 250일 코스피200·나스닥 일간 수익에 베타조정 노출을 곱한 손익 분포의 5% 분위(종목 고유 위험 제외 — 표기 필수).
기준 계산 docs/desk_kb/rounds/2026-10-21-hf-gaps.md.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hf_book as H  # noqa: E402

SEMIS_US = {"LRCX", "NVDA", "AMD", "AMAT", "KLAC", "MU", "TSM", "AVGO", "INTC", "QCOM", "ASML", "SMH", "SOXX", "MRVL", "ARM", "TXN", "ADI", "NXPI", "ON", "MCHP"}
FX_WARN = 0.05
STRESS = (  # 이름, 코스피200, 나스닥, 국장 IV 배수, 미장 IV 배수
    ("2020-03형 폭락", -0.30, -0.25, 1.6, 2.5),
    ("2024-08 엔캐리형", -0.12, -0.08, 1.4, 2.0),
    ("AI 랠리", 0.10, 0.08, 0.9, 0.9),
    ("국장 단독 반등", 0.08, 0.0, 0.9, 1.0),
    ("국장 단독 급락", -0.10, 0.0, 1.3, 1.0),
)


def _sgn(p):
    return 1 if p["side"] == "롱" else -1


def _ctx():
    d, u = H.deriv_last(), H.us_last()
    return d, u


def _opt_state(p, d, u):
    us = p["kind"] in H.US
    spot = u["spx"] if us else d["k200"]
    iv = u["iv"] if us else d["iv"]
    t = max((date.fromisoformat(p["expiry"]) - date.fromisoformat(u["date"] if us else d["date"])).days, 0) / 365
    return spot, iv, t, (p["kind"][4:] if us else p["kind"])


def _spread_now(p, d):
    import hf_spread as SP
    st = H.spread_state(p, d)
    return st, SP.years(p["expiry"], st["date"])


def exposure(p, d, u) -> float:
    """장부 대비 델타 노출(부호 있음, 베타 전)."""
    if p["kind"] in H.SPREAD:
        import hf_spread as SP
        st, t = _spread_now(p, d)
        return SP.delta(H.bs_delta, p["right"], st["s"], p["k_long"], p["k_short"], t, st["iv"]) * st["s"] * p["contracts"] * st["mult"] / H.AUM
    if p["kind"] in H.OPT:
        spot, iv, t, k = _opt_state(p, d, u)
        units = p["weight"] / p["entry"] if p["entry"] else 0.0
        return units * spot * H.bs_delta(k, spot, p["strike"], t, iv)
    return _sgn(p) * p["weight"]


def beta(p) -> float:
    if p["kind"] in ("spx_put", "spx_call"):
        return H.beta_of("es", None)
    return p.get("beta") or 1.0


def theme(p) -> str:
    if p["kind"] in H.SPREAD:
        und = p.get("und")
        if und == "K200":
            return "반도체"
        if und == "SPX":
            return "미 지수"
        return theme({**p, "kind": "stock" if p["kind"] == "spread" else "us_stock", "code": und})
    if p["kind"] in ("fut", "put", "call"):
        return "반도체"          # 코스피200 = 삼성전자·SK하이닉스 비중이 커서 반도체 테마로 묶는다
    if p["kind"] == "stock":
        try:
            t = json.loads((ROOT / "reports" / "detail" / "KR" / f"{p['code']}.json").read_text(encoding="utf-8")).get("theme") or ""
        except Exception:  # noqa: BLE001
            t = ""
        return "반도체" if "반도체" in t else (t.split("|")[0] or f"KR:{p['code']}")
    if p["kind"] == "us_stock":
        return "반도체" if p["code"] in SEMIS_US else f"US:{p['code']}"
    return "미 지수"


def stress_pnl(b, d, u, k200, ndx, mkr, mus) -> float:
    tot = 0.0
    es_b = H.beta_of("es", None)
    for p in b["open"]:
        if p["kind"] in H.SPREAD:
            import hf_spread as SP
            st, t = _spread_now(p, d)
            shock = (ndx if p["kind"] in H.US else k200) * (p.get("beta") or 1.0)
            new = SP.value(H.bs, p["right"], st["s"] * (1 + shock), p["k_long"], p["k_short"], max(t - 5 / 365, 0), st["iv"] * (mus if p["kind"] in H.US else mkr))
            tot += (new - p["last"]) * p["contracts"] * st["mult"] / H.AUM
            continue
        if p["kind"] in H.OPT:
            spot, iv, t, k = _opt_state(p, d, u)
            shock = (es_b * ndx) if p["kind"] in H.US else k200
            new = H.bs(k, spot * (1 + shock), p["strike"], max(t - 5 / 365, 0), iv * (mus if p["kind"] in H.US else mkr))
            tot += p["weight"] * (new - p["last"]) / p["entry"]
        else:
            shock = ndx if p["kind"] in H.US else k200
            tot += _sgn(p) * p["weight"] * beta(p) * shock
    return tot


def _series():
    kr = {r["date"]: float(r["k200_close"]) for r in csv.DictReader(open(ROOT / "data" / "deriv" / "daily.csv", encoding="utf-8")) if r.get("k200_close")}
    us = {x[0]: x[4] for x in json.loads((ROOT / "reports" / "macro_series.json").read_text(encoding="utf-8"))["series"]["NASDAQ"]}
    return kr, us


def var_es(e_kr: float, e_us: float, n: int = 250) -> tuple[float, float, int] | None:
    kr, us = _series()
    ds = sorted(set(kr) & set(us))
    if len(ds) < 60:
        return None
    ds = ds[-(n + 1):]
    pl = sorted(e_kr * (kr[ds[i]] / kr[ds[i - 1]] - 1) + e_us * (us[ds[i]] / us[ds[i - 1]] - 1) for i in range(1, len(ds)))
    k = max(1, int(0.05 * len(pl)))
    return -pl[k - 1], -sum(pl[:k]) / k, len(pl)


def _with_baskets(b: dict) -> dict:
    """바스켓(hf_basket) 다리를 주식 포지션처럼 펼쳐 노출·테마·스트레스·VaR 에 넣는다."""
    legs = [{"kind": "stock", "side": l["side"], "weight": l["w"], "code": l["code"], "name": l["name"], "beta": l["beta"]}
            for x in (b.get("baskets") or {}).get("open") or [] for l in x["legs"]]
    return {**b, "open": b["open"] + legs} if legs else b


def report_lines(b: dict) -> list[str]:
    b = _with_baskets(b)
    if not b["open"]:
        return ["위험: 열린 포지션 없음"]
    d, u = _ctx()
    rows = [(p, exposure(p, d, u)) for p in b["open"]]
    gross = sum(abs(e) for _, e in rows)
    e_kr = sum(e for p, e in rows if p["kind"] not in H.US)
    e_us = sum(e for p, e in rows if p["kind"] in H.US)
    b_kr = sum(e * beta(p) for p, e in rows if p["kind"] not in H.US)
    b_us = sum(e * beta(p) for p, e in rows if p["kind"] in H.US)
    ls = [f"위험: 총 델타노출 {gross * 100:.1f}% · 국장 순 {e_kr * 100:+.2f}%(베타 {b_kr * 100:+.2f}%) · 미장 순 {e_us * 100:+.2f}%(베타 {b_us * 100:+.2f}%)"
          + f" · 달러 순노출 {e_us * 100:+.2f}%" + (" ⚠️ ±5% 초과 — 환헤지 검토" if abs(e_us) > FX_WARN else "")]
    th = {}
    for p, e in rows:
        th.setdefault(theme(p), []).append((p, e))
    warn = [f"{k} 롱 중복({', '.join(x['name'] for x, e in v if e > 0)})" for k, v in th.items() if sum(1 for _, e in v if e > 0) >= 2]
    warn += [f"{k} 숏 중복({', '.join(x['name'] for x, e in v if e < 0)})" for k, v in th.items() if sum(1 for _, e in v if e < 0) >= 2]
    tl = " · ".join(f"{k} {sum(e for _, e in v) * 100:+.2f}%" for k, v in sorted(th.items(), key=lambda kv: -abs(sum(e for _, e in kv[1]))))
    ls.append(f"테마 순노출: {tl}" + (f" · ⚠️ {'; '.join(warn)}" if warn else ""))
    st = [(nm, stress_pnl(b, d, u, k, n, a, c)) for nm, k, n, a, c in STRESS]
    worst = min(st, key=lambda x: x[1])
    ls.append("스트레스: " + " · ".join(f"{nm} {v * 100:+.2f}%" for nm, v in st) + f" → 최악 {worst[0]}")
    ve = var_es(b_kr, b_us)
    if ve:
        ls.append(f"VaR(1일 95%, 지수 요인만·종목 고유 제외) {ve[0] * 100:.2f}% · ES {ve[1] * 100:.2f}% (과거 {ve[2]}일)")
    return ls


if __name__ == "__main__":
    print("\n".join(report_lines(H.load())))
