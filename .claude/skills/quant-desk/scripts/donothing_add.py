#!/usr/bin/env python3
"""무행동 장부에 체결(trade) 한 줄 추가 — 퀀트 스킬 시범(2026-10-28). 장부는 **비공개 저장소**에만 있다.

장부  pb-private scorecard/donothing_book.csv  (이 공개 저장소에는 경로·형식만 둔다 — 수량·단가·종목 값 0건)
형식  kind,date,mkt,key,qty,price,bucket,source
      kind=trade · date=체결일(YYYY-MM-DD, 국내 KST · 미국 ET 세션일) · mkt=KR|US · key=종목 코드/티커
      qty=+매수 / −매도(0 금지) · price>0(체결 단가, 현지 통화) · bucket=장부 머리 주석 '# bucket:' 에 적힌 값 또는 etc
      source=근거(예: 체결 내역 문서 이름). 기준 보유(base)·현금(cash)·입출금(flow)은 이 도구로 넣지 않는다.

  python3 .claude/skills/quant-desk/scripts/donothing_add.py --date 2026-10-28 --mkt KR --key <코드> --qty <±수량> \\
          --price <단가> --bucket <버킷> --source "<근거>"            # 검사만 (기본, 아무것도 안 씀)
  ... --write          # 검사 통과 시 장부 끝에 1행 추가
  ... --write --run    # 추가 후 pb-private scorecard/donothing.py --quiet 재계산(갭 재계산)

장부 위치: --book > 환경변수 PB_DIR/scorecard/donothing_book.csv > 이 저장소 옆 pb-private/.
안전장치: 장부가 이 공개 저장소 안이면 거부 · 같은 행 중복 거부 · 출력에 수량·단가를 찍지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HEADER = ["kind", "date", "mkt", "key", "qty", "price", "bucket", "source"]


def default_book() -> Path:
    if os.environ.get("PB_DIR"):
        return Path(os.environ["PB_DIR"]) / "scorecard" / "donothing_book.csv"
    for up in [ROOT, *ROOT.parents]:   # worktree(.claude/worktrees/…) 안에서도 저장소 옆 pb-private 를 찾는다
        cand = up.parent / "pb-private" / "scorecard" / "donothing_book.csv"
        if cand.exists():
            return cand
    return ROOT.parent / "pb-private" / "scorecard" / "donothing_book.csv"


def buckets_of(text: str) -> set[str]:
    out = {"etc"}
    for line in text.splitlines():
        if line.startswith("# bucket:"):
            out |= set(re.findall(r"([a-z_]+)\s*=", line))
    return out


def validate(a, text: str) -> list[str]:
    err = []
    rows = [r for r in csv.reader(l for l in text.splitlines() if l.strip() and not l.startswith("#"))]
    if not rows or rows[0] != HEADER:
        err.append(f"장부 머리줄이 {','.join(HEADER)} 가 아님")
    try:
        d = date.fromisoformat(a.date)
        if d > date.today():
            err.append("미래 날짜")
    except ValueError:
        err.append("date 형식 YYYY-MM-DD 아님")
    if a.mkt not in ("KR", "US"):
        err.append("mkt 는 KR|US")
    if not re.fullmatch(r"[A-Za-z0-9.\-]+", a.key or ""):
        err.append("key 형식(영숫자·.·-)")
    if a.qty == 0:
        err.append("qty 0 금지(+매수/−매도)")
    if not a.price > 0:
        err.append("price 는 양수")
    b = buckets_of(text)
    if a.bucket not in b:
        err.append(f"bucket 은 {sorted(b)} 중 하나")
    if "," in a.source or not a.source.strip():
        err.append("source 비었거나 쉼표 포함")
    return err


def row_of(a) -> list[str]:
    q = int(a.qty) if float(a.qty).is_integer() else a.qty
    p = int(a.price) if float(a.price).is_integer() else a.price
    return ["trade", a.date, a.mkt, a.key, str(q), str(p), a.bucket, a.source.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", type=Path, default=None)
    ap.add_argument("--date", required=True)
    ap.add_argument("--mkt", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--qty", type=float, required=True)
    ap.add_argument("--price", type=float, required=True)
    ap.add_argument("--bucket", default="etc")
    ap.add_argument("--source", required=True)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--run", action="store_true", help="추가 후 donothing.py --quiet 재계산")
    a = ap.parse_args(argv)
    book = (a.book or default_book()).resolve()
    if ROOT in book.parents or "market-screener" in book.parts:
        print("거부: 장부가 공개 저장소(market-screener) 안에 있음 — 비공개 저장소 경로만 허용", file=sys.stderr)
        return 2
    if not book.exists():
        print(f"장부 없음: {book} (PB_DIR 또는 --book 지정)", file=sys.stderr)
        return 2
    text = book.read_text(encoding="utf-8")
    err = validate(a, text)
    new = row_of(a)
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerow(new)
    line = buf.getvalue()
    if line.strip() in {l.strip() for l in text.splitlines()}:
        err.append("같은 행이 이미 있음(중복)")
    if err:
        for e in err:
            print("✗", e, file=sys.stderr)
        return 1
    tag = f"trade {a.date} {a.mkt} bucket={a.bucket} ({'매수' if a.qty > 0 else '매도'})"   # 수량·단가는 찍지 않는다
    if not a.write:
        print(f"검사 통과 — {tag}. --write 로 추가")
        return 0
    with book.open("a", encoding="utf-8") as f:
        if not text.endswith("\n"):
            f.write("\n")
        f.write(line)
    print(f"추가 1행 — {tag} → {book}")
    if a.run:
        dn = book.parent / "donothing.py"
        r = subprocess.run([sys.executable, str(dn), "--quiet"], cwd=book.parents[1])
        print(f"donothing.py 재계산 종료코드 {r.returncode} (산출 analysis/donothing.json)")
        return r.returncode
    print("다음: pb-private 에서 python3 scorecard/donothing.py (갭 재계산) → 비공개 저장소에 커밋")
    return 0


if __name__ == "__main__":
    sys.exit(main())
