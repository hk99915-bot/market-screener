#!/usr/bin/env python3
"""검증 데스크 주간 독립 채점 — 알파북(체계)·HF 재량 북 (req-verify-ef13d7a3 · req-verify-53fd7992, 2026-10-23 규약 v1).

비유: 장부를 쓴 사람이 아니라 옆 부서가 영수증(체결 기록)과 시세표(원 가격)만 들고 장부 잔액을 다시 맞춰 보는 것.
독립성(kb:verify#8): screener/alphabook.py · scripts/hf_book.py 를 import 하지 않는다. 상태 파일의 '체결 기록'과
reports/detail 차트(o·h·l·c)·data/deriv/daily.csv 만 읽어 다시 계산한다. 규약 숫자(벤치·비용·한도)는 명세(머리말·요청 원문)에서 옮겨 적었다.

규약(매주 금 장후, KR·US 각각) — 사전 고정, 바꾸면 버전을 올리고 이유를 docs/desk_kb/verify.md 에 적는다:
 A 알파북 (reports/alphabook.json)
  A1 수익: NAV 재계산(현금 + Σ수량×종가) vs 장부 nav[] — 일치 허용오차 |차| ≤ 0.0001(0.01%p). 누적·벤치(KR 069500·US SPY 종가)
     누적·초과 누적. IR = 일별 초과 평균÷표준편차×√252, 표본 < 20일이면 미산출(장부 규칙과 같음).
  A2 청산 R: n·적중률(R>0)·평균·중앙·분포(≤−1 / −1~0 / 0~1.5 / >1.5). 소스 OOS 예상(B1 1차 선도달 36%·손절 46%·E[R] +0.083R)과
     비교는 Wilson 95% 구간(kb:verify#4) — 예상이 구간 밖이면 '이탈'.
  A3 규칙 위반: ① 스탑 — 보유 중 봉 저가 ≤ 스탑인데 다음 봉 시가에 청산 안 됨 ② 진입 — 체결가가 주문 구간 [lo,hi] 밖이거나
     after 다음 첫 봉 시가가 아님 ③ 크기 — 주문 weight 가 0.5%×컨빅션×시장배수÷손절폭(상한 15%) 식과 1% 넘게 다름, 또는
     체결가 기준 실현 리스크가 주문 리스크의 1.1배 초과(⚠ 경고 — 위반 아님, 체결가가 기준가보다 불리했다는 뜻).
  A4 중단 판정: 8주(40거래일) 누적 실현 E[R] ≤ 기준선 −0.015R → 'B1 진입 중단'. n < 10 이면 '판정 보류(n 부족)' + SE 병기.
 H HF 재량 북 (reports/hf_discretion.json)
  H1 동일 노출 초과: 각 회차 손익(R×리스크) − 같은 부호·같은 명목을 KR=코스피200 선물(fut_close)·US=SPY 에 같은 기간 둔 손익.
     옵션은 델타 미상 → 벤치 0(표기). 장부 손익 재현: Σ청산 R×리스크 + 열린 회차 평가 vs 장부 nav[] 마지막 pnl, 허용오차 0.0001.
  H2 청산 R 분포·적중률(헤지 다리 포함/제외 둘 다), 주관 승률 있는 회차는 Brier.
  H3 무효: trade plan(진입·손절·1차 목표) · 사전 손절 · 청산 사유 중 하나라도 없으면 성적 무효(문언). 옵션 매수의 '손절 없음'은
     문언상 무효로 세되 '정의된 위험(프리미엄)'으로 따로 표기 — HF 해석 회신 대기.
  H4 겹침: 날짜별 KR 순노출 부호(HF 재량·알파북·PB 픽 decisions.json) — 같은 날 둘 다 노출일 때 같은 방향 비율, 같은 종목 같은 방향 건수.
     일별 수익 상관은 표본 20일 미만이면 미산출.
산출: reports/verify_weekly/<날짜>.json · .md (개인 금액·보유 없음 — 가상 1단위 모의 장부만).
사용: python3 scripts/verify_weekly.py [--date YYYY-MM-DD] [--write]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "verify_weekly"
TOL = 0.0001
BENCH = {"KR": "069500", "US": "SPY"}
EXPECT = {"B1": {"t1_first": 0.36, "stop": 0.46, "ev_r": 0.083}}
BASELINE_R = -0.015
RISK_BASE, WEIGHT_CAP = 0.005, 0.15
INVERSE = {"114800", "252670", "SOXS", "SQQQ", "SPXU", "SH", "PSQ", "SDS"}


# ───────────── 순수 함수 ─────────────

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (mid - half, mid + half)


def ir(excess: list[float], min_n: int = 20) -> float | None:
    if len(excess) < min_n:
        return None
    sd = st.pstdev(excess)
    return None if sd == 0 else st.mean(excess) / sd * math.sqrt(252)


def r_summary(rs: list[float]) -> dict:
    n = len(rs)
    if n == 0:
        return {"n": 0}
    hit = sum(1 for r in rs if r > 0)
    se = st.stdev(rs) / math.sqrt(n) if n > 1 else None
    return {"n": n, "hit": hit / n, "hit_ci": wilson(hit, n), "mean": st.mean(rs), "median": st.median(rs), "se": se,
            "bins": {"≤−1": sum(r <= -1 for r in rs), "−1~0": sum(-1 < r <= 0 for r in rs),
                     "0~1.5": sum(0 < r <= 1.5 for r in rs), ">1.5": sum(r > 1.5 for r in rs)}}


def stop_decision(rs: list[float], min_n: int = 10, base: float = BASELINE_R) -> dict:
    s = r_summary(rs)
    if s["n"] < min_n:
        return {"verdict": "판정 보류(n 부족)", "n": s["n"], "mean": s.get("mean"), "se": s.get("se")}
    return {"verdict": "B1 진입 중단" if s["mean"] <= base else "유지", "n": s["n"], "mean": s["mean"], "se": s["se"]}


def replay_nav(cash: float, holdings: dict, closes: dict) -> float:
    """holdings {code: qty} · closes {code: 종가} — 현금 + Σ 수량×종가."""
    return cash + sum(q * closes[c] for c, q in holdings.items())


def stop_breaches(bars: list[dict], entry_d: str, stop: float, exit_d: str | None) -> list[dict]:
    """보유 중 저가 ≤ 스탑인 봉 → 다음 봉 시가 청산이어야 함. exit_d 가 그 다음 봉 날짜가 아니면 위반."""
    out = []
    held = [b for b in bars if b["t"] >= entry_d and (exit_d is None or b["t"] < exit_d)]
    for i, b in enumerate(held):
        if b["l"] <= stop:
            nxt = next((x["t"] for x in bars if x["t"] > b["t"]), None)
            out.append({"bar": b["t"], "low": b["l"], "stop": stop, "need_exit": nxt, "exit_d": exit_d,
                        "ok": exit_d is not None and nxt is not None and exit_d == nxt})
            break
    return out


def entry_check(order: dict, fill_d: str, fill_px: float, bars: list[dict]) -> dict:
    nxt = next((b for b in bars if b["t"] > order["after"]), None)
    in_band = order["lo"] - 1e-9 <= fill_px <= order["hi"] + 1e-9
    at_open = nxt is not None and nxt["t"] == fill_d and abs(nxt["o"] - fill_px) <= 1e-6 * max(1.0, fill_px)
    return {"in_band": in_band, "next_open": at_open, "ok": in_band and at_open}


def size_check(order: dict, fill_px: float) -> dict:
    """주문 식 재계산(명세 문자열의 숫자) + 체결가 기준 실현 리스크."""
    import re
    m = re.search(r"([\d.]+)% × 컨빅션 ([\d.]+) × 시장 ([\d.]+) ÷ 손절폭 ([\d.]+)%", order.get("formula", ""))
    out = {"weight": order["weight"], "risk_plan": order.get("risk_pct")}
    if m:
        base, conv, mult, sp = (float(m.group(i)) for i in range(1, 5))
        w = min(base / 100 * conv * mult / (sp / 100), WEIGHT_CAP)
        out["weight_formula"] = w
        out["formula_ok"] = abs(w - order["weight"]) <= 0.01 * w + 0.0005   # 공식 문자열의 손절폭 반올림(0.1%) 허용
    real = order["weight"] * (fill_px - order["stop"]) / fill_px
    out["risk_real"] = real
    out["risk_warn"] = bool(order.get("risk_pct")) and real > 1.1 * order["risk_pct"]
    return out


def sign_of(x: float, eps: float = 1e-9) -> int:
    return 0 if abs(x) < eps else (1 if x > 0 else -1)


def overlap(days: dict) -> dict:
    """days {d: {book: sign}} → 같은 날 둘 다 노출일 때 같은 방향 비율(쌍별)."""
    books = sorted({b for v in days.values() for b in v})
    res = {}
    for i, a in enumerate(books):
        for b in books[i + 1:]:
            both = [(v[a], v[b]) for v in days.values() if v.get(a) and v.get(b)]
            res[f"{a}~{b}"] = {"days_both": len(both), "same": sum(x == y for x, y in both),
                               "ratio": (sum(x == y for x, y in both) / len(both)) if both else None}
    return res


# ───────────── 파일 읽기 ─────────────

def _chart(market: str, code: str) -> list[dict]:
    p = ROOT / "reports" / "detail" / market / f"{code}.json"
    if not p.exists():
        return []
    return [b for b in json.loads(p.read_text()).get("chart") or [] if b.get("t")]


def _fut() -> dict:
    out = {}
    with open(ROOT / "data" / "deriv" / "daily.csv") as f:
        for r in csv.DictReader(f):
            try:
                out[r["date"]] = float(r["fut_close"])
            except (TypeError, ValueError):
                pass
    return out


def _git_orders(path: str = "reports/alphabook.json", since: str = "2026-10-01") -> dict:
    """상태 파일 git 이력에서 주문(pending)을 모은다 — 체결 뒤 사라지므로 이력이 유일한 원천. 키 = (시장, 코드, created)."""
    import subprocess
    try:
        revs = subprocess.run(["git", "-C", str(ROOT), "log", f"--since={since}", "--format=%h", "--", path],
                              capture_output=True, text=True, timeout=60).stdout.split()
    except Exception:
        return {}
    orders = {}
    for h in revs:
        try:
            d = json.loads(subprocess.run(["git", "-C", str(ROOT), "show", f"{h}:{path}"], capture_output=True,
                                          text=True, timeout=30).stdout)
        except Exception:
            continue
        for m, b in (d.get("books") or {}).items():
            for o in b.get("pending") or []:
                orders.setdefault((m, o["code"], o["created"]), o)
    return orders


def score_alphabook(ab: dict, asof: str) -> dict:
    orders = _git_orders()
    out = {}
    for m, b in ab["books"].items():
        bench = {x["t"]: x["c"] for x in _chart(m, BENCH[m])}
        rec = {"bench": BENCH[m]}
        # A1 NAV 재계산 — 체결 기록을 날짜순으로 재생
        cost = None
        fills = sorted(b.get("fills") or [], key=lambda f: f["d"])
        pos_qty = {p["code"]: p["qty0"] for p in b["positions"]}
        pos_qty.update({c["code"]: c.get("qty0", 0) for c in b.get("closed") or []})
        buys = [f for f in fills if f["kind"] == "buy"]
        if buys:
            gross = sum(pos_qty[f["code"]] * f["px"] for f in buys)
            cost = (1 - b["cash"]) / gross - 1 if not [f for f in fills if f["kind"] != "buy"] else None
        navs = []
        for row in b["nav"]:
            d = row["d"]
            held = {f["code"]: pos_qty[f["code"]] for f in buys if f["d"] <= d}
            closes = {}
            for c in held:
                bar = next((x for x in _chart(m, c) if x["t"] == d), None)
                if bar:
                    closes[c] = bar["c"]
            if len(closes) < len(held) or [f for f in fills if f["kind"] != "buy"]:
                navs.append({"d": d, "book": row["nav"], "rep": None})
                continue
            spent = sum(held[c] * next(f["px"] for f in buys if f["code"] == c) for c in held)
            cash = 1.0 - spent * (1 + (cost or 0))
            navs.append({"d": d, "book": row["nav"], "rep": replay_nav(cash, held, closes)})
        for r in navs:
            r["ok"] = None if r["rep"] is None else abs(r["rep"] - r["book"]) <= TOL
        rec["nav_rows"] = navs
        rec["side_cost_implied"] = cost
        d0 = b["nav"][0]["d"]
        last = navs[-1]
        b0, b1 = bench.get(d0), bench.get(last["d"])
        nav_last = last["rep"] if last["rep"] is not None else last["book"]
        rec["cum"] = nav_last - 1
        rec["bench_cum"] = (b1 / b0 - 1) if b0 and b1 else None
        rec["excess_cum"] = rec["cum"] - rec["bench_cum"] if rec["bench_cum"] is not None else None
        ex, prev = [], None
        for r in navs[1:]:
            i = navs.index(r)
            nv0 = navs[i - 1]["rep"] if navs[i - 1]["rep"] is not None else navs[i - 1]["book"]
            nv1 = r["rep"] if r["rep"] is not None else r["book"]
            bb0, bb1 = bench.get(navs[i - 1]["d"]), bench.get(r["d"])
            if bb0 and bb1:
                ex.append(nv1 / nv0 - 1 - (bb1 / bb0 - 1))
        rec["n_days"] = len(ex)
        rec["ir"] = ir(ex)
        rec["book_stats"] = (ab.get("summary") or {}).get(m, {}).get("stats")
        # A2 청산 R
        rs = [c.get("r") for c in b.get("closed") or [] if isinstance(c.get("r"), (int, float))]
        rec["closed_r"] = r_summary(rs)
        rec["expect"] = EXPECT
        # A3 위반
        viol, warn = [], []
        for f in buys:
            bars = _chart(m, f["code"])
            od = [o for (mm, c, cr), o in orders.items() if mm == m and c == f["code"] and cr <= f["d"]]
            if not od:
                warn.append(f"{f['code']} 주문 이력 없음 — 진입·크기 미검")
                continue
            o = sorted(od, key=lambda o: o["created"])[-1]
            ec = entry_check(o, f["d"], f["px"], bars)
            sc = size_check(o, f["px"])
            if not ec["ok"]:
                viol.append({"code": f["code"], "rule": "진입", **ec})
            if sc.get("formula_ok") is False:
                viol.append({"code": f["code"], "rule": "크기 공식", **sc})
            if sc["risk_warn"]:
                warn.append(f"{f['code']} 체결가 기준 리스크 {sc['risk_real']:.3%} > 주문 {o['risk_pct']:.3%}×1.1 "
                            f"(주문 기준가 대비 체결가 불리 — 크기를 체결가로 다시 맞추지 않음)")
        for p in list(b["positions"]) + list(b.get("closed") or []):
            for x in stop_breaches(_chart(m, p["code"]), p["entry_d"], p["stop"], p.get("exit_d")):
                if not x["ok"]:
                    viol.append({"code": p["code"], "rule": "스탑 다음 봉 시가", **x})
        rec["violations"] = viol
        rec["warnings"] = warn
        # A4
        rec["stop_decision"] = stop_decision(rs)
        out[m] = rec
    return out


def score_hf(hf: dict, ab: dict, decisions: dict, asof: str) -> dict:
    fut = _fut()
    spy = {x["t"]: x["c"] for x in _chart("US", "SPY")}
    rows, rs_all, rs_nohedge, brier = [], [], [], []
    pnl_closed = 0.0
    for p in hf.get("closed") or []:
        r, risk = p.get("r"), p.get("risk") or 0
        pnl = (r or 0) * risk
        pnl_closed += pnl
        mkt = p.get("market") or ("US" if p["kind"] in ("us_stock", "es", "nq", "spx_put", "spx_call") else "KR")
        sgn = 1 if p["side"] == "롱" else -1
        idx = fut if mkt == "KR" else spy
        d0, d1 = p.get("asof"), p.get("exit_d")
        opt = p["kind"] in ("put", "call", "spx_put", "spx_call")
        bpnl = None
        if not opt and idx.get(d0) and idx.get(d1):
            bpnl = sgn * (p.get("weight") or 0) * (idx[d1] / idx[d0] - 1)
        elif opt:
            bpnl = 0.0
        missing = [k for k, ok in (("plan", p.get("entry") and (p.get("stop") or opt) and p.get("t1")),
                                   ("사전 손절", p.get("stop") is not None), ("청산 사유", p.get("exit_why"))) if not ok]
        rows.append({"id": p["id"], "kind": p["kind"], "side": p["side"], "code": p.get("code"), "mkt": mkt,
                     "r": r, "pnl": pnl, "bench_pnl": bpnl, "excess": None if bpnl is None else pnl - bpnl,
                     "hedge": bool(p.get("hedge_of")), "invalid": missing, "option_defined_risk": opt and p.get("stop") is None})
        if isinstance(r, (int, float)):
            rs_all.append(r)
            if not p.get("hedge_of"):
                rs_nohedge.append(r)
            pw = (p.get("plan") or {}).get("p_win") or (p.get("check") or {}).get("p_win")
            if isinstance(pw, (int, float)):
                brier.append((pw - (1.0 if r > 0 else 0.0)) ** 2)
    pnl_open = 0.0
    for p in hf.get("open") or []:
        if p.get("r_unit") and p.get("last") and p.get("entry"):
            sgn = 1 if p["side"] == "롱" else -1
            pnl_open += sgn * (p["last"] - p["entry"]) / p["r_unit"] * (p.get("risk") or 0)
    for bk in (hf.get("baskets") or {}).get("open") or []:
        pnl_open += bk.get("pnl") or 0
    book_pnl = (hf.get("nav") or [{}])[-1].get("pnl")
    rep = pnl_closed + pnl_open
    valid = [x for x in rows if not x["invalid"]]
    ex = [x["excess"] for x in rows if x["excess"] is not None]
    # H4 겹침 — KR 날짜별 순노출 부호
    days: dict = {}
    for p in list(hf.get("closed") or []) + list(hf.get("open") or []):
        if (p.get("market") or "KR") != "KR" or p["kind"] in ("us_stock", "es", "nq", "spx_put", "spx_call"):
            continue
        sgn = (1 if p["side"] == "롱" else -1) * (-1 if p["kind"] == "put" else 1)
        for d in sorted(fut):
            if p.get("asof") and p["asof"] <= d <= (p.get("exit_d") or asof) and d >= "2026-10-19":
                days.setdefault(d, {}).setdefault("_hf", 0.0)
                days[d]["_hf"] += sgn * (p.get("weight") or 0)
    for f in (ab["books"]["KR"].get("fills") or []):
        for d in sorted(fut):
            if f["kind"] == "buy" and f["d"] <= d <= asof:
                days.setdefault(d, {})["알파북"] = 1
    same_code = []
    hf_codes = {(p.get("code"), "롱" if p["side"] == "롱" else "숏") for p in list(hf.get("closed") or []) + list(hf.get("open") or [])}
    for f in ab["books"]["KR"].get("fills") or []:
        if (f["code"], "롱") in hf_codes:
            same_code.append(f"{f['code']} {f.get('name', '')} — 알파북·HF 재량 같은 방향(롱)")
    for it in decisions.get("items") or []:
        if it.get("kind") != "entry" or it.get("date", "") < "2026-10-19":
            continue
        for who in ("PB", "PB🔥"):          # PB 재량·공격 PB 는 따로 센다(같은 PB 라도 픽이 다름)
            pk = (it.get("picks") or {}).get(who) or {}
            t = pk.get("ticker")
            if t and t[:1].isdigit():
                days.setdefault(it["date"], {})[who] = -1 if (t in INVERSE or "인버스" in (pk.get("name") or "")) else 1
    for d, v in days.items():
        if "_hf" in v:
            v["HF재량"] = sign_of(v.pop("_hf"))
    return {"rows": rows, "pnl_rep": rep, "pnl_book": book_pnl, "pnl_ok": book_pnl is not None and abs(rep - book_pnl) <= TOL,
            "excess_sum": sum(ex) if ex else None, "r_all": r_summary(rs_all), "r_nohedge": r_summary(rs_nohedge),
            "brier": (st.mean(brier), len(brier)) if brier else None, "invalid_n": len(rows) - len(valid), "n": len(rows),
            "overlap_days": {d: days[d] for d in sorted(days)}, "overlap": overlap(days), "same_code": same_code,
            "corr": "미산출(일별 표본 < 20)"}


def render(res: dict) -> str:
    def pct(x, n=2):
        return "—" if x is None else f"{x * 100:+.{n}f}%"
    L = [f"# 주간 독립 채점 — {res['asof']} (검증 데스크, 규약 v1)", "",
         "> 가상 1단위 모의 장부만. 원 코드(alphabook.py·hf_book.py) 미사용 — 체결 기록 + 원 가격으로 재계산. 규약: scripts/verify_weekly.py 머리말.", ""]
    L.append("## A. 알파북")
    L.append("| 시장 | NAV 재현 | 누적 | 벤치 누적 | 초과 누적 | IR | 청산 n | 위반 | 경고 | 중단 판정 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for m, r in res["alphabook"].items():
        ok = [x["ok"] for x in r["nav_rows"] if x["ok"] is not None]
        L.append(f"| {m}({r['bench']}) | {sum(ok)}/{len(ok)} 일치 | {pct(r['cum'])} | {pct(r['bench_cum'])} | {pct(r['excess_cum'])} | "
                 f"{'미산출(n ' + str(r['n_days']) + '<20)' if r['ir'] is None else round(r['ir'], 2)} | {r['closed_r']['n']} | "
                 f"{len(r['violations'])} | {len(r['warnings'])} | {r['stop_decision']['verdict']} |")
    for m, r in res["alphabook"].items():
        for v in r["violations"]:
            L.append(f"- ❌ {m} {v['code']} {v['rule']}: {json.dumps({k: v[k] for k in v if k not in ('code', 'rule')}, ensure_ascii=False)}")
        for w in r["warnings"]:
            L.append(f"- ⚠ {m} {w}")
    L.append(f"- A2 소스 OOS 예상(B1 1차 선도달 36%·손절 46%·E[R] +0.083R) 대조: 청산 0건이면 미대조 — 첫 대조는 청산 ≥ 1건 주부터, 판정은 Wilson 구간.")
    h = res["hf"]
    L += ["", "## H. HF 재량 북",
          f"- H1 장부 손익 재현: 재현 {pct(h['pnl_rep'], 3)} vs 장부 {pct(h['pnl_book'], 3)} → {'일치' if h['pnl_ok'] else '불일치'}(허용 0.01%p). "
          f"동일 노출(KR 코스피200 선물·US SPY, 옵션 0) 대비 초과 합 {pct(h['excess_sum'], 3)}. "
          "주의: 벤치는 진입일·청산일 **종가** 근사 — 선물 회차의 '초과'는 장중 청산 시각 차이일 뿐 알파가 아니다.",
          f"- H2 청산 R(전체 n {h['r_all']['n']}): 적중 {pct(h['r_all'].get('hit'), 0)} · 평균 {h['r_all'].get('mean', 0):+.3f}R · 중앙 {h['r_all'].get('median', 0):+.3f}R · "
          f"분포 {h['r_all'].get('bins')} / 헤지 다리 제외 n {h['r_nohedge']['n']} 평균 {h['r_nohedge'].get('mean', 0):+.3f}R · "
          f"Brier {('%.3f (n %d)' % h['brier']) if h['brier'] else '—'}",
          f"- H3 무효(문언): {h['invalid_n']}/{h['n']}회차", "",
          "| id | 종류 | 방향 | R | 손익 | 동일노출 | 초과 | 무효 사유 |", "|---|---|---|---|---|---|---|---|"]
    for x in h["rows"]:
        L.append(f"| {x['id']} | {x['kind']}{'(헤지)' if x['hedge'] else ''} | {x['side']} | {x['r']:+.3f} | {pct(x['pnl'], 3)} | "
                 f"{pct(x['bench_pnl'], 3)} | {pct(x['excess'], 3)} | {', '.join(x['invalid']) or '—'}{' (옵션 정의된 위험)' if x['option_defined_risk'] else ''} |")
    L += ["", "- H4 겹침(KR 날짜별 순노출 부호): " + json.dumps(h["overlap_days"], ensure_ascii=False),
          "- 쌍별 같은 방향 비율: " + "; ".join(f"{k} {v['same']}/{v['days_both']}" for k, v in h["overlap"].items()),
          "- 같은 종목 같은 방향: " + ("; ".join(h["same_code"]) or "없음"), f"- 일별 수익 상관: {h['corr']}", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    ab = json.loads((ROOT / "reports" / "alphabook.json").read_text())
    hf = json.loads((ROOT / "reports" / "hf_discretion.json").read_text())
    dec = json.loads((ROOT / "reports" / "decisions.json").read_text())
    asof = a.date or max(b["last_bar"] for b in ab["books"].values() if b.get("last_bar"))
    res = {"asof": asof, "protocol": "v1", "alphabook": score_alphabook(ab, asof), "hf": score_hf(hf, ab, dec, asof),
           "inputs": {"alphabook_updated": ab.get("updated"), "hf_asof": hf.get("asof")}}
    md = render(res)
    if a.write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / f"{asof}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        (OUT_DIR / f"{asof}.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
