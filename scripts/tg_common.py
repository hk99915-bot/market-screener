#!/usr/bin/env python3
"""공개 텔레그램 채널 수집 공용 모듈 — 받기·파싱·상태 저장 (채널 무관, 표준 라이브러리만).

- 로그인·토큰·계정 세션 없이 공개 웹 미리보기 https://t.me/s/<채널> 만 읽는다. 이전 글은 ?before=<id>.
- 원본은 이 파일(market-screener scripts/tg_common.py). 비공개 저장소에는 같은 내용의 복사본을 둔다
  (그쪽 Actions 는 이 저장소를 체크아웃하지 않음) — 고칠 땐 여기 먼저, 복사본은 그대로 덮어쓴다.
- 쓰는 곳: scripts/tg_feed.py(원자재 채널 → reports/feeds/), 비공개 저장소 채용 필터.

글 dict: {channel, post_id, posted(UTC ISO), lines:[(text, link|None)], links:[...], first_line,
          images:[사진 URL(telesco.pe)], reply_to: {channel, id}|None, fwd_from: {channel, id}|{"channel": ""}|None}
  전달 원본이 개인 계정이면 이름은 남기지 않는다(channel "" = 개인·비공개 원본).
본문 전체를 저장하는 함수는 두지 않는다 — 소비자는 first_line·줄 단위 제목·링크만 남긴다.
"""
from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (X11; Linux x86_64) tg_common/1.0"

POST_RE = re.compile(r'data-post="([^"/]+)/(\d+)"')
# 답장 미리보기(js-message_reply_text)는 남의 글이라 제외 — 본 글은 js-message_text 하나뿐
TEXT_RE = re.compile(r'<div class="tgme_widget_message_text js-message_text"[^>]*>(.*?)</div>', re.S)
TIME_RE = re.compile(r'<time datetime="([^"]+)"')
HREF_RE = re.compile(r'<a\s[^>]*href="([^"]+)"')
PREVIEW_RE = re.compile(r'<a class="tgme_widget_message_link_preview"[^>]*href="([^"]+)"')
PHOTO_RE = re.compile(r'<a class="tgme_widget_message_photo_wrap[^"]*"[^>]*background-image:url\(\'(https://[^\']+)\'\)')
REPLY_RE = re.compile(r'<a class="tgme_widget_message_reply[^"]*" href="https://t\.me/([^/"]+)/(\d+)"')
FWD_RE = re.compile(r'<div class="tgme_widget_message_forwarded_from[^"]*">(.*?)</div>', re.S)
FWD_CH_RE = re.compile(r'href="https://t\.me/([A-Za-z0-9_]{4,})(?:/(\d+))?"')


def unescape(s: str) -> str:
    """html 이스케이프를 끝까지 푼다(채널에 따라 &amp;amp; 이중 이스케이프)."""
    prev = None
    while prev != s:
        prev, s = s, html.unescape(s)
    return s


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", s))).strip()


def parse_page(page: str) -> list[dict]:
    """미리보기 HTML → 글 목록(id 오름차순)."""
    posts = []
    starts = [(m.start(), m.group(1), int(m.group(2))) for m in POST_RE.finditer(page)]
    for i, (pos, ch, pid) in enumerate(starts):
        chunk = page[pos: starts[i + 1][0] if i + 1 < len(starts) else len(page)]
        tm = TIME_RE.search(chunk)
        tx = TEXT_RE.search(chunk)
        lines: list[tuple[str, str | None]] = []
        links: list[str] = []
        if tx:
            for raw in re.split(r"<br\s*/?>", tx.group(1)):
                text = strip_tags(raw)
                hrefs = [unescape(h) for h in HREF_RE.findall(raw)]
                links += hrefs
                if text:
                    lines.append((text, hrefs[0] if hrefs else None))
        pv = PREVIEW_RE.search(chunk)
        if pv and unescape(pv.group(1)) not in links:
            links.append(unescape(pv.group(1)))
        rp = REPLY_RE.search(chunk)
        fw = FWD_RE.search(chunk)
        fwd = None
        if fw:
            fc = FWD_CH_RE.search(fw.group(1))
            fwd = {"channel": fc.group(1), "id": int(fc.group(2)) if fc.group(2) else None} if fc else {"channel": ""}
        posts.append({"channel": ch, "post_id": pid, "posted": tm.group(1) if tm else "",
                      "lines": lines, "links": links, "first_line": lines[0][0] if lines else "",
                      "images": [unescape(u) for u in PHOTO_RE.findall(chunk)],
                      "reply_to": {"channel": rp.group(1), "id": int(rp.group(2))} if rp else None,
                      "fwd_from": fwd})
    return sorted(posts, key=lambda p: p["post_id"])


def fetch(channel: str, before: int | None = None, timeout: int = 30) -> str:
    url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 200:
            raise RuntimeError(f"{url} → HTTP {r.status}")
        return r.read().decode("utf-8", "replace")


OG_RE = re.compile(r'<meta\s+[^>]*(?:property|name)="og:(title|site_name)"[^>]*>', re.I)
CONTENT_RE = re.compile(r'content="([^"]*)"', re.I)


def fetch_og(url: str, timeout: int = 5, limit: int = 300_000) -> dict:
    """링크 페이지의 og:title·og:site_name 만(본문 미저장). 실패하면 빈 값."""
    out = {"title": "", "site": ""}
    if not url.startswith(("http://", "https://")):
        return out
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko,en;q=0.8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if "html" not in (r.headers.get("Content-Type") or "html"):
                return out
            head = r.read(limit).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 — 네트워크·인증서·차단 모두 '비워 둠'
        return out
    for m in OG_RE.finditer(head):
        c = CONTENT_RE.search(m.group(0))
        key = "title" if m.group(1).lower() == "title" else "site"
        if c and not out[key]:
            out[key] = strip_tags(c.group(1))[:200]
    return out


def collect(channel: str, last_id: int = 0, pages: int = 3, fetcher=fetch) -> list[dict]:
    """last_id 보다 큰 글만(id 오름차순). 첫 페이지가 last_id 까지 못 닿으면 ?before 로 최대 pages 장."""
    got: dict[int, dict] = {}
    before = None
    for _ in range(max(1, pages)):
        posts = [p for p in parse_page(fetcher(channel, before)) if p["channel"].lower() == channel.lower()]
        if not posts:
            break
        for p in posts:
            if p["post_id"] > last_id:
                got[p["post_id"]] = p
        low = posts[0]["post_id"]
        if low <= last_id + 1 or low <= 1 or low == before:
            break
        before = low
    return [got[k] for k in sorted(got)]


def kst(posted: str) -> datetime | None:
    try:
        return datetime.fromisoformat(posted).astimezone(KST)
    except (TypeError, ValueError):
        return None


def load_state(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def last_id(state: dict, channel: str) -> int:
    return int((state.get(channel) or {}).get("last_id", 0))


def update_state(state: dict, channel: str, posts: list[dict], now: datetime | None = None) -> dict:
    """메모리 상태만 갱신(새 글 없으면 그대로). 파일 저장 없이 산출물 안에 상태를 넣는 소비자용."""
    if not posts:
        return state
    now = now or datetime.now(KST)
    state[channel] = {"last_id": max(last_id(state, channel), max(p["post_id"] for p in posts)),
                      "last_posted": posts[-1]["posted"], "updated": now.strftime("%Y-%m-%dT%H:%M+09:00")}
    return state


def save_state(path: Path, state: dict, channel: str, posts: list[dict], now: datetime | None = None) -> dict:
    """새 글이 있을 때만 갱신·저장(없으면 파일 그대로 — 변경 없으면 커밋도 없게)."""
    if not posts:
        return state
    update_state(state, channel, posts, now)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return state
