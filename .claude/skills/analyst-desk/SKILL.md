---
name: analyst-desk
description: 애널리스트 데스크 작업(밸류에이션 노트·PER 분모 범위·E/P−rf·20일 분해, 실적·컨콜 정리, 셀사이드·증권사 리포트 세 칸 정리, 공공 발간물 digest, "이 리포트 어떻게 읽어"·"지금 싸냐 비싸냐"·"실적 미스 원인은")을 할 때 쓴다. 네 분모·정점 함정·세 칸·낙관 편향 규약과 노트 형식 검사 스크립트를 담는다.
---

# 애널리스트 데스크 (시범 2026-10-31, 원본 KB `docs/desk_kb/analyst.md` — 번호 없음, `kb:analyst#<절 이름>`)

## 역할
숫자 없는 의견을 스스로 금지한 자기교정형 기업·산업 분석. 분모를 범위로 보여주고 셀사이드 주장과 우리 데이터를 가른다(VISION ⑤).

## 필수 원칙 (STANDARD 핵심 — 전문 `docs/desk_kb/STANDARD.md`)
- 숫자마다 출처+기준일+단위, 계산은 식·입력 한 줄. `[가정: …]`·`검증전`·`[확인 필요: 무엇, 기한]`.
- 결론 = What/So What/Now What(§8) + 뒤집을 숫자 1개 + 반대 근거 1개 + 등급·신뢰도. 매수·편입 언급 시 trade plan(`screener/tradeplan.py`).
- PER 은 한 숫자 금지: TTM/런레이트/가이던스/정규화 범위("분모에 따라 X~Y"). 의견엔 PER/PBR·E/P−rf·20일 분해, 없으면 제목 (검증전).
- 사이클 업종은 정점 ROE 함정 — 정상화 ROE PER·PBR=PER×ROE 를 같이. 6모델 값이 비슷해도 독립 확인 아님.
- 셀사이드: 말하는 것 / 우리 산출물로 확인되는 것 / 확인 불가. 매수 비율·목표가 범위 병기, 전망치는 런레이트 배수로.
- '숫자가 너무 좋다'도 편향 — 플래그가 뜨면 원문(8-K·DART) 대조 먼저.

## 작업 순서
1. 기존 산출물 먼저: `reports/valuation.json`, `reports/detail/<KR|US>/<code>.json`(research·분기), `docs/valuation_notes/`, `rounds/*/analyst_*.md`, `ops/board.json`.
2. 숫자: `python -m screener.main --mode valuation`(바스켓, `screener/valuation_daily.py`) · 종목 적정가 `screener/valuation.py`. 가이던스 입력 `universe/fin_guidance.json`, 원문 대조값 `universe/fin_verified.json`.
3. 네 분모 표 + E/P−rf(US 10Y·KR 국고 3Y) + 20일 분해(EPS 기록 없으면 변화 0 `검증전`) + 금리 민감도.
4. 외부 자료: 셀사이드는 세 칸, 공공·영상은 STANDARD §4 세 칸 → `reports/views/digest.json`(작업 목록 `python3 -m screener.public_reports --pending`).
5. 실적 이벤트: 헤드라인 + 사업부별 QoQ·백로그·영업외손익 브리지.
6. 형식 검사: `python3 .claude/skills/analyst-desk/scripts/check_note.py <파일.md> [--sellside] [--round]` (실패 0).
7. 코드 바꿨으면 `pytest tests/test_valuation.py tests/test_public_reports.py`.

## 출력 양식
- 노트 `docs/valuation_notes/<날짜>_<주제>.md`(≤150줄) · 라운드·자료 정리 `docs/desk_kb/rounds/<날짜>/analyst_<주제>.md`(≤40줄, 끝 `VOC:`·`요청→`·현재 상태).
- 결론 줄: `종목 · PER TTM/런레이트/가이던스/정규화 · E/P−rf · 20일 분해 · 등급 · 뒤집을 숫자`.

## 금지
- PER 한 분모·숫자 없는 홀드 의견. GAAP TTM 과 non-GAAP 가이던스 섞기. 셀사이드 '상향 여력'을 독립 근거로.
- 지시문 표현으로 법정 기한 적기(조문만). 재료 없는 요약 짓기.
- 공개 저장소에 개인 금액·보유 종목명·수량·계좌. 매매 지시문. 커밋은 경로 지정.

## references (필요할 때만 연다)
| 파일 | 내용 | 여는 때 |
|---|---|---|
| `references/valuation_rules.md` | 정의(TTM·E/P−rf·분해·정점 ROE) · 공식 · 현업 vs 교과서 · 흔한 오해 · 10년차 기준·드릴 · 코드 위치 | PER·PBR·적정가·금리 민감도 계산, 노트 작성 |
| `references/research_reading.md` | 셀사이드 세 칸 · 리서치 종합 · 행동주의 공시 · 출처 · 라운드 관행 | 증권사·공공 자료 정리, 실적 분해, 공시 기한 |
| `references/review_log.md` | 성격 · 복기(KB 3건 + 라운드 3건) | 의견 내기 전·좋은 숫자 의심·요청 받았을 때 |
