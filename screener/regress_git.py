"""커밋 직전 역행 검사 (재발방지대책 F) — 워크플로 '저장' 단계에서 `pull --rebase -X theirs` 뒤, push 전에 실행.

python -m screener.regress_git [--base origin/main]

`-X theirs` 는 충돌 시 '이번 실행의 커밋'을 이기게 한다. 실행 도중 main 에 더 새 날짜 산출물이 올라왔으면
늦게 끝난(또는 수동·주말) 실행이 그것을 과거 날짜로 덮는다. 여기서 감시 대상 파일마다 base(원격 main) 와 HEAD 의
날짜(guard.day 규칙)를 비교해, HEAD 가 더 과거면 base 판으로 되돌리고 커밋을 고친다(amend).
detail/<mk>/_index.json 이 역행이면 detail/<mk>/ 폴더 전체를 되돌린다. 차단 내역은 reports/freshness.json 에 기록.
항상 종료코드 0 (저장 단계를 멈추지 않음) — 되돌린 파일 수만 출력.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import guard

ROOT = Path(__file__).resolve().parents[1]


def _git(*a: str, check: bool = False) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout


def watched() -> list[tuple[str, str | None]]:
    """(경로, 날짜 키). 신선도 계약의 파일 + 날짜가 파일명에 없는 주요 산출물."""
    items = json.loads((ROOT / "ops" / "freshness.json").read_text(encoding="utf-8"))["items"]
    out = {(i["path"], i.get("key")) for i in items if i.get("kind", "session") == "session" and "." not in str(i.get("key") or "")}
    out |= {("reports/sim_signals_KR.json", None), ("reports/sim_signals_US.json", None),
            ("reports/trend_discovery_KR.json", None), ("reports/trend_discovery_US.json", None), ("reports/macro_view.json", None),
            ("reports/japan.json", "date")}
    return sorted(out, key=lambda x: x[0])


def _day_at(rev: str, path: str, key: str | None) -> str | None:
    raw = _git("show", f"{rev}:{path}")
    if not raw:
        return None
    if path.endswith(".json"):
        try:
            return guard.json_day(json.loads(raw), key)
        except Exception:  # noqa: BLE001
            return None
    return guard.text_day(raw)


def regressed(base: str = "origin/main", head: str = "HEAD") -> list[tuple[str, str, str]]:
    changed = set(_git("diff", "--name-only", base, head).split())
    bad = []
    for path, key in watched():
        if path not in changed:
            continue
        b, h = _day_at(base, path, key), _day_at(head, path, key)
        if b and h and h < b:
            bad.append((path, b, h))
    return bad


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    base = argv[argv.index("--base") + 1] if "--base" in argv else "origin/main"
    bad = regressed(base)
    if not bad:
        print("역행 없음")
        return 0
    for path, b, h in bad:
        tgt = str(Path(path).parent) if path.endswith("/_index.json") and "/detail/" in path else path
        if tgt != path:   # 상세 폴더 통째: HEAD 에만 있는 파일도 지우고 base 판으로
            _git("rm", "-r", "-q", "--cached", tgt)
            _git("checkout", base, "--", tgt)
        else:
            _git("checkout", base, "--", tgt)
        print(f"⛔ 역행 되돌림: {tgt} ({h} < 원격 {b})")
        try:
            guard.record_block(ROOT / path, b, h)
        except Exception:  # noqa: BLE001
            pass
    _git("add", "reports/freshness.json")
    _git("commit", "-q", "--amend", "--no-edit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
