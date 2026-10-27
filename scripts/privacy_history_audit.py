"""공개 저장소 개인정보 전수 감사 — git 전체 이력 + 현재 트리(공개 브랜치 끝) + 공개 Pages (10/27 감사 데스크).

배경: 외부 모델이 공개 저장소·Pages 만 보고 오너 개인 금액을 언급(10/27). 10/25 유출 사고(감사 req-pb-9e7fce79) 후속 전수 감사.
탐지(값은 절대 출력·저장하지 않는다 — 결과는 범위·파일·줄·커밋·종류·문맥어·숫자를 9로 가린 미리보기뿐):
  amount     screener.redact.personal_amount_hits (원화 금액 + 개인 문맥어, 허용 목록 적용)
  email      screener.redact.public_emails (허용 목록 밖 이메일)
  ctx_amount 순자산|순금융|가용자산|월 적립|저축|연봉|지원금|용돈|보유 문맥 + 원화 금액 (허용 목록 미적용 — 분류로 오탐 처리)
  birth      생년월일·생일·출생 문맥 + 날짜, 주민번호 꼴
  account    계좌·은행 문맥 + 계좌번호 꼴(3~4 묶음 숫자-숫자-숫자)
  qty_ctx    보유·평단·매입가 문맥 + 'N주'
  holding    (--private-dir) 오너 보유 종목코드·티커 + 실제 보유 수량 'N주' (이름·수량은 비공개 저장소에서 실행 중에만 읽음)
  private    (--private-dir) 비공개 장부의 실제 금액(현금성·예적금·투자자산·순자산 합·ISA 월 적립)이 쉼표·만·억·M 꼴로 나타남
시장 데이터(reports/detail·data/·*.parquet·live·heatmap 등)는 스캔하지 않고 변경 건수만 따로 센다.

  python3 scripts/privacy_history_audit.py                         # 이력(--all) + 현재 트리 + 공개 브랜치 끝
  python3 scripts/privacy_history_audit.py --pages --private-dir ../pb-private
  python3 scripts/privacy_history_audit.py --no-history --json /tmp/x.json
종료코드: 0 = 검토 필요(review) 히트 없음, 1 = 있음.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screener.redact import ALLOW_RX_AMT, AMOUNT_RX, personal_amount_hits, public_emails  # noqa: E402

# 시장 데이터 — 내용 스캔 제외, 변경 건수만 집계
MARKET_PATHSPEC = ["reports/detail", "data", "*.parquet", "reports/live.json", "live.json", "daily_today.json",
                   "reports/heatmap_*", "reports/events_stats.json", "reports/intraday_last.json", "reports/daily_hist",
                   "daily_bars.json", "crosscheck.json", "sectors.json", "us_eod.json", "reports/*/daily_bars.json"]
MARKET_RX = re.compile(r"^(?:reports/detail/|data/|reports/daily_hist/|reports/heatmap_)|\.parquet$|"
                       r"(?:^|/)(?:live|daily_today|daily_bars|crosscheck|sectors|us_eod|events_stats|intraday_last)\.json$")
BIN_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".zip", ".gz", ".parquet", ".xlsx")
MAX_LINE = 200_000

CTX_RX = re.compile(r"순자산|순금융|가용자산|월\s?적립|저축|연봉|지원금|용돈|보유|청약|납입|식대|부모님")
BIRTH_CTX = re.compile(r"생년월일|생일|출생|태어난|birth", re.I)
DATE_RX = re.compile(r"(?<!\d)(?:19|20)\d\d\s?[-./년]\s?\d{1,2}\s?[-./월]\s?\d{1,2}(?!\d)|(?<!\d)\d{6}(?!\d)")
RRN_RX = re.compile(r"(?<![\d-])\d{6}-[1-4]\d{6}(?![\d-])")
ACCOUNT_RX = re.compile(r"(?<![\d-])\d{3,6}-\d{2,6}-\d{2,8}(?:-\d{1,3})?(?![\d-])")
ACCOUNT_CTX = re.compile(r"계좌|은행|account|입금|예금주", re.I)
QTY_RX = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})*\s?주(?![가-힣])(?!\s?(?:내|안|간|뒤|후|고|저|동안|째|보유\s?[≈엔]|대화|위치|,|\)))")
QTY_CTX = re.compile(r"보유|평단|매입가|(?<![가-힣])내\s|나의")
SYNTH_RX = re.compile(r"예시|예:|예를 들|가상|가정|모의|합성|fake|dummy|sample|\"notional\"|백테스트|적립 IRR|\"(?:analogy|example|q|exp)\":", re.I)
OWNER_RX = re.compile(r"겸이|오너\s?(?:개인|본인)|부모님")   # 오너 개인 문맥은 규정·시장 허용보다 먼저 검토로
REG_RX = re.compile(r"\[규정\]|시행령|세법|세액공제|공제|납입 한도|인정액|LTV|양도세|보금자리|디딤돌|국토부|금융위|비과세|분리과세")
PLAN_RX = re.compile(r"진입|손절|목표|\d\.?\d*R\b|롱|숏|헤지|잔고 (?:감소|증가)|공매도 잔고")
REF_RX = re.compile(r"\.(?:py|html|md|json|txt):\d")
MOCK_PATH = re.compile(r"^content/|^docs/desk_kb/rounds/[^/]*-hf-|^reports/hf_|^reports/idea_tracking|^reports/studies/")
GOAL_RX = re.compile(r"(?:순자산|자산)\s?목표|목표\s?(?:순자산|자산|금액)|\d\s?억\s?(?:\+|모으|달성|까지)")
WIN = 40
CLS_WIN = 80
TIGHT_WIN = 20
PAGES_URL = "https://hk99915-bot.github.io/market-screener/"


@dataclass
class Hit:
    scope: str           # tree | branch:<name> | history | message | pages
    path: str
    line: int
    kind: str
    ctx: str = ""        # 문맥어(값 아님)
    commit: str = ""
    category: str = ""   # review | synthetic | edu_mock | regulation | ref | date | owner_excluded | market | self
    preview: str = ""    # 숫자 → 9, 이메일·종목 → 가림
    public: bool = True
    _key: tuple = field(default=(), repr=False)   # 메모리 비교용(값 포함) — 출력 금지


def mask(text: str, names: set[str] | None = None) -> str:
    s = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", "[email]", text)
    for n in names or ():
        s = re.sub(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])", "[종목]", s)
    return re.sub(r"\d", "9", s)


# ---------------------------------------------------------------- 비공개 지문 (실행 중 메모리만)
def _num(s: str) -> int | None:
    try:
        return int(float(s.replace(",", "")))
    except ValueError:
        return None


def load_private(pdir: Path) -> tuple[list[int], dict[str, int]]:
    """비공개 장부에서 실제 금액(원)과 보유 {코드·티커: 수량}. 반환값은 출력하지 않는다."""
    vals: list[int] = []
    hold: dict[str, int] = {}
    h = pdir / "holdings.txt"
    if h.exists():
        for ln in h.read_text(encoding="utf-8").splitlines():
            t = ln.split()
            if ln.startswith("#") or not t:
                m = re.search(r"순자산총액\s*([\d,]+)", ln)
                if m and _num(m.group(1)):
                    vals.append(_num(m.group(1)))
                continue
            if t[0] in ("현금", "예적금", "ISA적립") and len(t) > 1 and _num(t[1]):
                vals.append(_num(t[1]))
            elif len(t) >= 2 and re.fullmatch(r"[A-Z]{1,5}|\d{6}", t[0]) and re.fullmatch(r"\d+", t[1]):
                hold[t[0]] = hold.get(t[0], 0) + int(t[1])
    for name in ("balances.csv", "networth_monthly.csv"):
        f = pdir / "household" / name
        if not f.exists():
            continue
        for row in csv.DictReader(f.open(encoding="utf-8")):
            nums = {k: _num(v) for k, v in row.items() if k and v and re.fullmatch(r"[\d,.]+", v or "")}
            nums = {k: v for k, v in nums.items() if v and v >= 1_000_000}
            vals += list(nums.values())
            if len(nums) >= 2:
                vals.append(sum(nums.values()))
    return sorted({v for v in vals if v >= 1_000_000}), hold


def private_forms(vals: list[int]) -> tuple[re.Pattern | None, re.Pattern | None]:
    """(정확 패턴, 반올림 패턴). 정확 숫자·쉼표는 문맥 없이, 반올림 꼴(만·억·M)은 개인 문맥어가 있어야 히트."""
    exact, rough = set(), set()
    for v in vals:
        exact |= {f"{v:,}", str(v)}
        man = round(v / 10_000)
        rough |= {f"{man:,}만", f"{man}만", f"{man:,} 만", f"{man} 만", f"{v / 1e8:.1f}억", f"{v / 1e8:.2f}억", f"{v / 1e6:.1f}M"}
    rough = {r for r in rough if not r.startswith(("0.", "0억"))}

    def alt(xs):
        return re.compile(r"(?<![\d,.])(?:" + "|".join(map(re.escape, sorted(xs, key=len, reverse=True))) + r")(?![\d,])") if xs else None
    return alt(exact), alt(rough)


# ---------------------------------------------------------------- 탐지
class Scanner:
    def __init__(self, private_dir: Path | None = None):
        self.vals, self.hold = load_private(private_dir) if private_dir else ([], {})
        self.exact_rx, self.rough_rx = private_forms(self.vals)
        self.names = set(self.hold)
        self.hold_rx = (re.compile(r"(?<![A-Za-z0-9])(" + "|".join(map(re.escape, sorted(self.hold, key=len, reverse=True)))
                                   + r")(?![A-Za-z0-9])") if self.hold else None)

    def line(self, text: str) -> list[tuple[str, str, tuple]]:
        """(kind, ctx, key) 목록. key 는 값을 담으므로 메모리 비교에만 쓴다."""
        if not text or len(text) > MAX_LINE:
            return []
        out: list[tuple[str, str, tuple]] = []
        if not any(c.isdigit() for c in text):
            return [("email", "", ("email", e.lower())) for e in public_emails(text)] if "@" in text else []
        amt_seen = set()
        for sig in personal_amount_hits(text):
            v, _, c = sig.partition("|")
            amt_seen.add(v)
            out.append(("amount", c, ("amount", v)))
        for e in (public_emails(text) if "@" in text else ()):
            out.append(("email", "", ("email", e.lower())))
        for m in AMOUNT_RX.finditer(text):
            s = m.group(0)
            if s in amt_seen or not re.search(r"[,원억만M]", s) or (_num(re.match(r"[\d,.]+", s).group(0)) or 0) == 0:
                continue
            cm = CTX_RX.search(text[max(0, m.start() - WIN): m.end() + WIN])
            if cm:
                out.append(("ctx_amount", cm.group(0), ("amount", s)))
        if BIRTH_CTX.search(text):
            for m in DATE_RX.finditer(text):
                if BIRTH_CTX.search(text[max(0, m.start() - 30): m.end() + 30]):
                    out.append(("birth", "", ("birth", m.group(0))))
        for m in RRN_RX.finditer(text):
            out.append(("birth", "주민번호꼴", ("rrn", m.group(0))))
        for m in ACCOUNT_RX.finditer(text):
            if ACCOUNT_CTX.search(text[max(0, m.start() - 30): m.end() + 30]):
                out.append(("account", "", ("account", m.group(0))))
        for m in QTY_RX.finditer(text):
            cm = QTY_CTX.search(text[max(0, m.start() - 30): m.end() + 30])
            if cm:
                out.append(("qty_ctx", cm.group(0).strip(), ("qty", m.group(0))))
        if self.hold_rx and "주" in text:
            for m in self.hold_rx.finditer(text):
                q = self.hold[m.group(1)]
                if re.search(rf"(?<![\d,.]){q}\s?주(?![가-힣])", text[m.end(): m.end() + 25]):
                    out.append(("holding", "", ("holding", m.group(1), q)))
        for rx, need_ctx in ((self.exact_rx, False), (self.rough_rx, True)):
            for m in (rx.finditer(text) if rx else ()):
                if need_ctx and not CTX_RX.search(text[max(0, m.start() - WIN): m.end() + WIN]):
                    continue
                out.append(("private", "문맥" if need_ctx else "정확", ("private", m.group(0))))
        return out

    def classify(self, path: str, text: str, kind: str, tight: str | None = None) -> str:
        """text = 히트 앞뒤 CLS_WIN 자, tight = 앞뒤 TIGHT_WIN 자. 허용(규정·시장·참조)은 값 바로 옆 문맥으로만 판단한다."""
        tight = text if tight is None else tight
        if path.startswith("tests/") or path == "scripts/privacy_history_audit.py":
            return "self" if "privacy" in path or "redact" in path or "personal_amount" in path else "synthetic"
        if kind == "account" and re.search(r"(?<!\d)(?:19|20)\d\d-\d{1,2}-\d{1,2}(?!\d)", tight) and not re.search(r"계좌번호|account no", text, re.I):
            return "date"
        if SYNTH_RX.search(tight):
            return "synthetic"
        if kind in ("amount", "ctx_amount") and GOAL_RX.search(tight):
            return "owner_excluded"   # 10/24 겸이 결정: 순자산 '목표' 금액은 이슈 아님
        if kind in ("private", "holding", "birth") or (kind in ("amount", "ctx_amount") and OWNER_RX.search(text)):
            return "review"
        if MOCK_PATH.search(path):
            return "edu_mock"
        if REF_RX.search(tight) and kind in ("amount", "ctx_amount", "account"):
            return "ref"
        if REG_RX.search(tight):
            return "regulation"
        if kind in ("amount", "ctx_amount", "qty_ctx") and (ALLOW_RX_AMT.search(tight) or PLAN_RX.search(tight)):
            return "market"
        return "review"

    def hits(self, scope: str, path: str, lineno: int, text: str, commit: str = "") -> list[Hit]:
        """분류·미리보기는 히트 주변 창(앞뒤 CLS_WIN 자)으로 — 한 줄짜리 큰 JSON 에서 먼 '예시' 가 실제 누출을 가리지 않게."""
        res, seen = [], set()
        for kind, ctx, key in self.line(text):
            if (kind, key) in seen:
                continue
            seen.add((kind, key))
            pos = text.find(str(key[1])) if len(key) > 1 else -1
            n = len(str(key[1]))
            win = text if pos < 0 else text[max(0, pos - CLS_WIN): pos + n + CLS_WIN]
            tight = text if pos < 0 else text[max(0, pos - TIGHT_WIN): pos + n + TIGHT_WIN]
            res.append(Hit(scope, path, lineno, kind, ctx, commit, self.classify(path, win, kind, tight),
                           mask(win.strip(), self.names)[:120], True, (path, key)))
        return res


# ---------------------------------------------------------------- 출처별 순회
def git(*a: str, text: bool = True):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=text, check=True).stdout


def skip_path(p: str) -> bool:
    return bool(MARKET_RX.search(p)) or p.lower().endswith(BIN_EXT)


def scan_tree(sc: Scanner) -> list[Hit]:
    out = []
    for p in git("ls-files").splitlines():
        if skip_path(p):
            continue
        f = ROOT / p
        try:
            body = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, ln in enumerate(body.splitlines(), 1):
            out += sc.hits("tree", p, i, ln)
    return out


def scan_branch_tips(sc: Scanner, skip=("origin/main", "origin/HEAD")) -> list[Hit]:
    out = []
    for ref in git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").split():
        if ref in skip or ref == "origin":
            continue
        for p in git("ls-tree", "-r", "--name-only", ref).splitlines():
            if skip_path(p):
                continue
            try:
                body = git("show", f"{ref}:{p}", text=False).decode("utf-8")
            except (UnicodeDecodeError, subprocess.CalledProcessError):
                continue
            for i, ln in enumerate(body.splitlines(), 1):
                out += sc.hits(f"branch:{ref}", p, i, ln)
    return out


HUNK_RX = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")


def scan_history(sc: Scanner, refs: list[str]) -> tuple[list[Hit], int]:
    """git log -p (추가된 줄만) + 커밋 메시지. 반환: (히트, 스캔한 커밋 수)."""
    cmd = ["git", "-C", str(ROOT), "log", *refs, "-p", "-U0", "--no-color", "--no-renames", "--no-ext-diff",
           "--format=%x01%H%n%B%x02", "--", ".", *[f":(exclude){p}" for p in MARKET_PATHSPEC]]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    out: list[Hit] = []
    commit, path, ln_no, in_msg, msg_no, n = "", "", 0, False, 0, 0
    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if line.startswith("\x01"):
            commit, in_msg, msg_no, path, n = line[1:41], True, 0, "", n + 1
            continue
        if in_msg:
            if line.endswith("\x02"):
                in_msg = False
                line = line[:-1]
            msg_no += 1
            out += sc.hits("message", "(commit message)", msg_no, line, commit)
            continue
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
            continue
        if line.startswith("@@"):
            m = HUNK_RX.match(line)
            ln_no = int(m.group(1)) if m else 0
            continue
        if line.startswith("+") and path and not skip_path(path):
            out += sc.hits("history", path, ln_no, line[1:], commit)
            ln_no += 1
    proc.wait()
    return out, n


def market_changes(refs: list[str]) -> int:
    names = git("log", *refs, "--format=", "--name-only", "--", *MARKET_PATHSPEC)
    return sum(1 for x in names.splitlines() if x.strip())


def scan_pages(sc: Scanner, url: str) -> tuple[list[Hit], str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "privacy-audit (Claude noreply@anthropic.com)"})
        body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except Exception as e:   # 네트워크 실패는 결과에 적는다(조용히 넘기지 않음)
        return [], f"실패: {type(e).__name__}"
    out = []
    for i, ln in enumerate(body.splitlines(), 1):
        out += sc.hits("pages", url.rstrip("/").rsplit("/", 1)[-1] or "index.html", i, ln)
    return out, f"{len(body):,} bytes"


# ---------------------------------------------------------------- 정리
def dedupe_history(hist: list[Hit], current_keys: set) -> list[Hit]:
    """같은 (파일, 값)은 처음 들어온 커밋 1건만(git log 는 최신순 → 마지막 것이 최초). 현재 트리에 남은 것은 뺀다."""
    first: dict[tuple, Hit] = {}
    for h in hist:
        k = (h.scope, h._key, h.commit) if h.scope == "message" else h._key
        first[k] = h
    return [h for h in first.values() if h._key not in current_keys]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refs", default="--all", help="git log 범위 (기본 --all)")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--pages", nargs="?", const=PAGES_URL, default="", help=f"공개 Pages URL (값 없으면 {PAGES_URL})")
    ap.add_argument("--private-dir", default="", help="비공개 저장소 경로 — 실제 금액·보유 지문 (값은 출력 안 함)")
    ap.add_argument("--json", default="", help="가린 결과 JSON 저장 경로")
    ap.add_argument("--show", default="review", help="미리보기를 출력할 분류(쉼표, all)")
    a = ap.parse_args(argv)

    sc = Scanner(Path(a.private_dir) if a.private_dir else None)
    tree = scan_tree(sc)
    tips = scan_branch_tips(sc)
    current_keys = {h._key for h in tree + tips}
    refs = a.refs.split()
    hist, ncommit, nmarket = [], 0, 0
    if not a.no_history:
        raw, ncommit = scan_history(sc, refs)
        public = set(git("rev-list", "--remotes=origin").split())
        for h in raw:
            h.public = h.commit in public
        hist = dedupe_history(raw, current_keys)
        nmarket = market_changes(refs)
    pages, pmsg = scan_pages(sc, a.pages) if a.pages else ([], "건너뜀")

    allh = tree + tips + hist + pages
    show = None if a.show == "all" else set(a.show.split(","))
    print(f"# privacy_history_audit — 지문: 금액 {len(sc.vals)}개·보유 {len(sc.hold)}종(값 비공개) · 이력 커밋 {ncommit} · "
          f"시장데이터 변경(제외) {nmarket}건 · Pages {pmsg}")
    cnt = Counter((h.scope.split(":")[0], h.kind, h.category) for h in allh)
    for (s, k, c), v in sorted(cnt.items()):
        print(f"  {s:8s} {k:11s} {c:15s} {v}")
    for h in allh:
        if show is None or h.category in show:
            pub = "" if h.public else " (비공개 로컬 커밋)"
            print(f"- [{h.scope}] {h.path}:{h.line} {h.commit[:9]}{pub} {h.kind}/{h.ctx} {h.category} | {h.preview}")
    if a.json:
        rows = [{k: v for k, v in asdict(h).items() if k != "_key"} for h in allh]
        Path(a.json).write_text(json.dumps({"commits": ncommit, "market_changes_excluded": nmarket, "pages": pmsg,
                                            "hits": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if any(h.category == "review" and h.public for h in allh) else 0


if __name__ == "__main__":
    sys.exit(main())
