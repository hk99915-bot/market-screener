#!/usr/bin/env python3
"""백테스트(연구 json) 표준 출력 검사 — 퀀트 스킬 시범(2026-10-28). 얇은 래퍼: m 추출·주제 N 은 scripts/trial_log.py 를 그대로 쓴다.

  python3 .claude/skills/quant-desk/scripts/check_backtest.py reports/studies/<연구>.json [...]
  python3 .claude/skills/quant-desk/scripts/check_backtest.py --all      # reports/studies/*.json 전부(요약만)

실패(종료코드 1): prereg(dict) 없음 · m 미등록(trial_log.extract_m 기준) · 등급 없음(trial_log._grade_counts 자리) · 등급 값이 A/B/C/F/검증전 으로 시작 안 함
               · prereg 의 α 가 0.05/m 과 다름(±2%).
경고(통과는 함): IS/OOS 분할점(is_end·oos·split) 없음 · 비용 가정(cost) 없음 · 생존편향 표기 없음 · DSR/PBO 없음(kb:quant KR2, 11/1~)
               · trial_log.json 주제 태그 없음.
출력 끝에 주제 N 과 α(N)=0.05/N 을 붙인다(kb:quant#13·#30). 등급은 바꾸지 않는다 — 검사만.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
import trial_log  # noqa: E402

GRADE_RE = re.compile(r"^(A|B|C|F|검증전)")


def _walk_keys(d, out=None):
    out = set() if out is None else out
    if isinstance(d, dict):
        for k, v in d.items():
            out.add(str(k).lower())
            _walk_keys(v, out)
    elif isinstance(d, list):
        for v in d:
            _walk_keys(v, out)
    return out


def check(d: dict, name: str, topics: dict, manual: dict) -> tuple[list[str], list[str], list[str]]:
    fail, warn, info = [], [], []
    pr = d.get("prereg")
    if not isinstance(pr, dict):
        pr = None
        fail.append("prereg 없음/dict 아님 (사전등록 kb:quant#1)")
    m, src = trial_log.extract_m(d)
    if not m:
        fail.append(f"m 미등록 또는 0 ({src})")
    else:
        info.append(f"m={m} ({src}) · Bonferroni α=0.05/{m}={0.05 / m:.5f}")
        a = (pr or {}).get("alpha_bonf", (pr or {}).get("alpha"))
        if a == 0.05:   # 보정 전 기본 α 를 적은 연구 — 비교 대상 아님
            a = None
        if isinstance(a, (int, float)) and abs(a - 0.05 / m) > 0.02 * (0.05 / m):
            fail.append(f"prereg α {a} ≠ 0.05/m {0.05 / m:.5f}")
    gc = trial_log._grade_counts(d)   # grades{} · signals[] · hypotheses[] · lens_grade — trial_log 과 같은 자리
    if not gc:
        fail.append("등급 없음 (grades·signals·hypotheses·lens_grade) — STANDARD §2 등급 없는 자체연구 인용 금지")
    else:
        bad = [k for k in gc if not GRADE_RE.match(k.strip())]
        if bad:
            fail.append("등급 값 형식 밖: " + ", ".join(bad[:5]))
        info.append("등급 분포 " + " ".join(f"{k}×{v}" for k, v in gc.items()))
    keys = _walk_keys(d)
    if not any(k in keys for k in ("is_end", "oos", "oos_start", "split", "is", "is_oos")):
        warn.append("IS/OOS 분할점 필드 없음 (kb:quant#2·#15)")
    if not any("cost" in k for k in keys):
        warn.append("비용 가정 필드 없음 (10년차 기준 ③)")
    if not any("surviv" in k for k in keys):
        warn.append("생존편향 표기 없음 (KR2)")
    if not any(k in keys for k in ("dsr", "deflated_sharpe", "pbo")):
        warn.append("DSR/PBO 없음 (KR2 — 11/1 이후 평가 필수)")
    t = manual.get(name, {}).get("topic")
    if not t:
        warn.append("trial_log.json 주제 태그 없음 → 주제 N 미집계")
    else:
        T = topics.get(t, {})
        info.append(f"주제 {t}: N={T.get('N')} · α(N)={T.get('alpha_N')}")
    return fail, warn, info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    files = [Path(f) for f in a.files]
    if a.all:
        files = [f for f in sorted(trial_log.STUDIES.glob("*.json")) if f.name != trial_log.LOG_JSON.name]
    if not files:
        ap.error("연구 json 경로 또는 --all")
    b = trial_log.build()
    manual = json.loads(trial_log.LOG_JSON.read_text(encoding="utf-8")).get("studies", {})
    nfail = 0
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            print(f"[건너뜀] {f.name}: dict 아님")
            continue
        fail, warn, info = check(d, f.stem, b["topics"], manual)
        nfail += bool(fail)
        print(f"[{'실패' if fail else '통과'}] {f.name}  실패 {len(fail)} · 경고 {len(warn)}")
        if not a.all:
            for x in fail:
                print("  ✗", x)
            for x in warn:
                print("  △", x)
            for x in info:
                print("  ·", x)
    print(f"전체 N={b['N_total']} · α(N)={b['alpha_total']} (reports/studies/trial_log.md)")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
