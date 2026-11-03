#!/usr/bin/env python3
"""금투협 공지사항(m_17) 수집 → reports/feeds/kofia_notice.json (11/3 겸이 지시, 데이터엔지니어).

  python3 scripts/kofia_notice.py [--pages 2] [--dry-run]

- 목록만 읽는다(번호·제목·작성일·조회수·첨부 수·seq·링크). 본문·첨부 파일은 받지 않는다.
- 시장 관련 공지만 태깅해 저장(시총비중·채권시장·규정제도·자격시험). 입찰·채용·인증신청 등은 저장 안 함(seen 에만 기록).
- 중복 방지: 산출물 안 `state.seen`(본 seq 전부, 최근 400개). 새 공지가 없으면 파일을 안 바꿔 커밋 없음.
- 자격시험 일정 공지(투자자산운용사 등)는 exam_schedule:true 플래그만 — 개인 D-day 연결은 비공개 저장소 몫.
- 용도: 애널 digest 입력(관찰). 펀드 편입 한도 관련 '시총비중' 공지는 숫자가 PDF 첨부에 있으니 링크로만 안내.
"""
from __future__ import annotations

import argparse
import html
import http.client
import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "feeds" / "kofia_notice.json"
BASE = "https://www.kofia.or.kr/brd/m_17/"
SEEN_KEEP = 400
NOTE = "관찰 입력 — 목록(제목·작성일·조회수·링크)만, 첨부·본문 미저장. 숫자는 링크 원문 확인 전 인용 금지."

ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
SEQ_RE = re.compile(r"view\.do\?seq=(\d+)")
FILE_RE = re.compile(r"down\.do\?[^\"']*file_seq=")

EXCLUDE = re.compile(r"입찰|용역|사업자 선정|업체 선정|외부감사인|채용|인증 신청|교육기관|공모|구독")
TAGS = [  # (태그, 정규식) — 순서대로 전부 검사, 여러 개 가능
    ("시총비중", re.compile(r"시가총액\s*비중")),
    ("채권시장", re.compile(r"채권시장|채권\s*시장|채권.{0,6}전망")),
    ("규정제도", re.compile(r"규정|제도|개정|세칙|지침|표준|가이드라인|시행|약관|공시")),
    ("자격시험", re.compile(r"자격시험|시험\s*일정|투자자산운용사|펀드투자권유|증권투자권유|파생상품투자권유|투자권유자문인력")),
]
EXAM_RE = re.compile(r"투자자산운용사")
EXAM_WHEN_RE = re.compile(r"시험|일정|접수|원서|계획")


def fetch(page: int) -> str:
    req = urllib.request.Request(f"{BASE}list.do?page={page}", headers={"User-Agent": "Mozilla/5.0"})
    last = b""
    for i in range(3):   # kofia_jobs.py(pb-private)와 같은 IncompleteRead 재시도 — 끝까지 끊기면 받은 만큼
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "replace")
        except http.client.IncompleteRead as e:
            last = e.partial or last
            time.sleep(2 * (i + 1))
    return last.decode("utf-8", "replace")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse(page_html: str) -> list[dict]:
    rows = []
    for tr in ROW_RE.findall(page_html):
        cells = CELL_RE.findall(tr)
        m = SEQ_RE.search(tr)
        if len(cells) < 4 or not m:
            continue
        texts = [_text(c) for c in cells]
        date_cell = next((t for t in texts if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t)), "")
        nums = [t for t in texts if re.fullmatch(r"[\d,]+", t)]
        title = next((t for t in texts[1:] if t and t != date_cell and not re.fullmatch(r"[\d,]+", t)), "")
        if not title or not date_cell:
            continue
        rows.append({"seq": int(m.group(1)), "no": int(nums[0].replace(",", "")) if nums else None, "title": title,
                     "date": date_cell, "views": int(nums[-1].replace(",", "")) if len(nums) > 1 else None,
                     "files": len(FILE_RE.findall(tr)), "link": f"{BASE}view.do?seq={m.group(1)}"})
    return rows


def classify(title: str) -> dict | None:
    """시장 관련이면 {tags, exam_schedule}, 아니면 None."""
    if EXCLUDE.search(title):
        return None
    tags = [t for t, rx in TAGS if rx.search(title)]
    if not tags:
        return None
    return {"tags": tags, "exam_schedule": bool(EXAM_RE.search(title) and EXAM_WHEN_RE.search(title))}


def load(path: Path = OUT) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"note": NOTE, "source": BASE + "list.do", "state": {"seen": []}, "items": []}


def merge(data: dict, rows: list[dict], now: datetime) -> tuple[dict, list[dict], int]:
    """새 seq 만 반영. 반환 (data, 새 시장공지, 새 전체 건수)."""
    seen = set(data["state"]["seen"])
    new_rows = [r for r in rows if r["seq"] not in seen]
    added = []
    for r in sorted(new_rows, key=lambda r: r["seq"]):
        seen.add(r["seq"])
        c = classify(r["title"])
        if c:
            item = {**r, **c, "collected": now.strftime("%Y-%m-%dT%H:%M+09:00")}
            data["items"].append(item)
            added.append(item)
    data["items"].sort(key=lambda r: r["seq"], reverse=True)
    data["state"]["seen"] = sorted(seen)[-SEEN_KEEP:]
    return data, added, len(new_rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    now = datetime.now(timezone(timedelta(hours=9)))
    rows = []
    for p in range(1, a.pages + 1):
        rows += parse(fetch(p))
    data = load()
    first = not data["state"]["seen"]
    data, added, n_new = merge(data, rows, now)
    dist: dict[str, int] = {}
    for it in added:
        for t in it["tags"]:
            dist[t] = dist.get(t, 0) + 1
    print(f"읽음 {len(rows)}건 · 신규 {n_new}건 · 시장 태그 {len(added)}건 {dist}"
          + (" · exam_schedule 있음" if any(i["exam_schedule"] for i in added) else " · 시험일정 공지 없음")
          + (" (첫 수집)" if first else ""))
    if n_new and not a.dry_run:
        data["updated"] = now.strftime("%Y-%m-%dT%H:%M+09:00")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
