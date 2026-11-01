"""reports/company_links.json 빌더 (애널 데스크, 2026-11-01). 실행: cd market-screener && python3 <this>"""
import json, sys, os
sys.path.insert(0, ".")
from screener.drivers import CHAINS

ASOF = "2026-11-01"
macro = json.load(open("reports/macro_series.json"))
fx_row = macro["series"]["USDKRW"][-1]
FX, FX_DATE = float(fx_row[4]), fx_row[0]

code2chain = {}
for k, c in CHAINS.items():
    for cd in c["codes"]:
        code2chain.setdefault(cd, k)

nodes = {}


def kr(code, name, groups):
    d = json.load(open(f"reports/detail/KR/{code}.json"))
    sh = ((d.get("valuation") or {}).get("shares") or {}).get("shares")
    mc = round(d["close"] * sh / FX, -6) if sh else None
    nodes[code] = {"id": code, "name": name, "mkt": "KR", "mc_usd": mc,
                   "mc_asof": f"{d['asof']} 종가×DART 주식수 ÷ USDKRW {FX:.2f}({FX_DATE}) · reports/detail/KR",
                   "chain": code2chain.get(code), "groups": list(groups), "listed": True}


def us(t, name, groups, chain=None):
    p = f"reports/detail/US/{t}.json"
    mc, asof = None, "미확인(시세·주식수 없음)"
    if os.path.exists(p):
        d = json.load(open(p))
        sh = ((d.get("valuation") or {}).get("shares") or {}).get("shares")
        if not sh:
            import pandas as pd
            q = pd.read_parquet("data/fin/us_quarterly.parquet")
            q = q[(q.ticker == t) & (q.item == "shares")]
            sh = float(q.value.iloc[-1]) if len(q) else None
            src = f"us_quarterly shares {q.end.iloc[-1]}" if len(q) else None
        else:
            src = "SEC 주식수 최근값"
        if sh:
            mc = round(d["close"] * sh, -6)
            asof = f"{d['asof']} 종가×{src} · reports/detail/US"
        else:
            asof = f"{d['asof']} 종가 있음, 주식수 미확인"
    nodes[t] = {"id": t, "name": name, "mkt": "US", "mc_usd": mc, "mc_asof": asof,
                "chain": chain, "groups": list(groups), "listed": True}


def other(i, name, mkt, groups, mc=None, mc_asof="미확인", listed=False, chain=None):
    nodes[i] = {"id": i, "name": name, "mkt": mkt, "mc_usd": mc, "mc_asof": mc_asof,
                "chain": chain, "groups": list(groups), "listed": listed}


AI, SE, PSD, BAT = "ai_circle", "kr_semis", "kr_power_ship_defense", "kr_battery"
# ---------- ai_circle ----------
for t, n, ch in [("NVDA", "엔비디아", None), ("MSFT", "마이크로소프트", None), ("GOOGL", "알파벳(구글)", None),
                 ("AMZN", "아마존", None), ("ORCL", "오라클", None), ("AMD", "AMD", None), ("INTC", "인텔", None),
                 ("GLW", "코닝", None), ("CRWV", "코어위브", None), ("NBIS", "네비우스", None)]:
    us(t, n, [AI])
other("OPENAI", "OpenAI", "PRIVATE", [AI], 8.52e11, "2026-04 시리즈 마감 사후 기업가치 $852B(2차: Bloomberg Law 2026-04; 사전 $730B 설도 있음) — 차트 기준일 2026-05-06 값과 대조 필요")
other("ANTHROPIC", "Anthropic", "PRIVATE", [AI], None, "출처 상충: 2026-04 구글·아마존 투자 기준 사전 $350B(2차) vs 2026-05 시리즈 H $965B(집계사이트, 검증전) — null 처리")
other("XAI", "xAI", "PRIVATE", [AI], None, "미확인(2026-02 SpaceX 합병 보도, 검증전)")
other("MISTRAL", "Mistral AI", "PRIVATE", [AI], None, "미확인(2025-09 ASML 주도 라운드, 2차)")
other("NSCALE", "Nscale", "PRIVATE", [AI], None, "미확인")
other("FIGURE", "Figure AI", "PRIVATE", [AI], None, "미확인")
other("CURSOR", "Cursor(Anysphere)", "PRIVATE", [AI], None, "미확인")
other("HARVEY", "Harvey", "PRIVATE", [AI], None, "미확인")
other("AMBIENCE", "Ambience Healthcare", "PRIVATE", [AI], None, "미확인")
other("SOFTBANK", "소프트뱅크그룹(9984.T)", "OTHER", [AI], None, "미확인(도쿄 상장, 우리 시세 데이터 없음)", listed=True)
other("SBENERGY", "SB Energy", "PRIVATE", [AI], None, "미확인(소프트뱅크 소유)")

# ---------- kr_semis ----------
for c, n in [("005930", "삼성전자"), ("000660", "SK하이닉스"), ("402340", "SK스퀘어"), ("042700", "한미반도체"),
             ("240810", "원익IPS"), ("357780", "솔브레인"), ("005290", "동진쎄미켐"), ("095340", "ISC"),
             ("067310", "하나마이크론"), ("222800", "심텍"), ("007660", "이수페타시스"), ("009150", "삼성전기"),
             ("011070", "LG이노텍")]:
    kr(c, n, [SE])
for t, n in [("MU", "마이크론"), ("AAPL", "애플"), ("AVGO", "브로드컴")]:
    us(t, n, [SE])

# ---------- kr_power_ship_defense ----------
for c, n in [("267260", "HD현대일렉트릭"), ("298040", "효성중공업"), ("010120", "LS ELECTRIC"), ("329180", "HD현대중공업"),
             ("042660", "한화오션"), ("010140", "삼성중공업"), ("009540", "HD한국조선해양"), ("012450", "한화에어로스페이스"),
             ("064350", "현대로템"), ("047810", "한국항공우주(KAI)"), ("005490", "POSCO홀딩스"), ("004020", "현대제철"),
             ("015760", "한국전력"), ("082740", "한화엔진"), ("034020", "두산에너빌리티"), ("267250", "HD현대"),
             ("006260", "LS"), ("272210", "한화시스템"), ("099320", "쎄트렉아이"), ("077970", "STX엔진")]:
    kr(c, n, [PSD])
us("NEE", "넥스트에라 에너지", [PSD])
us("BA", "보잉", [PSD])
other("GE", "GE에어로스페이스", "US", [PSD], None, "미확인(우리 시세 데이터 없음)", listed=True)
other("SEC_SA", "사우디전력청(SEC)", "OTHER", [PSD], None, "미확인(타다울 상장)", listed=True)
other("DAPA", "방위사업청", "GOV", [PSD], None, "정부기관 — 해당 없음")
other("PL_GOV", "폴란드 정부(군비청)", "GOV", [PSD], None, "정부기관 — 해당 없음")

# ---------- kr_battery ----------
for c, n in [("373220", "LG에너지솔루션"), ("006400", "삼성SDI"), ("096770", "SK이노베이션(SK온)"), ("086520", "에코프로"),
             ("247540", "에코프로비엠"), ("003670", "포스코퓨처엠"), ("051910", "LG화학"), ("005380", "현대차"), ("000270", "기아")]:
    kr(c, n, [BAT])
us("GM", "GM", [BAT])
us("F", "포드", [BAT])
for i, n in [("BMW", "BMW"), ("VW", "폭스바겐그룹"), ("STLA", "스텔란티스"), ("MBG", "메르세데스-벤츠그룹")]:
    other(i, n, "OTHER", [BAT], None, "미확인(유럽 상장, 우리 시세 데이터 없음)", listed=True)
other("ULTIUM", "Ultium Cells(LG엔솔·GM JV)", "PRIVATE", [BAT], None, "비상장 JV — 해당 없음")

edges = []
DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


def e(f, t, typ, why, src, status, date, groups, size=None):
    assert f in nodes and t in nodes, (f, t)
    edges.append({"from": f, "to": t, "type": typ, "size": size, "why": why, "src": src,
                  "status": status, "date": date, "groups": groups})
    for n in (f, t):
        for g in groups:
            if g not in nodes[n]["groups"]:
                nodes[n]["groups"].append(g)


BB = "2차: Bloomberg 'Nvidia Is at the Center of Circular AI Deals' 차트(2026-05-06)"
# ===== ai_circle =====
e("MSFT", "OPENAI", "investment", "재자본화 후 OpenAI Group PBC 약 27% 지분(지분 가치 약 $135B), IP 권리 2032년까지",
  "1차: Microsoft 공식 블로그 2025-10-28 'The next chapter of the Microsoft–OpenAI partnership' · 보도 https://www.geekwire.com/2025/microsoft-secures-27-stake-in-openai-in-new-deal-with-commitment-for-250b-in-azure-usage/",
  "1차", "2025-10-28", [AI], "약 27% (약 $135B)")
e("MSFT", "OPENAI", "service", "OpenAI가 Azure 서비스 추가 $250B 구매 약정 — 대신 MS의 컴퓨트 우선협상권 소멸",
  "1차: Microsoft 공식 블로그 2025-10-28 · https://www.geekwire.com/2025/microsoft-secures-27-stake-in-openai-in-new-deal-with-commitment-for-250b-in-azure-usage/",
  "1차", "2025-10-28", [AI], "$250B(추가 약정)")
e("NVDA", "OPENAI", "investment", "2026-02 라운드에 $30B 참여 — 2025-09 '최대 $100B LOI' 대체 여부는 불분명",
  "2차: 보도 https://chatgptiseatingtheworld.com/2026/02/28/openai-announced-110b-funding-by-amazon-nvidia-and-softbank/ · NVDA 10-Q 원문 대조 전",
  "2차", "2026-02-27", [AI], "$30B")
e("NVDA", "OPENAI", "hardware", "OpenAI 데이터센터에 엔비디아 시스템 최소 10GW 배치(2025-09 LOI)",
  "2차: 2025-09-22 양사 발표 보도 · " + BB, "2차", "2025-09-22", [AI], "10GW(LOI)")
e("AMD", "OPENAI", "hardware", "Instinct GPU 6GW 공급, 1차 1GW MI450 2026 하반기부터",
  "1차: SEC 8-K AMD 2025-10-06 https://www.sec.gov/Archives/edgar/data/2488/000119312525230895/d28189d8k.htm",
  "1차", "2025-10-05", [AI], "6GW")
e("AMD", "OPENAI", "investment", "OpenAI에 AMD 보통주 최대 1.6억주 워런트 — 구매량·주가($600 최종) 조건부 베스팅, 만기 2030-10-05",
  "1차: SEC 8-K AMD 2025-10-06 (Exhibit) https://www.sec.gov/Archives/edgar/data/2488/000119312525230895/d28189d8k.htm",
  "1차", "2025-10-05", [AI], "최대 1.6억주(행사가 $0.01는 2차)")
e("ORCL", "OPENAI", "service", "OpenAI가 5년 약 $300B 컴퓨트 계약(2027년 시작) — Stargate 파트너",
  "2차: WSJ 2025-09 보도 인용 https://www.etcentric.org/tag/microsoft/page/3 · Oracle 10-Q RPO에 상대방명 없음 → 상대방은 2차",
  "2차", "2025-09-10", [AI], "$300B/5년(보도)")
e("AMZN", "OPENAI", "service", "AWS 7년 $38B 컴퓨트 계약 + 2026-02 라운드 연계 Trainium 2GW 사용",
  "1차: Amazon 보도자료 2025-11-03(원문 링크 미첨부) · 2차 https://w.media/openai-raises-us-110-billion-and-expands-ties-with-softbank-nvidia-and-amazon/",
  "2차", "2025-11-03", [AI], "$38B + Trainium 2GW")
e("AMZN", "OPENAI", "investment", "2026-02 라운드 $50B 약정 — $15B 선집행, $35B 조건부",
  "2차: https://english.aaj.tv/news/amp/330453182 · https://news.bloomberglaw.com/tech-and-telecom-law/openai-valued-at-852-billion-after-closing-122-billion-round",
  "2차", "2026-02-27", [AI], "$50B($15B+조건부 $35B)")
e("SOFTBANK", "OPENAI", "investment", "2026-02 라운드 $30B(공동 주도) — 2025년 투자분 별도",
  "2차: https://www.hl.co.uk/shares/stock-market-news/company--news/openai-raises-$110bn-from-softbank,-nvidia,-amazon",
  "2차", "2026-02-27", [AI], "$30B")
e("SOFTBANK", "SBENERGY", "investment", "SB Energy는 소프트뱅크 소유, 2026-01 $500M 추가",
  "1차: SB Energy 보도자료 https://sbenergy.com/openai-and-softbank-group-partner-with-sb-energy/",
  "1차", "2026-01-09", [AI], "$500M")
e("OPENAI", "SBENERGY", "investment", "OpenAI $500M 투자",
  "1차: OpenAI 발표 https://openai.com/index/stargate-sb-energy-partnership/", "1차", "2026-01-09", [AI], "$500M")
e("SBENERGY", "OPENAI", "service", "텍사스 밀람 카운티 1.2GW 데이터센터 건설·운영(Stargate)",
  "1차: https://openai.com/index/stargate-sb-energy-partnership/", "1차", "2026-01-09", [AI], "1.2GW")
e("NVDA", "CRWV", "investment", "클래스A 보통주 $2B 매입(주당 $87.20) — 지분 약 12%는 2차",
  "1차: SEC 8-K CoreWeave Ex.99.1 2026-01-26 https://www.sec.gov/Archives/edgar/data/1769628/000176962826000044/ex991pressrelease_final.htm",
  "1차", "2026-01-26", [AI], "$2B")
e("CRWV", "NVDA", "service", "엔비디아가 2032년까지 미판매 용량 구매 약정(약 $6.3B) — 고객 겸 투자자",
  "2차: https://www.bloomberg.com/news/articles/2026-01-26/nvidia-invests-another-2-billion-in-coreweave-offers-new-chip (원 8-K 2025-09 대조 전)",
  "2차", "2025-09", [AI], "약 $6.3B")
e("NVDA", "CRWV", "hardware", "Rubin·Vera CPU·BlueField 등 여러 세대 채택",
  "1차: SEC 8-K CoreWeave Ex.99.1 2026-01-26", "1차", "2026-01-26", [AI])
e("CRWV", "OPENAI", "service", "OpenAI와 누적 약 $22.4B 컴퓨트 계약(3차례)",
  "2차: 보도·" + BB + " (CoreWeave 8-K 개별 대조 전)", "2차", "2025-09", [AI], "약 $22.4B(보도)")
e("CRWV", "MSFT", "service", "MS가 최대 고객(2024 매출 62%, S-1)", "2차: CoreWeave S-1 인용 보도 — 원문 대조 전",
  "2차", "2025-03", [AI], "2024 매출 62%")
e("NBIS", "MSFT", "service", "뉴저지 바인랜드 DC GPU 용량 $17.4B(옵션 포함 최대 $19.4B), 2031까지",
  "2차: https://www.etcentric.org/microsoft-contracts-with-nebius-for-17-4-billion-in-ai-capacity/ (Nebius 6-K 대조 전)",
  "2차", "2025-09-08", [AI], "$17.4B~$19.4B")
e("NVDA", "NBIS", "investment", "2024 Nebius 사모 라운드 참여", BB, "2차", "2024-12", [AI])
e("NSCALE", "MSFT", "service", "MS 대상 GPU 용량 공급 계약", BB, "2차", "2025-10", [AI])
e("NVDA", "NSCALE", "investment", "Nscale 라운드 참여", BB, "2차", "2025", [AI])
e("NVDA", "INTC", "investment", "인텔 보통주 $5B 매입 + x86-RTX SoC 공동개발",
  "1차: Intel 8-K 2025-09-18(원문 링크 미첨부) · " + BB, "2차", "2025-09-18", [AI], "$5B")
e("SOFTBANK", "INTC", "investment", "인텔 보통주 $2B 매입", "2차: 2025-08 보도 · " + BB, "2차", "2025-08-18", [AI], "$2B")
e("NVDA", "GLW", "investment", "선지급 워런트 300만주($0.0001)+행사가 $180 워런트 1,500만주 — $500M, 전부 행사 시 약 $3.2B",
  "2차: https://news.bgov.com/capital-markets/nvidia-inks-500-million-deal-for-stock-in-fiber-maker-corning · 코닝 발표 https://www.corning.com/worldwide/en/the-progress-report/in-the-news/nvidia-to-invest-up-to-3-2-billion-in-corning-as-part-of-massive-optical-fiber-deal-with-3-new-factories-focused-on-ai",
  "2차", "2026-05-06", [AI], "$500M(최대 약 $3.2B)")
e("GLW", "NVDA", "supply", "AI DC용 광섬유·광연결(CPO) 공급, 미국 신공장 3곳", "2차: 코닝 발표(위 링크)", "2차", "2026-05-06", [AI])
e("MSFT", "ANTHROPIC", "investment", "최대 $5B 투자", "1차: Microsoft 공식 블로그 2025-11-18(원문 링크 미첨부) · https://www.semafor.com/article/11/18/2025/anthropic-agreement-with-nvidia-and-microsoft-raises-ai-circularity-concerns",
  "2차", "2025-11-18", [AI], "최대 $5B")
e("NVDA", "ANTHROPIC", "investment", "최대 $10B 투자", "2차: 위 Semafor", "2차", "2025-11-18", [AI], "최대 $10B")
e("MSFT", "ANTHROPIC", "service", "Anthropic이 Azure 컴퓨트 $30B 구매 약정", "2차: 위 Semafor", "2차", "2025-11-18", [AI], "$30B")
e("NVDA", "ANTHROPIC", "hardware", "Grace Blackwell·Vera Rubin 최대 1GW 채택", "2차: 위 Semafor", "2차", "2025-11-18", [AI], "최대 1GW")
e("GOOGL", "ANTHROPIC", "investment", "최대 $40B: 즉시 $10B(사전 $350B 기준)+마일스톤 조건부 $30B",
  "2차: https://www.cyprus-mail.com/2026/04/24/google-plans-to-invest-up-to-40-billion-in-anthropic", "2차", "2026-04-24", [AI], "최대 $40B")
e("GOOGL", "ANTHROPIC", "service", "구글클라우드 TPU 5GW/5년(2025-10 '최대 100만 TPU' 계약 확대)",
  "2차: https://www.noqta.tn/en/news/google-40-billion-anthropic-tpu-investment-2026", "2차", "2026-04-24", [AI], "5GW")
e("AMZN", "ANTHROPIC", "investment", "누적 $8B + 2026-04 추가 투자, 1Q26 세전 평가이익 $16.8B 보도",
  "2차: https://news.bgov.com/artificial-intelligence/amazon-to-invest-an-additional-5-billion-in-anthropic · https://www.fortune.com/2026/06/04/amazon-google-billions-anthropic-ipo/ (AMZN 10-Q 대조 전)",
  "2차", "2026-04", [AI], "$8B+추가 $5B(보도)")
e("AMZN", "ANTHROPIC", "service", "AWS 10년 $100B+ 사용 약정, Trainium(Project Rainier)", "2차: 위 Bloomberg Gov 보도", "2차", "2026-04", [AI], "$100B+/10년(보도)")
e("AMD", "ORCL", "hardware", "OCI에 MI450 5만개 배치(2026 3Q~)", "2차: 2025-10-14 양사 발표 보도", "2차", "2025-10-14", [AI], "5만 GPU")
e("NVDA", "ORCL", "hardware", "OCI·Stargate 애빌린 GB200 대량 구매", BB, "2차", "2025", [AI])
e("NVDA", "XAI", "investment", "xAI 라운드 지분 투자(최대 $2B 보도)", BB, "2차", "2025-10", [AI], "최대 $2B(보도)")
e("NVDA", "XAI", "hardware", "콜로서스 GPU 공급", BB, "2차", "2025", [AI])
e("NVDA", "MISTRAL", "investment", "2025-09 시리즈 C 참여(ASML 주도 €1.7B)", BB, "2차", "2025-09", [AI])
e("MSFT", "MISTRAL", "investment", "2024 €15M 전환사채 투자 + Azure 모델 유통", BB, "2차", "2024-02", [AI], "€15M")
e("NVDA", "FIGURE", "investment", "Figure 시리즈B·C 참여", BB, "2차", "2024-02", [AI])
e("MSFT", "FIGURE", "investment", "Figure 시리즈B 참여", BB, "2차", "2024-02", [AI])
e("INTC", "FIGURE", "investment", "Intel Capital 시리즈B 참여", BB, "2차", "2024-02", [AI])
e("NVDA", "CURSOR", "investment", "Anysphere 2025-11 라운드 참여", BB, "2차", "2025-11", [AI])
e("GOOGL", "CURSOR", "investment", "Anysphere 2025-11 라운드 참여", BB, "2차", "2025-11", [AI])
e("OPENAI", "CURSOR", "service", "모델 API 공급(Cursor는 OpenAI·Anthropic 모델 사용)", BB, "2차", "2025", [AI])
e("ANTHROPIC", "CURSOR", "service", "Claude 모델 API 공급", BB, "2차", "2025", [AI])
e("OPENAI", "HARVEY", "investment", "OpenAI Startup Fund 초기 투자", BB, "2차", "2022-11", [AI])
e("OPENAI", "HARVEY", "service", "법률 특화 모델 공동개발·API 공급", BB, "2차", "2023", [AI])
e("OPENAI", "AMBIENCE", "investment", "OpenAI Startup Fund 투자", BB, "검증전", "2023", [AI])

# ===== kr_semis =====
SS, HX = "1차: DART 005930 반기보고서 rcept_no 20260814003699", "DART 000660 반기보고서 rcept_no 20260814003509"
for c in ["GOOGL", "AMZN", "AAPL"]:
    e("005930", c, "customer", "'주요 매출처 Alphabet, Amazon, Apple, Hong Kong Techtronics, Supreme Electronics 등' — 5대 매출처 약 25%",
      SS + " " + DART + "20260814003699", "1차", "2026-06-30", [SE], "5대 합산 약 25%")
e("MU", "005930", "supply", "DX 모바일용 메모리 매입 12.2%(DX 원재료 대비) 매입처 Micron·Kioxia", SS, "1차", "2026-06-30", [SE], "DX 원재료의 12.2%")
e("NVDA", "005930", "supply", "Harman SOC(CPU) 매입처 NVIDIA·Intel — 5.5%(Harman 원재료 대비)", SS, "1차", "2026-06-30", [SE, AI], "Harman 원재료의 5.5%")
e("AAPL", "005930", "supply", "SDC Cover Glass 매입처 Apple·LENS(14.3%)", SS, "1차", "2026-06-30", [SE], "SDC 원재료의 14.3%")
e("357780", "005930", "supply", "DS Chemical·Wafer 매입처 '솔브레인㈜, SILTRONIC 등'", SS, "1차", "2026-06-30", [SE])
e("005930", "NVDA", "supply", "HBM3E/HBM4 공급 — 삼성 공시엔 고객명 없음", "2차: 언론 보도(HBM 퀄 통과) — DART 문구 없음", "2차", "2026", [SE, AI])
e("000660", "NVDA", "supply", "HBM 최대 공급사 — 하이닉스 공시는 '주요 고객사와 월별/분기별 합의'로 고객명 비공개",
  "2차: 보도·NVDA 공급망 통념 / 1차 " + HX + " 고객명 없음", "2차", "2026", [SE, AI])
e("000660", "AMD", "supply", "MI 시리즈 HBM 공급", "2차: 보도", "검증전", "2026", [SE, AI])
e("000660", "AVGO", "supply", "구글 TPU 등 ASIC용 HBM 공급(브로드컴 경유)", "2차: 보도", "검증전", "2026", [SE, AI])
e("402340", "000660", "investment", "'SK하이닉스와 같은 주요 자회사' — 지분율 약 20%는 검증전",
  "1차: DART 402340 반기보고서 rcept_no 20260814003471", "1차", "2026-06-30", [SE], "약 20%(검증전)")
e("042700", "000660", "hardware", "TC본더 고객사 'SK하이닉스, Micron Technology, ASE, AmKor…'",
  "1차: DART 042700 반기보고서 rcept_no 20260814003665", "1차", "2026-06-30", [SE])
e("042700", "MU", "hardware", "고객사 명시 'Micron Technology'", "1차: DART 042700 rcept_no 20260814003665", "1차", "2026-06-30", [SE])
for c in ["005930", "000660"]:
    e("357780", c, "supply", "'주요매출처는 삼성전자, SK하이닉스, LG디스플레이 및 삼성SDI'",
      "1차: DART 357780 반기보고서 rcept_no 20260814003813", "1차", "2026-06-30", [SE])
e("005290", "005930", "supply", "'삼성전자(주) 매출 4,191.97억원으로 제54기 2분기 매출의 62%대' — 수주계약 없이 공급",
  "1차: DART 005290 반기보고서 rcept_no 20260814002890", "1차", "2026-06-30", [SE], "반기 매출의 약 62%")
e("005290", "000660", "supply", "주요 매출처 에스케이하이닉스(주)", "1차: DART 005290 rcept_no 20260814002890", "1차", "2026-06-30", [SE])
for c in ["005930", "000660"]:
    e("095340", c, "supply", "내수 '삼성전자, 하이닉스 외' 직접 판매 — 매출 83%는 비메모리 소켓(2025 4Q)",
      "1차: DART 095340 반기보고서 rcept_no 20260814000114", "1차", "2026-06-30", [SE])
    e("067310", c, "service", "반도체 패키징 거래기본계약(삼성 2001~, 하이닉스 2004~·외주임가공 ~2029-12)",
      "1차: DART 067310 반기보고서 rcept_no 20260814003753", "1차", "2026-06-30", [SE])
    e("222800", c, "supply", "메모리 기판 고객 '글로벌 Big5 메모리칩메이커(삼성전자, SK하이닉스, USA chipmaker 등)' — 고객별 비중은 상호 비공개",
      "1차: DART 222800 반기보고서 rcept_no 20260813001430", "1차", "2026-06-30", [SE])
e("222800", "MU", "supply", "'USA chipmaker' = 마이크론 해석(애널) — 공시는 실명 아님", "1차 문구 + 해석: DART 222800 rcept_no 20260813001430", "검증전", "2026-06-30", [SE])
e("240810", "005930", "hardware", "증착·열처리 장비 — 공시는 '국내외 주요 고객사', 내수 73.56%(고객명 없음)",
  "1차(비중)/해석(고객명): DART 240810 반기보고서 rcept_no 20260814001845", "검증전", "2026-06-30", [SE], "내수 73.56%")
e("007660", "GOOGL", "supply", "'AI가속기 시장 G사와 N사를 주요 고객' — G=구글 해석, 10% 초과 1개사 약 40%",
  "1차 문구 + 해석: DART 007660 반기보고서 rcept_no 20260814002283", "검증전", "2026-06-30", [SE, AI], "최대 고객 약 40%(실명 비공개)")
e("007660", "NVDA", "supply", "'N사' = 엔비디아 해석(애널)", "1차 문구 + 해석: DART 007660 rcept_no 20260814002283", "검증전", "2026-06-30", [SE, AI])
e("007660", "MSFT", "supply", "스위치 기판 'G사와 M사를 고객으로 확보, A사 신규 진입 협의' — M=MS 해석", "1차 문구 + 해석: DART 007660 rcept_no 20260814002283", "검증전", "2026-06-30", [SE, AI])
e("009150", "005930", "supply", "'주요 매출처는 삼성전자와 그 종속기업, 약 26%'", "1차: DART 009150 반기보고서 rcept_no 20260814003805", "1차", "2026-06-30", [SE], "약 26%")
e("011070", "AAPL", "supply", "'10% 이상 단일 고객 광학/패키지 매출 8.84조원' — 단일 고객 = 애플 해석, 상위10 86%",
  "1차 문구 + 해석: DART 011070 반기보고서 rcept_no 20260814001879", "검증전", "2026-06-30", [SE], "8.84조원(단일 고객)")

# ===== kr_power_ship_defense =====
D = lambda c, r: f"1차: DART {c} 반기보고서 rcept_no {r}"
e("267260", "NEE", "supply", "'연결매출 5% 초과 주요 매출처 NextEra Energy, 사우디전력청' · 수출 78%", D("267260", "20260814003228"), "1차", "2026-06-30", [PSD], ">5%")
e("267260", "SEC_SA", "supply", "주요 매출처 사우디전력청(5% 초과)", D("267260", "20260814003228"), "1차", "2026-06-30", [PSD], ">5%")
e("005490", "267260", "supply", "변압기 강판 매입 8.7% — 매입처 포스코모빌리티솔루션·㈜포스코 등", D("267260", "20260814003228"), "1차", "2026-06-30", [PSD], "원재료의 8.7%")
e("267260", "329180", "service", "CEMS(에너지관리) 구축 프로젝트 — HD현대중공업 울산공장(2026-05 계약)", D("267260", "20260814003228"), "1차", "2026-05", [PSD])
e("267250", "267260", "investment", "HD현대 연결 '전기전자 5%' 부문 = HD현대일렉 — 지분율 검증전", "1차: DART 267250 반기보고서 rcept_no 20260814003420", "1차", "2026-06-30", [PSD])
e("267250", "009540", "investment", "HD현대 연결 '조선해양 40%' = HD한국조선해양", "1차: DART 267250 rcept_no 20260814003420", "1차", "2026-06-30", [PSD], "연결 매출 40%")
e("009540", "329180", "investment", "HD한국조선해양 연결 조선 부문에 HD현대중공업 포함(중간지주)", D("009540", "20260814002569"), "1차", "2026-06-30", [PSD])
e("298040", "015760", "supply", "2026 상반기 주요 매출처 한국전력 9.09%", D("298040", "20260813001554"), "1차", "2026-06-30", [PSD], "9.09%")
e("298040", "042660", "supply", "주요 매출처 한화오션 3.06% — 조선과 전력기기가 직접 거래", D("298040", "20260813001554"), "1차", "2026-06-30", [PSD], "3.06%")
e("005490", "298040", "supply", "변압기·전동기용 강판 매입처 '포스코, 삼동, 티씨머티리얼즈'", D("298040", "20260813001554"), "1차", "2026-06-30", [PSD])
e("010120", "015760", "supply", "'주요 고객 국내외 전력청, 특약점, 데이터센터' — 한전은 연간보고서에 명시", "1차: DART 010120 rcept_no 20260814003088(반기) · 20260318001243(연간 '한국전력')", "1차", "2026-06-30", [PSD])
e("005490", "010120", "supply", "전력 원재료(은·동·철·전기강판) 13.10% — 매입처 포스코모빌리티솔루션 등", D("010120", "20260814003088"), "1차", "2026-06-30", [PSD], "13.10%")
e("006260", "010120", "investment", "LS ELECTRIC은 LS 그룹 계열(IT서비스 '주요고객 LS그룹 계열사') — 지분율 검증전", D("010120", "20260814003088"), "1차", "2026-06-30", [PSD])
for s, why in [("005490", "조선 기자재·강재 68.18% 주요 매입처 ㈜포스코·현대제철"), ("004020", "같은 표 '현대제철㈜'")]:
    e(s, "329180", "supply", why, D("329180", "20260814002879"), "1차", "2026-06-30", [PSD], "조선 매입의 68.18%(합산)")
for s in ["005490", "004020", "329180", "082740", "034020"]:
    e(s, "042660", "supply", "상선 원재료 78.5% 매입처 'POSCO·현대제철·동국제강·HD현대중공업·한화엔진·두산에너빌리티'(엔진은 HD현대중·한화엔진)",
      D("042660", "20260812000829"), "1차", "2026-06-30", [PSD], "상선 매입의 78.5%(합산)")
for s in ["005490", "082740", "329180"]:
    e(s, "010140", "supply", "조선해양 원재료 98.0% 매입처 'POSCO, 한화엔진, HD현대중공업 등'", D("010140", "20260814003496"), "1차", "2026-06-30", [PSD], "매입의 98.0%(합산)")
e("012450", "042660", "investment", "한화에어로 사업부문 '해양: 한화오션㈜ 및 종속회사' 연결 — 연결조정 전 매출의 63.9%",
  D("012450", "20260814003198") + " · analyst_chain_links_appendix §2-25", "1차", "2026-06-30", [PSD], "연결 매출 63.9%")
e("012450", "272210", "investment", "방산부문·IT서비스에 한화시스템 연결", D("012450", "20260814003198"), "1차", "2026-06-30", [PSD])
e("012450", "099320", "investment", "항공우주부문에 ㈜쎄트렉아이 연결", D("012450", "20260814003198"), "1차", "2026-06-30", [PSD])
e("012450", "DAPA", "supply", "방산 29.7%(K9·천무·KM-SAM 등) — 최종 수요 방위사업청 + 수출", D("012450", "20260814003198"), "1차", "2026-06-30", [PSD], "연결 매출 29.7%")
e("012450", "PL_GOV", "supply", "K9·천무 폴란드 수출 — 공시는 '여러 국가 수출 성사'", "2차: 언론(폴란드 K9·천무 계약) · DART 012450 국가명 비중 없음", "2차", "2026-06-30", [PSD])
e("GE", "012450", "supply", "항공부문 원재료 1.08조원 매입처 'GE, P&W, Rolls-Royce, Boeing Distr…'", D("012450", "20260814003198"), "1차", "2026-06-30", [PSD], "1.08조원(복수 매입처 합산)")
e("047810", "DAPA", "supply", "'방위사업청 등 내수 48.24%'", D("047810", "20260814003309"), "1차", "2026-06-30", [PSD], "48.24%")
e("047810", "PL_GOV", "supply", "'폴란드 등 완제기 수출국 30.07%'(FA-50)", D("047810", "20260814003309"), "1차", "2026-06-30", [PSD], "30.07%(복수국)")
e("047810", "BA", "supply", "'Boeing, Airbus, IAI 등 21.69%'(기체 부품)", D("047810", "20260814003309"), "1차", "2026-06-30", [PSD], "21.69%(복수사)")
e("047810", "012450", "supply", "KAI 매출처 표 '한화에어로스페이스 발사체 사업' — 반기 3.69억원, 미미", D("047810", "20260814003309"), "1차", "2026-06-30", [PSD], "3.69억원")
e("064350", "PL_GOV", "supply", "'25년 8월 약 8.5조 규모 폴란드 EC2(K2) 추가 수주'", D("064350", "20260814002977"), "1차", "2025-08", [PSD], "약 8.5조원(수주)")
e("064350", "DAPA", "supply", "K2·차륜형장갑차 내수 — 공시는 사업본부 경로만, 비중 없음", D("064350", "20260814002977"), "검증전", "2026-06-30", [PSD])
e("005380", "064350", "investment", "현대차 원재료 표 '기타부문은 현대로템 기준' — 연결 자회사", "1차: DART 005380 반기보고서 rcept_no 20260814003521", "1차", "2026-06-30", [PSD, BAT])
e("077970", "012450", "supply", "STX엔진 '주요 매출처 방위사업청, 한화에어로스페이스, 에스케이오션플랜트, LIG넥스원'", "1차: DART 077970 사업보고서 rcept_no 20260323000690", "1차", "2025-12-31", [PSD])
e("077970", "DAPA", "supply", "주요 매출처 방위사업청", "1차: DART 077970 rcept_no 20260323000690", "1차", "2025-12-31", [PSD])
e("042660", "DAPA", "supply", "잠수함·수상함 특수선 건조 — 비중은 3Q 분기보고서 대조 필요", D("012450", "20260814003198"), "검증전", "2026-06-30", [PSD])

# ===== kr_battery =====
e("373220", "ULTIUM", "jv", "해외법인 'Ultium Cells Holdings LLC/Ultium Cells LLC'(GM JV) 연결", "1차: DART 373220 반기보고서 rcept_no 20260813000255", "1차", "2026-06-30", [BAT])
e("GM", "ULTIUM", "jv", "GM–LG엔솔 50:50 셀 JV(지분율은 2차)", "2차: GM 10-K 대조 전", "2차", "2026-06-30", [BAT])
e("ULTIUM", "GM", "supply", "Ultium 셀 → GM EV(얼티엄 플랫폼)", "2차: GM IR 일반 설명 — 원문 대조 전", "2차", "2026", [BAT])
e("373220", "GM", "customer", "'주요 매출처 자동차/ESS 고객, 5대 매출처 약 56%' — 고객명 비공개, GM 포함은 해석", "1차 비중 + 해석: DART 373220 rcept_no 20260813000255", "검증전", "2026-06-30", [BAT], "5대 합산 약 56%")
e("051910", "373220", "investment", "LG화학 연결 매출의 53.4%가 LG에너지솔루션", "1차: DART 051910 반기보고서 rcept_no 20260814002655", "1차", "2026-06-30", [BAT], "연결 매출 53.4%")
e("051910", "373220", "supply", "첨단소재 양극재·분리막 → 국내외 2차전지업체, LG엔솔 매입처 LG화학", "1차: DART 051910 rcept_no 20260313001195 · 373220 매입처", "1차", "2026-06-30", [BAT])
for c in ["BMW", "005930", "STLA", "VW"]:
    e("006400", c, "supply", "'주요 매출처 BMW, 삼성전자, Stellantis, Volkswagen Group 등'", "1차: DART 006400 반기보고서 rcept_no 20260814003578", "1차", "2026-06-30", [BAT] + ([SE] if c == "005930" else []))
e("006400", "GM", "jv", "SDI-GM Synergy Cells 합작(콜·풋옵션 조항)", "1차: DART 006400 rcept_no 20260814003578", "1차", "2026-06-30", [BAT])
e("006400", "STLA", "jv", "FCA US와 StarPlus Energy 합작", "1차: DART 006400 rcept_no 20260814003578", "1차", "2026-06-30", [BAT])
e("006400", "247540", "jv", "㈜에코프로이엠 합작(SDI 풋/비엠 콜옵션)", "1차: DART 006400 · 247540 rcept_no 20260814002535", "1차", "2026-06-30", [BAT])
e("247540", "006400", "supply", "'주요 매출처 삼성SDI, SK온 — 비중 94.7%'", "1차: DART 247540 반기보고서 rcept_no 20260814002535", "1차", "2026-06-30", [BAT], "SDI+SK온 94.7%")
e("247540", "096770", "supply", "같은 문구 SK온(SK이노 연결)", "1차: DART 247540 rcept_no 20260814002535", "1차", "2026-06-30", [BAT], "SDI+SK온 94.7%")
e("086520", "247540", "investment", "에코프로비엠 지배회사(종속기업 에코프로이엠 등 연결) — 지분율 검증전", "1차: DART 086520 [기재정정]반기 rcept_no 20260917000296", "1차", "2026-06-30", [BAT])
for c in ["ULTIUM", "373220", "006400", "096770"]:
    e("003670", c, "supply", "에너지소재 매출처 'Ultium Cells, LG에너지솔루션, 삼성SDI, SK온 등 53.0%'", "1차: DART 003670 [기재정정]반기 rcept_no 20260902000346", "1차", "2026-06-30", [BAT], "합산 53.0%")
e("003670", "GM", "jv", "GM 양극재 JV(당사 85%, GM 15%) 캐나다 퀘벡", "1차: DART 003670 rcept_no 20260902000346", "1차", "2026-06-30", [BAT], "85:15")
e("003670", "005490", "supply", "내화물 ㈜포스코 등 15.8% · 라임화성 ㈜포스코·OCI 31.2%", "1차: DART 003670 rcept_no 20260902000346", "1차", "2026-06-30", [BAT, PSD], "15.8%/31.2%")
e("005490", "003670", "investment", "포스코그룹 계열 지배(지분율 검증전)", "2차: 그룹 구조 통념 — DART 지분 표 미수집", "2차", "2026-06-30", [BAT])
for c, why in [("005380", "'주요 고객 현대자동차그룹, 메르세데스-벤츠, 폭스바겐, 포드'"), ("000270", "'현대차·기아 및 독일 다임러 포함 글로벌 자동차사에 배터리 공급'"),
               ("MBG", "주요 고객 메르세데스-벤츠 그룹"), ("VW", "주요 고객 폭스바겐"), ("F", "주요 고객 포드")]:
    e("096770", c, "supply", "SK온 " + why, "1차: DART 096770 반기보고서 rcept_no 20260814002500", "1차", "2026-06-30", [BAT])
e("096770", "F", "jv", "BlueOval SK 합작 2026-05 종료 → SK ON TENNESSEE로 개명", "1차: DART 096770 rcept_no 20260814002500", "1차", "2026-05", [BAT], "합작 종료")
e("005380", "000270", "investment", "기아 매입처 '현대자동차 등' 계열 — 현대차가 기아 최대주주(지분율 검증전)", "1차: DART 000270 [기재정정]반기 rcept_no 20260916000427", "1차", "2026-06-30", [BAT])

# 연결 보조
out = {"asof": ASOF,
       "basis": f"DART 사업·반기보고서 '사업의 내용'(data/dart_biz, 반기 우선) · SEC 8-K·IR · 언론/Bloomberg 차트(2026-05-06)는 2차 · 시총 = reports/detail 종가(2026-10-30) × 주식수, 원화는 USDKRW {FX:.2f}({FX_DATE}, macro_series) · 개인 데이터 없음(기업 공시만)",
       "desk": "analyst",
       "note": "dir: investment=투자자→피투자, service/hardware/supply=공급자→고객, customer=매출 주체→고객(공시 '주요 매출처' 원문 그대로), jv=참여자→JV/상대. status 1차=공시·SEC·회사 발표 원문, 2차=언론·Bloomberg 차트, 검증전=공시 이니셜·비공개 고객을 애널이 해석했거나 단일 보도. 금액은 '수주·계약 규모' 의미.",
       "groups": [
           {"key": AI, "name": "AI 순환 거래", "desc": "Bloomberg 'Nvidia Is at the Center of Circular AI Deals'(2026-05-06) 노드 기준 — 투자→컴퓨트 약정→GPU 구매가 다시 같은 회사로 돌아오는 고리. 차트 자체는 2차."},
           {"key": SE, "name": "국내 반도체 공급망", "desc": "소재·장비·후공정·기판 → 삼성·하이닉스 → 미국 빅테크. DART 반기 '주요 매출처·매입처' 문구 기준."},
           {"key": PSD, "name": "전력기기·조선·방산", "desc": "포스코 강판이 세 업종 공통 원가, 한화에어로→한화오션 연결, 효성중→한화오션 직거래, 방사청·폴란드가 공통 수요."},
           {"key": BAT, "name": "2차전지 ↔ 완성차", "desc": "소재(에코프로·포스코퓨처엠) → 셀 3사 → 해외 완성차·JV. 국내 완성차 연결은 SK온만 명시."}],
       "nodes": list(nodes.values()), "edges": edges}
json.dump(out, open("reports/company_links.json", "w"), ensure_ascii=False, indent=1)
from collections import Counter
print(len(nodes), "nodes", len(edges), "edges", Counter(x["status"] for x in edges), Counter(g for x in edges for g in x["groups"]))
print("mc null:", [n["id"] for n in nodes.values() if n["mc_usd"] is None])
