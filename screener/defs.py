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
    "D2": "전체 투자자산 (NAV)",
    "D3": "투자 가능 자산",
    "D4": "순자산 전체",
    "D5": "매매 슬리브",
}

# 한도 (비율)
SEMI_CAP = 0.40           # denominator=D2 테마 밴드 목표 40%
SEMI_BAND = 0.45          # denominator=D2 테마 밴드 발동선 45%
LOSS_LIMIT = 0.12         # denominator=D2 누적 손실 한도 (구 규칙)
STRESS_LIMIT = 0.15       # denominator=D2 스트레스 −15%
ISA_BAND = 0.05           # 코어 북 목표 비중 ±5%p
ISA_TARGET = {"S&P500": 0.40, "NDX": 0.10, "K200": 0.15, "KTB": 0.20, "Gold": 0.15}   # 코어 북 목표 (안건 8)

# 시장 판정
REBOUND_THRESHOLD = 0.005   # 반등일: 14:30 코스피 ≥ 전일 종가 × 1.005
CRASH_PCT = -0.05           # 급락일: 종가 ≤ 전일 × 0.95
CRASH_NEAR_PCT = -0.04      # 급락일 근접 (운용회의 표시)
CRASH_ALERT_PCT = -0.045    # 15:05 장중 급락 신호 (확정 −5% 보다 느슨하게, 15:20 동시호가 준비)

# 주문표
MIN_RR = 2.0                # 주문표 R:R ≥ 2
HARD_STOP = 0.08            # 실효 손절 = max(주문표 손절가, 매수가 × (1 − 0.08))
RISK_PCT_DEFAULT = 0.25     # denominator=D5 1회 리스크 1단계 0.25%
COOLDOWN_MIN = 30           # 매도·판정·포상 후 신규 주문표 금지(분, 결재 #14 ③)

# 상수 이름 → rules_terms.md 용어표의 용어 (check_rules_terms 가 문서에 있는지 검사)
TERMS = {
    "SEMI_CAP": "테마 밴드 40/45/30", "SEMI_BAND": "테마 밴드 40/45/30", "LOSS_LIMIT": "누적 손실 한도",
    "STRESS_LIMIT": "스트레스 −15%", "ISA_BAND": "코어 북", "ISA_TARGET": "코어 북",
    "REBOUND_THRESHOLD": "반등일", "CRASH_PCT": "급락일", "CRASH_NEAR_PCT": "급락일", "CRASH_ALERT_PCT": "급락일",
    "MIN_RR": "주문표 R:R", "HARD_STOP": "실효 손절", "RISK_PCT_DEFAULT": "1회 리스크", "COOLDOWN_MIN": "쿨다운",
}

# 규칙 파일에서 숫자로 재정의하면 안 되는 지역 이름 (모듈 내 별칭 포함)
LOCAL_ALIASES = {
    "THRESHOLD": "REBOUND_THRESHOLD", "CRASH_ALERT_PCT": "CRASH_ALERT_PCT", "MIN_RR": "MIN_RR", "HARD_STOP": "HARD_STOP",
    "RISK_PCT_DEFAULT": "RISK_PCT_DEFAULT", "COOLDOWN_MIN": "COOLDOWN_MIN", "ISA_BAND": "ISA_BAND", "STRESS_LIMIT": "STRESS_LIMIT",
    "SEMI_CAP": "SEMI_CAP", "SEMI_BAND": "SEMI_BAND", "LOSS_LIMIT": "LOSS_LIMIT", "CRASH_PCT": "CRASH_PCT",
}
