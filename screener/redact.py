"""공개 산출물 개인정보 가림 (10/21 감사 D1: reports/logs/pdf_boxes.json 에 애널리스트 실명·회사 이메일 공개).

- mask_emails: 저장 전 텍스트의 이메일을 전부 가린다(허용 목록 없음 — 저장 코드는 무조건 가림).
- public_emails: 공개 저장소 검사용(pre-push 훅). 커밋 신원·예시 도메인만 허용하고 나머지 이메일을 돌려준다.
값을 출력하지 말 것 — 호출하는 쪽은 개수·파일만 보고한다.
"""
from __future__ import annotations

import re

EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# 허용: 커밋 신원, GitHub noreply, RFC 2606 예약 도메인(example.*, .test, .invalid, .localhost)
ALLOW_RX = re.compile(r"^(noreply@anthropic\.com|[^@]+@users\.noreply\.github\.com"
                      r"|[^@]+@(?:[A-Za-z0-9-]+\.)*example\.(?:com|org|net)"
                      r"|[^@]+@[^@]+\.(?:test|invalid|localhost|example))$", re.I)
MASK = "[email]"


def mask_emails(text: str) -> str:
    return EMAIL_RX.sub(MASK, text) if text else text


def public_emails(text: str) -> list[str]:
    """허용 목록 밖 이메일 (공개 저장소에 올라가면 안 되는 것)."""
    return [m.group(0) for m in EMAIL_RX.finditer(text or "") if not ALLOW_RX.match(m.group(0))]


# ---------------------------------------------------------------- 개인 금액 (10/25 PB 누출 사고 재발 방지 — 감사 req-dev-d026b1af)
# 원화 금액 패턴(쉼표 숫자·만/억/원/M 단위) + 개인 문맥어가 같은 창(앞뒤 40자)에 같이 있으면 '개인 금액 의심'.
# 비율(%)·가상 예시·모의 고정 사이즈·순자산 '목표' 금액은 허용(slop_audit (e) 와 같은 취지, 10/24 C1·10/26 겸이 '잡지마').
AMOUNT_RX = re.compile(
    r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"(?:\s?(?:천만\s?원|백만\s?원|만\s?원|억\s?원|원(?![가-힣\w/])|억(?![가-힣\w])|만(?![가-힣\w])(?!\s?(?:콜|건|개|명|주|회))|M(?![A-Za-z가-힣\w]))|(?![\d,]|\s?%|\s?[행건개주명회일종]))")
PERSONAL_RX = re.compile(r"연봉|월급|순자산|내\s?자산|보유|평단|매입가|계좌|잔고|예적금|적립|투자금|원금|용돈|지원금|식대|청약|납입|부모님|(?<![가-힣])내\s|나의|실제\s?금액")
ALLOW_RX_AMT = re.compile(
    r"예시|예:|예를 들|가상|가정|모의|pb_view|고정\s?사이즈|(?:순자산|자산)\s?목표|목표\s?(?:순자산|자산|금액)|"
    r"종가|목표가|지수|포인트|주가|주\s?가격|콜 한도|시가총액|영업이익|매출|순이익|공시|환율|거래대금|순매수|순매도|선물|계약|명목")
CTX_WIN = 40


def personal_amount_hits(text: str) -> list[str]:
    """개인 금액 의심 서명 목록('금액|개인어' — 값이 들어 있으니 호출부는 개수만 쓰고 출력하지 않는다)."""
    out = []
    for m in AMOUNT_RX.finditer(text or ""):
        # 쉼표 없는 맨 숫자(단위 없음)는 위 패턴이 거부 — 단위 없는 것은 쉼표 숫자만 통과
        s = m.group(0)
        if not re.search(r"[,원억만M]", s):
            continue
        ctx = text[max(0, m.start() - CTX_WIN): m.end() + CTX_WIN]
        pm = PERSONAL_RX.search(ctx)
        if ALLOW_RX_AMT.search(ctx) or not pm:
            continue
        if float(re.match(r"[\d,.]+", s).group(0).replace(",", "") or 0) == 0:
            continue
        out.append(f"{s}|{pm.group(0).strip()}")   # 서명 = 금액|개인어 (이웃 글이 바뀌어도 같은 항목으로 센다)
    return out


def has_personal_amount(text: str) -> bool:
    return bool(personal_amount_hits(text))
