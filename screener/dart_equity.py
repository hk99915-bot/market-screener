"""OpenDART 정형 지분 데이터 — 타법인 출자현황 + 최대주주 현황 (11/1 겸이 "원자재 금융 등 다른 섹터도", PB 전달).

관계도(reports/company_links.json)는 사업보고서 본문(dart_biz)의 매출처·매입처에서 공급망 엣지를 뽑는다. 금융·지주·원자재는
'매출처'가 거의 없고 **지분·계열**이 관계의 핵심이라, 사업보고서 주요정보의 정형 엔드포인트 두 개를 받는다.

- otrCprInvstmntSttus.json (타법인 출자현황) → 이 회사가 출자한 법인·기말 지분율·장부가·출자 목적  = 나가는 투자 엣지
- hyslrSttus.json          (최대주주 현황)   → 최대주주와 특수관계인·기말 지분율                 = 들어오는 지분 엣지

흐름: 종목코드 → DART 고유번호(fin.corp_codes) → 제출 기한이 지난 최신 보고 기간부터(fin.periods) 데이터가 있는 첫 기간
→ data/dart_equity/<코드>.json + 색인 data/dart_equity/index.json.
- 종목당 정상 2콜(출자·최대주주), 최신 기간이 비었으면 한 기간씩 뒤로(최대 3기간). 이미 그 최신 기간으로 받은 종목은 건너뜀.
- 호출 예산(--max-calls)·시간 예산(--max-minutes)·일일 한도(020) 감지 시 받은 만큼 저장하고 중단(dart_biz 와 같은 장치).
- 공시 원문은 공개 정보(최대주주 성명·지분율은 법정 공시 사항). 개인 보유·금액 등 우리 쪽 개인 데이터 없음.

  python -m screener.dart_equity --codes 105560,055550
  python -m screener.dart_equity --file data/dart_biz/targets_supply.txt
  python -m screener.dart_equity                       # 기본 대상: reports/peers_KR.json 전 종목
환경변수 DART_API_KEY 가 없으면 아무것도 하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DATA_DIR, REPORT_DIR
from .dart import key
from .dart_biz import Budget, DailyLimit, TimeBudget, _get, _uniq

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = DATA_DIR / "dart_equity"
INDEX = OUT / "index.json"
VERSION = 1
TRIES = 3                       # 최신 기간이 비었을 때 뒤로 몇 기간까지
NONE_RETRY_DAYS = 30            # 없던 종목·옛 기간으로만 받은 종목은 이 기간 동안 다시 묻지 않음
_now = time.monotonic

# 저장할 칸 (DART 원래 키 → 짧은 키). 숫자는 '-'·쉼표를 걷어 float, 못 읽으면 None.
INV = {"inv_prm": "name", "invstmnt_purps": "purpose", "frst_acqs_de": "first_acq",
       "trmend_blce_qy": "shares", "trmend_blce_qota_rt": "pct", "trmend_blce_acntbk_amount": "book",
       "bsis_blce_qota_rt": "pct_begin", "recent_bsns_year_fnnr_sttus_tot_assets": "tgt_assets",
       "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "tgt_netprofit"}
HOLD = {"nm": "name", "relate": "relation", "stock_knd": "kind", "trmend_posesn_stock_co": "shares",
        "trmend_posesn_stock_qota_rt": "pct", "bsis_posesn_stock_qota_rt": "pct_begin", "rm": "note"}
NUM = {"shares", "pct", "book", "pct_begin", "tgt_assets", "tgt_netprofit"}
REPRT_NM = {"11013": "1분기", "11012": "반기", "11014": "3분기", "11011": "사업"}


# ───────────── 정리 (순수 함수 — 테스트 대상) ─────────────

def num(v) -> float | None:
    s = re.sub(r"[,\s]", "", str(v or ""))
    if s in ("", "-", "−"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    try:
        x = float(s.strip("()"))
    except ValueError:
        return None
    return -x if neg else x


def tidy(rows: list[dict], cols: dict[str, str]) -> list[dict]:
    """DART 행 → 짧은 키 행. 합계 행('합 계'·'계')은 뺀다. 이름 공백 정리."""
    out = []
    for r in rows or []:
        d = {}
        for k, nk in cols.items():
            v = r.get(k)
            d[nk] = num(v) if nk in NUM else (re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "-") else "")
        nm = d.get("name", "").replace(" ", "")
        if not nm or nm in ("합계", "계", "소계", "총계"):
            continue
        out.append(d)
    return out


def candidates(tries: int = TRIES) -> list[tuple[int, str]]:
    """제출 기한이 지난 보고 기간, 최신부터 tries 개."""
    from .fin import periods
    return list(reversed(periods(2)))[:tries]


# ───────────── 색인 ─────────────

def load_index() -> dict:
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"items": []}


def save_index(ix: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ix["items"] = sorted(ix.get("items", []), key=lambda r: r["code"])
    ix["updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    INDEX.write_text(json.dumps(ix, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def fresh(row: dict | None, newest: tuple[int, str], today: str) -> bool:
    """다시 받을 필요가 없나: 최신 기간으로 이미 받음 / 그 밖(없음·옛 기간)은 받은 지 NONE_RETRY_DAYS 안."""
    if not row:
        return False
    if row.get("status") == "ok" and (row.get("year"), row.get("reprt")) == newest:
        return True
    try:
        age = (datetime.fromisoformat(today) - datetime.fromisoformat(row.get("fetched", "1900-01-01"))).days
    except ValueError:
        return False
    return age < NONE_RETRY_DAYS


# ───────────── 대상 ─────────────

def peers_codes() -> list[str]:
    try:
        rows = json.loads((REPORT_DIR / "peers_KR.json").read_text(encoding="utf-8"))["rows"]
    except Exception:  # noqa: BLE001
        return []
    return _uniq([r.get("s", "") for r in sorted(rows, key=lambda r: -(r.get("mc") or 0))])


def file_codes(path: str | Path) -> list[str]:
    return _uniq([ln.split("#", 1)[0].strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()])


# ───────────── 실행 ─────────────

def fetch_one(cc: str, bud: Budget, cands: list[tuple[int, str]], sleep: float) -> tuple[tuple[int, str] | None, list, list]:
    """데이터가 있는 최신 기간의 (기간, 출자 행, 최대주주 행). 둘 다 빈 기간은 건너뛰고 뒤로."""
    for y, rc in cands:
        p = {"corp_code": cc, "bsns_year": str(y), "reprt_code": rc}
        inv = (_get("otrCprInvstmntSttus.json", p, bud) or {}).get("list") or []
        time.sleep(sleep)
        hold = (_get("hyslrSttus.json", p, bud) or {}).get("list") or []
        time.sleep(sleep)
        if inv or hold:
            return (y, rc), inv, hold
    return None, [], []


def update(codes: list[str], max_calls: int = 1500, sleep: float = 0.2, max_minutes: float = 35) -> dict:
    if not key():
        log.info("DART_API_KEY 없음 — 지분 데이터 건너뜀")
        return {"skipped": "no key"}
    from .fin import corp_codes
    cmap = corp_codes()
    ix = load_index()
    by = {r["code"]: r for r in ix.get("items", [])}
    cands = candidates()
    newest = cands[0] if cands else (0, "")
    today = datetime.now(KST).strftime("%Y-%m-%d")
    bud = Budget(max_calls)
    stat = {"codes": len(codes), "new": 0, "skip": 0, "none": 0, "no_corp": 0, "err": 0, "done_codes": 0,
            "period": f"{newest[0]} {REPRT_NM.get(newest[1], newest[1])}"}
    stop = ""
    t0 = _now()
    try:
        for i, code in enumerate(codes):
            stat["done_codes"] = i
            if max_minutes and _now() - t0 > max_minutes * 60:
                raise TimeBudget("time budget")
            if fresh(by.get(code), newest, today):
                stat["skip"] += 1
                continue
            cc = cmap.get(code)
            if not cc:
                stat["no_corp"] += 1
                continue
            try:
                per, inv, hold = fetch_one(cc, bud, cands, sleep)
            except DailyLimit:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("%s 지분 실패: %s", code, e)
                stat["err"] += 1
                continue
            name = next((r.get("corp_name") for r in inv + hold if r.get("corp_name")), "")
            row = {"code": code, "name": name, "fetched": today, "v": VERSION}
            if per is None:
                row.update(status="none")
                stat["none"] += 1
            else:
                inv_t, hold_t = tidy(inv, INV), tidy(hold, HOLD)
                rcept = next((r.get("rcept_no") for r in inv + hold if r.get("rcept_no")), "")
                OUT.mkdir(parents=True, exist_ok=True)
                doc = {"code": code, "name": name, "corp_code": cc, "year": per[0], "reprt": per[1],
                       "report": REPRT_NM.get(per[1], per[1]), "rcept_no": rcept,
                       "source": "OpenDART otrCprInvstmntSttus·hyslrSttus (정기보고서 주요정보, 공개 공시)",
                       "fetched": today, "invest": inv_t, "holders": hold_t}
                (OUT / f"{code}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                row.update(status="ok", year=per[0], reprt=per[1], rcept_no=rcept, n_invest=len(inv_t), n_holders=len(hold_t))
                stat["new"] += 1
            by[code] = row
            if (i + 1) % 25 == 0:
                ix["items"] = list(by.values())
                save_index(ix)
        stat["done_codes"] = len(codes)
    except DailyLimit as e:
        stop = str(e)
        log.warning("중단: %s — 받은 만큼 저장, 다음 실행에서 이어받음", e)
    stat.update(api_calls=bud.used, stopped=stop, minutes=round((_now() - t0) / 60, 1),
                remaining=len(codes) - stat["done_codes"])
    ix["items"] = list(by.values())
    ix["last_run"] = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), **stat}
    save_index(ix)
    log.info("지분 데이터 %s", stat)
    return stat


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DART 타법인 출자현황·최대주주 현황 수집")
    ap.add_argument("--codes", default="", help="쉼표 구분 종목코드")
    ap.add_argument("--file", default="", help="종목코드 목록 파일(줄마다 코드, # 주석)")
    ap.add_argument("--max-calls", type=int, default=1500)
    ap.add_argument("--max-minutes", type=float, default=35)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    codes = _uniq(a.codes.replace(" ", ",").split(",")) if a.codes.strip() else []
    if a.file.strip():
        codes = _uniq(codes + file_codes(a.file.strip()))
    if not codes:
        codes = peers_codes()
    log.info("대상 %d종목", len(codes))
    print(json.dumps(update(codes, max_calls=a.max_calls, max_minutes=a.max_minutes), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
