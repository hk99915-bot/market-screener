"""서울 아파트 실거래 백필(국토부 RTMS 2021-07~2023-12) + 같은 단지·면적 반복매매로 2022~23 하락폭·회복 비교.

- 목적(10/27): 시장 밈 '파란선 안'(중심 10구) vs 밖(14구)의 2022~23 하락폭·회복을 1차 원자료로 검증.
  사전등록(10/27, 데이터 보기 전): 밖 중위 하락폭 ≥ 안 중위 하락폭 × 1.5 **그리고** 밖 회복률 < 안 회복률 → '밖이 더 취약' 가설 지지,
  아니면 기각. 집단 쌍 30개 미만이면 판정 보류. 창: 고점 2021-10~2022-03 · 저점 2022-12~2023-03 · 회복 2023-10~12.
- 원자료: data/realestate/rtms_hist/<구코드>.csv (취소 제외 매매만, 금액 만원) + _manifest.json(완료 월).
  수집은 Actions(.github/workflows/re_hist.yml, 수동 실행)에서만 — 키(DATA_GO_KR_KEY)는 파라미터로만 쓰고 저장·로그 금지.
- 산출: reports/studies/re_bluezone_drawdown.json (집단별 n·중위 하락폭·회복률·판정). 표시 전용 · 매매 신호 아님.
"""
from __future__ import annotations

import csv
import json
import logging
import random
import statistics
from pathlib import Path

from .config import REPORT_DIR
from .realestate import GU_CODES, RTMS_TRADE, _num, _scrub, fetch_rtms, is_cancelled

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
HIST_DIR = ROOT / "data" / "realestate" / "rtms_hist"
OUT = REPORT_DIR / "studies" / "re_bluezone_drawdown.json"

# 시장 밈 '파란선 안'(중심지) = 강남·서초·송파·용산 + 한강벨트 마포·성동·광진·동작·강동·영등포. 구 전체 단위 근사(밈은 '영등포 일부').
INSIDE = {"강남구", "서초구", "송파구", "용산구", "마포구", "성동구", "광진구", "동작구", "강동구", "영등포구"}
EXCLUDE = {"중구"}   # 거래 표본 얇음(10/24 25구 표에서도 제외) — 밖 14구 = 25 − 10 − 중구
WIN = {"peak": ("202110", "202203"), "trough": ("202212", "202303"), "rec": ("202310", "202312")}
RULE = {"ratio": 1.5, "min_pairs": 30}
COLS = ["ym", "d", "dong", "apt", "seq", "a", "fl", "p", "by"]


def months(start: str = "202107", end: str = "202312") -> list[str]:
    y, m = int(start[:4]), int(start[4:])
    out = []
    while f"{y}{m:02d}" <= end:
        out.append(f"{y}{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def compact(items: list[dict], ym: str) -> list[dict]:
    """RTMS item → 짧은 행(취소 제외·금액 없는 행 제외). 금액 단위 만원(정수)."""
    out = []
    for x in items:
        if is_cancelled(x):
            continue
        p, a = _num(x.get("dealAmount")), _num(x.get("excluUseAr"))
        if p is None or a is None:
            continue
        try:
            d = int(x.get("dealDay") or 0)
        except ValueError:
            d = 0
        by = _num(x.get("buildYear"))
        out.append({"ym": ym, "d": d, "dong": (x.get("umdNm") or "").strip(), "apt": (x.get("aptNm") or "").strip(),
                    "seq": (x.get("aptSeq") or "").strip(), "a": round(a, 2), "fl": (x.get("floor") or "").strip(),
                    "p": int(p), "by": int(by) if by else ""})
    return out


def _manifest(d: Path) -> dict:
    try:
        return json.loads((d / "_manifest.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"done": {}}


def load_rows(cd: str, d: Path | None = None) -> list[dict]:
    f = (d or HIST_DIR) / f"{cd}.csv"
    if not f.exists():
        return []
    with f.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def backfill(get, key: str, mlist: list[str], out_dir: Path | None = None, max_calls: int = 900, sleep=None) -> dict:
    """구 × 월 수집(이어받기: manifest 의 완료 월은 건너뜀). 호출 상한 max_calls 에서 멈춤. 반환 = 요약(키 없음)."""
    out_dir = out_dir or HIST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    man = _manifest(out_dir)
    calls, failed = 0, []
    for gu, cd in GU_CODES.items():
        done = set(man["done"].get(cd, []))
        todo = [m for m in mlist if m not in done]
        if not todo:
            continue
        rows = [r for r in load_rows(cd, out_dir) if r["ym"] not in todo]
        for ym in todo:
            if calls >= max_calls:
                break
            try:
                items = fetch_rtms(get, RTMS_TRADE, cd, ym, key)
                calls += 1 + len(items) // 1000
                rows += compact(items, ym)
                done.add(ym)
            except Exception as e:  # noqa: BLE001
                calls += 1
                failed.append({"gu": gu, "ym": ym, "why": _scrub(f"{type(e).__name__}: {e}", key)})
            if sleep:
                sleep(0.15)
        rows.sort(key=lambda r: (r["ym"], int(r["d"] or 0), r["dong"], r["apt"], float(r["a"])))
        with (out_dir / f"{cd}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            w.writeheader()
            w.writerows(rows)
        man["done"][cd] = sorted(done)
        if calls >= max_calls:
            break
    n_done = sum(len(v) for v in man["done"].values())
    man.update(src="국토교통부 아파트 매매(상세) 실거래가 — 공공데이터포털 RTMSDataSvcAptTradeDev (1차, 신고 기준·해제 거래 제외)",
               unit="p = 만원 · a = 전용㎡ · d = 계약일 · seq = 단지 일련번호(aptSeq)", target=f"{mlist[0]}~{mlist[-1]}",
               n_gu_month_done=n_done, n_gu_month_target=len(mlist) * len(GU_CODES))
    (out_dir / "_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("RTMS 백필: 호출 %d · 완료 구×월 %d/%d · 실패 %d", calls, n_done, man["n_gu_month_target"], len(failed))
    return {"calls": calls, "done": n_done, "target": man["n_gu_month_target"], "failed": failed}


def _in(ym: str, w: tuple[str, str]) -> bool:
    return w[0] <= ym <= w[1]


def pairs(rows_by_gu: dict[str, list[dict]], min_floor: int | None = None) -> list[dict]:
    """같은 단지(aptSeq, 없으면 동+이름)·같은 면적(전용 정수)에서 고점·저점 창 거래가 모두 있는 쌍 → 하락폭·회복률."""
    out = []
    for gu, rows in rows_by_gu.items():
        grp: dict[tuple, dict[str, list[float]]] = {}
        for r in rows:
            if min_floor is not None:
                fl = _num(r.get("fl"))
                if fl is None or fl < min_floor:
                    continue
            k = (r.get("seq") or f"{r['dong']}|{r['apt']}", int(round(float(r["a"]))))
            for nm, w in WIN.items():
                if _in(r["ym"], w):
                    grp.setdefault(k, {}).setdefault(nm, []).append(float(r["p"]))
        for k, g in grp.items():
            if "peak" not in g or "trough" not in g:
                continue
            pk, tr = statistics.median(g["peak"]), statistics.median(g["trough"])
            rec = statistics.median(g["rec"]) if "rec" in g else None
            drop = tr / pk - 1
            recov = (rec - tr) / (pk - tr) if rec is not None and pk > tr else None
            out.append({"gu": gu, "inside": gu in INSIDE, "key": k[0], "a": k[1], "peak": pk, "trough": tr, "rec": rec,
                        "drop": drop, "recov": recov, "rec_lvl": (rec / pk - 1) if rec is not None else None,
                        "n": sum(len(v) for v in g.values())})
    return out


def _boot_ratio(a: list[float], b: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float] | None:
    """중위 하락폭 비(밖 ÷ 안) 부트스트랩 95% 구간."""
    if len(a) < 5 or len(b) < 5:
        return None
    rnd = random.Random(seed)
    rs = []
    for _ in range(n):
        ma = statistics.median(rnd.choices(a, k=len(a)))
        mb = statistics.median(rnd.choices(b, k=len(b)))
        if mb < 0:
            rs.append(ma / mb)
    rs.sort()
    return (round(rs[int(len(rs) * 0.025)], 2), round(rs[int(len(rs) * 0.975) - 1], 2)) if rs else None


def group_stats(ps: list[dict]) -> dict:
    md = lambda v: round(statistics.median(v), 4) if v else None  # noqa: E731
    dr = [p["drop"] for p in ps]
    rc = [p["recov"] for p in ps if p["recov"] is not None]
    rl = [p["rec_lvl"] for p in ps if p["rec_lvl"] is not None]
    return {"n_pairs": len(ps), "n_trades": sum(p["n"] for p in ps), "drop_med": md(dr),
            "drop_mean": round(statistics.fmean(dr), 4) if dr else None,
            "share_down20": round(sum(1 for x in dr if x <= -0.2) / len(dr), 3) if dr else None,
            "n_recov": len(rc), "recov_med": md(rc), "rec_lvl_med": md(rl)}


def judge(ins: dict, out: dict, rule: dict = RULE) -> dict:
    """사전등록 판정. 하락폭은 음수 — '밖 ≥ 안×1.5' = 밖 중위 ≤ 안 중위 × 1.5."""
    if min(ins["n_pairs"], out["n_pairs"]) < rule["min_pairs"] or ins["drop_med"] is None or out["drop_med"] is None:
        return {"verdict": "보류", "why": f"쌍 {rule['min_pairs']}개 미만"}
    ratio = out["drop_med"] / ins["drop_med"] if ins["drop_med"] < 0 else None
    deeper = ratio is not None and ratio >= rule["ratio"]
    slower = (out["recov_med"] is not None and ins["recov_med"] is not None and out["recov_med"] < ins["recov_med"])
    return {"ratio_out_in": round(ratio, 2) if ratio is not None else None, "deeper": deeper, "slower_recovery": slower,
            "verdict": "지지" if deeper and slower else "기각",
            "why": f"하락폭 비 {ratio:.2f}(기준 ≥{rule['ratio']}) · 회복 밖 {out['recov_med']} vs 안 {ins['recov_med']}" if ratio is not None
            else "안 중위 하락 없음"}


def analyze(rows_by_gu: dict[str, list[dict]]) -> dict:
    rows_by_gu = {g: r for g, r in rows_by_gu.items() if g not in EXCLUDE}
    res = {}
    for label, mf in (("all_floors", None), ("floor3plus", 3)):
        ps = pairs(rows_by_gu, mf)
        ins, outs = [p for p in ps if p["inside"]], [p for p in ps if not p["inside"]]
        si, so = group_stats(ins), group_stats(outs)
        res[label] = {"inside": si, "outside": so, "judge": judge(si, so),
                      "ratio_ci95": _boot_ratio([p["drop"] for p in outs], [p["drop"] for p in ins])}
        if label == "all_floors":
            # 보조(사전등록): 안 '하단'(고점가 안 집단 하위 25%) vs 밖 '중위'(밖 집단 고점가 40~60%)
            def band(xs, lo, hi):
                if not xs:
                    return []
                v = sorted(p["peak"] for p in xs)
                a, b = v[int(len(v) * lo)], v[min(len(v) - 1, int(len(v) * hi))]
                return [p for p in xs if a <= p["peak"] <= b]
            res["low_in_vs_mid_out"] = {"inside_low25": group_stats(band(ins, 0.0, 0.25)), "outside_mid40_60": group_stats(band(outs, 0.4, 0.6))}
            res["by_gu"] = {g: group_stats([p for p in ps if p["gu"] == g]) for g in sorted({p["gu"] for p in ps})}
    return res


def run_analysis(d: Path | None = None) -> dict:
    d = d or HIST_DIR
    man = _manifest(d)
    rows = {gu: load_rows(cd, d) for gu, cd in GU_CODES.items()}
    res = analyze(rows)
    return {"schema": 1, "asof": man.get("target"), "coverage": f"{man.get('n_gu_month_done', 0)}/{man.get('n_gu_month_target', 0)} 구×월",
            "prereg": {"date": "2026-10-27", "windows": WIN, "rule": f"밖 중위 하락폭 ≥ 안 × {RULE['ratio']} 그리고 밖 회복률 < 안 → 지지, 아니면 기각 · 쌍 {RULE['min_pairs']}개 미만 보류",
                       "inside": sorted(INSIDE), "excluded": sorted(EXCLUDE),
                       "pair": "같은 단지(aptSeq)·전용 정수㎡ · 창별 중위가 · 하락폭 = 저점 ÷ 고점 − 1 · 회복률 = (회복 − 저점) ÷ (고점 − 저점)"},
            "result": res, "src": man.get("src"), "grade": "자체연구-검증전(1차 원자료 집계 · 구 단위 근사 · 층·향 미통제)",
            "label": "표시 전용 · 매매 신호 아님"}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import time
    from .realestate import _fetch_bytes
    ap = argparse.ArgumentParser(description="RTMS 서울 백필 + 2022~23 반복매매 하락폭 비교")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--start", default="202107")
    ap.add_argument("--end", default="202312")
    ap.add_argument("--max-calls", type=int, default=900)
    ap.add_argument("--analyze", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if a.fetch:
        key = os.environ.get("DATA_GO_KR_KEY")
        if not key:
            log.error("DATA_GO_KR_KEY 없음 — 수집 불가(Actions 에서만)")
            return 2
        s = backfill(_fetch_bytes, key, months(a.start, a.end), max_calls=a.max_calls, sleep=time.sleep)
        log.info("요약 %s", json.dumps({k: v for k, v in s.items() if k != "failed"}, ensure_ascii=False))
        for f in s["failed"][:20]:
            log.warning("실패 %s %s %s", f["gu"], f["ym"], f["why"])
    if a.analyze:
        doc = run_analysis()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        r = doc["result"].get("all_floors", {})
        log.info("판정 %s", json.dumps(r.get("judge"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
