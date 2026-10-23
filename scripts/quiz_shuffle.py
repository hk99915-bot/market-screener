"""정답 위치 균등화 (kb:edu#5①·#7c) — content/study/quiz_bank.json + track_*.json 의 v3 모듈 quiz.

문항·선택지 문장·정답(문장)·duel.pick(문장)은 그대로 두고 **정답 선택지의 자리만** 옮긴다.
- 자리 배정: 모듈 단위로, (그 모듈 안 같은 자리 수, 전체 같은 자리 수)가 가장 적은 자리를 고른다 → 모듈 5문항 = 2·1·1·1, 전체 ≈ 25%씩.
  동률은 문항 id 해시로 결정적으로 깬다(다시 돌려도 같은 결과 = 멱등).
- 오답지는 원래 상대 순서를 유지(최소 변경). duel.pick 은 같은 문장을 가리키도록 다시 매핑.
- 숫자 선택지가 이미 오름/내림차순인 문항은 그대로 둔다(Haladyna 2002 '논리·숫자 순서로 배치' 지침 우선) — 배정 시 그 자리를 계산에 넣는다.
- why·q 에 선택지 번호(①·1번·보기 2 등)를 쓰는 문항은 옮기지 않고 경고한다(의미 보존).

  python scripts/quiz_shuffle.py           # 분포만 출력 (dry-run)
  python scripts/quiz_shuffle.py --write   # 원본 수정 후 → python scripts/study_content_check.py --build
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "content" / "study"
N = 4
POS_REF = re.compile(r"(①|②|③|④|[1-4]\s*번(?!째)|보기\s*[1-4]|선택지\s*[1-4]|위\s*모두|모두\s*아님)")
NUM = re.compile(r"[+\-]?\d[\d.,]*")


def _val(s: str) -> float | None:
    s = str(s).replace("−", "-").replace(",", "")
    if not re.match(r"^\s*[+\-]?\s*\d", s):
        return None
    m = NUM.search(s)
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None


def ordered_numeric(ch: list) -> bool:
    vs = [_val(c) for c in ch]
    return all(v is not None for v in vs) and (vs == sorted(vs) or vs == sorted(vs, reverse=True))


def has_pos_ref(q: dict) -> bool:
    return bool(POS_REF.search(" ".join(str(q.get(k) or "") for k in ("q", "why"))))


def _h(s: str) -> int:
    return int(hashlib.sha1(s.encode("utf-8")).hexdigest()[:8], 16)


def move(q: dict, target: int) -> dict:
    """정답 문장을 target 자리로, 오답지는 상대 순서 유지. duel.pick 은 문장 기준 재매핑."""
    ch = list(q["choices"])
    ans_txt = ch[q["answer"]]
    others = [c for i, c in enumerate(ch) if i != q["answer"]]
    new = others[:target] + [ans_txt] + others[target:]
    o = dict(q)
    o["choices"] = new
    o["answer"] = target
    d = q.get("duel")
    if isinstance(d, dict) and isinstance(d.get("pick"), int):
        o["duel"] = {**d, "pick": new.index(ch[d["pick"]])}
    return o


def balance(groups: list[tuple[str, list[dict]]]) -> tuple[list[tuple[str, list[dict]]], list[str]]:
    """groups = [(모듈, [문항…])] (파일 순서). 반환 (새 groups, 경고)."""
    glob: Counter = Counter()
    warns: list[str] = []
    out = []
    for mid, qs in groups:
        loc: Counter = Counter()
        fixed = [not isinstance(q.get("answer"), int) or len(q.get("choices") or []) != N or ordered_numeric(q["choices"]) or has_pos_ref(q) for q in qs]
        for q, f in zip(qs, fixed):
            if f and isinstance(q.get("answer"), int):
                loc[q["answer"]] += 1
                glob[q["answer"]] += 1
                if has_pos_ref(q):
                    warns.append(f"{q.get('id', mid)}: 문두/해설이 선택지 번호를 언급 — 자리 고정")
        new = []
        for q, f in zip(qs, fixed):
            if f:
                new.append(q)
                continue
            key = str(q.get("id") or (mid + q["q"]))
            t = min(range(N), key=lambda p: (loc[p], glob[p], (_h(key) + p) % N))
            loc[t] += 1
            glob[t] += 1
            new.append(move(q, t))
        out.append((mid, new))
    return out, warns


def _dump(p: Path, o) -> None:
    p.write_text(json.dumps(o, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def dist(qs: list[dict]) -> Counter:
    return Counter(q["answer"] for q in qs if isinstance(q.get("answer"), int))


def same_meaning(a: dict, b: dict) -> bool:
    pick = lambda q: (q["choices"][q["duel"]["pick"]] if isinstance(q.get("duel"), dict) and isinstance(q["duel"].get("pick"), int) else None)  # noqa: E731
    return (sorted(a["choices"]) == sorted(b["choices"]) and a["choices"][a["answer"]] == b["choices"][b["answer"]]
            and pick(a) == pick(b) and {k: v for k, v in a.items() if k not in ("choices", "answer", "duel")} == {k: v for k, v in b.items() if k not in ("choices", "answer", "duel")})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    rc = 0
    # 1) quiz_bank
    bp = SRC / "quiz_bank.json"
    bank = json.loads(bp.read_text(encoding="utf-8"))
    order: list[str] = []
    by: dict[str, list[dict]] = {}
    for it in bank["items"]:
        if it["module"] not in by:
            order.append(it["module"])
        by.setdefault(it["module"], []).append(it)
    new_groups, w1 = balance([(m, by[m]) for m in order])
    new_by = dict(new_groups)
    cursor = {m: 0 for m in order}
    new_items = []
    for it in bank["items"]:
        q = new_by[it["module"]][cursor[it["module"]]]
        cursor[it["module"]] += 1
        assert same_meaning(it, q), it["id"]
        new_items.append(q)
    print(f"quiz_bank {len(new_items)}문항: 전 {dict(sorted(dist(bank['items']).items()))} → 후 {dict(sorted(dist(new_items).items()))}")
    # 2) 모듈 v3 quiz (track_*.json)
    tracks = []
    groups = []
    for p in sorted(SRC.glob("track_*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        tracks.append((p, t))
        for m in t.get("modules", []):
            qs = [q for q in m.get("quiz", []) if "choices" in q]
            if qs:
                groups.append((m["id"], qs))
    before = [q for _, qs in groups for q in qs]
    new_groups2, w2 = balance(groups)
    after = [q for _, qs in new_groups2 for q in qs]
    for x, y in zip(before, after):
        assert same_meaning(x, y), x.get("q")
    print(f"모듈 v3 quiz {len(after)}문항: 전 {dict(sorted(dist(before).items()))} → 후 {dict(sorted(dist(after).items()))}")
    for w in w1 + w2:
        print("WARN", w)
    if a.write:
        bank["items"] = new_items
        _dump(bp, bank)
        nb = dict(new_groups2)
        for p, t in tracks:
            for m in t.get("modules", []):
                if m["id"] in nb:
                    it = iter(nb[m["id"]])
                    m["quiz"] = [next(it) if "choices" in q else q for q in m["quiz"]]
            _dump(p, t)
        print("written — 다음: python scripts/study_content_check.py --build")
    return rc


if __name__ == "__main__":
    sys.exit(main())
