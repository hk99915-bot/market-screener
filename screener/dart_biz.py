"""OpenDART 사업보고서 본문 수집 — 'II. 사업의 내용' 섹션 텍스트 (11/1 겸이 "Open api도 있고", req-dev-8d32d432).

공시 목록(dart.py)·재무 숫자(fin.py)만 받던 것에 더해, 정기보고서 **본문**의 사업 서술(시장점유율·사업 구조·주요 제품·경쟁)을
텍스트로 남긴다. 애널리스트·산업 데스크가 원문을 직접 인용할 수 있게 하는 입력층이다.

흐름: 종목코드 → DART 고유번호(fin.corp_codes) → list.json(pblntf_ty=A 정기공시, 최종보고서만)에서 최신 사업보고서·반기보고서
→ document.xml(zip) → 본문 XML 에서 'II. 사업의 내용' SECTION 을 잘라 텍스트로(태그 제거, 표는 행=줄·칸=탭)
→ data/dart_biz/<코드>_<rcept_no>.txt + 색인 data/dart_biz/index.json.

- 이미 색인에 있는 rcept_no 는 다시 받지 않는다(섹션을 못 찾은 것도 status 로 남겨 반복 호출 방지).
- 호출 예산(--max-calls, 기본 400)·재시도 3회·일일 한도(020) 감지 시 즉시 중단하고 받은 만큼 저장.
- 종목마다 사업보고서 최신 1건 + 그보다 새 반기보고서 1건만 보관 — 옛 rcept_no 파일은 지운다(저장소 크기).
- 공시 원문은 공개 정보. 개인정보 없음.

  python -m screener.dart_biz --chain cybersecurity
  python -m screener.dart_biz --codes 053800,263860
  python -m screener.dart_biz                       # 기본 대상: KR 체인 전 종목 + 상세 리포트 우선순위 상위
환경변수 DART_API_KEY 가 없으면 아무것도 하지 않는다.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .config import DATA_DIR, REPORT_DIR
from .dart import BASE, key

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = DATA_DIR / "dart_biz"
INDEX = OUT / "index.json"
PARSER = 3                     # 추출 규칙 버전 — 올리면 옛 버전 결과를 다음 실행에서 다시 받음(파일은 덮어씀)
MAX_CHARS = 600_000            # 비정상적으로 긴 섹션 상한(파일 하나 ≈ 1.5MB 이하)
KINDS = {"사업보고서": "사업", "반기보고서": "반기"}


class DailyLimit(RuntimeError):
    pass


class Budget:
    def __init__(self, n: int):
        self.left = n
        self.used = 0

    def take(self) -> None:
        if self.left <= 0:
            raise DailyLimit("호출 예산 소진")
        self.left -= 1
        self.used += 1


# ───────────── 섹션 추출 (순수 함수 — 테스트 대상) ─────────────

_TITLE = re.compile(r"<TITLE\b[^>]*>(.*?)</TITLE>", re.S | re.I)
_BIZ = re.compile(r"^\s*(?:II|Ⅱ|2)\s*[.．]\s*사업의\s*내용")
_NEXT = re.compile(r"^\s*(?:III|Ⅲ|3)\s*[.．]")
_CELL = re.compile(r"<(TD|TH|TE|TU)\b[^>]*>(.*?)</\1\s*>", re.S | re.I)
_ROW = re.compile(r"<TR\b[^>]*>(.*?)</TR\s*>", re.S | re.I)
_TABLE_INNER = re.compile(r"<TABLE(?=[\s>])[^>]*>((?:(?!<TABLE[\s>]).)*?)</TABLE\s*>", re.S | re.I)   # TABLE-GROUP 은 표 아님
_TAG = re.compile(r"<[^>]+>")


def _plain(s: str) -> str:
    s = s.replace("&cr;", " ")
    s = _TAG.sub(" ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _block(s: str) -> str:
    """칸 하나짜리 행(DART 가 본문 문단을 1칸 표로 감싼 경우) — 문단 줄바꿈을 살린다."""
    s = re.sub(r"</P\s*>|<BR\b[^>]*/?>|&cr;", "\n", s, flags=re.I)
    lines = (re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", ln))).strip() for ln in s.split("\n"))
    return "\n".join(ln for ln in lines if ln)


def _table(m: re.Match) -> str:
    rows = []
    for r in _ROW.findall(m.group(1)):
        raw = _CELL.findall(r)
        cells = [_block(raw[0][1])] if len(raw) == 1 else [_plain(c) for _, c in raw]
        if any(cells):
            rows.append("\t".join(cells))
    return "\n" + "\n".join(rows) + "\n" if rows else "\n"


def xml_to_text(x: str) -> str:
    """DART 본문 XML 조각 → 텍스트. 표는 행마다 한 줄, 칸은 탭. 제목은 앞뒤 줄바꿈."""
    # 그림만 지운다. LIBRARY 는 본문 묶음(서식 라이브러리)이라 지우면 안 된다 — 11/1 첫 실행 13/14 누락 원인
    x = re.sub(r"<IMAGE\b[^>]*>.*?</IMAGE\s*>", " ", x, flags=re.S | re.I)
    x = re.sub(r"<IMG\b[^>]*/>|<IMG\b[^>]*>[^<]*</IMG\s*>", " ", x, flags=re.I)
    x = re.sub(r"<!--.*?-->", " ", x, flags=re.S)
    while True:                                              # 안쪽 표부터 (중첩 표 대비)
        y = _TABLE_INNER.sub(lambda m: _table(m).replace("\n", "\x00").replace("\t", "\x01"), x)
        if y == x:
            break
        x = y
    x = x.replace("&cr;", "\n")
    x = re.sub(r"<TITLE\b[^>]*>", "\n\n", x, flags=re.I)
    x = re.sub(r"</(TITLE|P|SECTION-\d|PGBRK|TABLE-GROUP)\s*>|<(BR|PGBRK)\b[^>]*/?>", "\n", x, flags=re.I)
    x = _TAG.sub("", x)
    x = html.unescape(x)
    lines = []
    for ln in x.replace("\x00", "\n").split("\n"):
        if "\x01" in ln:
            ln = "\t".join(c.strip() for c in ln.split("\x01"))
        else:
            ln = re.sub(r"[ \t 　]+", " ", ln).strip()
        lines.append(ln)
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out


def biz_section(xml: str) -> str | None:
    """본문 XML 에서 'II. 사업의 내용' 섹션 XML 을 잘라낸다. 없으면 None.

    섹션 = 그 TITLE 을 품은 <SECTION-1> 의 끝(</SECTION-1>)까지. SECTION 태그가 없으면 다음 'III.' 제목 직전까지.
    목차(TOC)에 같은 제목이 먼저 나오는 경우를 피하려 SECTION 안의 TITLE 을 우선한다.
    """
    hits = [m for m in _TITLE.finditer(xml) if _BIZ.match(_plain(m.group(1)))]
    if not hits:
        return None
    for m in hits:
        open_ = xml.rfind("<SECTION-1", 0, m.start())
        if open_ < 0 or xml.rfind("</SECTION-1>", 0, m.start()) > open_:
            continue
        end = xml.find("</SECTION-1>", m.end())
        if end > 0:
            return xml[m.start():end]
    m = hits[-1]
    nxt = next((t for t in _TITLE.finditer(xml, m.end()) if _NEXT.match(_plain(t.group(1)))), None)
    return xml[m.start(): nxt.start() if nxt else len(xml)]


def _decode(b: bytes) -> str:
    head = b[:200].decode("ascii", "ignore").lower()
    enc = "utf-8"
    mm = re.search(r'encoding="([^"]+)"', head)
    if mm:
        enc = mm.group(1)
    for e in (enc, "utf-8", "cp949"):
        try:
            return b.decode(e)
        except (LookupError, UnicodeDecodeError):
            continue
    return b.decode("utf-8", "ignore")


def extract_from_zip(blob: bytes, rcept_no: str) -> str | None:
    """document.xml zip → '사업의 내용' 텍스트. 본문 파일(<rcept_no>.xml) 먼저, 없으면 나머지 파일에서 찾는다."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    names = sorted(z.namelist(), key=lambda n: (n != f"{rcept_no}.xml", "_" in n, -z.getinfo(n).file_size))
    for n in names:
        sec = biz_section(_decode(z.read(n)))
        if sec:
            t = xml_to_text(sec)
            if len(t) > 50:
                return t[:MAX_CHARS]
    return None


def diagnose(blob: bytes, rcept_no: str) -> str:
    """추출 실패 원인 추적용 한 줄: 파일·크기·'사업의 내용' 포함 제목·섹션 길이."""
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return "zip 아님"
    out = []
    for n in z.namelist()[:6]:
        x = _decode(z.read(n))
        tt = [_plain(m.group(1))[:30] for m in _TITLE.finditer(x)]
        biz = [t for t in tt if "사업의" in t]
        sec = biz_section(x)
        out.append(f"{n}({len(x)}자 제목{len(tt)} 사업{biz[:2]} 섹션{len(sec) if sec else 0}→글{len(xml_to_text(sec)) if sec else 0})")
    return " · ".join(out)


def pick_reports(rows: list[dict]) -> list[dict]:
    """list.json 행들 → 받을 보고서: 최신 사업보고서 1 + (그보다 새면) 최신 반기보고서 1. 분기보고서 제외."""
    best: dict[str, dict] = {}
    for r in rows:
        nm = (r.get("report_nm") or "").replace(" ", "")
        kind = next((v for k, v in KINDS.items() if k in nm), None)
        if not kind or "분기" in nm:
            continue
        if kind not in best or (r.get("rcept_dt", ""), r.get("rcept_no", "")) > (best[kind].get("rcept_dt", ""), best[kind].get("rcept_no", "")):
            best[kind] = {**r, "kind": kind}
    out = []
    if "사업" in best:
        out.append(best["사업"])
    if "반기" in best and ("사업" not in best or best["반기"]["rcept_dt"] > best["사업"]["rcept_dt"]):
        out.append(best["반기"])
    return out


# ───────────── 네트워크 ─────────────

def _get(path: str, params: dict, bud: Budget, binary: bool = False):
    for i in range(3):
        bud.take()
        try:
            r = requests.get(f"{BASE}/{path}", params={"crtfc_key": key(), **params}, timeout=60)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            if i == 2:
                raise
            log.info("DART %s 재시도 %d: %s", path, i + 1, e)
            time.sleep(3 * (i + 1))
            continue
        if binary and r.content[:2] == b"PK":
            return r.content
        txt = r.content.decode("utf-8", "ignore")
        st = (re.search(r'"status"\s*:\s*"(\d+)"', txt) or re.search(r"<status>(\d+)</status>", txt))
        st = st.group(1) if st else ""
        if st == "020":
            raise DailyLimit("DART 일일 한도 초과(020)")
        if binary:
            return st or "nozip"                              # 014 파일 없음 등 → 호출측이 기록
        j = json.loads(txt)
        if j.get("status") in ("000", "013"):
            return j
        raise RuntimeError(f"DART {j.get('status')}: {j.get('message')}")
    return None


def list_reports(corp_code: str, bud: Budget, days: int = 560) -> list[dict]:
    today = datetime.now(KST).date()
    j = _get("list.json", {"corp_code": corp_code, "bgn_de": (today - timedelta(days=days)).strftime("%Y%m%d"),
                           "end_de": today.strftime("%Y%m%d"), "pblntf_ty": "A", "last_reprt_at": "Y",
                           "page_count": 100}, bud)
    return (j or {}).get("list") or []


# ───────────── 색인 ─────────────

def load_index() -> dict:
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"items": []}


def save_index(ix: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ix["items"] = sorted(ix.get("items", []), key=lambda r: (r["code"], r.get("date", ""), r["rcept_no"]))
    ix["updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    INDEX.write_text(json.dumps(ix, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def prune(ix: dict, code: str, keep: set[str]) -> None:
    """종목의 색인·파일 중 keep(이번에 고른 최신 rcept_no) 밖의 옛 보고서를 지운다."""
    if not keep:
        return
    rest = []
    for r in ix.get("items", []):
        if r["code"] == code and r["rcept_no"] not in keep:
            (OUT / f"{code}_{r['rcept_no']}.txt").unlink(missing_ok=True)
            continue
        rest.append(r)
    ix["items"] = rest


# ───────────── 대상 ─────────────

def chain_codes(chain: str | None = None) -> list[str]:
    from .drivers import CHAINS
    if chain:
        if chain not in CHAINS:
            raise SystemExit(f"알 수 없는 체인: {chain} (가능: {', '.join(CHAINS)})")
        return list(CHAINS[chain]["codes"])
    out = list(CHAINS["cybersecurity"]["codes"])               # 사이버보안 먼저(11/1 요청)
    for k, v in CHAINS.items():
        out += v["codes"]
    return out


def default_codes(top: int = 60) -> list[str]:
    """KR 체인 구성 종목 + reports/detail/KR 가 있는 종목 중 fin.priority_codes 순 상위 top."""
    from .fin import priority_codes
    have = {p.stem for p in (REPORT_DIR / "detail" / "KR").glob("*.json")}
    pri = [c for c in priority_codes(600) if c in have][:top]
    return _uniq(chain_codes() + pri)


def _uniq(xs: list[str]) -> list[str]:
    seen, out = set(), []
    for c in xs:
        c = (c or "").strip()
        if c and c not in seen and re.fullmatch(r"[0-9A-Z]{6}", c):
            seen.add(c)
            out.append(c)
    return out


# ───────────── 실행 ─────────────

def update(codes: list[str], max_calls: int = 400, sleep: float = 0.3) -> dict:
    if not key():
        log.info("DART_API_KEY 없음 — 사업보고서 본문 건너뜀")
        return {"skipped": "no key"}
    from .fin import corp_codes
    cmap = corp_codes()
    ix = load_index()
    have = {r["rcept_no"] for r in ix.get("items", []) if r.get("parser", 1) >= PARSER}   # 옛 규칙 결과는 성공도 다시 받음
    ix["items"] = [r for r in ix.get("items", []) if r["rcept_no"] in have]   # 옛 규칙 기록은 새로 씀
    bud = Budget(max_calls)
    stat = {"codes": len(codes), "new": 0, "skip": 0, "no_section": 0, "no_report": 0, "no_corp": 0, "err": 0}
    stop = ""
    try:
        for i, code in enumerate(codes):
            cc = cmap.get(code)
            if not cc:
                stat["no_corp"] += 1
                continue
            try:
                picks = pick_reports(list_reports(cc, bud))
            except DailyLimit:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("%s 목록 실패: %s", code, e)
                stat["err"] += 1
                continue
            if not picks:
                stat["no_report"] += 1
                continue
            for r in picks:
                rn = r["rcept_no"]
                if rn in have:
                    stat["skip"] += 1
                    continue
                time.sleep(sleep)
                got = _get("document.xml", {"rcept_no": rn}, bud, binary=True)
                row = {"code": code, "name": r.get("corp_name", ""), "rcept_no": rn, "report": r.get("report_nm", "").strip(),
                       "kind": r["kind"], "date": r.get("rcept_dt", ""), "chars": 0,
                       "fetched": datetime.now(KST).strftime("%Y-%m-%d"), "parser": PARSER}
                text = None
                if isinstance(got, bytes):
                    try:
                        text = extract_from_zip(got, rn)
                    except zipfile.BadZipFile:
                        got = "badzip"
                if text:
                    OUT.mkdir(parents=True, exist_ok=True)
                    hdr = f"# {row['name']} ({code}) · {row['report']} · 접수 {row['date']} · rcept_no {rn}\n# 원문 https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rn}\n\n"
                    (OUT / f"{code}_{rn}.txt").write_text(hdr + text + "\n", encoding="utf-8")
                    row.update(chars=len(text), status="ok")
                    stat["new"] += 1
                elif isinstance(got, bytes) or got in ("014", "badzip"):   # 확정 실패만 기록(재호출 방지)
                    row["status"] = "no_section" if isinstance(got, bytes) else f"doc_{got}"
                    if isinstance(got, bytes):
                        log.warning("%s %s 사업의 내용 못 찾음 — %s", code, rn, diagnose(got, rn))
                    stat["no_section"] += 1
                else:                                            # 일시 오류 — 기록 안 함, 다음 실행에서 재시도
                    log.warning("%s %s 본문 받기 실패(%s)", code, rn, got)
                    stat["err"] += 1
                    continue
                ix.setdefault("items", []).append(row)
                have.add(rn)
            prune(ix, code, {r["rcept_no"] for r in picks})
            if (i + 1) % 10 == 0:
                save_index(ix)                                   # 중간 저장
            time.sleep(sleep)
    except DailyLimit as e:
        stop = str(e)
        log.warning("중단: %s — 받은 만큼 저장, 다음 실행에서 이어받음", e)
    stat.update(api_calls=bud.used, stopped=stop)
    ix["last_run"] = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), **stat}
    save_index(ix)
    log.info("사업보고서 본문 %s", stat)
    return stat


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DART 사업보고서 'II. 사업의 내용' 수집")
    ap.add_argument("--codes", default="", help="쉼표 구분 종목코드 (주면 이것만)")
    ap.add_argument("--chain", default="", help="drivers.CHAINS 키 (예: cybersecurity) — codes 와 합침")
    ap.add_argument("--top", type=int, default=60, help="기본 대상일 때 상세 리포트 우선순위 상위 몇 종목")
    ap.add_argument("--max-calls", type=int, default=400)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    codes = _uniq(a.codes.replace(" ", ",").split(",")) if a.codes.strip() else []
    if a.chain.strip():
        codes = _uniq(codes + chain_codes(a.chain.strip()))
    if not codes:
        codes = default_codes(a.top)
    log.info("대상 %d종목: %s%s", len(codes), ",".join(codes[:12]), " …" if len(codes) > 12 else "")
    st = update(codes, max_calls=a.max_calls)
    print(json.dumps(st, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
