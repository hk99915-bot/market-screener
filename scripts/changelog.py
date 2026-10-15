"""변경 이력: 이 저장소(market-screener)의 git log → reports/changelog.json + reports/ops/daily/YYYY-MM-DD.md 작업내역 보고.

  python scripts/changelog.py              # 전체 이력(처음부터) 다시 생성, 일일 보고는 바뀐 날만 다시 씀
  python scripts/changelog.py --days 3     # 일일 보고는 최근 3일만

- 날짜는 KST 기준.
- 봇 자동 커밋(`briefing: dashboard 2026-…`, `live: …`, `report: KR …` 등 '접두어 + 날짜/시각' 꼴)은 개수만 세고 '자동 갱신 N회'로 접는다.
- 영역은 바뀐 파일 경로로 추정 (화면·엔진·워크플로·운영·콘텐츠·도구·문서·데이터).
- 이 저장소의 git log 만 읽는다. private 저장소 이력은 절대 넣지 않는다.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "changelog.json"
DAILY = ROOT / "reports" / "ops" / "daily"
BOARD = "ops/board.json"
KST = timezone(timedelta(hours=9))

AREAS = [  # (키, 표시 이름, 경로 패턴) — 위에서부터 우선
    ("web", "화면", ["apps-script/*", "index.html", "scripts/build_pages.py"]),
    ("workflow", "워크플로", [".github/workflows/*"]),
    ("engine", "엔진", ["screener/*"]),
    ("ops", "운영", ["ops/*", "scripts/changelog.py", "scripts/check_functions.py", "scripts/board.py",
                     "scripts/lock.py", "scripts/ops_runs.py", "reports/ops/*", "reports/changelog.json"]),
    ("content", "콘텐츠", ["content/*"]),
    ("tools", "도구", ["scripts/*", "tests/*", "requirements.txt", ".gitignore"]),
    ("docs", "문서", ["README.md", "notes/*", "*.md"]),
    ("data", "데이터", ["reports/*", "data/*", "universe/*"]),
]
AREA_LABEL = {k: n for k, n, _ in AREAS} | {"etc": "기타"}

# 메시지 접두어 → 한국어 주제
TOPIC = {
    "bonds": "채권", "lab": "전략 연구소", "study": "스터디", "calendar": "캘린더", "committee": "운용회의",
    "probe": "데이터 점검", "diag": "진단", "briefing": "브리핑", "screener": "스크리너", "gitignore": "설정",
    "my": "MY", "home": "HOME", "life": "LIFE", "live loop": "실시간 루프", "close_kr": "장 마감", "lock": "잠금",
    "unlock": "잠금 해제", "ops": "운영", "web": "웹", "macro series": "매크로 시계열", "indicators": "경제지표",
    "stock detail": "종목 상세", "excel skin": "엑셀 스킨", "scorecard": "성적표", "kr prices": "KR 시세",
    "momentum": "모멘텀", "pb call": "PB 콜", "exit duel": "청산 대결", "telegram": "텔레그램", "schedule": "예약",
    "backup scheduler (apps script)": "백업 예약기", "tghtml": "텔레그램 HTML", "us committee": "미장 운용회의",
}
AUTO = re.compile(r"^([A-Za-z_]+):?\s+(?:([A-Za-z_]+)\s+)?\d{4}-\d{2}-\d{2}(?:T[\d:]+)?\s*$")
BOT_AUTHORS = {"screener-bot", "github-actions[bot]"}
AGENT_AUTHORS = {"Claude"}
# 혹시 모를 금액 표기는 가린다 (공개 저장소)
MONEY = re.compile(r"\d[\d,.]*\s*(?:만원|억원|천원|원|만|억)(?![가-힣])")


def git(*a: str) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def area_of(path: str) -> str:
    for k, _, pats in AREAS:
        if any(fnmatch.fnmatch(path, p) for p in pats):
            return k
    return "etc"


def redact(s: str) -> str:
    return MONEY.sub("[금액]", s)


def summarize(subj: str) -> str:
    s = redact(subj.strip())
    m = re.match(r"^([^:]{1,40}):\s*(.+)$", s)
    if m:
        head, rest = m.group(1).strip(), m.group(2).strip()
        ko = TOPIC.get(head.lower())
        if ko:
            s = f"{ko} — {rest}"
    return s if len(s) <= 140 else s[:137] + "…"


def read_log() -> list[dict]:
    raw = git("log", "--reverse", "--no-merges", "--format=\x1e%H\x1f%ct\x1f%an\x1f%s", "--name-only")
    out = []
    for chunk in raw.split("\x1e"):
        if not chunk.strip():
            continue
        head, *files = chunk.strip("\n").split("\n")
        sha, ct, an, subj = head.split("\x1f", 3)
        files = [f for f in files if f.strip()]
        out.append({"sha": sha, "ts": int(ct), "author": an, "subject": subj, "files": files})
    return out


def load_board_at(rev: str | None) -> dict:
    if rev is None:
        p = ROOT / BOARD
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"tasks": []}
    try:
        return json.loads(git("show", f"{rev}:{BOARD}"))
    except Exception:
        return {"tasks": []}


def board_rev_before(when: datetime) -> str | None:
    r = git("rev-list", "-1", f"--before={when.isoformat()}", "HEAD", "--", BOARD).strip()
    return r or None


SHARED = ["apps-script/Index.html", "apps-script/Code.gs", "scripts/build_pages.py", "index.html",
          "screener/committee.py", "screener/main.py", ".github/workflows/*"]


def tasks_for(files: list[str], subject: str, day: str, tasks: list[dict]) -> list[str]:
    """커밋 → 작업 연결. 공유 파일(Index.html 등)은 모두가 고치므로 근거로 쓰지 않고,
    작업 고유 파일이나 메시지 속 `[작업id]` 로만 연결. 작업 시작일 전 커밋은 제외."""
    own = [f for f in files if not any(fnmatch.fnmatch(f, s) for s in SHARED)]
    hit = []
    for t in tasks:
        if f"[{t['id']}]" in subject:
            hit.append(t["id"]); continue
        if not t.get("started") or day < t["started"]:
            continue   # 시작 전 작업은 파일 근거로 연결하지 않음
        pats = [p for p in t.get("files") or [] if not any(fnmatch.fnmatch(p, s) for s in SHARED)]
        if any(fnmatch.fnmatch(f, p) for f in own for p in pats):
            hit.append(t["id"])
    return hit


def build(commits: list[dict], board: dict) -> dict:
    days: dict[str, dict] = {}
    tasks = board.get("tasks", [])
    for c in commits:
        dt = datetime.fromtimestamp(c["ts"], KST)
        d = dt.strftime("%Y-%m-%d")
        day = days.setdefault(d, {"date": d, "total": 0, "work": 0, "auto": 0, "areas": defaultdict(list),
                                  "auto_kinds": Counter(), "tasks": Counter(), "kinds": Counter()})
        day["total"] += 1
        m = AUTO.match(c["subject"])
        is_bot = c["author"] in BOT_AUTHORS
        if m and (is_bot or not c["files"] or all(area_of(f) in ("data", "ops") for f in c["files"])):
            day["auto"] += 1
            day["auto_kinds"][m.group(1).lower()] += 1
            continue
        kind = "bot" if is_bot else "agent" if c["author"] in AGENT_AUTHORS else "human"
        areas = sorted({area_of(f) for f in c["files"]}, key=lambda k: [a[0] for a in AREAS].index(k) if k in AREA_LABEL and k != "etc" else 99)
        primary = areas[0] if areas else "etc"
        if re.match(r"^(un)?lock:", c["subject"]):
            primary = "ops"
        tids = tasks_for(c["files"], c["subject"], d, tasks)
        for t in tids:
            day["tasks"][t] += 1
        day["work"] += 1
        day["kinds"][kind] += 1
        day["areas"][primary].append({
            "sha": c["sha"][:8], "time": dt.strftime("%H:%M"), "kind": kind,
            "summary": summarize(c["subject"]), "areas": areas, "files": len(c["files"]), "tasks": tids,
        })
    order = [a[0] for a in AREAS] + ["etc"]
    out_days = []
    for d in sorted(days, reverse=True):
        x = days[d]
        ars = [{"area": k, "label": AREA_LABEL[k], "n": len(x["areas"][k]), "items": sorted(x["areas"][k], key=lambda i: i["time"], reverse=True)}
               for k in order if x["areas"].get(k)]
        out_days.append({
            "date": d, "total": x["total"], "work": x["work"], "auto": x["auto"],
            "by": dict(x["kinds"]),
            "areas": ars,
            "auto_updates": {"n": x["auto"], "label": f"자동 갱신 {x['auto']}회", "kinds": dict(x["auto_kinds"].most_common())},
            "tasks": dict(x["tasks"].most_common()),
        })
    return {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "repo": "hk99915-bot/market-screener",
        "note": "이 저장소 git log 만으로 생성 (scripts/changelog.py). 봇 자동 커밋은 '자동 갱신 N회'로 접음.",
        "areas": AREA_LABEL,
        "first": out_days[-1]["date"] if out_days else None,
        "days": out_days,
    }


def board_moves(d: str) -> tuple[list[str], dict, dict]:
    start = datetime.fromisoformat(d + "T00:00:00+09:00")
    end = start + timedelta(days=1)
    r0 = board_rev_before(start)
    b0 = load_board_at(r0) if r0 else {"tasks": []}
    is_today = d == datetime.now(KST).strftime("%Y-%m-%d")
    r1 = board_rev_before(end)
    b1 = load_board_at(None) if is_today else (load_board_at(r1) if r1 else {"tasks": []})
    t0 = {t["id"]: t for t in b0.get("tasks", [])}
    t1 = {t["id"]: t for t in b1.get("tasks", [])}
    moves = []
    for tid, t in t1.items():
        if tid not in t0:
            moves.append(f"`{tid}` {t['title']} — 신규 등록 ({t['status']}, {t['priority']}, {t['owner']})")
        elif t0[tid].get("status") != t.get("status"):
            moves.append(f"`{tid}` {t['title']} — {t0[tid].get('status')} → **{t['status']}**")
    for tid in t0:
        if tid not in t1:
            moves.append(f"`{tid}` {t0[tid]['title']} — 보드에서 삭제")
    return moves, b1, t1


def daily_md(day: dict, today: str) -> str:
    d = day["date"]
    moves, board, tmap = board_moves(d)
    L = [f"# 작업내역 보고 — {d}", "",
         "> 자동 생성 (`scripts/changelog.py`, 이 저장소 git log + `ops/board.json`). 개인 데이터 없음.", "",
         "## 요약", "",
         f"- 커밋 {day['total']}건 = 작업 {day['work']}건 + {day['auto_updates']['label']}",
         "- 영역: " + (" · ".join(f"{a['label']} {a['n']}" for a in day["areas"]) or "—"),
         ""]
    if day["by"]:
        L.insert(-1, "- 작성: " + " · ".join(f"{ {'agent': '에이전트', 'human': '사람', 'bot': '봇 계정'}[k]} {v}" for k, v in day["by"].items()))
    L += ["## 무엇이 바뀌었나", ""]
    for a in day["areas"]:
        L.append(f"### {a['label']} ({a['n']})")
        L.append("")
        for i in a["items"]:
            tg = f" `[{', '.join(i['tasks'])}]`" if i["tasks"] else ""
            L.append(f"- {i['time']} {i['summary']}{tg} <sub>{i['sha']}</sub>")
        L.append("")
    if day["auto_updates"]["n"]:
        L += [f"### {day['auto_updates']['label']}", "",
              "- " + " · ".join(f"{k} {v}" for k, v in day["auto_updates"]["kinds"].items()), ""]
    L += ["## 작업 보드 변동", ""]
    L += [f"- {m}" for m in moves] or ["- 상태 변화 없음"]
    if day["tasks"]:
        L += ["", "작업별 커밋: " + " · ".join(f"`{k}` {v}" for k, v in day["tasks"].items())]
    L += ["", "## 열린 이슈", ""]
    iss = []
    for t in board.get("tasks", []):
        if t["status"] == "완료":
            continue
        if t.get("due") and t["due"] < d:
            iss.append(f"기한 지남: `{t['id']}` {t['title']} ({t['due']}, {t['owner']})")
        elif t.get("due") and t["due"] <= (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%d"):
            iss.append(f"기한 임박: `{t['id']}` {t['title']} ({t['due']}, {t['owner']}, {t['status']})")
        if t["status"] == "보류":
            iss.append(f"보류: `{t['id']}` {t['title']} — {t.get('notes','')}")
        for dep in t.get("depends_on") or []:
            if dep in tmap and tmap[dep]["status"] != "완료" and t["status"] in ("진행", "검수"):
                iss.append(f"선행 미완: `{t['id']}` ← `{dep}` ({tmap[dep]['status']})")
    if d == today:
        try:
            h = json.loads((ROOT / "reports" / "health.json").read_text(encoding="utf-8"))
            iss += [f"자가점검: {x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)}" for x in h.get("issues", [])]
        except Exception:
            pass
        try:
            r = json.loads((ROOT / "reports" / "ops" / "runs.json").read_text(encoding="utf-8"))
            for w in r.get("workflows", []):
                if w.get("failure"):
                    iss.append(f"워크플로 실패: {w['name']} {w['failure']}회 / {w['runs']}회 (최근 24h)")
                if (w.get("max_delay_min") or 0) > 60:
                    iss.append(f"예약 지연: {w['name']} 최대 {w['max_delay_min']}분")
        except Exception:
            pass
        try:
            lk = json.loads((ROOT / "ops" / "locks.json").read_text(encoding="utf-8")).get("locks", [])
            for x in lk:
                iss.append(f"잠금 유지 중: `{x['file']}` — {x['owner']} ({x.get('task')}, {x.get('since')})")
        except Exception:
            pass
    L += [f"- {x}" for x in iss] or ["- 없음"]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="일일 보고를 최근 N일만 (0 = 전체 백필)")
    a = ap.parse_args()
    commits = read_log()
    board = load_board_at(None)
    cl = build(commits, board)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cl, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    DAILY.mkdir(parents=True, exist_ok=True)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    days = cl["days"][: a.days] if a.days else cl["days"]
    n = 0
    for day in days:
        p = DAILY / f"{day['date']}.md"
        md = daily_md(day, today)
        if not p.exists() or p.read_text(encoding="utf-8") != md:
            p.write_text(md, encoding="utf-8"); n += 1
    idx = sorted((p.stem for p in DAILY.glob("*.md")), reverse=True)
    (DAILY / "_index.json").write_text(json.dumps(idx, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"changelog.json: {len(commits)}커밋 · {len(cl['days'])}일 · 일일 보고 {n}개 갱신")


if __name__ == "__main__":
    main()
