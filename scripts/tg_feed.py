#!/usr/bin/env python3
"""공개 텔레그램 채널 → 관찰 피드 (11/1 PB: 원자재 애널 채널 + 셀사이드 1·개인 4).

  python3 scripts/tg_feed.py                 # ops/tg_feeds.json 의 채널 전부
  python3 scripts/tg_feed.py akacommodity    # 설정에 있는 채널 하나만  [--pages 2] [--keep 200] [--no-og]

- 받기·파싱·상태는 scripts/tg_common.py(공용, 로그인·토큰 없이 공개 웹 미리보기만).
- 채널 목록·type(sellside|individual)·보유 고지 = ops/tg_feeds.json 한 곳. 결과 = reports/feeds/<out>(채널당 파일 1개).
- 글 칸: id · at(KST) · head(첫 줄 120자) · link · images(사진 URL만, 파일 미저장) · og{title, site}(링크 페이지 메타만)
  · ctx{prev: 같은 채널 직전 글 3개 id, reply_to, fwd_from}. **본문·기사 본문·이메일·연락처는 저장하지 않는다.**
- '왜 올렸나' 해석은 데스크가 reports/feeds/tg_why.json 에 {post_id, why, thesis_link, conf} 로 채운다(이 스크립트는 안 씀,
  LLM 호출 없음). tier 1 = 평일 저녁 매일, tier 2 = 토요일 묶음 — 실행은 PB 쪽 예약(데스크 에이전트). 채널 2주 채점 4칸도 같은 파일.
- mode=headline(marketfeed): 실행마다 지난번 id 까지 ?before 로 최대 max_pages(10) 거슬러 받음 · why 대상 아님 ·
  키워드 일치를 글마다 'hit' 로 표시(데스크는 hit 만 봄) · og 조회 생략 · keep_days(7)일만 보관.
- individual 채널 파일엔 label '개인 채널·보유 가능성'. 상태(last_id)는 산출물 안 `state` — 새 글이 없으면 파일을 안 바꿔 커밋 없음.
- 용도: 매크로 데스크 관찰 입력. 원문 확인 전 숫자 인용 금지 · 종목 언급은 관찰만(docs/desk_kb/macro.md).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tg_common as tg  # noqa: E402

CONFIG = ROOT / "ops" / "tg_feeds.json"
FEEDS = ROOT / "reports" / "feeds"
HEAD_LEN = 120
NO_TEXT = "(텍스트 없음 — 사진·파일·답장만)"
NOTE = "관찰 입력 — 첫 줄·링크·사진 URL·링크 메타만(본문 미저장). 원문 확인 전 숫자 인용 금지, 종목 언급은 관찰만(docs/desk_kb/macro.md)."
LABEL = {"individual": "개인 채널·보유 가능성", "sellside": "셀사이드"}
CONTACT_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}|(?<![\w/=])(?:\+\d{1,3}[-\s]?)?0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4}(?!\w)"
                        r"|(?<![\w/=])01[016789]\d{7,8}(?!\w)")   # 이메일·전화(URL 안 숫자는 제외)
WHY_FORMAT = {"post_id": "채널/글 id (예: akacommodity/24869)", "why": "채널 주인이 올린 이유 추론 1~2줄",
              "thesis_link": "연결되는 우리 뷰·KB 항목(예: macro.md #29) 또는 빈칸", "conf": "상|중|하"}


def scrub(s: str) -> str:
    return CONTACT_RE.sub("[연락처 삭제]", s).strip()


def load_config(path: Path = CONFIG) -> list[dict]:
    chans = json.loads(path.read_text(encoding="utf-8"))["channels"]
    for c in chans:
        assert c["type"] in ("sellside", "individual") and c.get("tier") in (1, 2), c
    return chans


def hits(text: str, keywords: list[str]) -> list[str]:
    """영문 헤드라인 키워드 일치(대소문자 무시, 낱말 경계). 'hyperscaler capex' 같은 구는 낱말이 모두 있으면 일치."""
    lo = text.lower()
    out = []
    for k in keywords:
        words = k.lower().split()
        if all(re.search(rf"(?<![a-z0-9]){re.escape(w)}s?(?![a-z0-9])(?!['’]t(?![a-z]))", lo) for w in words):
            out.append(k)
    return out


def to_item(post: dict, prev: list[int], og_fetch=None, keywords: list[str] | None = None) -> dict:
    t = tg.kst(post["posted"])
    own = f"https://t.me/{post['channel']}".lower()
    links = [u for u in post["links"] if not u.lower().startswith(own) and u.startswith(("http://", "https://"))]
    link = links[0] if links else ""
    og = og_fetch(link) if (og_fetch and link) else {"title": "", "site": ""}
    item = {"id": post["post_id"], "at": t.strftime("%Y-%m-%dT%H:%M+09:00") if t else "",
            "head": scrub(post["first_line"])[:HEAD_LEN] or NO_TEXT, "link": link,
            "images": post.get("images", []),
            "og": {"title": scrub(og.get("title", "")), "site": scrub(og.get("site", ""))},
            "ctx": {"prev": prev[-3:][::-1], "reply_to": post.get("reply_to"), "fwd_from": post.get("fwd_from")}}
    if keywords is not None:                       # 헤드라인 채널: why 대상 아님 → 키워드 hit 만
        item["hit"] = hits(f"{post['first_line']} {og['title']}", keywords)
    return item


def merge(doc: dict, cfg: dict, posts: list[dict], keep: int, now: datetime, og_fetch=None) -> dict:
    headline = cfg.get("mode") == "headline"
    kws = cfg.get("keywords", []) if headline else None
    items = {it["id"]: it for it in doc.get("posts", [])}
    known = sorted(set(items) | {p["post_id"] for p in posts})
    for p in posts:
        prev = [i for i in known if i < p["post_id"]]
        items[p["post_id"]] = to_item(p, prev, None if headline else og_fetch, kws)
    kept = sorted(items.values(), key=lambda x: -x["id"])[:keep]
    if cfg.get("keep_days"):                       # 공개 저장소 용량 — 최근 N일만
        cut = (now - timedelta(days=int(cfg["keep_days"]))).strftime("%Y-%m-%dT%H:%M+09:00")
        kept = [x for x in kept if x["at"] >= cut]
    channel = cfg["name"]
    state = tg.update_state(doc.get("state", {}), channel, posts, now)
    out = {"channel": channel, "source": f"https://t.me/s/{channel}", "desc": cfg.get("desc", ""),
           "type": cfg["type"], "holding_disclosure": bool(cfg.get("holding_disclosure")),
           "label": LABEL[cfg["type"]], "note": NOTE,
           "tier": int(cfg.get("tier", 2)), "why": "hit 글만" if headline else "전체",
           "why_file": "reports/feeds/tg_why.json",
           "updated": now.strftime("%Y-%m-%dT%H:%M+09:00"), "state": state}
    if headline:
        out["mode"] = "headline"
        out["hit_rule"] = "데스크는 hit 가 빈칸이 아닌 글만 본다·why 도 hit 글만(키워드 = ops/tg_feeds.json keywords)."
        out["hit_count"] = sum(1 for x in kept if x.get("hit"))
    out["posts"] = kept
    return out


SCORE_COLS = {"new_info_ratio": "새 정보 비율(우리 피드·KB에 없던 정보 ÷ 채점 글)", "port_link_ratio": "포트 연결 비율(보유·관심 섹터에 닿는 글 ÷ 채점 글)",
              "leading": "선행 여부(가격·공식 발표보다 먼저 나온 사례가 있었나: 예/아니오/미확인 + 사례 id)",
              "noise_ratio": "소음 비율(잡담·중복·근거 없는 단정 ÷ 채점 글)"}


def why_skeleton(chans: list[dict]) -> dict:
    return {"_doc": "데스크가 채우는 '채널 주인이 이걸 왜 올렸나' 해석과 채널 2주 채점. 수집기(tg_feed.py·워크플로)는 쓰지 않음 — "
                    "실행은 PB 쪽 예약(데스크 에이전트). 추론 재료 = reports/feeds/tg_*.json 의 head·link·og·images(임시로 받아 보고 "
                    "커밋 금지)·ctx. 원문 확인 전 숫자 인용 금지, 개인 채널은 펌핑 가능성 감안.",
            "schedule": {"tier1": "평일 저녁 매일(marketfeed 는 hit 글만)", "tier2": "매주 토요일 묶어서"},
            "format": WHY_FORMAT, "items": [],
            "score_format": SCORE_COLS,
            "channel_scores": {c["name"]: {"tier": int(c.get("tier", 2)), "window": "", "n": None,
                                           **{k: None for k in SCORE_COLS}} for c in chans}}


def ensure_why(path: Path, chans: list[dict] | None = None) -> None:
    """데스크용 해석 파일 — 없을 때만 빈 틀을 만든다(있으면 절대 안 건드림)."""
    if path.exists():
        return
    chans = load_config() if chans is None else chans
    path.write_text(json.dumps(why_skeleton(chans), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def run_one(cfg: dict, pages: int, keep: int, og: bool, out_dir: Path = FEEDS) -> int:
    out = out_dir / cfg["out"]
    try:
        doc = json.loads(out.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        doc = {}
    pages = int(cfg.get("max_pages", pages))       # 헤드라인 채널은 지난번 id 까지 최대 N페이지 거슬러
    keep = int(cfg.get("keep", keep))
    posts = tg.collect(cfg["name"], tg.last_id(doc.get("state", {}), cfg["name"]), pages, fetcher=tg.fetch)
    print(f"[tg_feed] {cfg['name']}: 새 글 {len(posts)}")
    if not posts:
        return 0                                   # 파일 그대로 → 커밋 없음
    new = merge(doc, cfg, posts, keep, datetime.now(tg.KST), tg.fetch_og if og else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return len(posts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("channel", nargs="?", help="설정(ops/tg_feeds.json)에 있는 채널 하나만")
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--keep", type=int, default=200, help="채널당 최근 글 몇 개까지 남길지")
    ap.add_argument("--no-og", action="store_true", help="링크 페이지 og 메타 조회 생략")
    a = ap.parse_args(argv)
    chans = load_config()
    if a.channel:
        name = a.channel.lstrip("@").split("/")[-1].lower()
        chans = [c for c in chans if c["name"].lower() == name]
        if not chans:
            print(f"[tg_feed] 설정에 없는 채널: {a.channel} — ops/tg_feeds.json 에 먼저 추가", file=sys.stderr)
            return 2
    FEEDS.mkdir(parents=True, exist_ok=True)
    ensure_why(FEEDS / "tg_why.json", load_config())
    fail = 0
    for c in chans:
        try:
            run_one(c, a.pages, a.keep, not a.no_og)
        except Exception as e:  # noqa: BLE001 — 한 채널 실패가 나머지를 막지 않게
            fail += 1
            print(f"::warning::tg_feed {c['name']} 실패: {type(e).__name__}: {e}")
    return 1 if fail == len(chans) else 0


if __name__ == "__main__":
    sys.exit(main())
