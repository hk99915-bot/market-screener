"""파생·수급 이력 소스 탐침 (Actions 전용 — 로컬 샌드박스는 KRX·네이버 차단).

python scripts/probe_deriv_sources.py  → 표준출력에 각 소스의 응답 모양을 찍는다.
결과는 screener/deriv_hist.py 의 소스 선택 근거로 docstring 에 요약한다.
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"}
M_UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
        "Referer": "https://m.stock.naver.com/"}


def hdr(t):
    print("\n" + "=" * 8 + " " + t + " " + "=" * 8, flush=True)


def txt(h, n=900):
    h = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = re.sub(r"&nbsp;", " ", h)
    return re.sub(r"\s+", " ", h)[:n]


def krx_post(bld, **params):
    from pykrx.website.comm.webio import get_session
    params["bld"] = bld
    s = get_session()
    head = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
            "X-Requested-With": "XMLHttpRequest"}
    if s is None:
        return requests.post("https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd", data=params, headers=head, timeout=30)
    h = s.get_headers()
    h.update(head)
    return s.session.post("https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd", data=params, headers=h, timeout=30)


def krx_get(url):
    from pykrx.website.comm.webio import get_session
    s = get_session()
    if s is None:
        return requests.get(url, headers=UA, timeout=30)
    h = s.get_headers()
    return s.session.get(url, headers=h, timeout=30)


def show_json(r, n=1200):
    try:
        j = r.json()
    except Exception:  # noqa: BLE001
        print("status", r.status_code, "non-json", r.text[:300].replace("\n", " "))
        return None
    if isinstance(j, dict):
        print("status", r.status_code, "keys", list(j.keys())[:20])
        for k, v in j.items():
            if isinstance(v, list):
                print(f"  {k}: list[{len(v)}]", json.dumps(v[:2], ensure_ascii=False)[:n])
                if len(v) > 2:
                    print("   ... last:", json.dumps(v[-1], ensure_ascii=False)[:400])
    else:
        print("status", r.status_code, json.dumps(j, ensure_ascii=False)[:n])
    return j


def step(name, fn):
    hdr(name)
    try:
        fn()
    except Exception:  # noqa: BLE001
        traceback.print_exc(file=sys.stdout)


def p_pykrx_flows():
    from pykrx import stock
    df = stock.get_market_trading_value_by_date("20100101", "20261231", "KOSPI")
    print(df.shape, list(df.columns))
    print(df.head(3).to_string())
    print(df.tail(3).to_string())
    df2 = stock.get_market_trading_value_by_date("20260901", "20261231", "KOSPI", detail=True)
    print(df2.shape, list(df2.columns))
    print(df2.tail(2).to_string())


def p_krx_futboard():
    today = datetime.now(KST).date()
    for back in range(0, 4):
        d = today - timedelta(days=back)
        r = krx_post("dbms/MDC/STAT/standard/MDCSTAT12501", trdDd=d.strftime("%Y%m%d"), prodId="KRDRVFUK2I", mktTpCd="T", rghtTpCd="T")
        j = r.json()
        out = j.get("output") or []
        print(d, "rows", len(out), "keys", list(out[0].keys()) if out else None)
        for x in out:
            nm = x.get("ISU_NM", "")
            if "SP" in nm or "스프레드" in nm:
                continue
            print("  ", {k: x.get(k) for k in ("ISU_NM", "TDD_OPNPRC", "TDD_CLSPRC", "CMPPREVDD_PRC", "SPOT_PRC", "SETL_PRC", "ACC_TRDVOL", "ACC_TRDVAL", "ACC_OPNINT_QTY")})
    # 미니·옵션 이름 확인 (야간 행)
    r = krx_post("dbms/MDC/STAT/standard/MDCSTAT12501", trdDd=today.strftime("%Y%m%d"), prodId="KRDRVOPK2I", mktTpCd="T", rghtTpCd="T")
    out = r.json().get("output") or []
    nms = [x.get("ISU_NM", "") for x in out]
    print("options rows", len(out), "야간 rows", sum("야간" in n for n in nms), "sample", nms[:3], [n for n in nms if "야간" in n][:3])
    w = [n for n in nms if re.search(r"W|위클리", n)]
    print("weekly-like names", len(w), w[:5])


def p_krx_screens():
    # 파생 투자자별·프로그램 화면의 bld 를 찾기 위해 화면 템플릿을 읽는다
    for code in ["12501", "12502", "12601", "12602", "12701", "12801", "12802", "12901", "12902", "13001", "13002",
                 "13101", "13102", "13103", "13201", "13202", "13301", "13302", "13401", "13501", "13601",
                 "02601", "02602", "02701", "02702", "02801"]:
        for url in (f"https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT{code}.cmd",):
            try:
                r = krx_get(url)
                h = r.text
                title = re.findall(r"<(?:h2|h3|title)[^>]*>([^<]{2,80})<", h)
                blds = sorted(set(re.findall(r"dbms/MDC/[A-Z_/]+MDCSTAT\d+", h)))
                params = sorted(set(re.findall(r"name=\"([a-zA-Z_]{3,20})\"", h)))[:40]
                print(code, r.status_code, len(h), "title", title[:3], "blds", blds[:5], "params", params)
            except Exception as e:  # noqa: BLE001
                print(code, "ERR", e)


def p_krx_inv_guess():
    s, e = "20260901", "20261016"
    trials = [
        ("dbms/MDC/STAT/standard/MDCSTAT13101", dict(strtDd=s, endDd=e, prodId="KRDRVFUK2I", inqTpCd="2", trdVolVal="2", askBid="3")),
        ("dbms/MDC/STAT/standard/MDCSTAT13102", dict(strtDd=s, endDd=e, prodId="KRDRVFUK2I", inqTpCd="2", trdVolVal="2", askBid="3")),
        ("dbms/MDC/STAT/standard/MDCSTAT13102", dict(strtDd=s, endDd=e, prodId="KRDRVFUK2I", subProdId="", inqTpCd="2", trdVolVal="2", askBid="3", isuOpt="F")),
        ("dbms/MDC/STAT/standard/MDCSTAT13001", dict(strtDd=s, endDd=e, prodId="KRDRVFUK2I")),
        ("dbms/MDC/STAT/standard/MDCSTAT13002", dict(strtDd=s, endDd=e, prodId="KRDRVFUK2I")),
        ("dbms/MDC/STAT/standard/MDCSTAT12601", dict(strtDd=s, endDd=e, prodId="KRDRVFUK2I")),
        ("dbms/MDC/STAT/standard/MDCSTAT12701", dict(strtDd=s, endDd=e, prodId="KRDRVFUK2I")),
        ("dbms/MDC/STAT/standard/MDCSTAT12801", dict(strtDd=s, endDd=e, prodId="KRDRVFUK2I")),
        ("dbms/MDC/STAT/standard/MDCSTAT12901", dict(strtDd=s, endDd=e, prodId="KRDRVFUK2I")),
        ("dbms/MDC/STAT/standard/MDCSTAT02601", dict(strtDd=s, endDd=e, mktId="STK")),
        ("dbms/MDC/STAT/standard/MDCSTAT02602", dict(strtDd=s, endDd=e, mktId="STK")),
    ]
    for bld, p in trials:
        print("--", bld, p)
        try:
            show_json(krx_post(bld, **p), 500)
        except Exception as e2:  # noqa: BLE001
            print("ERR", e2)


def p_naver_pc():
    today = datetime.now(KST).date().strftime("%Y%m%d")
    for path in [f"investorDealTrendDay.naver?bizdate={today}&sosok=",
                 f"investorDealTrendDay.naver?bizdate={today}&sosok=01",
                 f"investorDealTrendDay.naver?bizdate={today}&sosok=02",
                 f"investorDealTrendDay.naver?bizdate={today}&sosok=03",
                 f"investorDealTrendDay.naver?bizdate={today}&sosok=&page=40",
                 f"programDealTrendDay.naver?bizdate={today}&sosok=",
                 f"programDealTrendDay.naver?bizdate={today}&sosok=&page=40",
                 "sise_index_day.naver?code=FUT",
                 "sise_index.naver?code=FUT",
                 "investorDealTrendTime.naver?bizdate=" + today + "&sosok=03"]:
        url = "https://finance.naver.com/sise/" + path
        try:
            r = requests.get(url, headers={**UA, "Referer": "https://finance.naver.com/sise/"}, timeout=20)
            r.encoding = "euc-kr"
            print("--", path, r.status_code, len(r.text))
            print("  ", txt(r.text, 700))
        except Exception as e:  # noqa: BLE001
            print("--", path, "ERR", e)


def p_naver_mobile():
    for path in ["api/index/FUT/basic", "api/index/FUT/integration", "api/index/KPI200/basic",
                 "api/index/KOSPI/integration", "api/index/KOSPI/trend", "api/index/KOSPI/investor",
                 "api/index/FUT/price?pageSize=5&page=1", "api/index/KOSPI/price?pageSize=5&page=1",
                 "api/index/FUTN/basic", "api/index/NFUT/basic", "api/index/FUT_NIGHT/basic", "api/index/KPI200NF/basic"]:
        url = "https://m.stock.naver.com/" + path
        try:
            r = requests.get(url, headers=M_UA, timeout=15)
            print("--", path, r.status_code)
            if r.ok:
                j = show_json(r, 900)
                if isinstance(j, dict) and "dealTrendInfos" in j:
                    print("  dealTrendInfos:", json.dumps(j["dealTrendInfos"], ensure_ascii=False)[:1200])
                if isinstance(j, dict) and path.endswith("basic"):
                    print("  ", json.dumps(j, ensure_ascii=False)[:1200])
        except Exception as e:  # noqa: BLE001
            print("--", path, "ERR", e)
    for url in ["https://api.stock.naver.com/index/KOSPI/integration", "https://api.stock.naver.com/index/FUT/basic",
                "https://polling.finance.naver.com/api/realtime/domestic/index/FUT",
                "https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:FUT"]:
        try:
            r = requests.get(url, headers=M_UA, timeout=15)
            print("--", url, r.status_code, r.text[:800].replace("\n", " "))
        except Exception as e:  # noqa: BLE001
            print("--", url, "ERR", e)


def p_esignal_investing():
    for url in ["https://www.esignal.co.kr/kospi200-futures-night/", "https://www.esignal.co.kr/",
                "https://kr.investing.com/indices/korea-200-futures"]:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            print("--", url, r.status_code, len(r.text), txt(r.text, 400))
        except Exception as e:  # noqa: BLE001
            print("--", url, "ERR", e)


def p_krx_night():
    d = "20261015"
    for bld, base in [("dbms/MDC/STAT/standard/MDCSTAT12501", dict(trdDd=d, prodId="KRDRVFUK2I", rghtTpCd="T")),
                      ("dbms/MDC/STAT/standard/MDCSTAT12701", dict(strtDd="20261010", endDd="20261016", prodId="KRDRVFUK2I"))]:
        for mk in ["T", "N", "E", "A", "1", "2", "3", "0", "Y", None]:
            p = dict(base)
            if mk is not None:
                p["mktTpCd"] = mk
            try:
                out = krx_post(bld, **p).json().get("output") or []
                nm = [(x.get("TRD_DD") or "") + " " + (x.get("ISU_NM") or "") + " " + str(x.get("TDD_CLSPRC")) + " vol " + str(x.get("ACC_TRDVOL")) for x in out[:6]]
                print(bld[-5:], "mktTpCd", mk, "rows", len(out), nm)
            except Exception as e:  # noqa: BLE001
                print(bld[-5:], mk, "ERR", e)
    # 12701 은 기간 조회 — 야간 표기 행이 섞이는지 다른 파라미터 이름도 시도
    for k, v in [("trdTpCd", "N"), ("sessTpCd", "2"), ("ntTpCd", "N"), ("nightYn", "Y"), ("isuOpt", "N"), ("mktTpCd", "N")]:
        try:
            out = krx_post("dbms/MDC/STAT/standard/MDCSTAT12701", strtDd="20261010", endDd="20261016", prodId="KRDRVFUK2I", **{k: v}).json().get("output") or []
            print("12701", k, v, len(out), [(x.get("TRD_DD"), x.get("TDD_CLSPRC"), x.get("ACC_TRDVOL")) for x in out[:4]])
        except Exception as e:  # noqa: BLE001
            print("12701", k, v, "ERR", e)


def p_krx_inv2():
    s, e = "20261013", "20261015"
    base = dict(strtDd=s, endDd=e, prodId="KRDRVFUK2I")
    combos = [dict(), dict(mktTpCd="T"), dict(mktTpCd="T", rghtTpCd="T"), dict(inqTpCd="1"), dict(inqTpCd="2"),
              dict(inqTpCd="1", mktTpCd="T"), dict(inqTpCd="2", mktTpCd="T", trdVolVal="1", askBid="3"),
              dict(isuCd="", inqTpCd="2", mktTpCd="T"), dict(prodTpCd="F", inqTpCd="2"), dict(secugrpId="FU", inqTpCd="2")]
    for bld in ("dbms/MDC/STAT/standard/MDCSTAT13101", "dbms/MDC/STAT/standard/MDCSTAT13102", "dbms/MDC/STAT/standard/MDCSTAT13103"):
        for c in combos:
            try:
                r = krx_post(bld, **base, **c)
                j = r.json()
                out = j.get("output") or []
                nz = [x for x in out if any(str(v) not in ("0", "", "-") for k2, v in x.items() if "TRD" in k2)]
                print(bld[-5:], c, "rows", len(out), "nonzero", len(nz), json.dumps(nz[:3] or out[:1], ensure_ascii=False)[:600])
            except Exception as e2:  # noqa: BLE001
                print(bld[-5:], c, "ERR", str(e2)[:100])
    # 하루씩: 기간합계를 strt=end 로
    for c in [dict(mktTpCd="T"), dict(inqTpCd="1", mktTpCd="T", trdVolVal="1", askBid="3")]:
        try:
            out = krx_post("dbms/MDC/STAT/standard/MDCSTAT13101", strtDd="20261015", endDd="20261015", prodId="KRDRVFUK2I", **c).json().get("output") or []
            print("13101 1day", c, json.dumps(out[:11], ensure_ascii=False)[:1500])
        except Exception as e2:  # noqa: BLE001
            print("ERR", e2)


def p_krx_prog():
    for p in [dict(strtDd="20261015", endDd="20261015", mktId="STK"), dict(strtDd="20100104", endDd="20100104", mktId="STK"),
              dict(strtDd="20180102", endDd="20180102", mktId="STK")]:
        try:
            print("02601", p, json.dumps(krx_post("dbms/MDC/STAT/standard/MDCSTAT02601", **p).json().get("output"), ensure_ascii=False)[:700])
        except Exception as e:  # noqa: BLE001
            print("ERR", e)
    for p in [dict(strtDd="20261001", endDd="20261015", mktId="STK", inqTpCd="2"), dict(strtDd="20261001", endDd="20261015", mktId="STK", itmTpCd="2"),
              dict(strtDd="20261001", endDd="20261015", mktId="STK", inqTpCd="2", trdVolVal="2", askBid="3")]:
        try:
            r = krx_post("dbms/MDC/STAT/standard/MDCSTAT02602", **p)
            print("02602", p, r.text[:500].replace("\n", " ") if not r.text.startswith("{") else json.dumps(r.json(), ensure_ascii=False)[:700])
        except Exception as e:  # noqa: BLE001
            print("ERR", e)


def p_krx_opt_hist():
    # 옵션 보드가 얼마나 과거까지 나오나 + 만기월별 OI 분포
    for d in ["20261015", "20250612", "20240103", "20220103", "20190102", "20150105", "20120104"]:
        try:
            out = krx_post("dbms/MDC/STAT/standard/MDCSTAT12501", trdDd=d, prodId="KRDRVOPK2I", mktTpCd="T", rghtTpCd="T").json().get("output") or []
            nms = [x.get("ISU_NM", "") for x in out]
            by = {}
            for x in out:
                m = re.search(r"([CP])\s+(\S+)\s+([\d.]+)", x.get("ISU_NM", ""))
                if m:
                    key = (m.group(1), m.group(2))
                    by[key] = by.get(key, 0) + float(str(x.get("ACC_OPNINT_QTY") or 0).replace(",", "").replace("-", "0") or 0)
            print(d, "rows", len(out), "sample", nms[:2], "OI by (cp,month):", sorted(by.items(), key=lambda kv: -kv[1])[:10])
        except Exception as e:  # noqa: BLE001
            print(d, "ERR", e)
    for d in ["20261015", "20200102", "20150105"]:
        out = krx_post("dbms/MDC/STAT/standard/MDCSTAT12501", trdDd=d, prodId="KRDRVFUK2I", mktTpCd="T", rghtTpCd="T").json().get("output") or []
        print("fut", d, len(out), [(x.get("ISU_NM"), x.get("TDD_CLSPRC"), x.get("SPOT_PRC"), x.get("ACC_OPNINT_QTY")) for x in out[:2]])


def p_krx_night2():
    for d in ["20250605", "20250609", "20250610", "20250611", "20250901", "20260105", "20260914", "20261014", "20261015", "20261016"]:
        try:
            out = krx_post("dbms/MDC/STAT/standard/MDCSTAT12501", trdDd=d, prodId="KRDRVFUK2I", mktTpCd="T", rghtTpCd="T").json().get("output") or []
            print(d, len(out), [(x.get("ISU_NM"), x.get("TDD_OPNPRC"), x.get("TDD_CLSPRC"), x.get("ACC_TRDVOL")) for x in out if "SP" not in x.get("ISU_NM", "")][:3],
                  "야간", [(x.get("ISU_NM"), x.get("TDD_CLSPRC"), x.get("ACC_TRDVOL")) for x in out if "야간" in x.get("ISU_NM", "")][:2])
        except Exception as e:  # noqa: BLE001
            print(d, "ERR", e)
    out = krx_post("dbms/MDC/STAT/standard/MDCSTAT13001", strtDd="20261014", endDd="20261015").json().get("output") or []
    print("13001 rows", json.dumps(out, ensure_ascii=False)[:2500])
    r = krx_post("dbms/comm/finder/finder_drvprodisu", mktsel="ALL", searchText="", bld="dbms/comm/finder/finder_drvprodisu")
    print("finder", r.status_code, r.text[:1500])


def p_krx_sweep():
    found = []
    for a in range(130, 140):
        for b in range(1, 6):
            bld = f"dbms/MDC/STAT/standard/MDCSTAT{a}{b:02d}"
            for prm in (dict(trdDd="20261015", prodId="KRDRVFUK2I", mktTpCd="T", rghtTpCd="T"),
                        dict(strtDd="20261013", endDd="20261015", prodId="KRDRVFUK2I", mktTpCd="T", inqTpCd="2", trdVolVal="1", askBid="3")):
                try:
                    r = krx_post(bld, **prm)
                    if not r.text.startswith("{"):
                        continue
                    out = r.json().get("output") or r.json().get("OutBlock_1") or []
                    if out:
                        nz = any(any(ch.isdigit() and ch != "0" for ch in str(v)) for x in out[:15] for k, v in x.items() if "VOL" in k or "VAL" in k or "QTY" in k)
                        print(bld[-9:], list(prm)[0], "rows", len(out), "nonzero", nz, json.dumps(out[:2], ensure_ascii=False)[:500])
                        found.append(bld)
                except Exception as e:  # noqa: BLE001
                    pass
    print("found", found)


def p_round4():
    import os
    key = os.environ.get("KRX_API_KEY")
    print("KRX_API_KEY set:", bool(key))
    if key:
        for ep in ["drv/fut_bydd_trd", "drv/opt_bydd_trd", "idx/drvprod_dd_trd", "idx/kospi_dd_trd"]:
            for d in ["20261015", "20250612"]:
                try:
                    r = requests.get("https://data-dbg.krx.co.kr/svc/apis/" + ep, headers={"AUTH_KEY": key}, params={"basDd": d}, timeout=30)
                    j = r.json() if r.text.startswith("{") else {}
                    out = j.get("OutBlock_1") or []
                    k2 = [x for x in out if "코스피200" in json.dumps(x, ensure_ascii=False) or "KOSPI 200" in json.dumps(x, ensure_ascii=False)]
                    mk = sorted({x.get("MKT_NM") for x in out if x.get("MKT_NM")})
                    print(ep, d, r.status_code, "rows", len(out), "MKT_NM", mk, "k200", len(k2), json.dumps(k2[:3], ensure_ascii=False)[:900] or r.text[:300])
                    nt = [x for x in k2 if "야간" in json.dumps(x, ensure_ascii=False)]
                    print("   night rows", len(nt), json.dumps(nt[:2], ensure_ascii=False)[:700])
                except Exception as e:  # noqa: BLE001
                    print(ep, d, "ERR", e)
    out = krx_post("dbms/MDC/STAT/standard/MDCSTAT13001", trdDd="20261015").json().get("output") or []
    print("13001 keys", list(out[0].keys()) if out else None)
    for x in out:
        print("  ", x)
    for pid in ["KRDRVFUK2I", "KRDRVFUMKI", "KRDRVOPK2I", "KRDRVFUEQU", "", "ALL", "K2I", "KRDRVFU"]:
        for extra in (dict(), dict(trdVolVal="1", askBid="3", inqTpCd="1"), dict(isuCd="KR4A016C0004")):
            try:
                out = krx_post("dbms/MDC/STAT/standard/MDCSTAT13101", strtDd="20261015", endDd="20261015", prodId=pid, **extra).json().get("output") or []
                nz = [x for x in out if x.get("NETBID_TRDVOL") not in (None, "0", "-")]
                print("13101 prodId", repr(pid), extra, "rows", len(out), "nonzero", len(nz), json.dumps(nz[:4], ensure_ascii=False)[:500])
            except Exception as e:  # noqa: BLE001
                print("13101", pid, "ERR", str(e)[:80])
    try:
        r = requests.get("https://m.stock.naver.com/api/index/FUT/integration", headers=M_UA, timeout=15).json()
        print("naver FUT dealTrendInfo", json.dumps(r.get("dealTrendInfo"), ensure_ascii=False)[:1500])
        print("naver FUT programTrendInfo", json.dumps(r.get("programTrendInfo"), ensure_ascii=False)[:500])
        r = requests.get("https://m.stock.naver.com/api/index/KOSPI/integration", headers=M_UA, timeout=15).json()
        print("naver KOSPI dealTrendInfo", json.dumps(r.get("dealTrendInfo"), ensure_ascii=False)[:800])
        r = requests.get("https://m.stock.naver.com/api/index/KOSPI/trend", headers=M_UA, timeout=15)
        print("naver KOSPI trend", r.text[:600])
        for q in ("?pageSize=60&page=1", "?page=2&pageSize=20"):
            r = requests.get("https://m.stock.naver.com/api/index/KOSPI/trend" + q, headers=M_UA, timeout=15)
            print("trend", q, r.status_code, r.text[:300])
    except Exception as e:  # noqa: BLE001
        print("naver ERR", e)


if __name__ == "__main__":
    only = sys.argv[1:] or ["pykrx_flows", "krx_futboard", "krx_screens", "krx_inv_guess", "naver_pc", "naver_mobile", "esignal_investing"]
    for nm in only:
        step(nm, globals()["p_" + nm])
