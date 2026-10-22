"""규칙 상수 단일 원천 — 분모·한도·기한 (refactor_plan 결정 B, docs/rules_terms.md 와 같은 이름).

여기 값을 바꾸면 모든 코드가 같이 바뀐다. 다른 모듈은 숫자를 직접 쓰지 말고 `from .defs import …` 로 가져온다.
`scripts/check_rules_terms.py` 가 ① TERMS 의 용어가 rules_terms.md 용어표에 있는지 ② 규칙 파일에 같은 이름의 숫자
재정의가 없는지 ③ 화면(tab_my.html)의 같은 상수가 여기 값과 같은지 검사한다.
공개 저장소: 비율·기간만 둔다(금액은 env 로만 — SAT_BOOK_KRW 등).
"""
from __future__ import annotations

# 분모 코드 (rules_terms.md §0)
DENOMINATORS = {
    "D1": "위성 북 (일반계좌 전체)",
    "D1'": "위성 북 (원장 평가액)",
    "D2": "(a) 투자자산 (NAV = 위성+ISA+현금)",
    "D2b": "(b) 투자자산+예적금",   # 결재 #1 (10/17 09:28): 반도체 45% 발동선·스트레스 분모
    "D3": "투자 가능 자산",
    "D4": "(c) 순자산 전체",
    "D5": "매매 슬리브",
}

# 분모 라벨 — 화면·텔레그램은 이 문구 그대로 쓴다 (tab_my.html 에 같은 문자열, tests/test_rules_gaps.py 가 검사)
DENOM_TERMS = {"a": "(a) 투자자산", "b": "(b) 투자자산+예적금", "c": "(c) 순자산 전체"}

# 한도 (비율)
SEMI_CAP = 0.40           # denominator=D2 테마 밴드 목표 40%
SEMI_BAND = 0.45          # denominator=D2 테마 밴드 발동선 45%
LOSS_LIMIT = 0.12         # denominator=D2 누적 손실 한도 (구 규칙)
STRESS_LIMIT = 0.15       # denominator=D2 스트레스 −15%
ISA_BAND = 0.05           # 코어 북 목표 비중 ±5%p
ISA_TARGET = {"S&P500": 0.40, "NDX": 0.15, "K200": 0.15, "KTB": 0.20, "Gold": 0.10}   # 코어 북 목표 (안건 8 → 10/21 C안 오너 예외: NDX 15 상한·금 10 상한)

# 결재 #3 (10/17 14:09 도장): 반도체 밴드 레짐 연동 — denominator=D2 (b) 투자자산+예적금
SEMI_REGIME_CAP = {"하락장": 0.35, "회복확인": 0.40, "상승장": 0.40}   # 레짐별 목표(상한). 넘으면 반도체 신규 매수 금지
SEMI_FLOOR = 0.30         # 하단 30% — 아래면 '재매수 허용' 참고선 (의무 아님)
SEMI_GLIDE_TARGET = 0.35  # 적립 글라이드 목표: 11월 말까지 35% (ISA 월 적립 희석 + 필요 시 반등일 축소)
SEMI_GLIDE_BY = "2026-11-30"
SEMI_SWING = ("009150",)  # 삼성전기 — 포함 여부 11/15 리뷰까지 미해결, 화면·점검에 포함/제외 병기
VAR_WINDOW = 60           # VaR 계기판: 60거래일 실현 변동성
VAR99_Z = 2.326           # 1일 VaR99 = 2.326 × σ(60일) (정규 근사, kb:frm q3)
VAR99_LIMIT = 0.02        # denominator=D2 기본 2% (scorecard_week [11] 과 같은 수치)
VAR99_LIMIT_BEAR = 0.015  # denominator=D2 하락장 1.5% — 초과 시 '반도체 신규 매수 금지' 플래그만(강제 매도 없음)

# 결재 #14 (모의 대결): 레버리지·인버스 ETF 보유 상한 1일 + 리셋 비용 표시
MOCK_LEV_HOLD_DAYS = 1
MOCK_LEV_ETFS = {   # 코드/티커 → 배수 (음수 = 인버스). 이 목록 밖 레버리지 상품은 이름의 '레버리지·인버스·2X·3X'로 보조 판정
    "122630": 2, "233740": 2, "252670": -2, "114800": -1, "251340": -1,          # KODEX 레버리지 · 코스닥150 레버리지 · 200선물인버스2X(곱버스) · 인버스 · 코스닥150선물인버스
    "SOXL": 3, "SOXS": -3, "TQQQ": 3, "SQQQ": -3, "UPRO": 3, "SPXU": -3, "TNA": 3, "TZA": -3,
    "NVDL": 2, "TSLL": 2, "QLD": 2, "SSO": 2, "SH": -1, "PSQ": -1,
}

# 시장 판정
REBOUND_THRESHOLD = 0.005   # 반등일: 14:30 코스피 ≥ 전일 종가 × 1.005
CRASH_PCT = -0.05           # 급락일: 종가 ≤ 전일 × 0.95
CRASH_NEAR_PCT = -0.04      # 급락일 근접 (운용회의 표시)
CRASH_ALERT_PCT = -0.045    # 15:05 장중 급락 신호 (확정 −5% 보다 느슨하게, 15:20 동시호가 준비)

# 주문표
POS_BACKSTOP = 0.20          # 규칙 [5] 종목 평단 −20% 백스톱 (반등일 또는 2주 안 정리). 재협상 카운터 id
SEMI_HARD_FLOOR = 0.30       # [5] 개정안(10/17 사전등록, 10/31 도장): 반도체 보유분 평단 −30% 하드 바닥, 장중 터치 즉시
MIN_RR = 2.0                # 주문표 R:R ≥ 2
HARD_STOP = 0.08            # 실효 손절 = max(주문표 손절가, 매수가 × (1 − 0.08))
RISK_PCT_DEFAULT = 0.25     # denominator=D5 1회 리스크 1단계 0.25%
TELEGRAM_ALL_SILENT = True   # 오너 10/17 15시대 "전체 무음으로 해조" — 모든 텔레그램 무음(RING_KINDS 표는 보존, 되돌릴 땐 False)
COOLDOWN_MIN = 30           # 매도·판정·포상 후 신규 주문표 금지(분, 결재 #14 ③)
RENEGO_WARN_AT = 2          # 같은 규칙 재협상 n회째부터 주문표 ⛔ '재협상 2회째' + 사유 칸 필수 (오너 승인 10/17 14:09)
RENEGO_REASON_MIN = 10      # 재협상 사유 최소 글자 수 (agreements §7-4 — 'ㅇ' 1자 통과 금지, 감사 10/17 #24)
RENEGO_SCOPE = {"POS_BACKSTOP": "backstop"}   # 규칙 id → 관련 주문표 범위. 표에 없으면 모든 주문표 (renego.relates)
VAR_SEMI_BUY_BAN = "반도체 신규 매수 금지(결재 #3)"   # VaR 계기판 한도 초과 시 반도체 BUY 주문표 ⛔ (매도는 영향 없음)
SEMI_HARD_FLOOR_STATE = "사전등록(10/31 도장 전)"
# 결재 #15 (10/17 도장): ISA 시장 조건 무시 · 월 1회(1일, 휴장이면 다음 거래일) · 급락일 선매수 연 2회 상한
ISA_MONTHLY_DAY = 1
ISA_CRASH_PER_YEAR = 2
RENEGO_WINDOW_DAYS = 30     # 재협상 횟수를 세는 기간(일) [가정: 월 1회 복기 주기와 맞춤 — 11/30 월말 복기에서 재검토]

# 상수 이름 → rules_terms.md 용어표의 용어 (check_rules_terms 가 문서에 있는지 검사)
TERMS = {
    "SEMI_CAP": "테마 밴드 40/45/30", "SEMI_BAND": "테마 밴드 40/45/30", "LOSS_LIMIT": "누적 손실 한도",
    "STRESS_LIMIT": "스트레스 −15%", "ISA_BAND": "코어 북", "ISA_TARGET": "코어 북",
    "REBOUND_THRESHOLD": "반등일", "CRASH_PCT": "급락일", "CRASH_NEAR_PCT": "급락일", "CRASH_ALERT_PCT": "급락일",
    "MIN_RR": "주문표 R:R", "HARD_STOP": "실효 손절", "RISK_PCT_DEFAULT": "1회 리스크", "COOLDOWN_MIN": "쿨다운",
    "SEMI_REGIME_CAP": "테마 밴드 40/45/30", "SEMI_FLOOR": "테마 밴드 40/45/30", "SEMI_GLIDE_TARGET": "테마 밴드 40/45/30",
    "VAR99_LIMIT": "VaR99 (1일)", "VAR99_LIMIT_BEAR": "VaR99 (1일)",
    "POS_BACKSTOP": "백스톱", "SEMI_HARD_FLOOR": "백스톱",
}

# 규칙 파일에서 숫자로 재정의하면 안 되는 지역 이름 (모듈 내 별칭 포함)
LOCAL_ALIASES = {
    "THRESHOLD": "REBOUND_THRESHOLD", "CRASH_ALERT_PCT": "CRASH_ALERT_PCT", "MIN_RR": "MIN_RR", "HARD_STOP": "HARD_STOP",
    "RISK_PCT_DEFAULT": "RISK_PCT_DEFAULT", "COOLDOWN_MIN": "COOLDOWN_MIN", "ISA_BAND": "ISA_BAND", "STRESS_LIMIT": "STRESS_LIMIT",
    "SEMI_CAP": "SEMI_CAP", "SEMI_BAND": "SEMI_BAND", "LOSS_LIMIT": "LOSS_LIMIT", "CRASH_PCT": "CRASH_PCT",
    "SEMI_FLOOR": "SEMI_FLOOR", "SEMI_GLIDE_TARGET": "SEMI_GLIDE_TARGET", "VAR99_LIMIT": "VAR99_LIMIT", "VAR99_LIMIT_BEAR": "VAR99_LIMIT_BEAR",
}
