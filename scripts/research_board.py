"""연구 보드 — ops/research_pipeline.json(사람이 적는 단계·판정·관문) + 자동 칸 → reports/research_board.json (QUANT › 연구 보드).

자동 칸(사람이 안 적어도 되는 것):
  - 항목별 '마지막 갱신' = items[].auto 파일들의 날짜 중 최신 (json: generated/asof/registered/meta.asof/meta.run, md·py: 앞 20줄의 첫 YYYY-MM-DD)
  - 등급 분포 = items[].grades 연구 json (scripts/trial_log._grade_counts 재사용)
  - 미등록 연구 = reports/studies 에 있는데 어느 항목도 가리키지 않는 연구 (→ 퀀트가 파이프라인에 올릴 것)
  - 퀀트 앞 열린 요청 = docs/desk_kb/rounds/_requests.json (to=quant, status≠done) — '도전' 칸
'이번 주 할 일'·단계별 개수는 화면이 브라우저 날짜로 계산(빌드가 늦어도 마감 판정이 밀리지 않게).

사용: python3 scripts/research_board.py --build | --check     (ops.yml 23:47·00:07 KST 가 --build, 단계를 바꾼 데스크도 --build)
개인 금액·보유 없음 — 연구 메타데이터만.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from trial_log import _grade_counts  # noqa: E402

PIPE = ROOT / "ops" / "research_pipeline.json"
OUT = ROOT / "reports" / "research_board.json"
STUDIES = ROOT / "reports" / "studies"
REQS = ROOT / "docs" / "desk_kb" / "rounds" / "_requests.json"
STAGES = ("idea", "backtest", "verify", "paper", "live")
VERDICTS = ("진행", "통과", "보류", "폐기")
DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
UNTIL = re.compile(r"(20\d\d-\d\d-\d\d)(?!\s*까지)")
# 연구가 아닌 보조 파일 — 미등록 목록에서 뺀다
AUX = re.compile(r"^(trial_log|replication_.*|.*_screen|.*_preregistration|cio_.*)$")


def file_date(p: Path) -> str | None:
    """파일 안에 적힌 기준 날짜(YYYY-MM-DD). 없으면 None — git 시각은 쓰지 않는다(체크아웃마다 달라짐)."""
    if not p.exists():
        return None
    if p.suffix == ".json":
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return None
        if isinstance(d, dict):
            meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
            for v in (d.get("generated"), d.get("generated_at"), d.get("asof"), d.get("registered"), meta.get("asof"), meta.get("run"), meta.get("run_at_utc")):
                m = DATE.search(str(v or ""))
                if m:
                    return m.group(1)
        return None
    m = DATE.match(p.name)   # 2026-10-21_xxx.md — 파일 이름 날짜가 우선
    if m:
        return m.group(1)
    head = "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:20])
    m = UNTIL.search(head)   # '2027-04-15까지' 같은 기한 날짜는 건너뛴다
    return m.group(1) if m else None


def referenced(item: dict) -> set[str]:
    """항목이 가리키는 연구 파일 stem (reports/studies 안)."""
    out = set()
    for f in [*(item.get("files") or {}).values(), *(item.get("auto") or []), item.get("grades") or ""]:
        p = Path(str(f))
        if p.parent.as_posix() == "reports/studies":
            out.add(p.stem)
    return out


def validate(pipe: dict) -> list[str]:
    errs = []
    ids = set()
    for it in pipe.get("items", []):
        i = it.get("id")
        if not i or i in ids:
            errs.append(f"id 없음/중복: {i}")
        ids.add(i)
        if it.get("stage") not in STAGES:
            errs.append(f"{i}: stage {it.get('stage')} ∉ {STAGES}")
        if it.get("verdict") not in VERDICTS:
            errs.append(f"{i}: verdict {it.get('verdict')} ∉ {VERDICTS}")
        for k in ("name", "owner", "result", "gate"):
            if not it.get(k):
                errs.append(f"{i}: {k} 비어 있음")
        d = it.get("due")
        if d is not None and not re.fullmatch(r"20\d\d-\d\d-\d\d", str(d)):
            errs.append(f"{i}: due 형식 {d}")
        for f in [*(it.get("files") or {}).values(), *(it.get("auto") or [])]:
            if "/" in str(f) and not (ROOT / f).exists():
                errs.append(f"{i}: 파일 없음 {f}")
    if [s.get("id") for s in pipe.get("stages", [])] != list(STAGES):
        errs.append("stages 순서/구성 불일치")
    return errs


def build(pipe_path: Path = PIPE, studies: Path = STUDIES, reqs: Path = REQS) -> dict:
    pipe = json.loads(pipe_path.read_text(encoding="utf-8"))
    errs = validate(pipe)
    if errs:
        raise SystemExit("research_pipeline.json 오류:\n  " + "\n  ".join(errs))
    items, seen = [], set()
    for it in pipe["items"]:
        o = dict(it)
        dates = [d for d in (file_date(ROOT / f) for f in it.get("auto") or []) if d]
        o["updated"] = max(dates) if dates else None
        if it.get("grades"):
            try:
                o["grade_counts"] = _grade_counts(json.loads((ROOT / it["grades"]).read_text(encoding="utf-8")))
            except (OSError, ValueError):
                o["grade_counts"] = {}
        seen |= referenced(it)
        items.append(o)
    unreg = []
    for stem in sorted({p.stem for p in studies.glob("*.json")} | {p.stem for p in studies.glob("*.md")}):
        if AUX.match(stem) or stem in seen:
            continue
        p = studies / f"{stem}.md"
        unreg.append({"study": stem, "date": file_date(p if p.exists() else studies / f"{stem}.json"),
                      "file": f"reports/studies/{p.name if p.exists() else stem + '.json'}"})
    open_reqs = []
    if reqs.exists():
        for r in json.loads(reqs.read_text(encoding="utf-8")).get("requests", []):
            if r.get("to") == "quant" and r.get("status") != "done":
                o = {k: r.get(k) for k in ("id", "from", "opened", "due")}
                t = str(r.get("text") or "")
                o["text"] = t if len(t) <= 140 else t[:139] + "…"
                open_reqs.append(o)
    return {"schema_version": 1,
            "_doc": "scripts/research_board.py --build 산출물 — 손으로 고치지 않는다. 사람이 적는 칸은 ops/research_pipeline.json.",
            "asof": max([d for d in (o["updated"] for o in items) if d] or [None]),
            "stages": pipe["stages"], "verdicts": pipe["verdicts"], "challenge": pipe.get("challenge", {}),
            "items": items, "unregistered": unreg, "quant_requests": open_reqs}


def dump(b: dict) -> str:
    return json.dumps(b, ensure_ascii=False, indent=1) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    txt = dump(build())
    if a.build:
        OUT.write_text(txt, encoding="utf-8")
        b = json.loads(txt)
        print(f"wrote {OUT.relative_to(ROOT)} · 항목 {len(b['items'])} · 미등록 연구 {len(b['unregistered'])} · 퀀트 앞 요청 {len(b['quant_requests'])}")
        return 0
    if a.check:
        cur = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if cur != txt:
            print("research_board.json 이 원장과 다르다 → python3 scripts/research_board.py --build", file=sys.stderr)
            return 1
        print("research_board.json ok")
        return 0
    sys.stdout.write(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
