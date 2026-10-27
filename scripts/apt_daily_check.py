"""오늘의 인적성(reports/english/<D>.json 의 aptitude 3문항) 생성 규칙·검사 (req-edu-11644241 ①, 평가 교차 검수 10/23 §5).

문제(평가 실측, 10/21~10/23 21문항 기준): 정답 위치 ③ 11/21(52%)·⑤ 0/21, '숫자 오름차순 + 정답 가운데' 단서,
함정 계산값이 정답 보기와 같은 값으로 합쳐져 오해를 진단 못 하는 문항(E2026-10-21-0 ×(1−r) 7,690.6 ≈ 정답 7,690.7,
E2026-10-21-1 분모를 바꿔도 같은 1.2%).

생성 규칙 v1 (2026-10-28 출제분부터 — RULE_FROM):
  R1 숫자 보기는 값 오름차순(부호 포함)으로 놓는다 (Haladyna 2002 '논리·숫자 순서', kb:edu#5).
  R2 정답 위치는 `--plan D` 가 주는 3자리를 쓴다 — 5평일 블록(15문항)마다 ①~⑤ 각 3회, 블록 안 순서는 날짜 시드 셔플.
     오름차순을 지키면서 정답을 그 자리에 두려면 오답을 정답의 위/아래로 나눠 만든다
     (예: ⑤ → 오답 4개 모두 정답보다 작게, ① → 모두 크게). 그래서 '가운데 = 정답' 단서가 사라진다.
  R3 함정 보기를 `traps: [{"name": "분모 바꿔치기", "value": "<보기 문자열 그대로>"}]` 로 적는다(1~3개).
     각 함정 값은 보기 중 하나여야 하고 정답 보기와 같은 문자열이면 안 된다.
     계산한 함정 값이 표시 자릿수에서 정답과 같아지면(예 7,690.6 vs 7,690.7) 입력(등락률 2% 이상)을 바꾸거나 다른 함정을 쓴다.
  R4 보기 5개는 서로 다른 값.
  R5 최근 21문항(규칙 시행분, 10문항 이상부터) 정답 위치 각 10~30% — 35% 초과 또는 15문항 이상에서 0회면 실패.

  python3 scripts/apt_daily_check.py --plan 2026-10-28      # 그날 3문항 정답 자리(0~4)
  python3 scripts/apt_daily_check.py                         # reports/english 전체: 기준선(시행 전)·규칙 검사(시행 후)
  python3 scripts/apt_daily_check.py --file reports/english/2026-10-28.json   # 한 파일 (출제 세션이 커밋 전에)
종료 코드: 시행분 위반이 있으면 1. 시행 전 파일은 기준선만 출력(실패로 치지 않음).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENG = ROOT / "reports" / "english"
RULE_FROM = date(2026, 10, 28)
N_CH = 5
PER_DAY = 3
BLOCK_DAYS = 5
POS_MAX_SHARE = 0.35
WINDOW = 21
NUM = re.compile(r"[+\-]?\d[\d,]*(?:\.\d+)?")


def val(s) -> float | None:
    """보기 문자열의 첫 숫자(부호 포함). '약 12.3만 원' → 12.3, '−4.48%' → −4.48, 문장 보기 → None."""
    t = str(s).replace("−", "-").replace("–", "-")
    m = NUM.search(t)
    if not m:
        return None
    if re.search(r"[가-힣A-Za-z]{3,}", t[: m.start()]):  # 문장 앞부분에 숫자가 섞인 서술형 보기
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def numeric(choices: list) -> bool:
    return len(choices) == N_CH and all(val(c) is not None for c in choices)


def _bday_index(d: date) -> int:
    """RULE_FROM 부터 d 까지 평일 수(0부터). 주말이면 다음 평일 기준."""
    k, x = 0, RULE_FROM
    while x < d:
        x += timedelta(days=1)
        if x.weekday() < 5 and x <= d:
            k += 1
    return k


def plan(d: date) -> list[int]:
    """그날 3문항의 정답 자리(0~4). 5평일 블록 15자리 = 각 자리 3회, 블록 시드 셔플(결정적)."""
    k = _bday_index(d)
    blk, off = divmod(k, BLOCK_DAYS)
    slots = [p for p in range(N_CH) for _ in range(BLOCK_DAYS * PER_DAY // N_CH)]
    seed = int(hashlib.sha1(f"apt-{RULE_FROM}-{blk}".encode()).hexdigest()[:8], 16)
    random.Random(seed).shuffle(slots)
    return slots[off * PER_DAY:(off + 1) * PER_DAY]


def check_item(it: dict, where: str, want: int | None) -> list[str]:
    errs: list[str] = []
    ch = it.get("choices") or []
    a = it.get("a")
    if len(ch) != N_CH or not isinstance(a, int) or not 0 <= a < N_CH:
        return [f"{where}: 보기 5개·정답 번호 0~4 필요"]
    if len({str(c).strip() for c in ch}) != N_CH:
        errs.append(f"{where}: 같은 보기 중복 (R4)")
    if numeric(ch):
        vs = [val(c) for c in ch]
        if vs != sorted(vs):
            errs.append(f"{where}: 숫자 보기 오름차순 아님 {ch} (R1)")
        if len(set(vs)) != N_CH:
            errs.append(f"{where}: 숫자 값 중복 (R4)")
    if want is not None and a != want:
        errs.append(f"{where}: 정답 자리 {a + 1}번 ≠ 계획 {want + 1}번 (R2 --plan)")
    traps = it.get("traps")
    if not isinstance(traps, list) or not traps:
        errs.append(f"{where}: traps 없음 — 함정 이름·값 1~3개 (R3)")
    else:
        for t in traps:
            v = str((t or {}).get("value", "")).strip()
            if v == str(ch[a]).strip():
                errs.append(f"{where}: 함정 '{(t or {}).get('name')}' 값이 정답 보기와 같다 — 진단 불가 (R3, E21-0 사례)")
            elif v not in [str(c).strip() for c in ch]:
                errs.append(f"{where}: 함정 '{(t or {}).get('name')}' 값 {v!r} 이 보기에 없다 (R3)")
    return errs


def baseline(files: list[Path]) -> dict:
    """시행 전 기준선: 정답 위치 분포·숫자 보기 중 '오름차순 + 정답 가운데 3자리(②③④)' 비율."""
    pos: Counter = Counter()
    sorted_n = mid = n = 0
    for p in files:
        for it in (json.loads(p.read_text(encoding="utf-8")).get("aptitude") or []):
            if not isinstance(it.get("a"), int):
                continue
            n += 1
            pos[it["a"]] += 1
            ch = it.get("choices") or []
            if numeric(ch) and [val(c) for c in ch] == sorted(val(c) for c in ch):
                sorted_n += 1
                mid += it["a"] in (1, 2, 3)
    return {"n": n, "pos": [pos[i] for i in range(N_CH)], "sorted": sorted_n, "sorted_mid": mid}


def check_files(files: list[Path]) -> list[str]:
    errs: list[str] = []
    seq: list[int] = []
    for p in files:
        d = date.fromisoformat(p.stem)
        want = plan(d)
        items = json.loads(p.read_text(encoding="utf-8")).get("aptitude") or []
        if len(items) != PER_DAY:
            errs.append(f"{p.name}: aptitude {len(items)}문항 (3 필요)")
        for i, it in enumerate(items):
            errs += check_item(it, f"E{p.stem}-{i}", want[i] if i < len(want) else None)
            if isinstance(it.get("a"), int):
                seq.append(it["a"])
    w = seq[-WINDOW:]
    if len(w) >= 10:  # 10문항 미만은 분포를 말할 수 없다
        c = Counter(w)
        top = max(c.values())
        if top / len(w) > POS_MAX_SHARE:
            errs.append(f"최근 {len(w)}문항 정답 위치 쏠림 {top}/{len(w)} > {POS_MAX_SHARE:.0%} (R5)")
        if len(w) >= 15 and any(c[i] == 0 for i in range(N_CH)):
            errs.append(f"최근 {len(w)}문항에 한 번도 안 쓴 정답 자리 {[i + 1 for i in range(N_CH) if c[i] == 0]} (R5)")
    return errs


def _dated(paths) -> list[Path]:
    out = []
    for p in paths:
        try:
            date.fromisoformat(p.stem)
            out.append(p)
        except ValueError:
            continue
    return sorted(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", help="YYYY-MM-DD — 그날 정답 자리 출력")
    ap.add_argument("--file", help="한 파일만 검사(시행 전 날짜여도 규칙 적용)")
    ap.add_argument("--dir", default=str(ENG))
    a = ap.parse_args(argv)
    if a.plan:
        ps = plan(date.fromisoformat(a.plan))
        print(json.dumps({"date": a.plan, "answer_index": ps, "번호": [p + 1 for p in ps]}, ensure_ascii=False))
        return 0
    if a.file:
        errs = check_files([Path(a.file)])
    else:
        files = _dated(Path(a.dir).glob("*.json"))
        old = [p for p in files if date.fromisoformat(p.stem) < RULE_FROM]
        new = [p for p in files if date.fromisoformat(p.stem) >= RULE_FROM]
        b = baseline(old)
        if b["n"]:
            print(f"기준선(시행 전 {len(old)}일·{b['n']}문항): 정답 위치 ①~⑤ = {b['pos']} · 숫자 오름차순 {b['sorted']}문항 중 정답 ②③④ {b['sorted_mid']}")
        errs = check_files(new) if new else []
        print(f"규칙 v1 시행분: {len(new)}일")
    for e in errs:
        print("FAIL", e)
    if not errs:
        print("ok: 오늘의 인적성 생성 규칙 v1")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
