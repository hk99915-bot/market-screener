#!/usr/bin/env python3
"""STUDY 콘텐츠 검증·빌드 (교육 데스크) — 스키마: docs/study_spec.md

원본(편집 대상)  content/study/index.json · track_<id>.json · aptitude.json · quiz_bank.json · srs.json
산출물(터미널용) content/study.json  ← Code.gs getStudyGuide / build_pages.py 가 읽는 단일 파일. 손으로 고치지 않는다.

  python scripts/study_content_check.py            # 검증만 (CI). 실패 시 종료코드 1
  python scripts/study_content_check.py --build    # 검증 통과 시 content/study.json 재생성
  python scripts/study_content_check.py --split    # (1회성) 기존 content/study.json → content/study/*.json 분할

검사 항목: 필수 필드 · id 중복 · prereq 존재·순환 · quiz choices 4개·answer 범위 · est_min ≤ 20(v3) ·
          v3 핵심 개념/공식/실수의 출처 태그([consult:…] [kb:…] [reports/studies/…] [교육 보충]) ·
          로드맵 id 존재 · 인적성(선택지 5·정답 위치 분포·기출 메타 필드·https) · quiz_bank 모듈 참조·모듈당 ≥5·상황 문제 비중 · srs 규칙 · 2주 게이트(open 정확히 15) · 금지어 · study.json 동기화.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "content" / "study"
OUT = ROOT / "content" / "study.json"

CITE = re.compile(r"\[(consult:[a-z_]+#[qLx]\d+|kb:[a-z_]+#\d+|reports/studies/[a-z_]+|교육 보충)\]")
BANNED = ["누나"]
LEGACY_REQ = ["id", "title", "tags", "level", "hours", "summary", "analogy", "terms", "prereq", "concepts", "formulas", "example", "mistakes", "quiz"]
V3_REQ = ["id", "track", "title", "tags", "level", "est_min", "prereq", "objectives", "summary", "analogy", "terms", "concepts",
          "formulas", "example", "market_hook", "terminal_lookup", "rule_link", "pitfalls", "quiz", "next_door", "srs", "sources"]
QUIZ_KINDS = {"knowledge", "situation"}
SECTION_ORDER = ["summary", "analogy", "terms", "concepts", "formulas", "example", "market_hook", "pitfalls", "quiz"]


def _load(name: str):
    return json.loads((SRC / name).read_text(encoding="utf-8"))


def load_sources() -> dict:
    idx = _load("index.json")
    tracks = [_load(f"track_{tid}.json") for tid in idx["track_order"]]
    return {"index": idx, "tracks": tracks, "aptitude": _load("aptitude.json"),
            "quiz_bank": _load("quiz_bank.json") if (SRC / "quiz_bank.json").exists() else None,
            "srs": _load("srs.json") if (SRC / "srs.json").exists() else None}


# ───────────────────────── 검증 ─────────────────────────
class Check:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, s: str) -> None:
        self.errors.append(s)

    def warn(self, s: str) -> None:
        self.warnings.append(s)


def _cited(text: str) -> bool:
    return bool(CITE.search(text or ""))


def check_module(m: dict, track_id: str, c: Check) -> None:
    mid = m.get("id", "?")
    v3 = m.get("schema", 2) == 3
    req = V3_REQ if v3 else LEGACY_REQ
    for k in req:
        if k not in m:
            c.err(f"{mid}: 필수 필드 없음 '{k}'")
    if not isinstance(m.get("level"), int) or not 1 <= m["level"] <= 3:
        c.err(f"{mid}: level 은 1~3 정수")
    if v3:
        if m.get("track") != track_id:
            c.err(f"{mid}: track '{m.get('track')}' ≠ 파일 트랙 '{track_id}'")
        em = m.get("est_min")
        if not isinstance(em, int) or not 5 <= em <= 20:
            c.err(f"{mid}: est_min 은 5~20 (하루 1모듈 20분 상한, consult:pb_learner#L5) — {em}")
        if not isinstance(m.get("objectives"), list) or not 2 <= len(m.get("objectives", [])) <= 6:
            c.err(f"{mid}: objectives 2~6개")
        for sec in ("concepts", "pitfalls"):
            for i, t in enumerate(m.get(sec, [])):
                if not isinstance(t, str) or not _cited(t):
                    c.err(f"{mid}: {sec}[{i}] 출처 태그 없음 ([consult:…]/[kb:…]/[reports/studies/…]/[교육 보충])")
        for i, f in enumerate(m.get("formulas", [])):
            for k in ("name", "f", "example"):
                if not f.get(k):
                    c.err(f"{mid}: formulas[{i}].{k} 없음")
            if not _cited(f.get("src", "") + " " + f.get("note", "")):
                c.err(f"{mid}: formulas[{i}] 출처 태그 없음(src)")
        mh = m.get("market_hook") or {}
        for k in ("tab", "fields", "read"):
            if not mh.get(k):
                c.err(f"{mid}: market_hook.{k} 없음")
        if not isinstance(m.get("sources"), list) or not m["sources"]:
            c.err(f"{mid}: sources[] 비어 있음")
        for s in m.get("sources", []):
            if not CITE.fullmatch(f"[{s}]") and not s.startswith("reports/") and not s.startswith("docs/"):
                c.err(f"{mid}: sources 항목 형식 오류 '{s}'")
        srs = m.get("srs") or {}
        iv = srs.get("intervals")
        if not (isinstance(iv, list) and len(iv) >= 3 and all(isinstance(x, int) and x > 0 for x in iv) and iv == sorted(iv)):
            c.err(f"{mid}: srs.intervals 는 오름차순 양의 정수 리스트(기본 [1,3,7,21])")
        if not str(m.get("rule_link", "")).strip():
            c.err(f"{mid}: rule_link(규칙 조항 연결 한 줄) 비어 있음")
        if not str(m.get("next_door", "")).strip():
            c.err(f"{mid}: next_door(다음 질문으로 가는 문) 비어 있음")
        if not str(m.get("terminal_lookup", "")).strip():
            c.err(f"{mid}: terminal_lookup(오늘 터미널에서 이 숫자 찾기) 비어 있음")
    # quiz (양쪽 공통: choices 가 있으면 4개·answer 범위)
    qs = m.get("quiz", [])
    if not isinstance(qs, list) or len(qs) < (3 if v3 else 1):
        c.err(f"{mid}: quiz 는 {'3' if v3 else '1'}개 이상")
    for i, q in enumerate(qs if isinstance(qs, list) else []):
        check_quiz(q, f"{mid}.quiz[{i}]", c, require_v3=v3)
    # 금지어
    blob = json.dumps(m, ensure_ascii=False)
    for w in BANNED:
        if w in blob:
            c.err(f"{mid}: 금지어 '{w}'")
    if re.search(r"내 계좌|제 계좌|보유 금액|실제 보유", blob):
        c.warn(f"{mid}: 개인 보유/금액 표현 의심 — 비율·가상 숫자만 쓸 것")


def check_quiz(q: dict, where: str, c: Check, require_v3: bool) -> None:
    if not q.get("q"):
        c.err(f"{where}: q 없음")
    if not q.get("why"):
        c.err(f"{where}: why 없음")
    if "choices" in q or require_v3:
        ch = q.get("choices")
        if not isinstance(ch, list) or len(ch) != 4 or len(set(map(str, ch))) != 4:
            c.err(f"{where}: choices 는 서로 다른 4개")
        a = q.get("answer")
        if not isinstance(a, int) or isinstance(a, bool) or not (isinstance(ch, list) and 0 <= a < len(ch)):
            c.err(f"{where}: answer 인덱스 범위 밖 ({a})")
        if q.get("kind") not in QUIZ_KINDS:
            c.err(f"{where}: kind 는 knowledge|situation")
        d = q.get("duel")
        if d is not None:
            if not isinstance(d, dict) or not d.get("desk") or not isinstance(d.get("pick"), int) or not (isinstance(ch, list) and 0 <= d["pick"] < len(ch)):
                c.err(f"{where}: duel 은 {{desk, pick(인덱스), why?}}")
    else:
        if "a" not in q or "t" not in q:
            c.err(f"{where}: 구형 quiz 는 t/q/a/why")


APT_PAST_REQ = ["id", "exam", "year", "date", "booklet", "no", "area", "type", "topic", "strategy", "trap", "time_sec", "url", "checked_via"]


def check_aptitude(A: dict, c: Check) -> None:
    """인적성(aptitude.json): 자체 문항 선택지 5개·정답 위치 분포(kb:edu#7c) · 기출 메타(past) 필수 필드·https 원문 링크 · 출처 블록."""
    secs = A.get("sections", [])
    seen: set[str] = set()
    by_sec: dict[str, list[int]] = {}
    for it in A.get("items", []):
        iid = it.get("id", "?")
        if iid in seen:
            c.err(f"aptitude: id 중복 {iid}")
        seen.add(iid)
        if it.get("sec") not in secs:
            c.err(f"aptitude {iid}: sec '{it.get('sec')}' 가 sections 에 없음")
        ch = it.get("choices", [])
        if len(ch) != 5 or len(set(ch)) != 5:
            c.err(f"aptitude {iid}: choices 는 서로 다른 5개")
        a = it.get("a")
        if not isinstance(a, int) or not 0 <= a < len(ch):
            c.err(f"aptitude {iid}: a(0-index) 범위 밖 {a}")
            continue
        if not (it.get("exp") or "").strip():
            c.err(f"aptitude {iid}: exp 없음")
        if "why" in it and len(it["why"].strip()) < 15:
            c.err(f"aptitude {iid}: why 는 한 문장 근거 (kb:edu#7b)")
        by_sec.setdefault(it.get("sec"), []).append(a)
    for sec, arr in by_sec.items():
        if len(arr) >= 5:
            top = max(arr.count(i) for i in range(5))
            if top / len(arr) > 0.6:
                c.err(f"aptitude '{sec}': 같은 정답 위치 {top}/{len(arr)} > 60% (kb:edu#7c)")
    past = A.get("past")
    if past is not None:
        areas = past.get("areas", [])
        pids: set[str] = set()
        for it in past.get("items", []):
            pid = it.get("id", "?")
            for k in APT_PAST_REQ:
                if k not in it or it[k] in ("", None):
                    c.err(f"aptitude.past {pid}: 필수 필드 없음 '{k}'")
            if pid in pids:
                c.err(f"aptitude.past: id 중복 {pid}")
            pids.add(pid)
            for k in ("url", "checked_via"):
                if not str(it.get(k, "")).startswith("https://"):
                    c.err(f"aptitude.past {pid}: {k} 는 https 링크")
            if it.get("area") not in areas:
                c.err(f"aptitude.past {pid}: area '{it.get('area')}' ∉ {areas}")
            if not str(it.get("booklet", "")).endswith("책형"):
                c.err(f"aptitude.past {pid}: booklet 은 'O책형'")
        for ar in areas:
            if not any(it.get("area") == ar for it in past.get("items", [])):
                c.err(f"aptitude.past: 영역 '{ar}' 항목 0개")
        src = A.get("sources") or {}
        if not src.get("license_judgment") or not src.get("checked"):
            c.err("aptitude.sources: license_judgment·checked 필요 (past 가 있으면)")
        for s_ in src.get("list", []):
            if not str(s_.get("url", "")).startswith("https://"):
                c.err(f"aptitude.sources {s_.get('id')}: url 은 https")
    tm = A.get("type_map")
    if tm is not None:
        for r in tm.get("rows", []):
            if len(r) != len(tm.get("head", [])):
                c.err(f"aptitude.type_map: 행 길이 ≠ head ({r[:2]})")


def check_all(S: dict) -> Check:
    c = Check()
    idx = S["index"]
    for k in ("version", "updated", "title", "intro", "roadmap", "tesat", "track_order"):
        if k not in idx:
            c.err(f"index.json: '{k}' 없음")
    ids: dict[str, str] = {}
    mods: dict[str, dict] = {}
    for t in S["tracks"]:
        for k in ("id", "title", "modules"):
            if k not in t:
                c.err(f"track: '{k}' 없음 ({t.get('id')})")
        for m in t.get("modules", []):
            mid = m.get("id")
            if mid in ids:
                c.err(f"id 중복: {mid} ({ids[mid]} 와 {t['id']})")
            ids[mid] = t["id"]
            mods[mid] = m
            check_module(m, t["id"], c)
    # prereq 존재·순환
    for mid, m in mods.items():
        for p in m.get("prereq", []):
            if p not in mods:
                c.err(f"{mid}: prereq '{p}' 없는 모듈")
    state: dict[str, int] = {}

    def dfs(u: str, path: list[str]) -> None:
        state[u] = 1
        for p in mods[u].get("prereq", []):
            if p not in mods:
                continue
            if state.get(p) == 1:
                c.err(f"prereq 순환: {' → '.join(path + [u, p])}")
            elif state.get(p, 0) == 0:
                dfs(p, path + [u])
        state[u] = 2

    for mid in mods:
        if state.get(mid, 0) == 0:
            dfs(mid, [])
    # 로드맵
    rm = idx.get("roadmap", {})
    for i in rm.get("order", []):
        if i not in mods:
            c.err(f"roadmap.order: 없는 모듈 '{i}'")
    seen_in_steps: set[str] = set()
    for s in rm.get("steps", []):
        for i in s.get("ids", []):
            if i not in mods:
                c.err(f"roadmap.steps '{s.get('name')}': 없는 모듈 '{i}'")
            seen_in_steps.add(i)
    for mid in mods:
        if mid not in seen_in_steps:
            c.warn(f"{mid}: 로드맵 어느 단계에도 없음")
    if set(rm.get("order", [])) != set(mods):
        missing = set(mods) - set(rm.get("order", []))
        if missing:
            c.err(f"roadmap.order 에 빠진 모듈: {sorted(missing)}")
    # quiz_bank
    qb = S.get("quiz_bank")
    if qb is not None:
        qids: set[str] = set()
        per: dict[str, list] = {}
        for it in qb.get("items", []):
            if it.get("id") in qids:
                c.err(f"quiz_bank: id 중복 {it.get('id')}")
            qids.add(it.get("id"))
            if it.get("module") not in mods:
                c.err(f"quiz_bank {it.get('id')}: 없는 모듈 '{it.get('module')}'")
            if it.get("difficulty") not in (1, 2, 3):
                c.err(f"quiz_bank {it.get('id')}: difficulty 1~3")
            check_quiz(it, f"quiz_bank.{it.get('id')}", c, require_v3=True)
            per.setdefault(it.get("module"), []).append(it)
        for mid, m in mods.items():
            if m.get("schema", 2) == 3:
                n = len(per.get(mid, []))
                if n < 5:
                    c.err(f"quiz_bank: {mid} 문항 {n}개 < 5")
        all_items = qb.get("items", [])
        if all_items:
            share = sum(1 for it in all_items if it.get("kind") == "situation") / len(all_items)
            if share < 0.7:
                c.err(f"quiz_bank: 상황 판단 문제 비중 {share:.0%} < 70% (consult:pb_learner#L8)")
    # 2주 게이트: 열린 모듈 정확히 15개, 나머지 전부 잠김, 겹침 없음
    gate = idx.get("gate")
    if gate is None:
        if rm.get("first_two_weeks"):
            c.err("index.json: 'gate' 없음 (첫 2주 열린 모듈 15개)")
    else:
        op, lk = list(gate.get("open", [])), list(gate.get("locked", []))
        if len(op) != 15 or len(set(op)) != 15:
            c.err(f"gate.open 은 정확히 15개 (지금 {len(op)})")
        for i in op + lk:
            if i not in mods:
                c.err(f"gate: 없는 모듈 '{i}'")
        if set(op) & set(lk):
            c.err(f"gate: open·locked 겹침 {sorted(set(op) & set(lk))}")
        if set(op) | set(lk) != set(mods):
            c.err(f"gate: open+locked ≠ 전체 모듈 (빠짐 {sorted(set(mods) - set(op) - set(lk))})")
        if gate.get("unlock_rule") != "앞 모듈 done 이슈":
            c.err("gate.unlock_rule 은 '앞 모듈 done 이슈'")
        ftw = rm.get("first_two_weeks", [])
        if op[:len(ftw)] != ftw:
            c.err("gate.open 은 first_two_weeks 순서로 시작해야 함 (H2 → R1 → D1 …)")
    # srs
    srs = S.get("srs")
    if srs is not None:
        iv = srs.get("intervals")
        if iv != [1, 3, 7, 21]:
            c.err("srs.json: intervals 는 [1, 3, 7, 21]")
        for k in ("rules", "progress_store"):
            if k not in srs:
                c.err(f"srs.json: '{k}' 없음")
    if S.get("aptitude"):
        check_aptitude(S["aptitude"], c)
    return c


# ───────────────────────── 빌드 ─────────────────────────
def _legacy_quiz(q: dict) -> dict:
    out = dict(q)
    if "choices" in q:
        out.setdefault("t", "상황" if q.get("kind") == "situation" else "지식")
        out.setdefault("a", str(q["choices"][q["answer"]]))
    return out


def _legacy_module(m: dict) -> dict:
    """v3 모듈 → Index.html 이 읽는 구형 키를 덧붙인다 (원본은 손대지 않음)."""
    o = dict(m)
    if m.get("schema", 2) != 3:
        return o
    o["hours"] = round(m["est_min"] / 60, 2)
    mh = m["market_hook"]
    o["today"] = {"keys": list(mh.get("keys", [])), "text": f"[{mh['tab']}] {mh['read']}"}
    o["mistakes"] = list(m["pitfalls"])
    o["quiz"] = [_legacy_quiz(q) for q in m["quiz"]]
    o["formulas"] = [{**f, "f": f["f"], "note": " · ".join(x for x in (f.get("note", ""), f"예: {f['example']}") if x)} for f in m["formulas"]]
    return o


def build(S: dict) -> dict:
    idx = S["index"]
    tracks = []
    hours: dict[str, float] = {}
    gate = idx.get("gate") or {}
    open_ids = set(gate.get("open", []))
    for t in S["tracks"]:
        tt = {k: v for k, v in t.items() if k != "modules"}
        tt["modules"] = [_legacy_module(m) for m in t["modules"]]
        for m in tt["modules"]:
            hours[m["id"]] = float(m["hours"])
            if gate:   # 2주 게이트 플래그 (Index.html 은 무시해도 됨)
                m["locked"] = m["id"] not in open_ids
                m["open_until"] = None if m["locked"] else gate.get("open_until")
                if m["locked"]:
                    m["unlock_rule"] = gate.get("unlock_rule", "앞 모듈 done 이슈")
        tracks.append(tt)
    rm = json.loads(json.dumps(idx["roadmap"], ensure_ascii=False))
    for s in rm.get("steps", []):
        s["hours"] = round(sum(hours.get(i, 0) for i in s["ids"]), 1)
    rm["total_hours"] = round(sum(hours.values()), 1)
    rm["total_modules"] = len(hours)
    out = {"version": idx["version"], "updated": idx["updated"], "title": idx["title"], "intro": idx["intro"],
           "roadmap": rm, "tesat": idx["tesat"], "tracks": tracks, "aptitude": S["aptitude"],
           "gate": idx.get("gate"), "schema": "v3", "built_from": "content/study/*.json (scripts/study_content_check.py --build)"}
    if S.get("srs"):
        out["srs"] = {"intervals": S["srs"]["intervals"], "note": S["srs"].get("note", "")}
    return out


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, indent=1) + "\n"


def split_legacy() -> None:
    d = json.loads(OUT.read_text(encoding="utf-8"))
    SRC.mkdir(parents=True, exist_ok=True)
    order = [t["id"] for t in d["tracks"]]
    idx = {k: d[k] for k in ("version", "updated", "title", "intro", "roadmap", "tesat")}
    idx["track_order"] = order
    (SRC / "index.json").write_text(dumps(idx), encoding="utf-8")
    (SRC / "aptitude.json").write_text(dumps(d["aptitude"]), encoding="utf-8")
    for t in d["tracks"]:
        (SRC / f"track_{t['id']}.json").write_text(dumps(t), encoding="utf-8")
    print(f"split: {len(order)} tracks → {SRC}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--split", action="store_true")
    a = ap.parse_args()
    if a.split:
        split_legacy()
        return 0
    S = load_sources()
    c = check_all(S)
    for w in c.warnings:
        print("WARN", w)
    for e in c.errors:
        print("FAIL", e)
    if c.errors:
        print(f"{len(c.errors)} errors")
        return 1
    built = dumps(build(S))
    if a.build:
        OUT.write_text(built, encoding="utf-8")
        print(f"built {OUT.relative_to(ROOT)} ({len(built):,} bytes)")
    else:
        cur = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if cur != built:
            print("FAIL content/study.json 이 원본과 다름 — python scripts/study_content_check.py --build 실행")
            return 1
    n = sum(len(t["modules"]) for t in S["tracks"])
    print(f"ok: {n} modules, {len(c.warnings)} warnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
