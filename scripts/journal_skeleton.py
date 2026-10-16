"""일일 저널 뼈대 — 공개 데이터만으로 그날의 사실 줄을 미리 채운 Markdown 을 만든다.

읽는 것(전부 공개 reports/*):
  reports/events.json                  그날 이벤트(서킷·사이드카·연준 의장 등)
  reports/decisions.json               그날 대결 항목(나/나🔥/PB/PB🔥/규칙 픽·청산 코드) + 주문표(kind=ticket)
  reports/archive/committee/_index.json + 그날 회의 파일(세션·신호등·판정·Δ 줄)
  reports/rebound.json                 14:25 반등일 판정 (있으면)
  reports/live.json → reports/daily_hist/_index.json   코스피·코스닥 종가·등락
  reports/studies/*.json               그날 git 커밋에서 바뀐 등급(grade)
쓰지 않는 것: 보유·수량·금액. 모의 100만 단위(notional)도 출력하지 않는다.
감정·대응 칸은 전부 `…` 로 비워 두고, 비공개 저널에서 사람이 채운다.

  python scripts/journal_skeleton.py                       # 오늘(KST) → stdout
  python scripts/journal_skeleton.py --date 2026-10-16     # 특정 날짜
  python scripts/journal_skeleton.py --date D --out PATH   # 파일로 (이미 있으면 덮어쓰지 않고 diff 제안)
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo("Asia/Seoul")
WEEKDAY = "월화수목금토일"
EXIT_KO = {"next_open": "익일 시가", "next_close": "익일 종가", "same_close": "당일 종가", "d5_close": "5거래일 종가",
           "trail": "추세 끌고가기"}
ENTRY_KO = {"close": "종가", "open": "시가"}
SLOTS = ["나", "나🔥", "PB", "PB🔥", "규칙"]
TIMELINE_HEADER = "| 시각 | 마음 | 대응 | 결과 |\n|---|---|---|---|"
AMOUNT_KEYS = ("notional", "amount", "qty", "pnl", "holdings", "quantity")


# ── 읽기 ────────────────────────────────────────────────────────────────────
def _load(rep: Path, rel: str, default):
    try:
        return json.loads((rep / rel).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _pct(x) -> str:
    try:
        return f"{float(x) * 100:+.2f}%"
    except (TypeError, ValueError):
        return "?"


def _num(x) -> str:
    try:
        return f"{float(x):,.2f}"
    except (TypeError, ValueError):
        return "?"


def day_events(rep: Path, d: str) -> list[dict]:
    ev = (_load(rep, "events.json", {}) or {}).get("events") or []
    rows = [e for e in ev if e.get("date") == d]
    return sorted(rows, key=lambda e: e.get("time") or "")


def day_decisions(rep: Path, d: str) -> tuple[list[dict], list[dict]]:
    items = (_load(rep, "decisions.json", {}) or {}).get("items") or []
    today = [it for it in items if it.get("date") == d]
    duels = [it for it in today if it.get("kind") != "ticket"]
    tickets = [it for it in today if it.get("kind") == "ticket"]
    return duels, tickets


def day_committee(rep: Path, d: str) -> list[dict]:
    """그날 회의 — _index.json 의 순서(최신 먼저)를 시각 오름차순으로 뒤집어 돌려준다."""
    base = rep / "archive" / "committee"
    idx = (_load(rep, "archive/committee/_index.json", {}) or {}).get("days") or []
    out = []
    for row in idx:
        if row.get("date") != d:
            continue
        c = _load(base, f"{row.get('id')}.json", None) or {}
        bl = c.get("bottom_line") or {}
        lines = bl.get("lines") or []
        delta = next((ln for ln in lines if "대비" in ln and "직전" in ln), None)
        out.append({"session": row.get("session") or c.get("session") or "?", "asof": row.get("asof") or c.get("asof") or "",
                    "label": bl.get("label") or "", "stance": bl.get("stance") or (c.get("stance") or {}).get("stance") or "",
                    "verdict": c.get("verdict") or row.get("headline") or "", "delta": delta})
    return sorted(out, key=lambda r: r["asof"])


def day_rebound(rep: Path, d: str) -> dict | None:
    days = (_load(rep, "rebound.json", {}) or {}).get("days") or []
    return next((x for x in days if x.get("date") == d), None)


def day_close(rep: Path, d: str) -> dict[str, dict]:
    """코스피·코스닥 종가 — live.json 이 그날 CLOSE 면 그걸, 아니면 daily_hist 헤드라인 요약."""
    live = _load(rep, "live.json", {}) or {}
    upd = str(live.get("updated_at") or "")
    out: dict[str, dict] = {}
    if upd and upd[:5] == d[5:]:          # "10-16 18:42 KST" ↔ "2026-10-16"
        for it in live.get("items") or []:
            if it.get("key") in ("KOSPI", "KOSDAQ") and it.get("status") == "CLOSE":
                out[it["key"]] = {"last": it.get("last"), "chg": it.get("chg")}
    if out:
        return out
    for row in (_load(rep, "daily_hist/_index.json", {}) or {}).get("days") or []:
        if row.get("date") == d:
            m = re.search(r"KOSPI\s*([+-]?\d+(?:\.\d+)?)%", row.get("headline") or "")
            if m:
                out["KOSPI"] = {"last": None, "chg": float(m.group(1)) / 100, "note": "일일 요약"}
    return out


def _grades(obj, path="", acc=None) -> dict[str, str]:
    """JSON 안의 모든 *grade 키를 경로→값으로 평탄화 (문서용 *_doc 제외)."""
    acc = {} if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k)
            if key.endswith("_doc"):
                continue
            if "grade" in key.lower() and isinstance(v, (str, int, float)):
                acc[f"{path}{key}"] = str(v)
            elif "grade" in key.lower() and isinstance(v, dict) and all(not isinstance(x, (dict, list)) for x in v.values()):
                for kk, vv in v.items():
                    acc[f"{path}{key}.{kk}"] = str(vv)
            elif isinstance(v, (dict, list)):
                _grades(v, f"{path}{key}.", acc)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _grades(v, f"{path}{i}.", acc)
    return acc


def _git(root: Path, *a: str) -> str:
    try:
        return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        return ""


def study_grade_changes(root: Path, d: str) -> list[str]:
    """그날 커밋으로 reports/studies/*.json 의 grade 가 바뀐 항목 — 'file: key old→new'."""
    nxt = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
    shas = _git(root, "log", "--format=%H", f"--since={d}T00:00:00+09:00", f"--until={nxt}T00:00:00+09:00", "--", "reports/studies").split()
    if not shas:
        return []
    last, first = shas[0], shas[-1]
    files = sorted(set(_git(root, "diff", "--name-only", f"{first}^", last, "--", "reports/studies").split()))
    out = []
    for f in files:
        if not f.endswith(".json"):
            continue
        before = _git(root, "show", f"{first}^:{f}")
        after = _git(root, "show", f"{last}:{f}")
        try:
            g0 = _grades(json.loads(before)) if before else {}
            g1 = _grades(json.loads(after)) if after else {}
        except json.JSONDecodeError:
            continue
        name = Path(f).stem
        changed = {k: (g0.get(k), g1.get(k)) for k in sorted(set(g0) | set(g1)) if g0.get(k) != g1.get(k)}
        if not changed:
            continue
        top = next((k for k in ("grade", "lens_grade") if k in changed), None)
        head = f"{name}: 종합 {changed[top][0] or '—'} → {changed[top][1] or '—'}" if top else f"{name}:"
        from collections import Counter
        dist = Counter(v for _, v in changed.values() if v)
        tail = " · ".join(f"{g}×{n}" for g, n in sorted(dist.items(), key=lambda x: (-x[1], x[0])))
        out.append(f"{head} {'신규 ' if not g0 else '변경 '}{len(changed)}건 ({tail})")
    return out


# ── 쓰기 ────────────────────────────────────────────────────────────────────
def _pick_line(slot: str, p: dict) -> str | None:
    if not p:
        return None
    if p.get("cash"):
        return f"{slot}: 현금"
    if p.get("pending"):
        return f"{slot}: 미제출"
    nm = p.get("name") or p.get("ticker") or "?"
    ent = ENTRY_KO.get(p.get("entry"), p.get("entry") or "")
    ex = EXIT_KO.get(p.get("exit"), p.get("exit") or "")
    s = f"{slot}: {nm}"
    if ent or ex:
        s += f" ({ent} 진입 → {ex})"
    if p.get("submitted"):
        s += f" · 제출 {p['submitted']}"
    elif p.get("at"):
        s += f" · {p['at']}"
    return s


def _close_line(close: dict[str, dict]) -> str:
    if not close:
        return "- 종가: … (live.json 미확정)"
    parts = []
    for k, ko in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        c = close.get(k)
        if not c:
            continue
        parts.append(f"{ko} {_num(c['last'])} ({_pct(c['chg'])})" if c.get("last") else f"{ko} {_pct(c['chg'])}")
    return "- 종가: " + " · ".join(parts) if parts else "- 종가: …"


def build(d: str, rep: Path, root: Path | None = None) -> str:
    root = root or rep.parent
    dt = date.fromisoformat(d)
    events = day_events(rep, d)
    duels, tickets = day_decisions(rep, d)
    comm = day_committee(rep, d)
    reb = day_rebound(rep, d)
    close = day_close(rep, d)
    grades = study_grade_changes(root, d)

    L = [f"# 매매 일기 — {d}({WEEKDAY[dt.weekday()]})" + (" · 반등일" if reb and reb.get("ok") else ""), "",
         "> 공개 데이터로 미리 채운 뼈대. `…` 칸은 장을 보며 느낀 것·대응을 사람이 채운다. 숫자는 그 시각 기준.", "",
         "## 오늘의 장"]
    L.append(_close_line(close))
    if reb:
        L.append(f"- 14:25 반등일 판정: {'✅' if reb.get('ok') else '❌'} 코스피 {_num(reb.get('last'))} ({_pct(reb.get('chg'))}) · 기준 {_num(reb.get('thr'))}")
    if events:
        L.append("- 이벤트: " + " · ".join(f"{e.get('time', '')} {e.get('type', '')} — {e.get('title', '')}" for e in events))
    else:
        L.append("- 이벤트: 없음 (events.json)")
    if comm:
        for c in comm:
            L.append(f"- 회의 {c['session']}({c['asof'][-5:]}): {c['label']} · {c['verdict']}")
            if c.get("delta"):
                L.append(f"  - Δ {c['delta']}")
    else:
        L.append("- 회의: 기록 없음")
    L += ["- 수급: …", "- 파생: …", ""]

    L.append("## 오늘의 대결")
    if not duels and not tickets:
        L.append("- 없음")
    for it in duels:
        L.append(f"- {it.get('title') or it.get('id')}" + (f" [{it['market']}]" if it.get("market") else ""))
        for slot in SLOTS:
            ln = _pick_line(slot, (it.get("picks") or {}).get(slot) or {})
            if ln:
                L.append(f"  - {ln}")
        r = it.get("result") or {}
        if r.get("winner"):
            L.append(f"  - 결과: 승자 {r['winner']}")
    for t in tickets:
        L.append(f"- 주문표 {t.get('name') or t.get('code')}: {t.get('verdict', '')} · 손익비 1:{t.get('rr', '?')} · 보유 {t.get('horizon_days', '?')}일")
    L.append("")

    L += ["## 마음의 타임라인", TIMELINE_HEADER]
    stamps = []
    for e in events:
        stamps.append((e.get("time") or "", f"이벤트: {e.get('type', '')}"))
    for it in duels:
        for slot in SLOTS:
            p = (it.get("picks") or {}).get(slot) or {}
            t = p.get("submitted") or p.get("at")
            if t and not p.get("cash"):
                stamps.append((t, f"{slot} 픽 제출 — {p.get('name') or p.get('ticker') or ''}"))
    for t in tickets:
        stamps.append((str(t.get("submitted") or ""), f"주문표 {t.get('name') or ''} {t.get('verdict', '')}"))
    if reb:
        stamps.append((reb.get("time") or "14:25", f"반등일 판정 {'✅' if reb.get('ok') else '❌'}"))
    for c in comm:
        stamps.append((c["asof"][-5:], f"회의 {c['session']} {c['label']}"))
    for t, what in sorted(stamps, key=lambda x: x[0]):
        L.append(f"| {t} | … | … | {what} |")
    L += ["| … | … | … | … |", ""]

    L += ["## 패턴 메모", "- …", ""]
    L += ["## 연구 등급 변경"]
    L += [f"- {g}" for g in grades] or ["- 없음"]
    L.append("")
    L += ["## 14:30 이후", "- [ ] 14:30 집행 여부 (규정대로 / 보류 — 이유)",
          "- [ ] 종가 확인: " + _close_line(close)[len("- 종가: "):],
          "- [ ] 오늘 한 줄 회고", ""]
    md = "\n".join(L)
    assert_no_amounts(md)
    return md


def assert_no_amounts(md: str) -> None:
    """공개 스크립트 출력에 보유·금액 키가 섞이면 실패 — 데이터 구조가 바뀌어도 금액이 새지 않게."""
    bad = [k for k in AMOUNT_KEYS if k in md]
    if bad or re.search(r"\d[\d,]{5,}\s*원", md):
        raise SystemExit(f"journal_skeleton: 금액·보유 흔적이 출력에 포함됨 — {bad or '원 단위 금액'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", default=datetime.now(KST).strftime("%Y-%m-%d"))
    ap.add_argument("--out", default=None, help="저장 경로 (이미 있으면 덮어쓰지 않고 diff 제안만 출력)")
    ap.add_argument("--reports", default=str(ROOT / "reports"))
    a = ap.parse_args(argv)
    rep = Path(a.reports)
    md = build(a.date, rep, ROOT)
    if not a.out:
        sys.stdout.write(md)
        return 0
    out = Path(a.out)
    if out.exists():
        old = out.read_text(encoding="utf-8").splitlines()
        diff = list(difflib.unified_diff(old, md.splitlines(), fromfile=str(out), tofile="skeleton(new)", lineterm="", n=1))
        sys.stdout.write(f"{out} 이미 있음 — 덮어쓰지 않음. 뼈대와의 차이 {len(diff)}줄 (참고용):\n" + "\n".join(diff[:200]) + "\n")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
