# market-screener — 세션 상시 규칙

- 작업 규약: `docs/desk_kb/LOOP.md`(데스크 루프·잠금·커밋 접두), `docs/desk_kb/STANDARD.md`(현업급 기준), `docs/schedule_table.md`(실행 주체 일원화).
- **답변·변경 전 확인 원칙:** 숫자·사실·판단을 말하거나 코드를 바꾸기 전에 기존 산출물을 먼저 확인한다 — `reports/`(detail·valuation·studies·trial_log), `docs/valuation_notes/`, `docs/peer_reviews/`, `docs/desk_kb/`, `ops/board.json`. 판단 질문은 해당 데스크 산출물을 인용하거나 데스크를 실제로 돌린 뒤 답한다. 데스크 발언(VOC)은 실제 담당 데스크 에이전트를 호출해 받은 답만 인용한다 — PB가 대신 쓰거나 추정으로 표기하는 것 금지.
- 공개 저장소: 개인 금액·보유·연봉·계좌·의료 정보 금지(비율만). 커밋 신원 `Claude <noreply@anthropic.com>`.
- 검사: `pytest`, `python3 scripts/board.py --check`, `python3 scripts/check_functions.py`, `python3 scripts/check_rules_terms.py`, UI는 `scripts/ui_smoke.py`.
