#!/usr/bin/env python3
"""사내톡 피드 — 요청 장부 + 회신을 터미널 SYSTEM › 사내톡 탭용으로 묶는다 (10/23 겸이 "터미널에 사내톡 탭 만들어줘 자동갱신되게, 그리고 실제 누나들의 voc로").

입력
- docs/desk_kb/rounds/_requests.json — 요청(from→to) + replies[{by, at, text, voc}] (scripts/ask.py --reply)
- docs/desk_kb/rounds/*-msg-*.md — 사내 메신저 라운드 기록. 요청 id 가 들어간 '- `req-…`' 줄은 진행자 대행 회신(voc=False)으로 붙인다(옛 기록 호환).

출력: reports/msgr_feed.md — 내용은 JSON 한 덩어리.
  확장자가 .md 인 이유: GAS 는 Code.gs 의 getter 만 GitHub 에서 읽는데, 새 getter 를 만들면 겸이가 Code.gs 를 다시 붙여넣어야 한다.
  기존 getMarkdown(name)(reports/<name>.md 원문 반환)을 그대로 쓰면 HTML 탭만 추가해도 된다.

사용: python3 scripts/msgr_feed.py [--out reports/msgr_feed.md]   (표준 라이브러리만)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUNDS = ROOT / "docs" / "desk_kb" / "rounds"
KST = timezone(timedelta(hours=9))
RID = re.compile(r"req-[a-z]+-[0-9a-f]{8}")
MSG = re.compile(r"(\d{4}-\d{2}-\d{2})-msg-(\d{2})(\d{2})\.md$")
KEEP = ("id", "from", "to", "text", "opened", "opened_at", "due", "status", "done_at", "done_by", "resolution", "promoted_at")


def round_replies(rounds: Path) -> dict[str, list[dict]]:
    """메신저 라운드 기록의 요청별 줄 → 대행 회신."""
    out: dict[str, list[dict]] = {}
    for f in sorted(rounds.glob("*-msg-*.md")):
        m = MSG.search(f.name)
        if not m:
            continue
        at = f"{m.group(1)}T{m.group(2)}:{m.group(3)}+09:00"
        sec = ""
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.startswith("## "):
                sec = ln[3:].strip()
                continue
            ids = RID.findall(ln)
            if not (ln.startswith("- ") and ids):
                continue
            t = re.sub(r"^- `req-[a-z]+-[0-9a-f]{8}`\s*(\([^)]*\))?\s*:?\s*", "", ln.strip()).replace("**", "").strip()
            out.setdefault(ids[0], []).append({"by": None, "at": at, "text": t, "voc": False, "sec": sec, "src": f.name})
    return out


NAME2KEY = {"PB": "pb", "CIO": "cio", "자산배분": "alloc", "매크로": "macro", "채권": "bonds", "부동산·대체": "realestate", "퀀트": "quant",
            "애널": "analyst", "파생": "derivs", "데이터": "data", "리스크(FRM)": "frm", "행동": "behavior", "PM": "pm", "운영": "ops",
            "개발": "dev", "기록": "scribe", "교육": "edu", "평가": "eval", "내무": "household", "LIFE": "life", "검증": "verify",
            "피어리뷰": "peer", "감사": "audit", "컴플라이언스": "compliance", "포지션리스크": "posrisk",
            "프론트": "front"}
# CHARACTERS.md 표에 없는 데스크(10/21 신설) — 나이는 10/23 프로필 사진 프롬프트 설정, 한 줄은 각 KB 머리말 요약
EXTRA = [("hf", "HF", "헤지펀드", 34, "피도 눈물도 없는 알파북 운용역 — 숫자로 깔보고 리스크로 증명함"),
         ("uxui", "UXUI", "운영", 30, "겸이가 핵심 숫자를 몇 초 만에 찾는지 재는 화면 위계 담당"),
         ("maint", "유지보수", "운영", 31, "멈추거나 늦은 걸 제일 먼저 잡는 SRE — 조용한 실패 사냥꾼"),
         # 10/24 겸이 결재 리스크본부 신설 — CHARACTERS.md 표에도 있음(표가 우선, 여기는 표가 깨졌을 때 대비)
         ("compliance", "컴플라이언스", "리스크", 33, "조항 번호부터 대는 2선 감시자 — 위반은 로그로, 예외는 서면으로"),
         ("posrisk", "포지션리스크", "리스크", 30, "한도 사용률을 % 로만 말하는 계기판 — 팔 수 있는 날짜부터 셈"),
         # 10/24 겸이 결재 appr-staffing-30 운영본부 신설 — CHARACTERS.md 표에도 있음
         ("front", "프론트", "운영", 30, "폰에서 직접 열어 보기 전엔 '됐다' 소리 안 하는 화면 장인 — 1px 어긋남과 스킨 깨짐을 못 참음")]
ROLE = {"realestate": "정책·뉴스·서울 상급지/하급지·경기남부 집값·재개발·신도시 트래킹(10/23)",
        "household": "자산(순자산)·뱅샐·운동 등 숫자 트래킹(10/23)", "life": "코칭 — 목표·실행 점검(10/23)",
        "edu": "전 데스크 10년차 기준 강화(10/23)",
        "ops": "보드·잠금·예약·요청 장부(10/24 컴플 겸직 해제 → 컴플라이언스)",
        "compliance": "규칙·한도 준수 사전·사후 점검, 위반 로그·에스컬레이션(10/24 신설)",
        "posrisk": "모의 북·ISA 노출 한도 사용률·집중도·유동성·만기·최대손실 매일 점검(10/24 신설)",
        "front": "화면·스킨·텔레그램 UI·ui_smoke 구현 — 개발에서 화면 이관, UXUI 설계의 구현(10/24 신설)",
        "dev": "서버 로직·scripts·workflows·.gs·수집·배포(10/24 화면 구현은 프론트로 이관)"}


def profiles(chars: Path) -> list[dict]:
    """프로필 창용 — docs/desk_kb/CHARACTERS.md '한눈에' 표 + 신설 데스크. 사진은 assets/avatars/<key>.png(탭이 직접 읽음)."""
    out = []
    try:
        for ln in chars.read_text(encoding="utf-8").splitlines():
            c = [x.strip() for x in ln.strip().strip("|").split("|")]
            if len(c) == 4 and c[2].isdigit():
                nm = c[1].replace("*", "")
                k = NAME2KEY.get(nm)
                if k:
                    out.append({"key": k, "name": nm, "dept": c[0], "age": int(c[2]), "line": c[3], "role": ROLE.get(k, "")})
    except OSError:
        pass
    have = {p["key"] for p in out}
    out += [{"key": k, "name": n, "dept": d, "age": a, "line": l, "role": ROLE.get(k, "")} for k, n, d, a, l in EXTRA if k not in have]
    # 꾸미기(상태 메시지·배경·프로필 뮤직·취미) — assets/avatars/profiles.json. 배경사진은 탭이 assets/avatars/bg/<key>.jpg 를 직접 읽고 없으면 bg 그라디언트
    try:
        deco = json.loads((ROOT / "assets" / "avatars" / "profiles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        deco = {}
    for p in out:
        d = deco.get(p["key"]) or {}
        p.update({f: d[f] for f in ("msg", "bg", "bgm", "hobby") if d.get(f)})
    return out


def build(ledger: dict, rounds: Path, now: datetime) -> dict:
    rr = round_replies(rounds)
    items = []
    for r in ledger.get("requests", []):
        x = {k: r.get(k) for k in KEEP if r.get(k) is not None}
        reps = [dict(p) for p in rr.get(r["id"], [])]
        for p in reps:
            p["by"] = r["to"]
        reps += [dict(p, sec="회신") for p in r.get("replies", [])]
        reps.sort(key=lambda p: p.get("at") or "")
        x["replies"] = reps
        items.append(x)
    items.sort(key=lambda x: (x.get("opened_at") or x.get("opened") or ""), reverse=True)
    st = {}
    for x in items:
        st[x["status"]] = st.get(x["status"], 0) + 1
    chat = sorted(ledger.get("chat", []), key=lambda c: c.get("at") or "")[-200:]   # 사담(ask.py --chat) 최근 200줄
    prof = profiles(rounds.parent / "CHARACTERS.md")
    for p in prof:
        k = p["key"]
        p["open_in"] = sum(1 for x in items if x.get("to") == k and x.get("status") != "done")
        p["sent"] = sum(1 for x in items if x.get("from") == k)
        p["replies"] = sum(1 for x in items for r in x.get("replies", []) if r.get("by") == k and r.get("voc"))
        last = [c for c in chat if c.get("by") == k]
        p["last_chat"] = last[-1]["text"] if last else ""
    return {"asof": now.strftime("%Y-%m-%d %H:%M"), "n": len(items), "status": st, "chat": chat, "profiles": prof,
            "n_reply": sum(1 for x in items if x["replies"]),
            "n_voc": sum(1 for x in items for p in x["replies"] if p.get("voc")),
            "items": items}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "msgr_feed.md")
    ap.add_argument("--ledger", type=Path, default=ROUNDS / "_requests.json")
    a = ap.parse_args(argv)
    led = json.loads(a.ledger.read_text(encoding="utf-8")) if a.ledger.exists() else {}
    feed = build(led, a.ledger.parent, datetime.now(KST))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(feed, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"사내톡 피드 {feed['n']}건 · 회신 {feed['n_reply']} · VOC {feed['n_voc']} → {a.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
