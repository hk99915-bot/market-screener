#!/usr/bin/env python3
"""시도 일지 집계 (퀀트 데스크, kb:quant#13) — 연구별 m(등록 가설 수)과 등록 전 탐색 횟수를 모아 N(전체 시도)을 센다.

Harvey & Liu(2015)는 연구 안의 m 이 아니라 **시도 횟수 N 전체**로 헤어컷을 정한다. 우리 보고서 §0 의 Bonferroni 는
연구 하나의 m 만 나누므로, 같은 질문을 여러 연구에서 다시 검정했으면 실제 보정은 더 커야 한다. 이 스크립트는
그 차이를 숫자로 보이게만 한다 — 등급을 바꾸지 않는다.

  python3 scripts/trial_log.py            # 표 출력
  python3 scripts/trial_log.py --build    # reports/studies/trial_log.md 재생성
  python3 scripts/trial_log.py --check    # md 가 json 과 동기화돼 있는지 (CI)

입력  reports/studies/*.json (각 연구가 쓰는 m 필드명이 달라서 아래 extract_m 이 모두 받는다)
      reports/studies/trial_log.json (주제 태그·등록 전 탐색 횟수·버린 이유 — 사람이 적음)
출력  reports/studies/trial_log.md

영향 범위  문서 전용 — 워크플로·탭·알림·등급 계산은 이 파일을 import 하지 않는다 (grep trial_log 로 확인, 2026-10-17).
롤백      git revert <도입 커밋> (파일 6개: trial_log.{py,json,md} · tests/test_trial_log.py · KB·라운드) — 다른 코드 의존 없음.
테스트    tests/test_trial_log.py 3건 (스키마 4종 추출 · 임시 디렉터리 집계 · 저장소 구조).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIES = ROOT / "reports" / "studies"
LOG_JSON = STUDIES / "trial_log.json"
OUT_MD = STUDIES / "trial_log.md"
ALPHA = 0.05


def extract_m(d: dict) -> tuple[int | None, str]:
    """연구 json 한 개에서 (등록 가설 수 m, 어디서 읽었나). 못 찾으면 (None, '미등록')."""
    if isinstance(d.get("m"), int):
        return d["m"], "m"
    pr = d.get("prereg")
    if isinstance(pr, dict) and isinstance(pr.get("m"), int):
        return pr["m"], "prereg.m"
    p = d.get("params")
    if isinstance(p, dict):
        if isinstance(p.get("m"), int):
            return p["m"], "params.m"
        fam = sorted(k for k, v in p.items() if k.startswith("m") and k[1:].isdigit() and isinstance(v, int))
        if fam:
            return sum(p[k] for k in fam), "params." + "+".join(fam)
    return None, "미등록"


def _grade_counts(d: dict) -> dict[str, int]:
    """등급 분포(있으면). 연구마다 자리가 달라 몇 군데만 본다."""
    out: dict[str, int] = {}

    def add(g):
        if isinstance(g, str) and g:
            out[g] = out.get(g, 0) + 1

    g = d.get("grades")
    if isinstance(g, dict):
        for v in g.values():
            # 재현 보고서(replication_*.json)는 {orig, rep, …} 꼴 — 재현 등급(rep)을 센다 (10/21 hollzzak 재현에서 KeyError)
            add((v.get("grade") or v.get("rep")) if isinstance(v, dict) else v)
    for key in ("signals", "hypotheses"):
        if isinstance(d.get(key), list):
            for h in d[key]:
                if isinstance(h, dict):
                    add(h.get("grade"))
    if isinstance(d.get("lens_grade"), str):
        add(d["lens_grade"])
    return out


def build(studies_dir: Path = STUDIES, log_json: Path = LOG_JSON) -> dict:
    log = json.loads(log_json.read_text(encoding="utf-8"))
    manual = log.get("studies", {})
    rows = []
    for f in sorted(studies_dir.glob("*.json")):
        if f.name == log_json.name:
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        m, src = extract_m(d)
        man = manual.get(f.stem, {})
        unreg = int(man.get("unregistered_trials", 0) or 0)
        rows.append({
            "study": f.stem,
            "date": str(d.get("generated") or d.get("asof") or d.get("registered") or "")[:10],
            "topic": man.get("topic", "(미분류)"),
            "m": m, "m_source": src,
            "alpha_bonf": round(ALPHA / m, 5) if m else None,
            "unregistered": unreg,
            "trials": (m or 0) + unreg,
            "grades": _grade_counts(d),
            "discarded": man.get("discarded", ""),
        })
    topics: dict[str, dict] = {}
    for r in rows:
        t = topics.setdefault(r["topic"], {"studies": [], "N": 0, "m_sum": 0, "unregistered": 0})
        t["studies"].append(r["study"])
        t["N"] += r["trials"]
        t["m_sum"] += r["m"] or 0
        t["unregistered"] += r["unregistered"]
    for t in topics.values():
        t["alpha_N"] = round(ALPHA / t["N"], 5) if t["N"] else None
    total = sum(r["trials"] for r in rows)
    missing = sorted(set(manual) - {r["study"] for r in rows})
    return {"rows": rows, "topics": topics, "N_total": total,
            "alpha_total": round(ALPHA / total, 5) if total else None,
            "trials": log.get("trials", []), "manual_without_file": missing}


def _fmt_grades(g: dict) -> str:
    return " ".join(f"{k}{v}" for k, v in sorted(g.items())) if g else "—"


def render_md(b: dict) -> str:
    L = ["# 시도 일지 (trial log)", "",
         "> `scripts/trial_log.py --build` 산출물 — 손으로 고치지 않는다. 사람이 적는 칸은 `trial_log.json`.",
         "> 출처: `reports/studies/*.json` (날짜 열 = 파일의 generated/asof/registered, 기준일 = 그 날짜) · 단위: 건(가설·조합 수) · α = 0.05/N (식: α(N)=0.05÷N, 소수 5자리).",
         "> 뜻: 각 연구의 Bonferroni 는 **그 연구 안의 m** 만 나눈다. 같은 질문을 여러 연구에서 다시 보면 시도 N 은 늘어나는데 p 는 그걸 모른다(Harvey & Liu 2015, kb:quant#13). 아래 'α(N)' 은 주제 전체 N 으로 나눴을 때의 문턱 — **등급은 바꾸지 않고** 얼마나 낙관적인지 보이는 용도.", "",
         f"## 0. 합계 — 시도 N = **{b['N_total']}** (등록 m 합 {sum(r['m'] or 0 for r in b['rows'])} + 등록 전 탐색 {sum(r['unregistered'] for r in b['rows'])}) → 전부 한 가족으로 보면 α = {b['alpha_total']}", "",
         "## 1. 연구별", "",
         "| 연구 | 날짜 | 주제 | m | 읽은 자리 | α(m) | 등록 전 탐색 | 등급 분포 | 버린 이유 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in b["rows"]:
        L.append(f"| {r['study']} | {r['date']} | {r['topic']} | {r['m'] if r['m'] is not None else '—'} | {r['m_source']} | "
                 f"{r['alpha_bonf'] if r['alpha_bonf'] else '—'} | {r['unregistered'] or '—'} | {_fmt_grades(r['grades'])} | {r['discarded'] or '—'} |")
    L += ["", "## 2. 주제별 N (같은 질문의 반복 검정)", "",
          "| 주제 | 연구 | 등록 m 합 | 등록 전 탐색 | N | α(N) |", "|---|---|---|---|---|---|"]
    for t, v in sorted(b["topics"].items(), key=lambda kv: -kv[1]["N"]):
        L.append(f"| {t} | {', '.join(v['studies'])} | {v['m_sum']} | {v['unregistered']} | {v['N']} | {v['alpha_N']} |")
    L += ["", "## 3. 시도 기록 (날짜 · 가설 · 파라미터 · 결과 · 버린 이유)", "",
          "| 날짜 | 주제 | 가설 | 파라미터 | 결과 | 버린 이유 | 연구 |", "|---|---|---|---|---|---|---|"]
    for t in b["trials"]:
        L.append(f"| {t.get('date','')} | {t.get('topic','')} | {t.get('hypothesis','')} | {t.get('params','')} | {t.get('result','')} | {t.get('discarded_why','')} | {t.get('study','')} |")
    if b["manual_without_file"]:
        L += ["", f"> ⚠ trial_log.json 에는 있으나 연구 파일이 없는 항목: {', '.join(b['manual_without_file'])}"]
    L += ["", "읽는 법: 주제 N 이 연구 m 의 2배를 넘으면(crash_entry 처럼) 그 주제의 C 등급은 '방향'이 아니라 '우연일 수 있는 방향'으로 읽는다. 새 연구 §0 에 그 주제의 현재 N 을 한 줄 적는다.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    md = render_md(build())
    if a.build:
        OUT_MD.write_text(md, encoding="utf-8")
        print(f"wrote {OUT_MD.relative_to(ROOT)}")
        return 0
    if a.check:
        cur = OUT_MD.read_text(encoding="utf-8") if OUT_MD.exists() else ""
        if cur != md:
            print("trial_log.md 가 json 과 다르다 → python3 scripts/trial_log.py --build", file=sys.stderr)
            return 1
        print("trial_log.md ok")
        return 0
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
