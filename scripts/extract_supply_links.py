"""DART 사업·반기보고서 '사업의 내용'에서 공급망 관계(매출처·매입처·납품·공급)를 자동 추출 → reports/company_links_auto.json
(애널 데스크, 2026-11-01 — 겸이 「하청들까지 다 안 되나 화신 아비코전자 등등」·「원자재 금융 등 다른 섹터도」).

수작업 reports/company_links.json 은 건드리지 않는다. 화면은 두 파일을 합쳐 쓴다(같은 스키마, status '1차(자동)').

규칙 요약
- 입력: data/dart_biz/<코드>_<rcept_no>.txt — 종목별 최신 보고서(반기 우선)부터 읽고, 같은 (공급자,고객) 쌍은 최신 근거만 남긴다.
  반기에 매출처 문구가 없으면 직전 사업보고서가 보충.
- 방향: 매출처·고객·납품 → {from: 이 회사, to: 상대, type: customer} / 매입처·구매처·공급처 → {from: 상대, to: 이 회사, type: supply}.
- 매칭: KR 유니버스(reports/peers_KR.json n·s) + 확장 상장사 이름(data/flows/names.json, 더 엄격) + 글로벌·원자재 별칭 사전 + 비상장 KR 대형.
  '(주)'·'㈜'·'주식회사'·공백 정규화, LG↔엘지 등 영문/한글 표기 변환, 긴 이름 우선(현대모비스가 '현대'로 안 잡힘).
- 오탐 방지: 이름 뒤 한글은 조사(은·는·의·와·및·등 …)만 허용('애플리케이션'·'메타버스' 차단), 3자 이하 이름은 앞 글자도 경계,
  일반어·그룹명 금지어(대상·동양·LG·SK·한화 …), 경쟁·점유율·주주·지분·합작·MOU 문장 제외, 자기 자신 제외,
  표는 머리행의 '매출처/매입처' 칸만 읽음(점유율 표 등 다른 칸 무시).
- 계열사: 문장에 '계열·종속·특수관계'가 있거나 같은 그룹 접두(현대차그룹·삼성·LG …)면 affil=true (엣지는 남김).
- '기타'·'외'·익명('A사'·'고객사 B')은 노드로 만들지 않고, 보고 회사 노드의 anon_refs 로 센다.
- tier: 1=완성품·대형(그래프 안에서 더 팔 곳이 없거나 글로벌·정부·시총 상위) / 2=tier1 에 직접 납품 / 3=그 아래. 지주사는 'holding'.
- 금융·지분: data/dart_equity/*.json(DART 타법인출자현황·최대주주현황, 개발 수집 예정)이 있으면 type investment(지분율 size)로 합친다.

  python3 scripts/extract_supply_links.py                     # 전체 → reports/company_links_auto.json
  python3 scripts/extract_supply_links.py --sample 30 --seed 1 # 정밀도 점검용 무작위 표본 출력
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASOF = "2026-11-01"
STATUS = "1차(자동)"

# ---------------------------------------------------------------- 사전
# 글로벌·원자재 고객/공급자: id → (이름, mkt, [별칭], 체인 힌트)
GLOBAL: dict[str, tuple[str, str, list[str], str]] = {
    "NVDA": ("엔비디아", "US", ["NVIDIA", "Nvidia", "엔비디아"], "semi"),
    "AAPL": ("애플", "US", ["Apple", "APPLE", "애플"], "elec"),
    "TSLA": ("테슬라", "US", ["Tesla", "TESLA", "테슬라"], "auto"),
    "GM": ("GM", "US", ["GM", "General Motors", "제너럴모터스", "제너럴 모터스", "지엠"], "auto"),
    "F": ("포드", "US", ["Ford", "FORD", "포드"], "auto"),
    "TSM": ("TSMC", "US", ["TSMC", "대만 TSMC"], "semi"),
    "MU": ("마이크론", "US", ["Micron", "MICRON", "마이크론"], "semi"),
    "QCOM": ("퀄컴", "US", ["Qualcomm", "QUALCOMM", "퀄컴"], "semi"),
    "AVGO": ("브로드컴", "US", ["Broadcom", "BROADCOM", "브로드컴"], "semi"),
    "INTC": ("인텔", "US", ["Intel", "INTEL", "인텔"], "semi"),
    "AMD": ("AMD", "US", ["AMD"], "semi"),
    "MSFT": ("마이크로소프트", "US", ["Microsoft", "마이크로소프트"], "elec"),
    "GOOGL": ("알파벳(구글)", "US", ["Google", "Alphabet", "구글", "알파벳"], "elec"),
    "AMZN": ("아마존", "US", ["Amazon", "아마존"], "elec"),
    "META": ("메타", "US", ["Meta Platforms"], "elec"),
    "DELL": ("델", "US", ["Dell", "DELL"], "elec"),
    "CSCO": ("시스코", "US", ["Cisco", "시스코"], "elec"),
    "TXN": ("텍사스인스트루먼트", "US", ["Texas Instruments", "텍사스인스트루먼트"], "semi"),
    "AMAT": ("어플라이드머티어리얼즈", "US", ["Applied Materials", "어플라이드 머티어리얼즈", "어플라이드머티리얼즈"], "semi"),
    "LRCX": ("램리서치", "US", ["Lam Research", "램리서치"], "semi"),
    "ASML": ("ASML", "US", ["ASML"], "semi"),
    "BA": ("보잉", "US", ["Boeing", "BOEING", "보잉"], "defense"),
    "LMT": ("록히드마틴", "US", ["Lockheed Martin", "록히드마틴", "록히드 마틴"], "defense"),
    "RTX": ("RTX", "US", ["Raytheon", "레이시온", "Pratt & Whitney", "프랫앤휘트니"], "defense"),
    "GE": ("GE에어로스페이스", "US", ["GE Aerospace", "GE에어로스페이스", "General Electric", "제너럴일렉트릭"], "defense"),
    "GEV": ("GE버노바", "US", ["GE Vernova", "GE버노바"], "power"),
    "NEE": ("넥스트에라 에너지", "US", ["NextEra", "넥스트에라"], "power"),
    "STLA": ("스텔란티스", "OTHER", ["Stellantis", "스텔란티스"], "auto"),
    "VW": ("폭스바겐그룹", "OTHER", ["Volkswagen", "폭스바겐", "Audi", "아우디", "Porsche", "포르쉐"], "auto"),
    "BMW": ("BMW", "OTHER", ["BMW"], "auto"),
    "MBG": ("메르세데스-벤츠그룹", "OTHER", ["Mercedes-Benz", "Mercedes", "메르세데스", "벤츠", "Daimler", "다임러"], "auto"),
    "TOYOTA": ("도요타", "OTHER", ["Toyota", "TOYOTA", "도요타", "토요타"], "auto"),
    "HONDA": ("혼다", "OTHER", ["Honda", "혼다"], "auto"),
    "NISSAN": ("닛산", "OTHER", ["Nissan", "닛산"], "auto"),
    "RENAULT": ("르노", "OTHER", ["Renault", "르노"], "auto"),
    "VOLVO": ("볼보", "OTHER", ["Volvo", "볼보"], "auto"),
    "RIVN": ("리비안", "US", ["Rivian", "리비안"], "auto"),
    "BYD": ("BYD", "OTHER", ["BYD"], "auto"),
    "CATL": ("CATL", "OTHER", ["CATL"], "battery"),
    "PANASONIC": ("파나소닉", "OTHER", ["Panasonic", "파나소닉"], "battery"),
    "SONY": ("소니", "OTHER", ["Sony", "SONY", "소니"], "elec"),
    "HUAWEI": ("화웨이", "PRIVATE", ["Huawei", "화웨이"], "elec"),
    "XIAOMI": ("샤오미", "OTHER", ["Xiaomi", "샤오미"], "elec"),
    "FOXCONN": ("폭스콘(홍하이)", "OTHER", ["Foxconn", "폭스콘", "Hon Hai", "홍하이"], "elec"),
    "BOSCH": ("보쉬", "PRIVATE", ["Bosch", "BOSCH", "보쉬"], "auto"),
    "CONTI": ("콘티넨탈", "OTHER", ["Continental", "콘티넨탈"], "auto"),
    "MAGNA": ("마그나", "OTHER", ["Magna", "마그나"], "auto"),
    "DENSO": ("덴소", "OTHER", ["Denso", "DENSO", "덴소"], "auto"),
    "SIEMENS": ("지멘스", "OTHER", ["Siemens", "지멘스"], "power"),
    "HITACHI": ("히타치", "OTHER", ["Hitachi", "히타치"], "power"),
    "ABB": ("ABB", "OTHER", ["ABB"], "power"),
    "SCHNEIDER": ("슈나이더일렉트릭", "OTHER", ["Schneider", "슈나이더"], "power"),
    "AIRBUS": ("에어버스", "OTHER", ["Airbus", "에어버스"], "defense"),
    # 원자재 — 광산·석유 메이저 (PB 11/1 추가 요청)
    "BHP": ("BHP", "OTHER", ["BHP"], "materials"),
    "RIO": ("리오틴토", "OTHER", ["Rio Tinto", "RIO TINTO", "리오틴토", "리오 틴토"], "materials"),
    "VALE": ("발레", "OTHER", ["Vale", "VALE", "발레"], "materials"),
    "GLEN": ("글렌코어", "OTHER", ["Glencore", "GLENCORE", "글렌코어"], "materials"),
    "FMG": ("포테스큐", "OTHER", ["Fortescue", "FMG", "포테스큐"], "materials"),
    "AAL": ("앵글로아메리칸", "OTHER", ["Anglo American", "앵글로아메리칸", "앵글로 아메리칸"], "materials"),
    "ARAMCO": ("사우디 아람코", "OTHER", ["Aramco", "ARAMCO", "아람코"], "materials"),
    "ADNOC": ("ADNOC(아부다비 국영석유)", "GOV", ["ADNOC", "아부다비국영석유"], "materials"),
    "KPC": ("쿠웨이트 국영석유(KPC)", "GOV", ["Kuwait Petroleum", "쿠웨이트국영석유"], "materials"),
    "XOM": ("엑슨모빌", "US", ["ExxonMobil", "Exxon", "엑슨모빌"], "materials"),
    "CVX": ("셰브론", "US", ["Chevron", "셰브론", "쉐브론"], "materials"),
    "SHEL": ("셸", "OTHER", ["Shell", "SHELL", "쉘"], "materials"),
    "BP": ("BP", "OTHER", ["BP"], "materials"),
    "ALB": ("앨버말", "US", ["Albemarle", "앨버말", "알버말"], "materials"),
    "SQM": ("SQM", "US", ["SQM"], "materials"),
    "GANFENG": ("간펑리튬", "OTHER", ["Ganfeng", "간펑"], "materials"),
    "TIANQI": ("톈치리튬", "OTHER", ["Tianqi", "톈치", "티엔치"], "materials"),
    "PLS": ("필바라 미네랄스", "OTHER", ["Pilbara", "필바라"], "materials"),
    "UMICORE": ("유미코아", "OTHER", ["Umicore", "유미코아"], "materials"),
    "NIPPONSTEEL": ("일본제철", "OTHER", ["Nippon Steel", "일본제철", "신일철주금"], "materials"),
    "CARGILL": ("카길", "PRIVATE", ["Cargill", "카길"], "materials"),
    "DAPA": ("방위사업청", "GOV", ["방위사업청", "방사청"], "defense"),
    "KEPCO_KHNP": ("한국수력원자력", "GOV", ["한국수력원자력", "한수원"], "power"),
}
# 비상장 KR 대형(자회사) — 상장 모회사로 귀속하는 경우는 KR 코드로, 아니면 PRIVATE
KR_PRIVATE: dict[str, tuple[str, list[str], str]] = {
    "SDC": ("삼성디스플레이(삼성전자 자회사)", ["삼성디스플레이"], "elec"),
    "HYTRANSYS": ("현대트랜시스", ["현대트랜시스"], "auto"),
    "HYKEFICO": ("현대케피코", ["현대케피코"], "auto"),
    "GMKOREA": ("한국GM", ["한국GM", "한국지엠", "GM Korea"], "auto"),
    "RENAULTKR": ("르노코리아", ["르노코리아", "르노삼성"], "auto"),
    "SKSILTRON": ("SK실트론", ["SK실트론", "에스케이실트론"], "semi"),
    "HANWHAQ": ("한화큐셀(한화솔루션 부문)", [], "power"),
}
# 상장 모회사로 귀속하는 자회사 별칭(수작업 company_links.json 과 같은 처리)
KR_ALIAS: dict[str, list[str]] = {
    "005380": ["현대자동차", "현대차", "Hyundai Motor", "HMC"],
    "000270": ["기아", "기아자동차", "Kia", "KIA"],
    "096770": ["SK온", "에스케이온", "SK On"],
    "005490": ["포스코", "POSCO", "(주)포스코", "주식회사 포스코"],
    "373220": ["LG엔솔", "엘지에너지솔루션"],
    "000660": ["하이닉스", "SK hynix", "SK Hynix"],
    "005930": ["Samsung Electronics", "삼성전자㈜"],
    "034220": ["LGD", "엘지디스플레이"],
    "009150": ["삼성전기"],
    "012330": ["모비스"],
    "009540": ["한국조선해양"],
    "329180": ["현대중공업"],
    "042660": ["대우조선해양"],
    "015760": ["한전"],
}
STOP = {"대상", "동양", "동서", "신흥", "선진", "무학", "서산", "국전", "원익", "두산", "한화", "LG", "SK", "GS", "LS", "CJ",
        "코오롱", "효성", "한진", "신세계", "DB", "DL", "HDC", "HD현대", "아세아", "웅진", "태광", "삼영", "신원", "디오", "피노",
        "오로라", "핑거", "스피어", "엘리스", "아톤", "야스", "SG", "E1", "KT", "NC", "LF", "케이씨", "브이엠", "태성", "제이오",
        "더즌", "노타", "컨텍", "퓨릿", "삼현", "그래피", "인투셀", "알멕", "엔켐", "천보", "디아이", "채비", "아크릴", "매드업",
        "메쥬", "베뉴지", "브이티", "우리로", "아스트", "엠로", "미코", "다날", "케이프", "웹젠", "제우스", "예스티", "제닉",
        "코칩", "하림", "나무가", "티쓰리", "와이씨", "솔루엠", "SFA", "ISC", "GST", "테스", "DMS", "SBS", "BGF", "대덕",
        "삼성", "현대", "롯데", "포스코홀딩스", "경방", "대동", "선광", "방림", "보령", "넥센", "서연", "서흥", "한샘", "광전자",
        "에스원", "유니드", "두올", "풍산", "우진", "한텍", "고영", "스맥", "하이브", "국보", "동방", "대원", "한국", "세원",
        "에이스", "유진", "신성", "대성", "동국", "삼보", "성우", "영진", "진성", "화인", "센트럴"}
GROUP_PREFIX = [("현대차그룹", ("현대자동차", "현대차", "기아", "현대모비스", "현대위아", "현대글로비스", "현대로템", "현대제철",
                               "현대오토에버", "현대트랜시스", "현대케피코", "현대비앤지", "현대건설")),
                ("HD현대", ("HD현대", "현대중공업", "현대미포", "한국조선해양", "현대일렉")),
                ("삼성", ("삼성",)), ("LG", ("LG", "엘지")), ("SK", ("SK", "에스케이")), ("한화", ("한화",)),
                ("포스코", ("포스코", "POSCO")), ("롯데", ("롯데",)), ("두산", ("두산",)), ("효성", ("효성",)),
                ("LS", ("LS",)), ("CJ", ("CJ",)), ("GS", ("GS",)), ("코오롱", ("코오롱",)), ("에코프로", ("에코프로",))]
HOLD_NAMES = {"LG", "SK", "GS", "CJ", "LS", "한화", "두산", "HD현대", "효성", "코오롱", "한진칼", "SK스퀘어", "DL", "DB",
              "HDC", "롯데지주", "HD한국조선해양", "삼성물산", "에코프로", "POSCO홀딩스", "포스코홀딩스", "현대지에프홀딩스", "아모레퍼시픽홀딩스"}

BIG_USD = 20e9                 # tier1 '대형' 기준 — 시총 $20B 이상(삼성·하이닉스·현대차·기아·POSCO 급)

# 섹터(peers_KR g) → 체인 그룹
SECTOR_GROUP = {
    "자동차": "auto", "운송장비·부품": "auto",
    "반도체": "semi", "반도체 장비·소재": "semi",
    "전기·전자": "elec", "디스플레이": "elec", "IT 하드웨어·디스플레이": "elec", "의료·정밀기기": "elec",
    "조선": "ship", "방산·우주": "defense", "2차전지": "battery", "전력기기·전선": "power", "원전": "power",
    "에너지·소재": "materials", "화학": "materials", "금속": "materials", "비철·제련": "materials", "비금속": "materials",
    "금융": "finance", "기타금융": "finance",
}
GROUPS = [
    ("sc_auto", "자동차 공급망(자동)", "완성차 ← 모듈·부품 1차 협력 ← 2차 협력. DART '주요 매출처·매입처' 자동 추출."),
    ("sc_elec", "전자부품(자동)", "세트(스마트폰·가전·디스플레이) ← 부품·소재."),
    ("sc_semi", "반도체(자동)", "소재·장비·후공정·기판 → 메모리·파운드리 → 글로벌 고객."),
    ("sc_ship", "조선 기자재(자동)", "조선소 ← 엔진·기자재·강재."),
    ("sc_defense", "방산(자동)", "방위사업청·해외 정부 ← 체계업체 ← 부품."),
    ("sc_battery", "2차전지(자동)", "완성차 ← 셀 ← 양극재·전구체·소재 ← 광물."),
    ("sc_power", "전력기기(자동)", "유틸리티·발전 ← 변압기·전선·원전 기자재."),
    ("sc_materials", "원자재(자동)", "광산·석유 메이저 → 철강·비철·화학·정유 → 조선·자동차·건설·가전."),
    ("sc_finance", "금융·지분(자동)", "지주사 → 자회사 지분(DART 타법인출자·최대주주, data/dart_equity 수집 후)."),
    ("sc_other", "기타 공급망(자동)", "위 체인 밖 업종의 매출처·매입처."),
]
GKEY = {k.split("_", 1)[1]: k for k, _, _ in GROUPS}

# 이름 바로 뒤 한글 덩어리로 허용하는 것(조사·연결어) — '애플리케이션'·'메타버스'·'이엘씨에이' 같은 이어붙은 다른 낱말 차단
PARTICLES = {"은", "는", "이", "가", "을", "를", "의", "와", "과", "에", "에게", "에서", "에는", "에도", "에의", "도", "및", "등",
             "등이", "등을", "등의", "등에", "등과", "등으로", "등은", "등에서", "등이며", "등입니다", "외", "외에", "로", "으로",
             "로부터", "으로부터", "로의", "으로의", "만", "향", "측", "그룹", "그룹사", "계열", "과의", "와의", "이며", "이고", "이다",
             "입니다", "에서는", "社", "사", "사와", "사의", "사에", "사로", "와는", "과는", "까지", "부터", "에게서", "이나", "나",
             "께", "에선", "이었", "였", "이며,", "그리고"}
CUST_KW = ("매출처", "판매처", "주요 고객", "주요고객", "고객사", "고객으로", "고객은", "고객인", "고객에", "납품", "발주처",
           "공급하고", "공급하는", "공급하며", "공급하여", "공급 중", "공급중", "공급을 하", "판매하고", "판매하는", "수출하고")
SUPP_KW = ("매입처", "구매처", "구입처", "조달처", "공급처", "공급업체", "공급사", "공급받", "매입하", "구매하", "구입하",
           "조달하", "수입하")
NEG_KW = ("경쟁", "점유율", "시장지위", "주주", "지분", "합작", "출자", "인수", "합병", "소송", "분쟁", "특허", "라이선스",
          "라이센스", "MOU", "양해각서", "업무협약", "제휴", "벤치마크", "대비 ", "순위", "앱스토어", "앱 스토어",
          "플레이스토어", "구글 플레이", "Google Play", "App Store", "자체 개발", "상품명", "대출", "임차", "인증", "마켓사", "관계기업", "계약 체결 당사자", "당사자", "위임받", "대금 지급", "지급됩니다", "출처 :", "출처:", "협동조합")
HDR_C = ("매출처", "판매처", "고객", "발주처", "납품처")
HDR_S = ("매입처", "구입처", "구매처", "공급처", "공급업체", "공급사", "조달처")
ANON_RE = re.compile(r"(?<![A-Za-z가-힣])[A-Z]사(?![가-힣A-Za-z])|고객사\s?[A-Z](?![A-Za-z])")
PCT_RE = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)\s*%")
HDR_LINE = re.compile(r"^#\s*(.+?)\s*\((\d{6})\)\s*·\s*(.+?)\s*·\s*접수\s*(\d{8})\s*·\s*rcept_no\s*(\d+)")


def norm(s: str) -> str:
    s = re.sub(r"\(주\)|㈜|주식회사|\(株\)|\s+", "", s or "")
    return s


def is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def is_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def group_of_name(name: str) -> str | None:
    for g, prefixes in GROUP_PREFIX:
        if any(name.startswith(p) for p in prefixes):
            return g
    return None


def is_holding(name: str) -> bool:
    return norm(name) in HOLD_NAMES or re.search(r"지주|홀딩스", name or "") is not None


# ---------------------------------------------------------------- 사전 구성
class Dictionary:
    def __init__(self, peers: list[dict], names: dict[str, str]):
        self.info: dict[str, dict] = {}          # id → {name, mkt, sector, chain, universe, mc_krw}
        self.alias: dict[str, tuple[str, bool]] = {}   # alias → (id, strict)
        for r in peers:
            self.info[r["s"]] = {"name": r["n"], "mkt": "KR", "sector": r.get("g"), "chain": SECTOR_GROUP.get(r.get("g"), "other"),
                                 "universe": "peers", "mc_krw": r.get("mc")}
            self._add_kr(r["s"], r["n"], strict=False)
        for code, n in names.items():
            if code in self.info or not re.fullmatch(r"\d{5}0", code):
                continue
            if re.search(r"스팩|ETF|ETN|리츠|KODEX|TIGER|우$|우B$|\d우", n):
                continue
            self.info[code] = {"name": n, "mkt": "KR", "sector": None, "chain": None, "universe": "names", "mc_krw": None}
            self._add_kr(code, n, strict=True)
        for code, al in KR_ALIAS.items():
            if code in self.info:
                for a in al:
                    self.alias[a] = (code, False)
        for i, (n, al, ch) in KR_PRIVATE.items():
            self.info[i] = {"name": n, "mkt": "PRIVATE", "sector": None, "chain": ch, "universe": "private", "mc_krw": None}
            for a in al:
                self.alias[a] = (i, False)
        for i, (n, mkt, al, ch) in GLOBAL.items():
            self.info[i] = {"name": n, "mkt": mkt, "sector": None, "chain": ch, "universe": "global", "mc_krw": None}
            for a in al:
                self.alias[a] = (i, len(a) <= 3)
        self.whitelist = {a for al in KR_ALIAS.values() for a in al} | {"기아", "현대차", "삼성SDI", "LG화학", "LG전자", "SK온", "한전"}
        keys = sorted(self.alias, key=len, reverse=True)
        self.rx = re.compile("|".join(re.escape(k) for k in keys))

    def _add_kr(self, code: str, n: str, strict: bool) -> None:
        base = norm(n)
        if not base or base in STOP:
            return
        hang = sum(is_hangul(c) for c in base)
        if strict and (len(base) < 3 or (hang == 0 and len(base) < 4)):
            return                              # 확장 이름은 3자 이상만
        short = len(base) <= 3
        variants = {base, n.strip()}
        for en, ko in (("LG", "엘지"), ("SK", "에스케이"), ("CJ", "씨제이"), ("GS", "지에스"), ("LS", "엘에스"), ("HD", "에이치디"),
                       ("KT", "케이티"), ("SDI", "에스디아이"), ("POSCO", "포스코")):
            if base.startswith(en):
                variants.add(ko + base[len(en):])
        for v in variants:
            if v and v not in STOP and (v not in self.alias or self.info[self.alias[v][0]]["universe"] != "peers"):
                self.alias[v] = (code, strict or short)

    @staticmethod
    def _listy(text: str, s: int, e: int) -> bool:
        pre = re.sub(r"(\(주\)|㈜|주식회사)\s*$", "", text[:s]).rstrip()
        post = re.sub(r"^\s*(\(주\)|㈜|주식회사)", "", text[e:])
        marked = pre != text[:s].rstrip() or post != text[e:]
        left = (not pre) or pre[-1] in ",、ㆍ·/(:|"
        right = (not post.strip()) or post.lstrip()[:1] in ",、ㆍ·/)外" or post.lstrip().startswith(("등", "및", "외"))
        return marked or (left and right)

    def find(self, text: str):
        """경계 규칙을 통과한 (start, end, id) 목록."""
        out = []
        for m in self.rx.finditer(text):
            a = m.group(0)
            i, strict = self.alias[a]
            s, e = m.start(), m.end()
            prev = text[s - 1] if s else " "
            nxt = text[e] if e < len(text) else " "
            if is_alnum(a[0]) and is_alnum(prev):
                continue
            if is_alnum(a[-1]) and is_alnum(nxt):
                continue
            if strict and is_hangul(a[0]) and (is_hangul(prev) or is_alnum(prev)):
                continue
            if is_hangul(nxt):
                tok = re.match(r"[가-힣]+", text[e:]).group(0)
                if tok not in PARTICLES:
                    continue
            if is_alnum(a[0]) and (prev == "-" or nxt == "-"):
                continue                        # 'HYUNDAI-POSCO …' 같은 합성 법인명
            if self.info[i]["mkt"] == "KR" and len(norm(a)) <= 4 and a not in self.whitelist and not self._listy(text, s, e):
                continue                        # 짧은 KR 이름(디바이스·심텍 …)은 목록·법인 표기 문맥에서만
            if self.info[i]["universe"] == "names" and not self._listy(text, s, e):
                continue                        # 확장 이름(유니버스 밖)은 목록·법인 표기 문맥에서만
            out.append((s, e, i))
        return out


# ---------------------------------------------------------------- 문서 파싱
def parse_header(first: str, path: Path) -> dict:
    m = HDR_LINE.match(first)
    if m:
        name, code, rpt, date, rno = m.groups()
    else:
        code, rno = path.stem.split("_")[:2]
        name, rpt, date = "", "", rno[:8]
    pm = re.search(r"\((\d{4})\.(\d{2})\)", rpt)
    period = f"{pm.group(1)}-{pm.group(2)}-{'30' if pm.group(2) in ('06', '09') else '31'}" if pm else None
    kind = "반기" if "반기" in rpt else ("분기" if "분기" in rpt else "사업")
    return {"name": name, "code": code, "rpt": rpt, "date": date, "rcept_no": rno, "period": period, "kind": kind}


def sentences(line: str) -> list[str]:
    parts = re.split(r"(?<=다\.)\s*|(?<=[.;])\s+(?=[가-힣A-Z(①-⑩\d])", line)
    return [p.strip() for p in parts if p and p.strip()]


def role_of_sentence(s: str, section: str | None = None) -> str | None:
    """section: 'raw'(원재료 절) | 'sales'(매출 절) | None — '주요 거래처'처럼 방향 없는 말은 절로 판정."""
    if any(k in s for k in NEG_KW):
        return None
    c = any(k in s for k in CUST_KW) or ("거래처" in s and section != "raw")
    if "거래처" in s and section == "raw" and not any(k in s for k in CUST_KW):
        return "S"
    sp = any(k in s for k in SUPP_KW)
    if c and not sp:
        return "C"
    if sp and not c:
        return "S"
    if c and sp:
        if "매출처" in s and "매입처" not in s:
            return "C"
        if "매입처" in s and "매출처" not in s:
            return "S"
        return "?"
    return None


def local_role(s: str, e: int, nxt_start: int) -> str | None:
    w = s[e:min(nxt_start, e + 30)]
    if re.search(r"(으)?로부터.{0,6}(수주|주문|발주|용역을 수행|의뢰)", w):
        return "C"                              # '…조선소로부터 수주' = 상대가 고객
    if re.search(r"(으)?로부터.{0,12}(매입|구매|구입|조달|수입|공급|납품)|에서\s?(매입|구매|구입|조달|수입|공급받)", w):
        return "S"
    if re.search(r"^\S{0,3}\s?(에|으로|로)\s?(납품|공급|판매|수출)|^\S{0,3}\s?향", w):
        return "C"
    return None


def clip(s: str, a: int, b: int, n: int = 120) -> str:
    s1 = s.replace("\t", " | ")
    if len(s1) <= n:
        return s1
    mid = (a + b) // 2
    lo = max(0, min(mid - n // 2, len(s1) - n))
    return ("…" if lo else "") + s1[lo:lo + n - 2] + ("…" if lo + n - 2 < len(s1) else "")


def extract_doc(text: str, path: Path, D: Dictionary) -> tuple[dict, list[dict], int]:
    lines = text.splitlines()
    meta = parse_header(lines[0] if lines else "", path)
    me = meta["code"]
    found: list[dict] = []
    anon = 0
    inf = D.info.get(me, {})
    if inf.get("chain") == "finance":
        return meta, found, 0                   # 금융사는 매출처 문구가 상품·차주 서술 — 지분 데이터로만
    holding_me = is_holding(inf.get("name") or meta["name"])
    hdr: dict | None = None            # {"cols": {idx: role}, "n": ncols} | {"neg": True}

    def emit(seg: str, s: int, e: int, nid: str, role: str, nxt_start: int, prose: bool = False):
        if nid == me or any(k in seg for k in NEG_KW):
            return
        if re.match(r"\s*(\(?주\d+\)|※|\*\d*\)?)", seg) and re.search(r"계열|관계", seg):
            return                              # 각주의 계열·관계 설명
        if prose and re.fullmatch(r"[\s\-\*·()\d.①-⑩◆■□○●]*((또한|한편|그리고|이 중|이중)\s*,?\s*)?(\(주\)|㈜)?", seg[:s]):
            return                              # 문장 첫머리 = 주어(연결 자회사 서술) — 상대방 아님
        tail = seg[e:e + 12]
        if re.match(r"(\(주\)|㈜)?(은|는)[ ,]", tail) or re.match(r"(\(주\)|㈜)?\s?(의 주요 (매출|매입)처|및\s?종속회사|과 그 종속)", tail):
            return                              # 문장 주어(자회사 설명 등) — 상대방이 아님
        w = seg[e:min(nxt_start, e + 30)]
        pm = PCT_RE.search(w)
        pct = float(pm.group(1)) if pm and 0 < float(pm.group(1)) <= 100 else None
        mine, other = D.info.get(me, {}).get("name") or meta["name"], D.info[nid]["name"]
        affil = bool(re.search(r"계열|종속|특수관계|관계회사", seg)) or (
            group_of_name(norm(mine)) is not None and group_of_name(norm(mine)) == group_of_name(norm(seg[s:e])))
        if affil and holding_me:
            return                              # 지주사 보고서의 자회사 서술 — 지분 엣지(sc_finance)로만
        found.append({"me": me, "other": nid, "role": role, "pct": pct, "why": clip(seg, s, e), "affil": affil})

    section = None
    for raw in lines[1:]:
        line = raw.strip()
        hm = re.match(r"^\d{1,2}\.\s*(.{0,30})$", line)
        if hm:
            section = "raw" if re.search(r"원재료|원자재|매입", hm.group(1)) else ("sales" if re.search(r"매출|판매|수주", hm.group(1)) else None)
        if not line or "\t" not in line:
            hdr = None
        if not line:
            continue
        if "\t" in line:
            cells = [c.strip() for c in line.split("\t")]
            cols = {}
            for j, c in enumerate(cells):
                if len(c) > 30:
                    continue
                if any(k in c for k in HDR_S):
                    cols[j] = "S"
                elif any(k in c for k in HDR_C):
                    cols[j] = "C"
            if cols and len([c for c in cells if c]) >= 2 and not any(D.find(c) for c in cells if len(c) <= 30 and c not in ()):
                hdr = {"cols": cols, "n": len(cells)}
                if any(any(k in c for k in ("점유율", "경쟁")) for c in cells):
                    hdr = {"neg": True}
                continue
            if any(any(k in c for k in ("점유율", "경쟁사", "경쟁업체")) for c in cells):
                hdr = {"neg": True}
                continue
            if hdr and hdr.get("neg"):
                continue
            if hdr:
                shift = hdr["n"] - len(cells)
                for j, role in hdr["cols"].items():
                    k = j - shift if shift > 0 else j
                    if not 0 <= k < len(cells):
                        continue
                    cell = cells[k]
                    if ANON_RE.search(cell):
                        anon += 1
                    hits = D.find(cell)
                    for t, (s, e, nid) in enumerate(hits):
                        nx = hits[t + 1][0] if t + 1 < len(hits) else len(cell)
                        emit(cell, s, e, nid, role, nx)
                continue
            segs = [line]
        else:
            segs = sentences(line)
        for seg in segs:
            role = role_of_sentence(seg, section)
            if role is None:
                continue
            if ANON_RE.search(seg) and role in ("C", "?"):
                anon += 1
            hits = D.find(seg)
            for t, (s, e, nid) in enumerate(hits):
                nx = hits[t + 1][0] if t + 1 < len(hits) else len(seg)
                r = local_role(seg, e, nx) or (role if role in ("C", "S") else None)
                if r:
                    emit(seg, s, e, nid, r, nx, prose="\t" not in seg)
    return meta, found, anon


# ---------------------------------------------------------------- 지분(금융) — data/dart_equity
def load_equity(eq_dir: Path, D: Dictionary) -> list[dict]:
    """DART 타법인출자현황(inv_prm·trmend_blce_qy_rt)·최대주주현황(nm·trmend_posesn_stock_qota_rt) 행을 관용적으로 읽는다.
    파일: <코드>_*.json, 내용은 dict(list 값들) 또는 list. 상대 이름은 정규화 후 완전 일치만(사람 이름 오탐 방지)."""
    out = []
    if not eq_dir.exists():
        return out
    exact = {norm(a): i for a, (i, _) in D.alias.items()}
    for p in sorted(eq_dir.glob("*.json")):
        code = p.stem.split("_")[0]
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = []
        for v in (d.values() if isinstance(d, dict) else [d]):
            if isinstance(v, list):
                rows += [r for r in v if isinstance(r, dict)]
        rno = d.get("rcept_no", "") if isinstance(d, dict) else ""
        for r in rows:
            code_r = r.get("stock_code") or code
            if "inv_prm" in r:
                tid = exact.get(norm(r["inv_prm"]))
                pct = r.get("trmend_blce_qy_rt")
                if tid and tid != code_r:
                    out.append({"from": code_r, "to": tid, "pct": pct, "why": f"타법인출자현황: {r['inv_prm']} 기말 지분율 {pct}%",
                                "rno": r.get("rcept_no", rno)})
            elif "nm" in r and ("trmend_posesn_stock_qota_rt" in r or "relate" in r):
                hid = exact.get(norm(r["nm"]))
                pct = r.get("trmend_posesn_stock_qota_rt")
                if hid and hid != code_r:
                    out.append({"from": hid, "to": code_r, "pct": pct, "why": f"최대주주현황: {r['nm']} 지분율 {pct}%",
                                "rno": r.get("rcept_no", rno)})
    return out


# ---------------------------------------------------------------- 그래프 조립
def latest_files(biz_dir: Path) -> dict[str, list[Path]]:
    by = collections.defaultdict(list)
    for p in biz_dir.glob("*_*.txt"):
        by[p.stem.split("_")[0]].append(p)
    return {c: sorted(v, key=lambda x: x.stem.split("_")[1], reverse=True) for c, v in by.items()}


def build(biz_dir: Path, peers: list[dict], names: dict[str, str], fx: float, eq_dir: Path | None = None) -> dict:
    D = Dictionary(peers, names)
    edges: dict[tuple, dict] = {}
    reporters, anon_refs = {}, collections.Counter()
    for code, files in sorted(latest_files(biz_dir).items()):
        for p in files:                          # 최신(반기) 먼저 — 같은 쌍은 먼저 들어온 근거 유지
            meta, found, anon = extract_doc(p.read_text(encoding="utf-8", errors="ignore"), p, D)
            reporters.setdefault(code, meta)
            if code not in D.info:
                D.info[code] = {"name": meta["name"] or code, "mkt": "KR", "sector": None, "chain": None,
                                "universe": "dart_biz", "mc_krw": None}
            anon_refs[code] = max(anon_refs[code], anon)
            for f in found:
                if f["role"] == "C":
                    a, b, typ = code, f["other"], "customer"
                else:
                    a, b, typ = f["other"], code, "supply"
                key = (a, b)
                if key in edges:
                    ed = edges[key]
                    if code not in ed["_rep"]:
                        ed["_rep"].append(code)        # 양쪽 공시가 같은 관계를 말함
                    if ed["size"] is None and f["pct"] is not None and ed["_rno"] == meta["rcept_no"]:
                        ed["size"] = f"{'매출' if typ == 'customer' else '매입'} 비중 {f['pct']:g}%(원문)"
                    continue
                edges[key] = {"from": a, "to": b, "type": typ,
                              "size": (f"{'매출' if typ == 'customer' else '매입'} 비중 {f['pct']:g}%(원문)" if f["pct"] is not None else None),
                              "why": f["why"], "src": f"DART {code} rcept_no {meta['rcept_no']}", "status": STATUS,
                              "date": meta["period"], "affil": f["affil"], "_rep": [code], "_rno": meta["rcept_no"]}
    for q in (load_equity(eq_dir, D) if eq_dir else []):
        key = (q["from"], q["to"])
        if key in edges and edges[key]["type"] == "investment":
            continue
        k2 = key if key not in edges else (q["from"], q["to"], "inv")
        edges[k2] = {"from": q["from"], "to": q["to"], "type": "investment",
                     "size": (f"지분율 {q['pct']}%" if q["pct"] not in (None, "", "-") else None), "why": q["why"][:120],
                     "src": f"DART {q['from'] if q['why'].startswith('타법인') else q['to']} rcept_no {q['rno']} (정형 API)",
                     "status": STATUS, "date": None, "affil": True, "_rep": [], "_rno": q["rno"]}

    # 노드
    used = {e["from"] for e in edges.values()} | {e["to"] for e in edges.values()}
    nodes = {}
    for i in sorted(used):
        inf = D.info[i]
        mc = round(inf["mc_krw"] / fx, -6) if inf.get("mc_krw") else None
        hold = inf["mkt"] == "KR" and is_holding(inf["name"])
        nodes[i] = {"id": i, "name": inf["name"], "mkt": inf["mkt"], "mc_usd": mc,
                    "mc_asof": ("reports/peers_KR.json mc ÷ USDKRW" if mc else "미확인(자동 추출 — 시총 없음)"),
                    "chain": inf.get("chain"), "sector": inf.get("sector"), "groups": [], "listed": inf["mkt"] in ("KR", "US", "OTHER"),
                    "universe": inf["universe"], "holding": bool(hold), "anon_refs": anon_refs.get(i, 0),
                    "reported": i in reporters}
    # 체인 그룹: KR 끝단의 섹터 체인, 없으면 상대의 체인
    for e in edges.values():
        chs = [nodes[x]["chain"] for x in (e["from"], e["to"]) if nodes[x]["chain"]]
        if e["type"] == "investment":
            chs = ["finance"]
        g = sorted({GKEY.get(c, "sc_other") for c in chs}) or ["sc_other"]
        e["groups"] = g
        for x in (e["from"], e["to"]):
            for gg in g:
                if gg not in nodes[x]["groups"]:
                    nodes[x]["groups"].append(gg)
    # tier — 공급 엣지(투자 제외)로 고객 방향 최단 거리
    cust = collections.defaultdict(set)
    for e in edges.values():
        if e["type"] in ("supply", "customer"):
            cust[e["from"]].add(e["to"])
    big = [n for n in nodes.values() if (n["mc_usd"] or 0) >= BIG_USD]
    tier1 = {i for i, n in nodes.items() if not cust.get(i) or n["mkt"] in ("US", "OTHER", "GOV", "PRIVATE") and n["universe"] == "global"}
    tier1 |= {n["id"] for n in big}
    tier = {i: 1 for i in tier1}
    for _ in range(4):
        for i in nodes:
            if i in tier1:
                continue
            ts = [tier[c] for c in cust.get(i, ()) if c in tier]
            if ts:
                tier[i] = min(3, min(ts) + 1)
    for i, n in nodes.items():
        n["tier"] = "holding" if n["holding"] else tier.get(i, 2)
    out_edges = []
    for e in edges.values():
        e["both_sides"] = len(e["_rep"]) >= 2
        e.pop("_rep"); e.pop("_rno")
        out_edges.append(e)
    out_edges.sort(key=lambda e: (e["groups"][0], e["from"], e["to"]))
    used_groups = {g for e in out_edges for g in e["groups"]}
    stats = {"reports": len(reporters), "files": sum(1 for _ in biz_dir.glob("*_*.txt")), "edges": len(out_edges),
             "nodes": len(nodes), "both_sides": sum(e["both_sides"] for e in out_edges),
             "with_size": sum(e["size"] is not None for e in out_edges),
             "affil": sum(e["affil"] for e in out_edges), "anon_refs": sum(anon_refs.values())}
    return {
        "asof": ASOF,
        "basis": "DART 사업·반기보고서 'II. 사업의 내용'(data/dart_biz, 반기 우선) 자동 추출 · scripts/extract_supply_links.py · "
                 "시총 = reports/peers_KR.json mc ÷ USDKRW · 기업 공시만(개인 데이터 없음)",
        "desk": "analyst",
        "note": "자동 1차 — 사람이 원문 대조 전. dir: supply=공급자→고객(매입처 공시), customer=매출 주체→고객(매출처 공시), "
                "investment=출자자→피출자(지분율). tier 1=완성품·대형 2=1차 협력 3=2차 협력(그래프 안 고객 거리로 추정), holding=지주사. "
                "affil=계열 거래, both_sides=양쪽 공시가 같은 관계를 말함. 수작업 reports/company_links.json 과 합쳐 쓴다(같은 id).",
        "stats": stats,
        "groups": [{"key": k, "name": n, "desc": d} for k, n, d in GROUPS if k in used_groups or k == "sc_finance"],
        "nodes": list(nodes.values()),
        "edges": out_edges,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--biz", default=str(ROOT / "data/dart_biz"))
    ap.add_argument("--equity", default=str(ROOT / "data/dart_equity"))
    ap.add_argument("--out", default=str(ROOT / "reports/company_links_auto.json"))
    ap.add_argument("--sample", type=int, default=0, help="무작위 엣지 표본 n 개 출력(정밀도 점검)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    peers = json.loads((ROOT / "reports/peers_KR.json").read_text(encoding="utf-8"))["rows"]
    np_ = ROOT / "data/flows/names.json"
    names = json.loads(np_.read_text(encoding="utf-8")) if np_.exists() else {}
    fx = float(json.loads((ROOT / "reports/macro_series.json").read_text(encoding="utf-8"))["series"]["USDKRW"][-1][4])
    d = build(Path(a.biz), peers, names, fx, Path(a.equity))
    Path(a.out).write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(d["stats"], ensure_ascii=False))
    if a.sample:
        rnd = random.Random(a.seed)
        nm = {n["id"]: n["name"] for n in d["nodes"]}
        for e in rnd.sample(d["edges"], min(a.sample, len(d["edges"]))):
            print(f"{nm[e['from']]} → {nm[e['to']]} [{e['type']}] {e['src']}\n    {e['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
