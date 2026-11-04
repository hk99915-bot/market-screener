#!/usr/bin/env python3
"""git 이 추적하는 parquet 전수 표 (보드 data-parquet-out 1조각, 겸이 11/4 18:28 결재).

목적: 11/6 새 저장소 스냅샷에서 parquet 을 빼기 전에 '무엇을 누가 쓰고 누가 읽는지'를 한 곳에 고정한다.
이 표에 없는 추적 parquet 이 생기면 tests/test_parquet_inventory.py 가 실패한다(조용히 늘어나는 것 방지).
이 스크립트는 읽기 전용 — 파일 이동·릴리스 업로드는 하지 않는다(릴리스 쓰기는 Actions 로만, dev.md).

  python3 scripts/parquet_inventory.py          # 표 + git 추적 파일과 대조
"""
from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# pattern: 추적 중 parquet / kind: 불변(연도 마감)·누적(매일 덮어씀) / writer: 쓰는 주체 / readers: 읽는 곳 / pull: 읽는 워크플로가 data_store pull 로 받나
INVENTORY = [
    {"pattern": "data/hist/kr_20[0-9][0-9].parquet", "kind": "불변(연도)", "writer": "scripts/build_hist.py(과거 1회 백필)",
     "readers": "screener/prices.load_kr(hist_from)←analysts·lab(lab.yml) · scripts/study_*", "pull": "아니오(git checkout 에 의존)"},
    {"pattern": "data/hist/us_20[0-9][0-9].parquet", "kind": "불변(연도)", "writer": "scripts/build_hist.py(과거 1회 백필)",
     "readers": "scripts/build_hist.py(업종 합성)·scripts/study_*", "pull": "아니오(git checkout 에 의존)"},
    {"pattern": "data/research.parquet", "kind": "누적(매일)", "writer": "screener/research.py ← fin.yml·screener.yml·briefing.yml 커밋",
     "readers": "screener/dashboard·research_synthesis(fin.yml)·scripts/study_alpha_sources", "pull": "아니오(커밋 대상 목록에 있음)"},
    {"pattern": "data/research_views.parquet", "kind": "누적(매일)", "writer": "screener/research_views.py ← fin.yml·briefing.yml 커밋",
     "readers": "screener/research_synthesis(fin.yml)", "pull": "아니오(커밋 대상 목록에 있음)"},
    {"pattern": "data/short_hist.parquet", "kind": "누적(매일)", "writer": "공매도 수집 ← screener.yml·briefing.yml 커밋",
     "readers": "scripts/study_hollzzak 외", "pull": "아니오(커밋 대상 목록에 있음)"},
    {"pattern": "data/dart.parquet", "kind": "누적(매일)", "writer": "screener/dart.py ← screener.yml·briefing.yml 커밋",
     "readers": "screener/entry_why·prices(분할 대조)·scripts/hf_ideas", "pull": "아니오(커밋 대상 목록에 있음)"},
    {"pattern": "data/fin/us_quarterly.parquet", "kind": "누적(분기)", "writer": "screener/sec.py(SEC XBRL) ← fin.yml",
     "readers": "scripts/build_company_links·study_*", "pull": "아니오(fin.yml 은 pull 하나 GROUPS 'fin' 에 이 파일 없음)"},
    {"pattern": "reports/us_eps_hist.parquet", "kind": "누적(매일)", "writer": "screener/us_eps_hist.py(drivers 에서 호출) ← reports 통째 커밋",
     "readers": "screener/us_eps_hist 자체(upsert)", "pull": "아니오(reports/ 에 있음)"},
]


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.parquet"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [x for x in out.splitlines() if x]


def classify(files: list[str] | None = None) -> tuple[dict[str, list[str]], list[str]]:
    """({pattern: [파일]}, 표에 없는 파일)."""
    files = tracked() if files is None else files
    by = {r["pattern"]: [] for r in INVENTORY}
    unknown = []
    for f in files:
        hit = [r["pattern"] for r in INVENTORY if fnmatch.fnmatch(f, r["pattern"])]
        (by[hit[0]].append(f) if hit else unknown.append(f))
    return by, unknown


def main() -> int:
    by, unknown = classify()
    tot = 0
    for r in INVENTORY:
        fs = by[r["pattern"]]
        sz = sum((ROOT / f).stat().st_size for f in fs if (ROOT / f).exists())
        tot += sz
        print(f"{r['pattern']:38} {len(fs):3}개 {sz / 1e6:7.1f}MB  {r['kind']} · 읽기 pull: {r['pull']}")
    print(f"합계 {tot / 1e6:.1f}MB · 표에 없는 추적 parquet {len(unknown)}개 {unknown}")
    return 1 if unknown else 0


if __name__ == "__main__":
    sys.exit(main())
