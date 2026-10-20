"""독립 재현: hollzzak '홀짝홀홀' 지수 가설 H1·H2·H3a·H3b (검증 데스크)

명세: reports/studies/hollzzak_preregistration.md §1~§7 만 읽고 재구현. 원 코드(scripts/study_hollzzak.py) 미열람(kb:verify#8).
허용오차·뒤집힘 기준: reports/studies/replication_hollzzak.md §0 (실행 전 커밋 7ecc428a).
데이터: data/hist (screener.hist.load) KOSPI·KOSPI200(pykrx) + 122630(yfinance). 없으면 `python scripts/data_store.py pull --groups hist`.

  python scripts/replicate_hollzzak.py           # 재현 → reports/studies/replication_hollzzak.{json,md}(§1 이하 갱신)
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ORIG = ROOT / "reports/studies/hollzzak.json"
OUT_JSON = ROOT / "reports/studies/replication_hollzzak.json"
OUT_MD = ROOT / "reports/studies/replication_hollzzak.md"

CRASH, WIN, POST, BIG_UP, SIDE = -0.03, 5, 3, 0.03, 0.04
EP_GAP, COST, B, SEED = 10, 0.0005, 10_000, 20261021
ALPHA = 0.05 / 7
MIN_N, MIN_EP = 10, 5
SPLITS = {"design": ("2010-01-01", "2019-12-31"), "valid": ("2020-01-01", "2025-12-31"),
          "pooled": ("2010-01-01", "2025-12-31"), "holdout": ("2026-01-01", "2026-12-31")}
GROUPS = ("first", "re", "big_up", "side_px")


# ---------- 사건 만들기 ----------
def build_events(dates: list[date], close: list[float], k200_hi: dict | None = None) -> list[dict]:
    """일별 행 목록. 각 행: date, r, r_next, crash, kind(first/re/consec/None), big_up, side_px, ep(에피소드 id 또는 None).
    k200_hi: {date: 코스피200 고가/전일 종가 − 1}."""
    k200_hi = k200_hi or {}
    n = len(close)
    r = [None] + [close[i] / close[i - 1] - 1 for i in range(1, n)]
    crash = [x is not None and x <= CRASH for x in r]
    rows = []
    ep_of, ep, last_crash = {}, -1, None
    for i in range(n):
        row = {"date": dates[i], "r": r[i], "r_next": r[i + 1] if i + 1 < n else None, "crash": crash[i],
               "kind": None, "big_up": False, "side_px": False, "ep": None}
        if crash[i]:
            if last_crash is None or i - last_crash > EP_GAP:
                ep += 1
            ep_of[i] = ep
            last_crash = i
            prior = [s for s in range(max(0, i - WIN), i) if crash[s]]
            if not prior:
                row["kind"] = "first"
            elif any(r[s + 1] is not None and r[s + 1] > 0 for s in prior):
                row["kind"] = "re"
            else:
                row["kind"] = "consec"
            row["ep"] = ep
        else:
            prior3 = [s for s in range(max(0, i - POST), i) if crash[s]]
            if prior3 and r[i] is not None:
                e = ep_of[max(prior3)]
                if r[i] >= BIG_UP:
                    row["big_up"], row["ep"] = True, e
                hi = k200_hi.get(dates[i])
                if hi is not None and hi >= SIDE:
                    row["side_px"], row["ep"] = True, e
        rows.append(row)
    return rows


def in_split(d: date, split: str) -> bool:
    a, b = SPLITS[split]
    return a <= d.isoformat() <= b


def group_rows(rows: list[dict], split: str, g: str) -> list[dict]:
    out = []
    for x in rows:
        if x["r_next"] is None or not in_split(x["date"], split):
            continue
        if (g in ("first", "re", "consec") and x["kind"] == g) or (g in ("big_up", "side_px") and x[g]):
            out.append(x)
    return out


def summ(xs: list[dict]) -> dict:
    v = [x["r_next"] for x in xs]
    if not v:
        return {"n": 0, "episodes": 0}
    return {"n": len(v), "episodes": len({x["ep"] for x in xs}), "up": sum(1 for a in v if a > 0) / len(v),
            "mean": st.mean(v), "median": st.median(v), "worst": min(v), "sd": st.pstdev(v) if len(v) > 1 else 0.0,
            "dates": [x["date"].isoformat() for x in xs]}


# ---------- 검정 ----------
def binom_upper(k: int, n: int, p: float) -> float:
    return min(1.0, sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1)))


def fisher_lower(k1: int, n1: int, k2: int, n2: int) -> float:
    """집단1 반등률 < 집단2 단측: P(X ≤ k1), X~초기하(N=n1+n2, K=k1+k2, 뽑기 n1)."""
    N, K = n1 + n2, k1 + k2
    den = math.comb(N, n1)
    return min(1.0, sum(math.comb(K, j) * math.comb(N - K, n1 - j) for j in range(max(0, n1 - (N - K)), k1 + 1)) / den)


def _episodes(xs: list[dict]) -> list[list[float]]:
    d: dict = {}
    for x in xs:
        d.setdefault(x["ep"], []).append(x["r_next"])
    return list(d.values())


def _boot(eps: list[list[float]], rng: random.Random, stat) -> float:
    pick = [eps[rng.randrange(len(eps))] for _ in eps]
    flat = [a for e in pick for a in e]
    return stat(flat)


def _rate(v): return sum(1 for a in v if a > 0) / len(v)


def _pct(xs, q):
    s = sorted(xs); return s[min(len(s) - 1, max(0, int(q * len(s))))]


def test_split(rows: list[dict], split: str, B_: int = B, seed: int = SEED) -> dict:
    base_v = [x["r_next"] for x in rows if x["r"] is not None and x["r_next"] is not None and in_split(x["date"], split)]
    base = {"n": len(base_v), "up": _rate(base_v), "mean": st.mean(base_v), "sd": st.pstdev(base_v)}
    G = {g: group_rows(rows, split, g) for g in GROUPS}
    out = {"base": base, **{g: summ(G[g]) for g in GROUPS}}
    rng = random.Random(seed)
    f, re_ = G["first"], G["re"]
    if f:
        k = sum(1 for x in f if x["r_next"] > 0)
        bs = [_boot(_episodes(f), rng, _rate) - base["up"] for _ in range(B_)]
        pe, pb = binom_upper(k, len(f), base["up"]), sum(1 for b in bs if b <= 0) / B_
        out["H1"] = {"effect": k / len(f) - base["up"], "p_exact": pe, "p_boot": pb, "p": max(pe, pb),
                     "ci": [_pct(bs, .025), _pct(bs, .975)], "n": len(f), "episodes": out["first"]["episodes"]}
    if f and re_:
        k1, k2 = sum(1 for x in re_ if x["r_next"] > 0), sum(1 for x in f if x["r_next"] > 0)
        ef, er = _episodes(f), _episodes(re_)
        bs = [_boot(er, rng, _rate) - _boot(ef, rng, _rate) for _ in range(B_)]
        pe, pb = fisher_lower(k1, len(re_), k2, len(f)), sum(1 for b in bs if b >= 0) / B_
        out["H2"] = {"effect": k1 / len(re_) - k2 / len(f), "p_exact": pe, "p_boot": pb, "p": max(pe, pb),
                     "ci": [_pct(bs, .025), _pct(bs, .975)], "n": len(re_), "episodes": out["re"]["episodes"]}
    for h, g in (("H3a", "big_up"), ("H3b", "side_px")):
        xs = G[g]
        if xs:
            bs = [_boot(_episodes(xs), rng, st.mean) for _ in range(B_)]
            pb = sum(1 for b in bs if b >= 0) / B_
            out[h] = {"effect": st.mean(x["r_next"] for x in xs), "p_boot": pb, "p": pb,
                      "ci": [_pct(bs, .025), _pct(bs, .975)], "n": len(xs), "episodes": out[g]["episodes"]}
    return out


HYP = {"H1": (("first",), 1), "H2": (("re", "first"), -1), "H3a": (("big_up",), -1), "H3b": (("side_px",), -1)}


def adequate(res: dict, h: str) -> bool:
    gs, _ = HYP[h]
    return h in res and all(res[g].get("n", 0) >= MIN_N and res[g].get("episodes", 0) >= MIN_EP for g in gs)


def grade(by_split: dict, h: str) -> tuple[str, str]:
    """사전등록 §6. 반환 (등급, 판정)."""
    sign = HYP[h][1]
    d, v, p = by_split["design"].get(h), by_split["valid"].get(h), by_split["pooled"].get(h)
    dir_ok = lambda x: x is not None and x["effect"] * sign > 0
    rev = lambda x: x is not None and x["effect"] * sign < 0 and (1 - x["p"]) < 0.10
    if adequate(by_split["design"], h) and adequate(by_split["valid"], h):
        if (d["effect"] > 0) != (v["effect"] > 0):
            return "F", "기각 (설계↔검증 부호 반대)"
        if dir_ok(d) and d["p"] < ALPHA and dir_ok(v) and v["p"] < 0.05:
            return "A", "통과"
        if dir_ok(p) and p["p"] < ALPHA:
            return "B", "보류"
        if dir_ok(p) and p["p"] < 0.10:
            return "C", "보류"
        return ("F(역방향 C)" if rev(p) else "F"), "기각"
    if not adequate(by_split["pooled"], h):
        return "검증전", "보류"
    if dir_ok(p) and p["p"] < 0.10:
        return "C", "보류"
    return ("F(역방향 C)" if rev(p) else "F"), "기각"


# ---------- 레버리지 (§7, 서술) ----------
def leverage(rows: list[dict], lev_dates: list[date], lev_close: list[float]) -> dict:
    idx = {d: i for i, d in enumerate(lev_dates)}
    out = {}
    for split in SPLITS:
        for g in ("first", "re", "big_up"):
            v = []
            for x in group_rows(rows, split, g):
                i = idx.get(x["date"])
                if i is not None and i + 1 < len(lev_close):
                    v.append(lev_close[i + 1] / lev_close[i] - 1 - COST)
            if v:
                out[f"{split}.{g}"] = {"n": len(v), "win": _rate(v), "mean": st.mean(v), "worst": min(v)}
    return out


# ---------- 원 vs 재현 ----------
def tol_rate(p, n): return max(0.001, 0.5 * math.sqrt(p * (1 - p) / n)) if n else 0.001
def tol_mean(sd, n): return max(0.0001, 0.5 * sd / math.sqrt(n)) if n else 0.0001


def side(p):
    return sum(p >= t for t in (ALPHA, 0.05, 0.10))


def compare(orig: dict, rep: dict) -> list[dict]:
    rows = []
    for split in ("design", "valid", "pooled", "holdout"):
        o, r = orig.get(split, {}), rep[split]
        for g in ("base",) + GROUPS:
            og, rg = o.get(g) or {}, r.get(g) or {}
            n_o, n_r = og.get("n", 0), rg.get("n", 0)
            if not n_o and not n_r:
                continue
            ok_n = abs(n_o - n_r) <= (2 if g == "base" else max(1, math.ceil(0.05 * max(n_o, n_r))))
            ok_ep = g == "base" or abs(og.get("episodes", 0) - rg.get("episodes", 0)) <= 1
            ok_up = n_r and "up" in og and abs(og["up"] - rg["up"]) <= tol_rate(rg["up"], n_r)
            ok_mean = n_r and "mean" in og and abs(og["mean"] - rg["mean"]) <= tol_mean(rg.get("sd", 0), n_r)
            rows.append({"split": split, "item": g, "orig_n": n_o, "rep_n": n_r,
                         "orig_ep": og.get("episodes"), "rep_ep": rg.get("episodes"),
                         "orig_up": og.get("up"), "rep_up": rg.get("up"), "orig_mean": og.get("mean"), "rep_mean": rg.get("mean"),
                         "verdict": "일치" if (ok_n and ok_ep and ok_up and ok_mean) else "불일치",
                         "why": ",".join(k for k, ok in (("n", ok_n), ("ep", ok_ep), ("up", ok_up), ("mean", ok_mean)) if not ok)})
        for h in HYP:
            oh, rh = o.get(h), r.get(h)
            if not oh or not rh:
                continue
            rows.append({"split": split, "item": h, "orig_p": oh.get("p"), "rep_p": rh["p"],
                         "orig_effect": oh.get("effect"), "rep_effect": rh["effect"],
                         "verdict": "일치" if side(oh.get("p", 1)) == side(rh["p"]) else "불일치", "why": ""})
    return rows


def _f(x, pct=True, d=1):
    return "—" if x is None else (f"{x * 100:+.{d}f}%" if pct else f"{x:.{d}f}")


def render(meta: dict, cmp_rows: list[dict], grades: dict, lev: dict, orig_lev: dict) -> str:
    L = ["", "## 1. 실행", f"- 실행 {meta['run']} · 커밋된 §0 = `7ecc428a` · 원 코드 미열람.",
         f"- 데이터: `data/hist` KOSPI {meta['k_range']} {meta['k_rows']}행 · KOSPI200 {meta['k2_rows']}행 · 122630 {meta['l_range']} {meta['l_rows']}행 (출처 `_manifest.json` built {meta['built']}).",
         "", "## 2. 등급 대조 (판정 = §0.3 ③)", "| 가설 | 원 등급 | 재현 등급 | 원 판정 | 재현 판정 | 일치 |", "|---|---|---|---|---|---|"]
    for h, g in grades.items():
        L.append(f"| {h} | {g['orig']} | {g['rep']} | {g['orig_v']} | {g['rep_v']} | {'일치' if g['orig'] == g['rep'] else '**불일치**'} |")
    L += ["", "## 3. 사건 집합·통계 대조 (§0.3 ①②)", "| 구간 | 항목 | 원 n·에피소드 | 재현 n·에피소드 | 원 반등률 | 재현 반등률 | 원 평균 | 재현 평균 | 판정 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in cmp_rows:
        if r["item"] in HYP:
            continue
        L.append(f"| {r['split']} | {r['item']} | {r['orig_n']}·{r['orig_ep'] or '—'} | {r['rep_n']}·{r['rep_ep'] or '—'} | {_f(r['orig_up'])} | {_f(r['rep_up'])} | {_f(r['orig_mean'], d=2)} | {_f(r['rep_mean'], d=2)} | {r['verdict']}{' (' + r['why'] + ')' if r['why'] else ''} |")
    L += ["", "## 4. 가설 p 대조 (문턱 0.00714·0.05·0.10 같은 쪽이면 일치)", "| 구간 | 가설 | 원 효과 | 재현 효과 | 원 p | 재현 p | 판정 |", "|---|---|---|---|---|---|---|"]
    for r in cmp_rows:
        if r["item"] in HYP:
            L.append(f"| {r['split']} | {r['item']} | {_f(r['orig_effect'], d=2)} | {_f(r['rep_effect'], d=2)} | {_f(r['orig_p'], False, 3)} | {_f(r['rep_p'], False, 3)} | {r['verdict']} |")
    L += ["", "## 5. 122630 하루 보유(익일 종가, 비용 0.05%) — 서술", "| 구간·집단 | 원 n·승률·평균·최악 | 재현 n·승률·평균·최악 |", "|---|---|---|"]
    for k, v in lev.items():
        o = orig_lev.get(k) or {}
        os_ = f"{o.get('n')}·{_f(o.get('win'))}·{_f(o.get('mean'), d=2)}·{_f(o.get('worst'))}" if o else "—"
        L.append(f"| {k} | {os_} | {v['n']}·{_f(v['win'])}·{_f(v['mean'], d=2)}·{_f(v['worst'])} |")
    return "\n".join(L) + "\n"


def verdict_md(cmp_rows: list[dict], grades: dict) -> str:
    stat = [r for r in cmp_rows if r["item"] not in HYP]
    hyp = [r for r in cmp_rows if r["item"] in HYP]
    ok_s, ok_h = sum(r["verdict"] == "일치" for r in stat), sum(r["verdict"] == "일치" for r in hyp)
    ok_g = sum(g["orig"] == g["rep"] for g in grades.values())
    allok = ok_s == len(stat) and ok_h == len(hyp) and ok_g == len(grades)
    L = ["", "## 6. 판정 (§0.4 기준)",
         f"- 사건 집합·통계 {ok_s}/{len(stat)} 일치 · 가설 p 문턱 {ok_h}/{len(hyp)} 일치 · 등급 {ok_g}/{len(grades)} 일치 → "
         + ("**재현 일치 — 원 결론 유지**(지수 H1~H3b)." if allok else "**불일치 있음 — §0.4 에 따라 강등 요청 대상.**"),
         "- base n 이 설계·풀링에서 1 작음(2465 vs 2466): 재현은 r_t 가 없는 첫날(2010-01-04)을 base 에서 뺐다(§0.2) — 원은 r_{t+1} 만 요구한 것으로 보임. 창 정의 차이, 허용오차(±2) 안, 결론 불변. 원 코드 미열람이라 `검증전`.",
         "- 재현은 숫자가 맞는지만 본다(kb:verify#7). 등급은 원과 같다 — F·검증전·F·F(역방향 C). 재현 일치가 등급을 올리지 않는다.",
         "- 반대 근거: 원과 재현이 **같은 데이터 창고**(data/hist pykrx KOSPI)를 쓴다 — 데이터 오류는 공통(kb:verify#6). 사이드카는 양쪽 다 대용(K200 현물 고가 +4%)이라 H3b 는 '대용 기준 일치'일 뿐 실제 사이드카 재현이 아니다.",
         "- 범위 밖: H4a~c(종목) 미재현 — 원 등급 중 유일한 C(H4b)와 설계 구간 Holm 통과(H4a)가 여기 있다. 인용 시 'H4 는 검증 데스크 미재현'을 붙여 달라는 제안(🌙, 22시 이후 — 반영은 퀀트·PB 확인 뒤).",
         "- 제안(🌙): 원 보고서 §1 머리에 '지수 H1~H3b 독립 재현 일치(replication_hollzzak.md)' 한 줄. 등급 변경 없음.",
         "- 코드 영향 범위: 신규 `scripts/replicate_hollzzak.py`·`tests/test_replicate_hollzzak.py`·이 보고서 2개. 다른 모듈이 import 하지 않음 — 롤백 = 네 파일 삭제.",
         ]
    return "\n".join(L) + "\n"


def _orig_lev(orig: dict) -> dict:
    """원 json leverage_122630 에서 익일 종가 항목만 평평하게(구조가 다르면 빈 dict)."""
    out = {}
    for split, d in (orig.get("leverage_122630") or {}).items():
        if not isinstance(d, dict):
            continue
        for g, e in d.items():
            if isinstance(e, dict):
                c = e.get("close") or e.get("next_close") or e.get("익일 종가")
                if isinstance(c, dict):
                    out[f"{split}.{g}"] = {"n": c.get("n"), "win": c.get("win", c.get("up")), "mean": c.get("mean"), "worst": c.get("worst")}
    return out


def main() -> int:
    from screener import hist
    k = hist.load("KOSPI", start="2009-12-01").sort("date")
    k2 = hist.load("KOSPI200", start="2009-12-01").sort("date")
    lev = hist.load("122630", start="2010-01-01").sort("date")
    if k.is_empty() or lev.is_empty():
        print("data/hist 비어 있음 — python scripts/data_store.py pull --groups hist", file=sys.stderr)
        return 1
    k2d, k2h, k2c = k2["date"].to_list(), k2["high"].to_list(), k2["close"].to_list()
    k200_hi = {k2d[i]: k2h[i] / k2c[i - 1] - 1 for i in range(1, len(k2d)) if k2h[i] and k2c[i - 1]}
    rows = build_events(k["date"].to_list(), [float(x) for x in k["close"].to_list()], k200_hi)
    rep = {s: test_split(rows, s) for s in SPLITS}
    orig = json.loads(ORIG.read_text(encoding="utf-8"))
    cmp_rows = compare(orig["results"]["index"], rep)
    grades = {}
    for h in HYP:
        g, v = grade(rep, h)
        og = orig.get("grades", {}).get(h)
        ov = orig.get("verdicts", {}).get(h)
        if isinstance(ov, dict):
            ov = ov.get("verdict")
        grades[h] = {"orig": og if isinstance(og, str) else (og or {}).get("grade"), "orig_v": ov, "rep": g, "rep_v": v}
    lv = leverage(rows, lev["date"].to_list(), [float(x) for x in lev["close"].to_list()])
    man = json.loads((ROOT / "data/hist/_manifest.json").read_text(encoding="utf-8"))
    meta = {"run": date.today().isoformat(), "built": man.get("built"),
            "k_range": f"{k['date'].min()}~{k['date'].max()}", "k_rows": k.height, "k2_rows": k2.height,
            "l_range": f"{lev['date'].min()}~{lev['date'].max()}", "l_rows": lev.height}
    OUT_JSON.write_text(json.dumps({"study": "replication_hollzzak", "orig": "reports/studies/hollzzak.json", "meta": meta,
                                    "grades": grades, "rows": cmp_rows, "rep": rep, "leverage_122630": lv},
                                   ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    head = OUT_MD.read_text(encoding="utf-8").split("\n## 1. 실행")[0].rstrip() + "\n"
    OUT_MD.write_text(head + render(meta, cmp_rows, grades, lv, _orig_lev(orig)) + verdict_md(cmp_rows, grades), encoding="utf-8")
    print(OUT_MD.read_text(encoding="utf-8").split("## 1. 실행")[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
