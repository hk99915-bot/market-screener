"""종목 한 줄 설명(겸이 10/24 "각 티커에서 이 회사가 뭐 하는 회사인지 한 줄") → reports/company_oneliner.json.

산출물(화면 표시용, 작게):
  reports/company_oneliner.json  {"asof","src_note","n":{KR,US},"KR":{code:{"line","industry","src","kind"?}},"US":{...}}
근거(검수용, 화면 미사용):
  reports/company_oneliner_ev.json {"asof","KR":{code:{"ev","sector","industry","at"}},"US":{...}}
  ev = 원천 영문/국문 요약의 **첫 문장만**(200자 이내) — 원문 전문은 저장하지 않는다.

원천(2026-10-24 데이터 데스크 실조회):
  - KR 1순위 KRX KIND 상장법인목록(corpList.do?method=download, 업종·주요제품 칸, EUC-KR HTML 표).
    이 컨테이너(클로드 샌드박스)는 403(Akamai) — Actions 에서 시도하고 실패하면 다음 순위로.
    KIND 가 되면 비어 있는 종목만 "{업종} · 주요제품 {주요제품}" 을 45자 안으로 다듬어 채운다(src='kind').
  - KR·US 공통 근거: 야후 quoteSummary assetProfile(sector·industry·longBusinessSummary 첫 문장).
    yfinance Ticker.info 는 401(Invalid Crumb) → fc.yahoo.com 쿠키 + getcrumb 직접 호출로 같은 엔드포인트를 읽는다.
    이 근거로 한국어 한 줄은 데이터 에이전트가 쓴다(src='yahoo+agent') — `todo` 로 배치를 뽑고 `apply` 로 병합.
  - ETF 는 상세 json etf.base(기초지수)로 기계 생성("코스피 200 추종 ETF", src='etf').
  - 우선주·스팩·리츠·ETN 은 이름 규칙으로 유형 표기(src='type').
증분: 줄이 있는 종목은 건드리지 않는다. 근거가 RECHECK_DAYS(분기) 넘게 묵은 종목만 다시 조회 — 근거 첫 문장이 바뀌면
  recheck=True 로 표시(줄은 유지, 사람이 다시 읽어 고친다).
못 쓴 종목은 line="" (화면 '설명 대기'). 공개 저장소 — 전 종목 공통 사실만, 보유·개인 정보 없음.

CLI:
  python -m screener.oneliner fetch KR|US [--budget N] [--full]   # 근거 조회(+KIND·ETF·유형 줄) — 네트워크
  python -m screener.oneliner todo US [N]                          # 줄 없는 종목 N개 TSV(sym, name, sector, industry, ev)
  python -m screener.oneliner apply US lines.tsv                   # 에이전트가 쓴 'sym<TAB>line' 병합
  python -m screener.oneliner stats                                # 커버리지
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
STORE = REPORT_DIR / "company_oneliner.json"
EV_STORE = REPORT_DIR / "company_oneliner_ev.json"
RECHECK_DAYS = 92
EV_MAX = 200
LINE_MAX = 50
PENDING = "설명 대기"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
KIND_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
YH_PROFILE = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}?modules=assetProfile&crumb={crumb}"
SRC_NOTE = ("KR: KRX KIND 상장법인목록 업종·주요제품(되면) / 야후 assetProfile 첫 문장을 근거로 데이터 데스크가 쓴 한국어 한 줄. "
            "US: 야후 assetProfile(sector·industry·사업 요약 첫 문장) 근거 한국어 한 줄. ETF=기초지수, 우선주·스팩·리츠=유형 표기. "
            "근거 첫 문장은 reports/company_oneliner_ev.json. 사업 내용 요약일 뿐 평가·전망 아님.")
# 홍보·전망 문구 — 한 줄에 넣지 않는다(apply 가 거부)
BANNED = ("선도", "최고", "최대 규모", "혁신적", "세계적", "글로벌 리더", "유망", "성장 기대", "전망", "1위")


# ---------- 유형 판정 ----------
def kind_of(name: str, is_etf: bool = False) -> str | None:
    n = (name or "").strip()
    if is_etf:
        return "ETF"
    if re.search(r"ETN", n):
        return "ETN"
    if "스팩" in n or re.search(r"기업인수목적", n):
        return "스팩"
    if "리츠" in n:   # 국내 이름 규칙만 — 미장 REIT 는 사업(타워·창고 등)이 달라 개별 줄로
        return "리츠"
    if re.search(r"\d?우[BC]?$|우\(전환\)$", n):
        return "우선주"
    return None


def pref_base(name: str) -> str:
    return re.sub(r"\d?우[BC]?$|우\(전환\)$", "", name.strip())


def clean_base(base: str) -> str:
    """기초지수 이름 다듬기: 산출 방식 괄호((PR)·(TR)·(Price Return)·(시장가격)·(총수익) 등)·'Index' 정리."""
    b = re.sub(r"\s*\((?:P\.?R\.?|T\.?R\.?|Price Return|Total Return|Net Total Return|NTR|시장가격(?:\s*지수)?|가격(?:\s*지수)?|"
               r"총수익(?:\s*지수)?|원화환산|원화 환산|USD|KRW)\)", "", base or "", flags=re.I)
    b = re.sub(r"\bIndex\b", "지수", b)
    b = re.sub(r"\s+", " ", b).strip()
    return b


def etf_line(name: str, base: str | None) -> str:
    """국내 ETF: 기초지수 + 성격(액티브·레버리지·인버스·커버드콜). 45자 넘으면 지수 이름을 줄인다."""
    n = name or ""
    tags = []
    if re.search(r"인버스", n):
        tags.append("인버스" + ("2X" if re.search(r"2X|곱버스", n) else ""))
    elif re.search(r"레버리지|2X", n):
        tags.append("레버리지")
    if "커버드콜" in n:
        tags.append("커버드콜")
    b = clean_base(base or "")
    act = "액티브" in n
    if tags:   # 지수 이름에 이미 들어 있는 성격 표기는 꼬리에서 뺀다
        tags = [t for t in tags if t.rstrip("2X") not in b]
    tail = (" 비교지수 액티브" if act else " 추종") if b else ""
    if not b:   # 기초지수 미상 → 이름에서 운용사 상표만 뗀다
        b = re.sub(r"^\S+\s+", "", n).replace("액티브", "").strip() or n
        tail = " 투자" + (" 액티브" if act else "")
    kind = " " + ("·".join(tags) + " " if tags else "") + "ETF"
    room = 45 - len(tail) - len(kind)
    if len(b) > room:
        b = b[: room - 1].rstrip() + "…"
    return f"{b}{tail}{kind}"


def type_line(kind: str, name: str) -> str:
    if kind == "우선주":
        return f"{pref_base(name)} 우선주(의결권 제한·배당 우선)"
    if kind == "스팩":
        return "기업인수목적회사(스팩) — 비상장사 합병이 목적인 상장 페이퍼컴퍼니"
    if kind == "리츠":
        return "부동산투자회사(리츠) — 부동산 임대수익을 배당하는 회사"
    if kind == "ETN":
        return "상장지수증권(ETN) — 증권사가 지수 수익을 약속하는 채권형 상품"
    return ""


# ---------- 문장 다듬기 ----------
_ABBR = {"Inc", "Corp", "Co", "Ltd", "No", "St", "Mr", "Dr", "vs", "etc", "Jr", "Sr", "Bros", "Mt", "Ft", "approx", "Intl"}

def first_sentence(text: str | None, n: int = EV_MAX) -> str:
    """요약의 첫 문장(약어 'Inc.'·'Co.' 등에서 끊지 않음), n자 이내."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not t:
        return ""
    end = None
    for m in re.finditer(r"[.。](?=\s+[A-Z가-힣\"(]|$)", t):
        w = re.search(r"([\w.]+)$", t[: m.start()])
        w = w.group(1) if w else ""
        if w in _ABBR or re.fullmatch(r"[A-Z]", w) or re.fullmatch(r"(?:[A-Za-z]\.)+[A-Za-z]", w):
            continue
        end = m.end()
        break
    s = t[:end] if end else t
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def check_line(line: str, kind: str | None = None) -> list[str]:
    """한 줄 규칙 위반 목록(빈 목록 = 통과): 길이·홍보·수치. ETF 는 지수 이름 속 숫자(15%·90% 참여 등)를 허용."""
    errs = []
    s = (line or "").strip()
    if not s:
        errs.append("빈 줄")
    if len(s) > LINE_MAX:
        errs.append(f"{len(s)}자 > {LINE_MAX}")
    for w in BANNED:
        if w in s:
            errs.append(f"홍보·전망 문구 '{w}'")
    if kind != "ETF" and (re.search(r"\d+(\.\d+)?\s*(%|조|억|만|bn|billion|million|달러|원)\b", s) or "%" in s or "$" in s):
        errs.append("수치·금액")
    return errs


# ---------- KIND ----------
def parse_kind(text: str) -> dict[str, dict]:
    """KIND corpList 다운로드(HTML 표) → {종목코드6: {name, industry, products}}. 헤더 이름으로 열을 찾는다."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S | re.I)
    out: dict[str, dict] = {}
    hdr: list[str] | None = None
    for r in rows:
        cells = [re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, flags=re.S | re.I)]
        cells = [_html.unescape(c).replace("\xa0", " ").strip() for c in cells]
        if not cells:
            continue
        if hdr is None:
            if any("종목코드" in c for c in cells):
                hdr = cells
            continue
        rec = dict(zip(hdr, cells))
        code = re.sub(r"\D", "", rec.get("종목코드", ""))[:6].zfill(6) if rec.get("종목코드") else ""
        if not code or code == "000000":
            continue
        out[code] = {"name": rec.get("회사명", ""), "industry": rec.get("업종", ""), "products": rec.get("주요제품", "")}
    return out


def kind_line(industry: str, products: str) -> str:
    """'{업종} · 주요제품 {주요제품}' → 45자 안으로(제품은 쉼표 단위로 자른다)."""
    ind = re.sub(r"\s*(제조업|업)$", "", (industry or "").strip()) or (industry or "").strip()
    prods = [p.strip() for p in re.split(r"[,，、/]", products or "") if p.strip()]
    if not prods:
        return ind
    s = f"{ind} · 주요제품 {prods[0]}"
    for p in prods[1:]:
        if len(s) + 2 + len(p) > 45:
            break
        s += f", {p}"
    return s if len(s) <= LINE_MAX else s[: LINE_MAX - 1] + "…"


def fetch_kind(timeout: int = 40) -> dict[str, dict]:
    import requests
    r = requests.get(KIND_URL, headers={"User-Agent": UA, "Referer": "https://kind.krx.co.kr/corpgeneral/corpList.do?method=loadInitPage"},
                     timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"KIND {r.status_code}")
    r.encoding = "euc-kr"
    return parse_kind(r.text)


# ---------- 야후 ----------
class Blocked(RuntimeError):
    """원천 전체 차단(crumb·429 연속) — 종목 실패로 기록하지 않고 이번 실행을 멈춘다."""


class Yahoo:
    def __init__(self, gap: float = 0.25):
        import requests
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Mozilla/5.0"   # 긴 브라우저 UA·curl_cffi 는 getcrumb 429(10/24 실측), 짧은 UA 는 200
        self.gap = gap
        self.crumb = None

    def _crumb(self) -> str:
        if not self.crumb:
            try:
                self.s.get("https://fc.yahoo.com", timeout=15)
            except Exception:  # noqa: BLE001 — 404 여도 쿠키는 받는다
                pass
            c = ""
            for k in range(3):   # getcrumb 이 'Too Many Requests'(평문 200/429)면 쉬었다 재시도
                c = self.s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15).text.strip()
                if c and "<" not in c and " " not in c and len(c) <= 40:
                    break
                time.sleep(15 * (k + 1))
            else:
                raise Blocked(f"야후 crumb 실패: {c[:60]!r}")
            self.crumb = c
        return self.crumb

    def profile(self, sym: str) -> dict | None:
        for k in range(2):
            r = self.s.get(YH_PROFILE.format(sym=sym, crumb=self._crumb()), timeout=20)
            time.sleep(self.gap)
            if r.status_code == 401 and k == 0:
                self.crumb = None
                continue
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                time.sleep(5)
                continue
            if r.status_code != 200:
                raise RuntimeError(f"야후 {sym} {r.status_code}")
            res = ((r.json().get("quoteSummary") or {}).get("result") or [None])[0] or {}
            p = res.get("assetProfile") or {}
            return {"sector": p.get("sector") or "", "industry": p.get("industry") or "",
                    "ev": first_sentence(p.get("longBusinessSummary") or p.get("description"))}
        raise Blocked(f"야후 {sym} 429/401 연속")


# ---------- 저장 ----------
def _today() -> date:
    return datetime.now(KST).date()


def load(path: Path = STORE) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def empty(today: date | None = None) -> dict:
    return {"asof": (today or _today()).isoformat(), "src_note": SRC_NOTE, "n": {}, "KR": {}, "US": {}}


def save(store: dict, ev: dict, today: date | None = None, store_path: Path = STORE, ev_path: Path = EV_STORE) -> None:
    from . import guard
    t = (today or _today()).isoformat()
    store["asof"], store["src_note"] = t, SRC_NOTE
    store["n"] = {m: {"total": len(store.get(m) or {}), "line": sum(1 for v in (store.get(m) or {}).values() if v.get("line"))}
                  for m in ("KR", "US")}
    for m in ("KR", "US"):   # 정렬 저장(diff 안정) — 제자리 정렬: update() 가 잡고 있는 dict 참조를 바꾸면 중간 저장 뒤 진행분이 사라진다
        for d in (store.setdefault(m, {}), ev.setdefault(m, {})):
            items = sorted(d.items())
            d.clear()
            d.update(items)
    ev["asof"] = t
    guard.write_json(store_path, store, indent=0, separators=(",", ":"))
    guard.write_json(ev_path, ev, indent=0)


def universe(market: str) -> dict[str, dict]:
    """상세 색인(reports/detail/<m>/_index.json) 종목 → {sym: {name, etf, base}}."""
    d = json.loads((REPORT_DIR / "detail" / market / "_index.json").read_text(encoding="utf-8"))
    etf = set(d.get("etf") or [])
    out = {}
    for s in d.get("symbols") or []:
        out[s] = {"name": (d.get("names") or {}).get(s, s), "etf": s in etf, "base": None}
        if s in etf:
            try:
                e = json.loads((REPORT_DIR / "detail" / market / f"{s}.json").read_text(encoding="utf-8")).get("etf") or {}
                out[s]["base"] = e.get("base")
                out[s]["summary"] = first_sentence(e.get("summary"))
                out[s]["category"] = e.get("category")
            except (FileNotFoundError, ValueError):
                pass
    return out


_KR_YF: dict[str, str] = {}


def yahoo_sym(market: str, sym: str) -> list[str]:
    """야후 심볼 후보 — KR 은 universe/kr.csv 의 yf(.KS/.KQ) 먼저."""
    if market == "US":
        return [sym.replace(".", "-")]
    if not _KR_YF:
        import csv
        from .config import UNIVERSE_DIR
        try:
            with open(UNIVERSE_DIR / "kr.csv", encoding="utf-8") as f:
                _KR_YF.update({r["symbol"].zfill(6): r["yf"] for r in csv.DictReader(f) if r.get("yf")})
        except FileNotFoundError:
            pass
    first = _KR_YF.get(sym)
    alt = [f"{sym}.KS", f"{sym}.KQ"]
    return [first] + [a for a in alt if a != first] if first else alt


def update(market: str, budget: int = 150, full: bool = False, today: date | None = None,
           uni: dict | None = None, yahoo: Callable[[str], dict | None] | None = None,
           kind: Callable[[], dict] | None = None, store: dict | None = None, ev: dict | None = None,
           write: bool = True) -> dict:
    """증분 갱신 — ① ETF·유형 줄(무료, 즉시) ② KR KIND 줄(빈 종목만) ③ 야후 근거(근거 없음 또는 분기 경과, budget 개)."""
    today = today or _today()
    uni = uni if uni is not None else universe(market)
    store = store if store is not None else (load() or empty(today))
    ev = ev if ev is not None else (load(EV_STORE) or {"KR": {}, "US": {}})
    S, E = store.setdefault(market, {}), ev.setdefault(market, {})
    stat = {"market": market, "universe": len(uni), "etf_type": 0, "kind": 0, "yahoo": 0, "yahoo_fail": 0, "recheck": 0}
    for s in list(S):   # 유니버스에서 빠진 종목은 정리(상폐·편출)
        if s not in uni:
            S.pop(s, None)
            E.pop(s, None)
    for s, u in uni.items():
        k = kind_of(u["name"], u.get("etf"))
        rec = S.setdefault(s, {"line": "", "industry": "", "src": ""})
        if k and not rec.get("line"):
            rec["line"] = etf_line(u["name"], u.get("base")) if k == "ETF" and market == "KR" else (type_line(k, u["name"]) if k != "ETF" else "")
            rec["kind"] = k
            if rec["line"]:
                rec["src"] = "etf" if k == "ETF" else "type"
                rec["industry"] = rec.get("industry") or (u.get("category") or k)
                stat["etf_type"] += 1
            if k == "ETF" and u.get("summary"):
                E.setdefault(s, {"ev": u["summary"], "sector": "", "industry": u.get("category") or "", "at": today.isoformat()})
    if market == "KR":
        need = [s for s, v in S.items() if not v.get("line") or v.get("src") == "kind"]
        if need:
            try:
                kd = (kind or fetch_kind)()
                for s in need:
                    r = kd.get(s)
                    if r and r.get("industry"):
                        ln = kind_line(r["industry"], r.get("products", ""))
                        if not S[s].get("line"):
                            S[s].update(line=ln, industry=r["industry"], src="kind")
                            stat["kind"] += 1
                        E.setdefault(s, {})["kind"] = f"{r['industry']} | {r.get('products', '')}"[:EV_MAX]
            except Exception as e:  # noqa: BLE001
                log.warning("KIND 실패(야후 근거로 계속): %s", e)
                stat["kind_err"] = str(e)[:80]
    # 야후 근거: 근거 없음 먼저, 다음 분기 경과
    def stale(s):
        at = (E.get(s) or {}).get("at")
        try:
            return full or (date.fromisoformat(at) - today).days <= -RECHECK_DAYS
        except (TypeError, ValueError):
            return True
    # 근거 조회 대상: 유형 줄(ETF·우선주·스팩·리츠·ETN) 아닌 종목만. 실패 기록(at 만 있음)도 분기 뒤 재시도
    order = [s for s in uni if not S[s].get("kind") and not (E.get(s) or {}).get("at")] + \
            [s for s in uni if not S[s].get("kind") and (E.get(s) or {}).get("at") and stale(s)]
    if order and budget > 0:
        yh = yahoo
        if yh is None:
            y = Yahoo()
            yh = y.profile
        for s in order[:budget]:
            got = None
            try:
                for ys in yahoo_sym(market, s):
                    got = yh(ys)
                    if got and (got.get("ev") or got.get("industry")):
                        break
            except Blocked as e:   # 원천 차단 — 남은 종목은 '시도 안 함'으로 두고 다음 실행에서 이어서
                log.warning("야후 차단, 중단(%d/%d): %s", stat["yahoo"], len(order[:budget]), e)
                stat["blocked"] = str(e)[:80]
                break
            except Exception as e:  # noqa: BLE001
                log.warning("야후 %s: %s", s, e)
            if not got or not (got.get("ev") or got.get("industry")):
                stat["yahoo_fail"] += 1
                E.setdefault(s, {})["at"] = today.isoformat()
                continue
            old = (E.get(s) or {}).get("ev")
            if old and got.get("ev") and old != got["ev"] and S[s].get("line"):
                S[s]["recheck"] = True
                stat["recheck"] += 1
            E[s] = {**(E.get(s) or {}), "ev": got.get("ev", ""), "sector": got.get("sector", ""),
                    "industry": got.get("industry", ""), "at": today.isoformat()}
            if not S[s].get("industry"):
                S[s]["industry"] = got.get("industry", "")
            stat["yahoo"] += 1
            if write and stat["yahoo"] % 100 == 0:   # 중간 저장(긴 실행이 끊겨도 진행분 보존)
                save(store, ev, today)
    stat["line"] = sum(1 for v in S.values() if v.get("line"))
    stat["pending"] = len(S) - stat["line"]
    if write:
        save(store, ev, today)
    return stat


def todo(market: str, n: int = 100, store: dict | None = None, ev: dict | None = None) -> list[dict]:
    store, ev = store or load(), ev or load(EV_STORE)
    names = {}
    try:
        names = json.loads((REPORT_DIR / "detail" / market / "_index.json").read_text(encoding="utf-8")).get("names") or {}
    except (FileNotFoundError, ValueError):
        pass
    out = []
    for s, v in (store.get(market) or {}).items():
        if v.get("line") and not v.get("recheck"):
            continue
        e = (ev.get(market) or {}).get(s) or {}
        out.append({"sym": s, "name": names.get(s, ""), "sector": e.get("sector", ""), "industry": e.get("industry", ""),
                    "ev": e.get("ev", ""), "kind": e.get("kind", "")})
        if len(out) >= n:
            break
    return out


def apply(market: str, lines: dict[str, str], src: str = "yahoo+agent", store: dict | None = None,
          write: bool = True, today: date | None = None) -> dict:
    """에이전트가 쓴 한 줄 병합. 규칙 위반(check_line) 줄은 거부하고 목록으로 돌려준다."""
    store = store if store is not None else load()
    ev = load(EV_STORE) or {"KR": {}, "US": {}}
    S = store.setdefault(market, {})
    ok, bad = 0, {}
    for s, ln in lines.items():
        ln = (ln or "").strip()
        errs = check_line(ln, (S.get(s) or {}).get("kind"))
        if s not in S:
            errs.append("유니버스 밖")
        if errs:
            bad[s] = errs
            continue
        S[s]["line"] = ln
        S[s]["src"] = src
        S[s].pop("recheck", None)
        if not S[s].get("industry"):
            S[s]["industry"] = ((ev.get(market) or {}).get(s) or {}).get("industry", "")
        ok += 1
    if write:
        save(store, ev, today)
    return {"applied": ok, "rejected": bad}


def read_tsv(path: str) -> dict[str, str]:
    out = {}
    for row in Path(path).read_text(encoding="utf-8").splitlines():
        if "\t" in row and not row.startswith("#"):
            k, v = row.split("\t", 1)
            out[k.strip()] = v.strip()
    return out


def stats(store: dict | None = None) -> dict:
    store = store or load()
    out = {}
    for m in ("KR", "US"):
        S = store.get(m) or {}
        src = {}
        for v in S.values():
            if v.get("line"):
                src[v.get("src") or "?"] = src.get(v.get("src") or "?", 0) + 1
        out[m] = {"total": len(S), "line": sum(1 for v in S.values() if v.get("line")), "by_src": src,
                  "recheck": sum(1 for v in S.values() if v.get("recheck"))}
    return out


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "fetch":
        m = argv[1]
        budget = int(argv[argv.index("--budget") + 1]) if "--budget" in argv else 150
        print(json.dumps(update(m, budget=budget, full="--full" in argv), ensure_ascii=False))
    elif cmd == "todo":
        n = int(argv[2]) if len(argv) > 2 else 100
        for r in todo(argv[1], n):
            print("\t".join([r["sym"], r["name"], r["sector"], r["industry"], r["kind"], r["ev"]]))
    elif cmd == "apply":
        r = apply(argv[1], read_tsv(argv[2]))
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
