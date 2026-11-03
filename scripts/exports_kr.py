#!/usr/bin/env python3
"""한국 수출 수집 → reports/exports_kr.json (11/3 데이터엔지니어; 애널·매크로 요청 11/1, 비공개 저장소 agreements 참조).

  python3 scripts/exports_kr.py [--days 45] [--dry-run]

소스(전부 정책브리핑 korea.kr 보도자료 전재 — 공공누리 1유형, 텍스트 이용. 관세청·산업부 사이트 직접 접근은 목록/JS 상세라 쓰지 않음):
  · 관세청 월간 잠정치 '○월 수출입 현황 [잠정치]' → 월 수출·수입·수지(백만달러) + 2025~26 월별 수출 시계열(PDF 표)
  · 관세청 10일 단위 '○월 ○일 ~ ○월 ○일 수출입 현황 [잠정치]' → 기간 수출·수입(억달러)·증감률·반도체
  · 산업통상부 '○월 수출입 동향' → 반도체 등 주요 품목 월 수출액(억달러)·증감률
PDF 첨부를 pdftotext(poppler)로 읽는다 — 없으면 해당 건 건너뛰고 다음 실행에 재시도. 새 건이 없으면 파일 안 바꿈.
기준일 = 보도자료 게시일. 확정 통계가 아니라 잠정(통관기준)이며 일부 수치는 정정될 수 있음(2027-02 확정).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "exports_kr.json"
KR = "https://www.korea.kr"
UA = {"User-Agent": "Mozilla/5.0"}
ITEMS = ["반도체", "컴퓨터", "무선통신기기", "자동차", "선박", "석유제품", "석유화학", "철강", "전기기기", "이차전지", "일반기계", "디스플레이"]
NOTE = ("수출 잠정치(통관기준) — 관세청·산업통상부 보도자료(정책브리핑 전재, 공공누리 1유형). 단위는 칸마다 명시. "
        "확정 통계 아님(2027-02 확정 시 정정 가능). 관찰 입력 — 판단은 데스크.")

T_MOTIE = re.compile(r"^(\d{4})년 (\d{1,2})월 수출입 동향")
T_MONTH = re.compile(r"^(\d{4})년 (\d{1,2})월 수출입 현황")
T_PERIOD = re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일\s*~\s*(\d{1,2})월 (\d{1,2})일 수출입 현황")


def _get(url: str, timeout: int = 40) -> bytes:
    for i in range(3):   # 연결 끊김(proxy·서버) 재시도
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except OSError:
            if i == 2:
                raise
            time.sleep(2 * (i + 1))
    return b""


def list_releases(days: int, today: date | None = None) -> list[dict]:
    today = today or date.today()
    out: dict[str, dict] = {}
    for pg in (1, 2, 3):   # 검색 결과가 페이지당 10건 안팎 — 3쪽까지(10일 단위 속보 포함)
        q = urllib.parse.urlencode({"startDate": (today - timedelta(days=days)).isoformat(), "endDate": today.isoformat(),
                                    "srchWord": "수출입", "pageIndex": pg})
        for r in parse_list(_get(f"{KR}/briefing/pressReleaseList.do?{q}").decode("utf-8", "replace")):
            out.setdefault(r["news_id"], r)
    return list(out.values())


def parse_list(page: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<a[^>]*href="/briefing/pressReleaseView\.do\?newsId=(\d+)[^"]*"[^>]*>(.*?)</a>', page, re.S):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        for kind, rx in (("motie_monthly", T_MOTIE), ("customs_monthly", T_MONTH), ("customs_period", T_PERIOD)):
            g = rx.match(t)
            if g:
                out.append({"news_id": m.group(1), "kind": kind, "groups": [int(x) for x in g.groups()], "title": g.group(0)})
                break
    return out


def pdf_text(news_id: str) -> tuple[str, str]:
    """보도자료 첨부 PDF → (본문 텍스트, 게시일). PDF 가 없거나 pdftotext 실패면 ('', '')."""
    view = _get(f"{KR}/briefing/pressReleaseView.do?newsId={news_id}").decode("utf-8", "replace")
    for fid in dict.fromkeys(re.findall(r"/common/download\.do\?fileId=(\d+)&amp;tblKey=GMN", view)):
        blob = _get(f"{KR}/common/download.do?fileId={fid}&tblKey=GMN", 90)
        if blob[:4] != b"%PDF":
            continue
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.pdf"
            p.write_bytes(blob)
            r = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            dm = re.search(r"배포\s+(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", r.stdout)
            return r.stdout, (f"{int(dm[1]):04d}-{int(dm[2]):02d}-{int(dm[3]):02d}" if dm else "")
    return "", ""


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _signed(pct: str, word: str) -> float:
    v = _num(pct)
    return -v if "감소" in word else v


def parse_customs_summary(text: str) -> dict:
    """'수출 1,153억 달러 ... 수입 728억 달러로 전년동기대비 수출 93.7%(…) 증가, 수입 36.0%(…) 증가' 형태(월간·10일 공통)."""
    m = re.search(r"수출\s*([\d,]+)억 달러,\s*수입\s*([\d,]+)억 달러로 전년동기대비 수출\s*([\d.]+)%[^,]*?(증가|감소),\s*수입\s*([\d.]+)%[^\n]*?(증가|감소)", text, re.S)
    if not m:
        return {}
    d = {"export_100m_usd": _num(m[1]), "import_100m_usd": _num(m[2]), "export_yoy_pct": _signed(m[3], m[4]),
         "import_yoy_pct": _signed(m[5], m[6])}
    d["balance_100m_usd"] = round(d["export_100m_usd"] - d["import_100m_usd"], 1)
    sm = re.search(r"반도체\(([\d,]+)억 달러\)", text)
    if sm:
        d["semiconductor_100m_usd"] = _num(sm[1])
    ym = re.search(r"반도체\(([\d.]+)%\)", text)
    if ym:
        d["semiconductor_yoy_pct"] = _num(ym[1])
    return d


def parse_monthly_series(text: str) -> dict:
    """관세청 월간 PDF '월별 수출입현황' 표 → {'export':{'2025':[12],'2026':[..]},'import':{...}} (백만달러). 못 읽으면 {}."""
    rows = []
    for ln in text.splitlines():
        if "금액" in ln:
            nums = re.findall(r"-?\d[\d,]*", ln.split("금액", 1)[1])
            if len(nums) >= 10:
                rows.append([int(n.replace(",", "")) for n in nums])
    if len(rows) < 4:
        return {}
    return {"unit": "백만달러(월 1~12, 2026은 잠정 월까지)",
            "export": {"2025": rows[0][:12], "2026": rows[1][:12]}, "import": {"2025": rows[2][:12], "2026": rows[3][:12]}}


def parse_motie_items(text: str) -> dict:
    """산업부 '품목(금액억 달러, +증감률%)' 서술 → {품목:{usd_100m, yoy_pct}}."""
    out = {}
    for name, val, sign, pct in re.findall(r"([가-힣]+)(?:\s*수출)?\(([\d,.]+)억 달러,\s*([+△\-]?)\s*([\d.]+)%\)", text):
        key = next((k for k in ITEMS if name.endswith(k)), None)
        if key and key not in out:
            out[key] = {"usd_100m": _num(val), "yoy_pct": -_num(pct) if sign in ("△", "-") else _num(pct)}
    return out


def load(path: Path = OUT) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"note": NOTE, "source": KR + "/briefing/pressReleaseList.do (관세청·산업통상부 보도자료 전재)",
            "monthly": {}, "periods": {}, "state": {"seen_news": []}}


def apply(data: dict, rel: dict, text: str, posted: str) -> bool:
    """파싱 결과를 data 에 반영. 반영했으면 True."""
    k, g = rel["kind"], rel["groups"]
    src = {"news_id": rel["news_id"], "title": rel["title"], "posted": posted}
    if k == "customs_monthly":
        s = parse_customs_summary(text)
        if not s:
            return False
        key = f"{g[0]}-{g[1]:02d}"
        data["monthly"].setdefault(key, {})["customs"] = {**s, "src": src}
        ser = parse_monthly_series(text)
        if ser:
            data["series_customs"] = {**ser, "as_of": key}
    elif k == "customs_period":
        s = parse_customs_summary(text)
        if not s:
            return False
        key = f"{g[0]}-{g[1]:02d}-{g[2]:02d}~{g[3]:02d}-{g[4]:02d}"
        data["periods"][key] = {**s, "src": src}
    else:
        it = parse_motie_items(text)
        if not it:
            return False
        key = f"{g[0]}-{g[1]:02d}"
        data["monthly"].setdefault(key, {})["motie_items"] = {"unit": "억달러·전년동월대비 %", "items": it, "src": src}
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    data = load()
    seen = set(data["state"]["seen_news"])
    n_new = 0
    for rel in list_releases(a.days):
        if rel["news_id"] in seen:
            continue
        try:
            text, posted = pdf_text(rel["news_id"])
        except (OSError, subprocess.SubprocessError) as e:
            print(f"건너뜀 {rel['title']}: {e}", file=sys.stderr)
            continue
        if text and apply(data, rel, text, posted):
            seen.add(rel["news_id"])
            n_new += 1
            print(f"신규 {rel['kind']} {rel['title']} ({posted})")
        else:
            print(f"파싱 못함(다음 실행 재시도) {rel['title']}", file=sys.stderr)
    print(f"신규 {n_new}건 · 월 {len(data['monthly'])} · 기간 {len(data['periods'])}")
    if n_new and not a.dry_run:
        now = datetime.now(timezone(timedelta(hours=9)))
        data["state"]["seen_news"] = sorted(seen)[-200:]
        data["updated"] = now.strftime("%Y-%m-%dT%H:%M+09:00")
        data["periods"] = dict(sorted(data["periods"].items())[-12:])
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
