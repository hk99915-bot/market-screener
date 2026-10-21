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
