# 정합성·연결 자동화 감사 — 2026-10-17 (감사 데스크)

- 지시(오너, 무편집): "이렇게 정합성 안맞고 데이터상 연결 자동화 안되는거 싹다찾아서 감사하고 개발 재발방지"
- 발단: 비공개 합의 원장의 미장 ETF 지정가 매도 줄이 '미체결 시 재시도·기한'으로 남아 있었는데 실제로는 10/17 00:17 체결 → PB가 낡은 줄로 안내(복기 20). 결정 줄과 집행 결과가 다른 파일에 있고 연결이 없음.
- 범위: 비공개 저장소(원장·인수인계·계획서·용어집·README류, history·journal·ledger README, 보유 파일 2종, rules.txt, scorecard·risk 스크립트, household README·월 보고 스크립트, views 개인 렌즈 스크립트) + 공개 `market-screener`(ops/board.json·README.md, docs/schedule_table.md·rules_terms.md·desk_kb/, screener/defs.py·pb.py·committee.py, scripts/ 검사기, apps-script/Scheduler.gs, .github/workflows) + Claude 예약 작업 목록(10/17 list_triggers 스냅샷). `life/`·money 원본·household 거래 행은 열지 않음.
- 기준 시점: 두 저장소 10/17 작업 사본(market-screener 93a8bbfc). 원장 줄 번호는 이 시점 기준이며 이후 편집으로 밀릴 수 있다.
- 무편집 원칙: 지적만 한다. 어느 파일도 고치지 않았다. 공개 문서이므로 금액·수량·평단·종목별 보유는 적지 않고 숫자 차이는 '값 불일치'로만 쓴다. 비공개 파일 경로는 `pb:` 접두로 표기.
- 심각도(audit KB §1): **치명** = 틀린 사실이 결정·안내에 쓰일 수 있는 상태 / **중** = 근거가 끊겨 검증 불가 / **경** = 표기·읽기 비용.

## 0. 요약

| 유형 | 건수 | 치명 | 중 | 경 |
|---|---|---|---|---|
| A 결정↔집행 불일치 | 10 | 1 | 6 | 3 |
| B 같은 사실의 다른 값 | 16 | 0 | 11 | 5 |
| C 연결 자동화 부재 | 14 | 3 | 8 | 3 |
| D 폐기·정정 안내 잔존 | 12 | 0 | 3 | 9 |
| E 검사기 사각지대 | 6 | 1 | 5 | 0 |
| **합계** | **58** | **5** | **33** | **20** |

치명 5건: **A-01**(세션 시작 문서에 체결된 매도가 '미체결·재시도'로 남음) · **C-01**(체결→원장→보유→합의 상태가 전부 손 옮김) · **C-02**(결재 ✅ → rules.txt → 예약 프롬프트 미반영, 월 14:42 예약 PB가 구 규칙으로 판단 가능) · **C-03**(보유·규칙 시크릿 손 붙여넣기, 백스톱 예외 발동선 줄이 보드 할 일에서 빠짐) · **E-06**(비공개 원장 정합성을 보는 검사기 0개).

공통 원인 한 줄: **같은 사실을 여러 파일이 각자 '서술'로 들고 있고, 상태 전이(🗳️→✅, 대기→체결, 결정→규정)를 기록하는 단일 출처와 그걸 대조하는 검사기가 없다.**

## 1. 발견 표

### A. 결정↔집행 불일치
| ID | 유형 | 위치 | 내용 | 심각도 | 재발방지 제안 |
|---|---|---|---|---|---|
| A-01 | A | pb:ops/HANDOFF.md:38 · pb:history/2026-10.md:12 · pb:ops/PLAN_2026-10-16.md:63,123-124 ↔ pb:history/2026-10.md:11,69,75 · pb:journal/2026-10-16.md:118 · pb:ops/agreements.md:20 | 발단 건. 원장 :20 은 10/17 23시에 '집행 완료'로 정정됐지만, **세션 시작 시 먼저 읽는** HANDOFF :38 은 여전히 '미장 플러스인 밤 지정가, 기한 10/23', history 현재 상태 :12 는 정정 전 줄을 `1-old` 로 남김, PLAN :123-124 는 '10/23 기한' 체크박스 열림. 같은 오안내 재발 경로가 3곳 남음 | 치명 | 자동 연결: `integrity_check`(P0-1)가 '미체결·재시도·기한' 문구 ↔ `scorecard/unsettled_trades.csv`·holdings 체결 주석 대조 / 단일 출처: HANDOFF '진행 중' 절을 생성형으로(P0-5) |
| A-02 | A | pb:ops/agreements.md:19 ↔ :20 · pb:history/2026-10.md:11 | 바로 아래 :20 은 체결 완료인데 :19(✅ '남은 축소: 미장 ETF + 국내 ETF')는 그대로 — 남은 축소 대상이 원장 안에서 두 가지로 읽힘 | 중 | 검사기: 같은 절 안 '남은/잔여' 목록 ↔ 완료 줄 대조(P0-1) |
| A-03 | A | pb:ops/HANDOFF.md:35-37 ↔ pb:history/2026-10.md:71-72 | '지금 진행 중인 실행 계획'에 10/16 반등일 1차 축소(이미 2회 체결)가 미래형으로 남음 | 중 | HANDOFF 진행 절 생성형(P0-5) |
| A-04 | A | pb:ops/HANDOFF.md:41-42 ↔ pb:ops/agreements.md:132-144 | '일요일(10/18) 안건'이 10/17 14:09 일괄 도장으로 처리됐는데 HANDOFF엔 미처리로 남음 | 중 | 동일 |
| A-05 | A | pb:ops/agreements.md:12,22,33,42,92,95,96,97,126,127,128,129,130 ↔ 같은 파일 :136,134,140,133(+history:119),135,137,135,115,141,142,143,144,158 | 🗳️·'미처리' 줄 13개가 뒤에 ✅로 결정됐는데 원래 줄 상태 표시가 안 바뀜(일부만 '🗳️→✅' 새 줄로 추가). 원장을 위에서 읽으면 결정된 안건이 열린 것으로 보임 | 중 | 원장 문법: 안건 키(#n·8-X)를 줄마다 의무화 → 같은 키에 ✅가 생기면 이전 🗳️ 줄에 '→ :행' 자동 표시(P0-1 검사 + 기록 데스크 규약) |
| A-06 | A | pb:ops/agreements.md:91 ↔ pb:history/2026-10.md:86 · pb:scorecard/README.md:4-9 | '성적표에 규칙 간 정합성 항목 추가' 🗳️ — 이미 10/16 구축·발행 | 경 | 동일(A-05) |
| A-07 | A | pb:ops/agreements.md:157 · pb:holdings.txt:17 ↔ pb:ops/agreements.md:7 · pb:history/2026-10.md:65 | ISA 월 적립액: :7·#15 도장은 ✅ 확정인데 :157 은 🗳️ '다르면 정정', holdings 메타 줄은 '확인 대기' | 중 | 단일 출처: 적립액은 holdings `ISA적립` 줄 하나 + 원장은 그 줄 참조(P1-9) |
| A-08 | A | ops/board.json:806(`my-rules-secret`) · :1365(`secret-missing-warning`) ↔ pb:history/2026-10.md:141 · pb:ops/agreements.md:105 | `my-rules-secret` 기한 10/17 대기인데 할 일 문구가 '테마 상한 0.40'뿐 — 결재 #2 백스톱 예외 발동선 touch 줄(원장 :105 '월 08:50 전')이 빠짐. `secret-missing-warning` 은 '대기'인데 history :141 은 '시크릿 없으면 ⚠ 알림 비활성 배지' 구현 완료로 기록 | 중 | board ↔ 커밋 연결 필드(P1-7), 시크릿 생성기(P0-4) |
| A-09 | A | ops/isa_buys.json(events 0건) ↔ pb:history/2026-10.md:73 | 결재 #15 ISA 매수 카운터가 비어 있음 — 10/16 ISA 1차 체결이 있었으나 '월 1회/급락일' 어느 쪽인지 분류 규칙이 없어 미기록 | 경 | 분류 규칙 + isa_holdings 변경 시 자동 기록(P2-13) |
| A-10 | A | pb:ledger/README.md:4 · pb:holdings.txt:4 · pb:scorecard/unsettled_trades.csv:2 ↔ pb:ledger/README.md:5-6 · pb:ledger/broker_full_2025-10-22_2026-10-15.csv | '체결가 확인 필요'(9/30 대비 차이)·'체결가 미확인' 방치. 같은 기간 증권사 원장(:5-6, broker_full)이 이미 들어와 대조 가능한데 닫히지 않음. 10/14 매도 1건은 원장 범위 밖이라 실제로 미확인 | 경 | slop (c) 기준을 비공개에도 적용(P1-8), 원장 대조 스크립트(P2-18) |

### B. 같은 사실의 다른 값
| ID | 유형 | 위치 | 내용 | 심각도 | 재발방지 제안 |
|---|---|---|---|---|---|
| B-01 | B | pb:ops/HANDOFF.md:50 ↔ pb:ops/agreements.md:139 ↔ pb:history/2026-10.md:117 ↔ pb:ops/PLAN_2026-10-16.md:110 ↔ pb:journal/2026-10-17.md:106,138 | 자소서 마감이 4갈래: 월 18:00(HANDOFF·PLAN) / 일 18:00 마감·월 08:50 제출(history) / 월 08:50 전 제출 고정(#12, journal). '마감'과 '자체 제출 기한'이 구분 없이 섞임 | 중 | 단일 출처: 일정은 한 파일(예: 일정 파일(미생성) 또는 원장 한 줄)에 '외부 마감 / 내부 기한' 두 칸, 나머지는 참조(P0-5) |
| B-02 | B | pb:ops/HANDOFF.md:50 · pb:ops/PLAN_2026-10-16.md:129 ↔ pb:ops/agreements.md:94 | 어학 시험: HANDOFF '재시험 예약', PLAN '재시험 예약 또는 응시가 완료 기준' vs 원장 ✅ '시험 계획 없음' | 경 | 동일 |
| B-03 | B | pb:rules.txt:11,96 ↔ pb:ops/agreements.md:93 · pb:history/2026-10.md:5 | 1개월 리뷰: rules.txt '11/16(일)'(요일도 틀림) vs 원장 ✅ '11/15(일) 확정, 11/16(월)은 선언만' | 중 | 결재→rules.txt 반영 검사(P0-2) |
| B-04 | B | screener/defs.py:22 ↔ pb:risk/rulebook.py:6-9,27-29 · pb:ops/agreements.md:26 vs :182 · pb:history/2026-10.md:7 | 분모 라벨 의미가 뒤집힘: 공개 `DENOM_TERMS` (a)=투자자산·(c)=순자산 전체 vs 비공개 rulebook (a)=순자산 전체·(c)=위성 북. 원장 :26·history :7 은 (a)=투자자산, 원장 :182 는 (a)=순자산(장기 목표). (b)만 일치 | 중 | 단일 출처: 분모 표 하나(defs) + rulebook 미러 + mirror_diff 대상에 추가(P1-6) |
| B-05 | B | docs/rules_terms.md:13-14 · screener/pb.py:302,320-324 · pb:scorecard/README.md:37 ↔ pb:ops/agreements.md:26 | 용어집은 D2=위성+ISA(예적금 없음), 'D3(+예적금) 제안 단계·코드 없음'. 그러나 결재 #1 ✅ 분모 (b)=투자+예적금이고 pb.py 는 예적금을 더하면서 라벨은 `denominator=D2`. 성적표 README 표는 예적금 없는 분모로 설명 | 중 | rules_terms.md D코드↔(a)(b)(c) 대응 확정 + check_rules_terms 라벨 값 검증(P1-6, E-02) |
| B-06 | B | pb:history/2026-10.md:54 ↔ :7,98 · pb:ops/agreements.md:26 · docs/peer_reviews/2026-10-17_recheck.md:15-16 | 같은 기준일(10/16)의 분모 (b) 반도체 비중이 문서마다 값 불일치(10/16 19시 제안값 vs 10/17 정정값), 같은 날 비공개 FRM 스크립트와 성적표 스크립트 출력도 값 불일치 | 경 | 비율은 생성 파일(risk/frm.json) 하나만 인용, 문장엔 '출처 파일·asof' 의무(STANDARD §1) |
| B-07 | B | pb:rules.txt:15 ↔ pb:household/README.md:46 · pb:household/build_month.py:265 · pb:ops/agreements.md:168 ↔ pb:ops/agreements.md:27 | 비상금 정의 3갈래: rules.txt '파킹통장 생활비 3개월' / 내무 '현금성 전체(10/16 확정)' / 원장 :27 🗳️ '금액 확정 필요' | 중 | 정의 먼저 조항([13]) 집행: 용어집 1행 + rules.txt 반영(P0-2) |
| B-08 | B | pb:rules.txt:32 · ops/board.json:806 · screener/committee.py:254 · pb:scorecard/README.md:37 ↔ pb:ops/agreements.md:134 · screener/defs.py:33 · pb:risk/rulebook.py:16 | 테마 한도: rules.txt·보드 시크릿 할 일·운용회의 문구·성적표 README '40%' vs 결재 #3 레짐 연동(하락장 35 / 40 / 발동 45 / 하단 30)과 코드 | 중 | 문구에 숫자 하드코딩 금지 → defs 상수 렌더(P1-12) |
| B-09 | B | pb:ops/agreements.md:23 · pb:rules.txt:80 ↔ pb:ops/agreements.md:134 · pb:history/2026-10.md:135 | VaR: 원장 :23 '한도→계기판 격하', rules.txt 는 여전히 한도, #3 은 'VaR 초과 시 반도체 신규 금지', history 는 '신규 매수 금지 발효 중' — 계기판인데 금지 효과가 있음 | 중 | 결재 문구에 '효과(경보/금지/매도)' 칸 의무, rules.txt 반영 검사(P0-2) |
| B-10 | B | pb:holdings.txt:6 ↔ pb:scorecard/unsettled_trades.csv:3 | 발단 매도 건의 결제일이 두 파일에서 다름 | 경 | 체결 1건 = 1행(unsettled_trades)만 쓰고 holdings 주석은 그 행 참조(P0-1) |
| B-11 | B | pb:rules.txt:6 ↔ pb:ops/agreements.md:135 | 규칙 변경 주기: rules.txt '월 1회, 포지션 없을 때만' vs 결재 #4 '파라미터 일요일·구조 월말·전면 분기' | 중 | P0-2 |
| B-12 | B | pb:rules.txt:48 ↔ pb:ops/agreements.md:102-104,162 | [5] 백스톱: rules.txt '−20% 다음 반등일/2주 내 정리'만 — 결재 #2 예외 1회(✅)와 −30% 하드 바닥 사전등록이 없음. rules.txt:6 이 '예약 PB 판단의 최우선 기준'이라 C-02 와 직결 | 중 | P0-2·P0-3 |
| B-13 | B | pb:ops/HANDOFF.md:24 ↔ pb:ops/agreements.md:75,122 ↔ pb:history/2026-10.md:140 ↔ 예약 실제(list_triggers 10/17: 매일 12:50·16:00·22:30) | 기록 데스크 슬롯: '12:50·16:00'(HANDOFF) / '평일'(:75) / '주말 확대'(:122) / '12:50 폐지' 🗳️(history) / 실제 매일 3슬롯 | 경 | 예약 스냅샷 단일 출처(P1-10) |
| B-14 | B | pb:ops/HANDOFF.md:30-33 ↔ 예약 실제 8개 ↔ docs/schedule_table.md:103 | HANDOFF '예약 작업'은 3개만(기록 3·강화 루프·ISA 1회 2건 누락). schedule_table :103 은 6종 — 10/19 09:45 ISA 검산 1회 예약 누락 | 중 | P1-10 |
| B-15 | B | Claude 예약 '오늘의 영어·인적성 (평일 07:20)' 이름 ↔ 같은 예약 cron 07:18 · pb:ops/HANDOFF.md:33 | 이름과 실제 시각 불일치 | 경 | P1-10 스냅샷 테스트가 이름 속 시각 ↔ cron 대조 |
| B-16 | B | pb:ops/HANDOFF.md:58 ↔ ops/README.md:93 · pb:ops/my_holdings_format.md:3 | MY 탭 보유 출처: HANDOFF 'MY 탭 보유는 브라우저 localStorage' vs README·형식 문서 '비공개 holdings.txt 를 토큰으로 읽음'. 어느 쪽이 현행인지 문서로 판정 불가 | 중 | 화면 데이터 출처 표를 schedule_table §4 처럼 생성(P1-10 범위 확장) |

### C. 연결 자동화 부재 (손 옮김 지점 · 어긋나면 누가 언제 아는가)
| ID | 유형 | 흐름 / 위치 | 손 옮김 지점 | 어긋나면 누가·언제 | 심각도 | 재발방지 제안 |
|---|---|---|---|---|---|---|
| C-01 | C | 체결 → pb:ledger 증권사 원장 → pb:scorecard/unsettled_trades.csv → pb:holdings.txt → pb:ops/agreements.md 상태 → pb:ops/HANDOFF.md·pb:history 현재 상태 | 5단계 전부 PB·기록 데스크 손 갱신. 체결 ID 없음, 상태 전이 기록 없음 | **아무도 자동으로 모름.** 발단 사례는 오너가 대화 중 정정(10/17 23시). 증권사 원장은 수동 업로드라 10/15 이후 공백 | 치명 | 체결 1건 = `unsettled_trades.csv` 1행(trade_id)을 단일 출처로, 원장 줄·holdings 주석은 trade_id 인용. `integrity_check`(P0-1)가 열린 '대기·미체결·재시도·기한' 줄 ↔ trade_id 대조, 세션 시작 훅 + 22:30 기록 예약에서 실행 |
| C-02 | C | 결재 ✅(pb:ops/agreements.md:132-144) → pb:rules.txt → screener/defs.py·pb:risk/rulebook.py → Claude 예약 '평일 14:42 PB 판단' 프롬프트 | rules.txt 는 v2.1(10/15) 그대로 — 원장 :2 '✅확정분은 rules.txt로 옮긴다'가 집행 안 됨. 코드는 #3 반영(defs·rulebook)했으나 **14:42 예약 프롬프트는 rules.txt 를 '최우선'으로 읽고, 프롬프트 본문에 구 규칙(테마 40%·−20% 백스톱·위성 상한 금액)을 하드코딩** | 월 14:42 첫 실행 때 PB 판단이 #2 예외·#3 밴드와 다르게 나와도 검출 장치 없음. 오너가 알아채야 함 | 치명 | rules.txt 상단 '결재 반영 현황' 블록(결재#→조항→반영 여부) + 미반영 시 P0-1 실패. 예약 프롬프트는 규칙 요약 삭제 → rulebook/defs·원장 ✅ 읽기로 [예약 변경] |
| C-03 | C | pb:holdings.txt → Actions 시크릿 `MY_HOLDINGS` / 결재 #2·#3 → 시크릿 `MY_RULES` (ops/README.md:93 · pb:ops/my_holdings_format.md:3,34) | 사람이 두 곳에 '같은 텍스트' 붙여넣기. 10/17 발단 매도로 보유가 바뀌었고 시크릿은 내용이 안 보임. 보드 할 일(board.json:806)엔 발동선 touch 줄 누락(A-08), 형식 문서에 예적금 줄 안내 없음 → 빠지면 pb.py:320-324 가 (a) 분모로 떨어짐 | 시크릿이 **없을 때**는 배지(history :141)로 앎. **낡았거나 줄이 빠졌을 때**는 아무도 모름 — 백스톱 예외 발동선 감시가 월 장중 조용히 꺼질 수 있음(원장 :177 이 증권사 스탑 주문을 권고한 이유) | 치명 | 시크릿 생성기(holdings + rulebook → 정확한 텍스트) + 내용 해시만 공개 쪽에 기록해 아침 점검이 '낡음' 표시(P0-4) |
| C-04 | C | 내무 `household/balances.csv` 예적금 ↔ pb:holdings.txt:16 `예적금` 줄 (pb:household/README.md:32) | 같은 값을 두 파일에 손으로 | 현재 일치. 어긋나면 분모 (b)가 틀려도 모름 | 중 | holdings 예적금 줄을 balances 최근 월에서 생성(P1-9) |
| C-05 | C | ISA 보유: pb:holdings.txt:20-24 `## ISA` ↔ pb:isa_holdings.txt (pb:risk/frm.py:4·pb:views/build_personal.py:47 은 전자, pb:scorecard/build_week.py:253,913 은 후자) | 스크립트마다 다른 파일을 읽음 | 현재 일치. ISA 2차 매수(10/19) 때 한쪽만 고치면 FRM·MY 렌즈와 성적표가 다른 ISA로 계산, 아무도 모름 | 중 | 한 파일만 남기거나 P0-1 동일성 검사 |
| C-06 | C | screener/defs.py → pb:risk/rulebook.py 미러 (`mirror_diff` :145) | 미러 대상 8개 상수만. 분모 라벨·백스톱 예외 발동선·위성 상한(build_week.py:34, build_personal.py:23 에 중복 하드코딩)·ISA 목표 비중·ISA 월 적립(build_personal.py:31 하드코딩) 미포함 | 값이 바뀌어도 테스트 통과 | 중 | mirror_diff 대상 확장 + 비공개 3스크립트는 rulebook 만 import(P1-6) |
| C-07 | C | ops/board.json 상태 ↔ 실제 커밋 | 상태·완료일 손 변경, 커밋 필드 없음. `pbfire-merge-fix` '완료'인데 files 에 적힌 파일이 저장소에 없음, '보드 밖 커밋 사후 등록' 관행(board 노트) | PM 수동 점검 때만 | 중 | 커밋 메시지 `board:<id>` 규약 + board.py 가 git log 로 마지막 커밋 표시·불일치 경고(P1-7) |
| C-08 | C | docs/schedule_table.md:103 ↔ Claude 예약 작업 | §3 는 워크플로·Scheduler.gs 에서 자동 생성·테스트되지만 Claude 예약은 손 목록. HANDOFF 목록도 별도(B-14) | 예약이 추가·중지돼도 표가 안 바뀜 | 중 | list_triggers 스냅샷(이름·cron·enabled만) → 표 생성 + 테스트(P1-10) |
| C-09 | C | Claude 예약 프롬프트 속 사실 하드코딩 — '월요일 10시 ISA 2차 매수 주문표'(10/16 생성) | 생성 시점의 바구니·목표 비중·잔여 현금 추정이 프롬프트에 고정. 원장 :193 의 10/18 비중 결정(금·나스닥)이 나면 낡음 | 월 10:00 실행 때 09:45 검산 예약과 다른 바구니가 나올 수 있음 — 오너가 두 메시지를 비교해야 앎 | 중 | 프롬프트는 '파일 X 읽기'만, 값은 파일에서(P2-15) [예약 변경] |
| C-10 | C | pb:history/2026-10.md:3-22 '현재 운용 상태' | 매일 손으로 덮어씀. 정정 전 줄을 지우지 않고 `1-old` 로 병기(:12) | 다음 독자가 오독할 때 | 중 | 원장·unsettled·board 에서 '열린 계획' 생성(P1-11) |
| C-11 | C | 코드 속 계획 서술: pb:scorecard/build_week.py:1036 · pb:risk/frm.py:52 · screener/committee.py:254 | 매매 계획·잔여 수량·한도 문구가 코드 문자열·상수 | 체결 후 다음 성적표에서 낡은 문장이 출력돼도 테스트 통과 | 중 | 계획은 데이터 파일에서 읽기(P1-12) |
| C-12 | C | 증권사 원장 업로드 → 성적표 | 원장이 10/15 결제분까지, 이후는 unsettled_trades 손 행. '원장 반영되면 자동 무시'는 있음 | 업로드 누락 기간이 길어져도 경고 없음 | 경 | build_week 가 원장 마지막 날짜 ↔ 오늘 차이 N거래일 초과 시 ⚠ 1줄 |
| C-13 | C | apps-script/Scheduler.gs ↔ 실제 GAS 편집기 | 오너 붙여넣기, 버전 확인은 tickTest 로그 육안 | ops_runs 의 GAS 도착표로 간접 확인만(ops/README.md:18) | 경 | dispatch 입력에 `SCHEDULER_VERSION` 실어 보내고 워크플로가 기대 버전과 비교해 ::warning |
| C-14 | C | 결재 #15 ISA 매수 → ops/isa_buys.json | 손 기록(A-09) | 연 2회 상한 카운트가 틀려도 모름 | 경 | isa_holdings 변경 커밋에서 카운터 자동 추가(P2-13) |

### D. 폐기·정정된 안내가 다른 문서에 살아 있음
| ID | 유형 | 위치(잔존) ↔ 정정 근거 | 내용 | 심각도 | 재발방지 제안 |
|---|---|---|---|---|---|
| D-01 | D | pb:ops/HANDOFF.md:46 · ops/board.json:82(`gas-repaste` 제목 'Index.html PIN 토큰') · :1201(`index-split` 노트 'Index + tab_* 14개 + Code.gs 붙여넣기') · ops/README.md:50-76 · pb:ops/ticket_howto.md:44 · pb:ops/PLAN_2026-10-16.md:26,41,62 · docs/desk_kb/dev.md:72 ↔ pb:ops/HANDOFF.md:58 · pb:ops/agreements.md:120 | 'GAS 17파일/Index.html·Code.gs 재붙여넣기' 안내가 7곳에 살아 있음. 정정은 'GAS 는 Scheduler.gs 한 파일만'(복기 11) | 중 | 폐기 문구 사전 + 두 저장소 스캔(P1-8) |
| D-02 | D | pb:ops/HANDOFF.md:38 · pb:rules.txt:86 · pb:ops/PLAN_2026-10-16.md:129,170 ↔ pb:ops/agreements.md:21,24,102-104 | 백스톱 예외 종목이 '조건부 매도(~10/29)'로 남음 — 결정은 '유지 + 결재 #2 예외 1회' | 중 | P1-8 + P0-2 |
| D-03 | D | pb:history/2026-10.md:13 ↔ :93 | 현재 상태에 '백스톱 A/B 일요일' — 10/17 09:02 B로 결정됨 | 경 | P1-11 |
| D-04 | D | pb:ops/HANDOFF.md:54 ↔ pb:CLAUDE.md(답변 전 확인 원칙 3) · pb:ops/agreements.md:170 | VOC: HANDOFF 'VOC 없으면 생략' vs 현행 '미호출이면 이번 답변은 데스크 미호출이라고만 쓴다' | 중 | HANDOFF 규칙 절을 CLAUDE.md 참조 1줄로(P0-5) |
| D-05 | D | pb:ops/HANDOFF.md:1 · pb:ops/agreements.md:4 | 헤더 '최신 10/16 07:51'·'최종 갱신 10/17 16:00' — 본문은 10/17 23시대까지 갱신 | 경 | 저장 시 헤더 스탬프 자동(P2-17) |
| D-06 | D | pb:ops/agreements.md:80(보존 액션 ①~④ 기한 10/21·10/24) ↔ :138(#10 '리팩토링 data 브랜치로 대체') | 대체된 표 행이 표시 없이 남음 | 경 | A-05 원장 문법 |
| D-07 | D | pb:history/2026-10.md:19 ↔ :98 · pb:ops/agreements.md:26 | '① 분모(b) [값] 확정' — 이후 정정된 값과 값 불일치, 취소선 처리 안 됨 | 경 | P1-11 |
| D-08 | D | docs/rules_terms.md:56-58('FRM 코드는 D1') ↔ pb:risk/frm.py:5 | FRM 은 10/17 이후 (b) 분모 | 경 | P1-6 |
| D-09 | D | pb:ops/PLAN_2026-10-16.md 전체 | 10/18 대청소·미장 ETF 매도 기한·GAS 재붙여넣기 등 처리·폐기된 계획서에 '보관/대체됨' 표시 없음 | 경 | P2-17 |
| D-10 | D | pb:ops/glossary.md:47,60,62 | 원장 행 번호 인용(`agreements.md:18,20,45`)이 원장 편집으로 밀려 다른 줄을 가리킴 | 경 | 행 번호 대신 안건 키 인용(P2-16) |
| D-11 | D | docs/schedule_table.md:12 | 토큰 만료일 '확인 필요' 꼬리표의 기한이 '10/18 붙여넣기 때'로만 — 담당 확인 기록 없음 | 경 | slop (c) 자동 항목이 이미 잡음 — 라운드 처리만 |
| D-12 | D | Claude 예약 '오늘의 영어·인적성' 프롬프트 4단계 `git pull --rebase -X theirs` ↔ pb:history/2026-10.md:120(역행 원인 중 하나 = `-X theirs`) | 정정된 위험 패턴이 예약 프롬프트에 남음(대상이 reports/english 3파일로 한정이라 영향 작음) | 경 | P2-14 [예약 변경] |

### E. 기존 검사기가 못 잡는 영역
| ID | 유형 | 검사기 | 사각지대 | 심각도 | 재발방지 제안 |
|---|---|---|---|---|---|
| E-01 | E | `scripts/board.py --check` | 스키마·의존만 검사. 기한 경과·완료/검수인데 files 없음(16건)·완료일 누락·커밋 연결 미검사. 상태에 '취소'가 없어 취소된 6건(activist·active-flow 계열, 노트 '[취소·닫힘]')이 '완료'로 집계 | 중 | P1-7 |
| E-02 | E | `scripts/check_rules_terms.py` | 공개 6파일에 `denominator` 라벨이 **있는지만** 봄 — 라벨 값이 합의된 분모와 맞는지(B-05: (b) 계산에 D2 라벨) 안 봄, 비공개 3스크립트 미대상 | 중 | 허용 라벨 = rules_terms 표 + 한도별 기대 분모 매핑 검증(P1-6) |
| E-03 | E | `scripts/slop_audit.py` | SCAN_GLOBS = docs·reports·content 만 — ops/*.md, apps-script 안내, 비공개 저장소 전체 미대상. '폐기된 안내' 탐지 규칙 없음 | 중 | P1-8 |
| E-04 | E | pb:`risk/rulebook.mirror_diff` | 8개 상수만(C-06) | 중 | P1-6 |
| E-05 | E | `tests/test_schedule_single.py` · `slot_guard --table` | GitHub cron·GAS 슬롯만. Claude 예약(8개)과 그 프롬프트 속 규칙·값 하드코딩 미검사 | 중 | P1-10 |
| E-06 | E | (없음) | 비공개 원장 정합성 검사기 0개: 원장 상태 쌍(🗳️↔✅), 지난 기한 열린 줄, '미체결·재시도·대기' ↔ 체결 기록, HANDOFF 섹션 최신성, holdings ↔ isa_holdings ↔ unsettled ↔ 원장, 결재 ✅ ↔ rules.txt. `trial_log --check`·`check_functions` 는 범위 밖 | 치명 | P0-1 |

## 2. 개발 데스크 이관 목록

비공개 저장소 쪽 구현(P0-1·2·5, P1-9·11 일부)은 비공개 파일을 바꾸므로 **오너 승인 후** 착수. 감사는 범위만 적는다.
### P0 — 다음 일요일 결재 전
| # | 항목 | 구현 범위 1줄 | 관련 ID | 라이브/예약 |
|---|---|---|---|---|
| P0-1 | 비공개 정합성 검사기 `integrity_check.py`(읽기 전용) | 원장 안건 키별 🗳️/✅ 쌍·지난 기한 열린 줄·'미체결/재시도/대기' ↔ unsettled_trades trade_id·HANDOFF 섹션 최신일·holdings `## ISA` == isa_holdings·holdings 예적금 == balances 최근 월 → 결과는 비공개 journal 1줄, 공개엔 건수만 | A-01,02,05,07,10 · B-10 · C-01,04,05 · E-06 | 세션 시작 훅에서 실행 = 비라이브. **22:30 기록 예약 프롬프트에 단계 추가 = 예약 변경** |
| P0-2 | 결재 ✅ → rules.txt 반영 현황 | rules.txt 상단에 '결재#·조항·반영 여부' 생성 블록, 미반영이면 P0-1 실패. 본문 개정 자체는 오너 일요일 결정 | B-03,07,09,11,12 · C-02 · D-02 | 비라이브(문서). 규칙 문구 변경은 오너 결정 |
| P0-3 | 14:42 PB 예약 프롬프트에서 규칙 요약 하드코딩 제거 | 프롬프트의 테마 한도·백스톱·위성 상한 문장 삭제 → rulebook/defs·원장 ✅ 결재 읽기 지시로 교체 | C-02 · B-08,12 | **예약 변경 — 월 장 전 변경 금지.** 월 14:42 1회는 현 프롬프트로 돎 → PB가 결과를 결재 #2·#3 과 수동 대조 |
| P0-4 | 시크릿 생성기 + 낡음 감지 | `holdings.txt`+rulebook → `MY_HOLDINGS`·`MY_RULES` 정확한 텍스트 출력(touch 줄·예적금·레짐 상한 포함), 내용 해시만 공개 쪽 기록 → 아침 점검이 '꺼짐'과 별도로 '낡음' 표시. board `my-rules-secret` 문구 정정 | C-03 · A-08 · B-08,16 | 생성기·문구는 비라이브. **alerts/pb 판정 경로 변경 = 라이브 알림 → 월 장 후** |
| P0-5 | HANDOFF 생성형 전환 | '지금 진행 중·대기 승인·예약 작업·일요일 안건·커리어 일정' 절을 원장·board·예약 스냅샷에서 생성하거나 링크 1줄로 대체, 규칙 절은 CLAUDE.md 참조 | A-01,03,04 · B-01,02,13,14 · D-01,04 | 비라이브 |

### P1 — 10/31 월말 리뷰 전
| # | 항목 | 구현 범위 1줄 | 관련 ID | 라이브/예약 |
|---|---|---|---|---|
| P1-6 | 분모 용어·미러 단일화 | defs `DENOM_TERMS` 의미 확정 → rulebook 미러, mirror_diff 에 분모 라벨·백스톱 발동선·위성 상한·ISA 목표·ISA 월 적립 추가, 비공개 3스크립트는 rulebook 만 import, rules_terms.md D코드↔(a)(b)(c) 대응표, check_rules_terms 라벨 값 검증 | B-04,05 · C-06 · D-08 · E-02,04 | 화면 라벨 문구 변경 포함 → **pages 배포는 장 후** |
| P1-7 | board.py 확장 | '취소' 상태 추가, `--check` 에 기한 경과 경고·완료/검수 files 존재·완료일 필수, 커밋 `board:<id>` 규약으로 마지막 커밋 표시 | A-08 · C-07 · E-01 | 비라이브(ops 23:47 BOARD.md 생성 형식만 바뀜) |
| P1-8 | 폐기 문구 사전 + 스캔 확장 | 폐기 문구 사전 파일(미생성, 예: ops 아래 json)(GAS 17파일·Index.html/Code.gs 재붙여넣기·'플러스 출발'·지난 기한 등, 정정 출처 포함) + slop_audit 대상에 ops/*.md·apps-script 안내 추가, 비공개 저장소 동일 스캔 옵션 | D-01,02 · E-03 · A-10 | 비라이브 |
| P1-9 | 보유·예적금 단일 출처 | ISA 는 isa_holdings.txt 하나(holdings `## ISA` 는 생성 또는 제거), holdings 예적금 줄은 balances 최근 월에서 생성, ISA 적립액은 holdings `ISA적립` 줄만 | A-07 · C-04,05 | 비라이브(비공개) |
| P1-10 | Claude 예약 스냅샷 | list_triggers 결과에서 이름·cron·enabled 만 예약 스냅샷 파일(미생성)로 → schedule_table §4·HANDOFF 예약 절 생성, 이름 속 시각 ↔ cron 대조 테스트, 화면 데이터 출처 표 포함 | B-13,14,15,16 · C-08 · E-05 | 스냅샷 수집은 세션 도구 필요(비라이브), 예약 자체는 안 바꿈 |
| P1-11 | history '현재 운용 상태' 생성 | 원장 열린 줄·unsettled·board 에서 열린 계획 목록 생성, 정정 전 줄 자동 제거 | A-01 · C-10 · D-03,07 | **16:00 기록 예약 절차 변경 = 예약 변경** |
| P1-12 | 코드 속 계획·한도 문구 제거 | build_week.py:1036·frm.py:52·committee.py:254 의 계획 수량·'40%' 문구를 데이터/defs 렌더로 | B-08 · C-11 | committee.py = **운용회의 브리핑(라이브) → 장 후 배포** |

### P2 — 11/15 리뷰 전
| # | 항목 | 구현 범위 1줄 | 관련 ID | 라이브/예약 |
|---|---|---|---|---|
| P2-13 | ISA 매수 카운터 자동화 | 반등일 대금 매수 분류 규칙 확정 + isa_holdings 변경 시 isa_buys.json 자동 기록 | A-09 · C-14 | 비라이브 |
| P2-14 | 영어 예약 정리 | `-X theirs` 제거, 예약 이름 시각을 cron 과 일치 | D-12 · B-15 | **예약 변경** |
| P2-15 | 일회성 예약 프롬프트 값 하드코딩 금지 | '파일 X 읽기'만 남기는 작성 규약 + 10/19 10:00 ISA 주문표 예약은 09:45 검산 결과를 따르게 | C-09 | **예약 변경 — 10/18 결정 후·월 09:45 전이면 장 전이므로 오너 확인 필요** |
| P2-16 | 행 번호 인용 → 안건 키 인용 | glossary 등 '파일:행' 인용을 안건 키·앵커로 | D-10 | 비라이브 |
| P2-17 | 헤더 스탬프·보관 배너 | HANDOFF·원장 '최종 갱신' 자동, 처리 끝난 계획서에 '보관' 배너 | D-05,09 | 비라이브 |
| P2-18 | 원장 대조 스크립트 | broker_full 로 9/30 대비 차이 재현 → ledger README '확인 필요' 닫기, 원장 공백 N일 경고(C-12) | A-10 · C-12 | 비라이브 |
| P2-19 | GAS 버전 대조 | dispatch 입력에 Scheduler 버전 → 워크플로 ::warning | C-13 | **GAS·워크플로 변경 = 라이브 예약 → 장 후 + 오너 붙여넣기** |

### 라이브 루프·cron·예약 변경이 필요한 항목 (월요일 장 전 변경 금지 — 별도 표시)
- **예약(Claude) 프롬프트:** P0-3(14:42 PB) · P0-1 의 22:30 기록 단계 · P1-11(16:00 기록) · P2-14(영어) · P2-15(10/19 10:00 ISA 주문표).
- **라이브 알림·브리핑 코드:** P0-4 의 alerts/pb 판정 경로 · P1-12 의 committee.py · P1-6 의 화면 라벨(pages).
- **GAS·워크플로:** P2-19.
- 장 전까지의 임시 통제(코드 변경 없음, 오너·PB 행동): 월 14:42 PB 결과를 결재 #2·#3 과 수동 대조 / 백스톱 예외 발동선은 원장 :177 권고대로 증권사 스탑 주문 / `MY_RULES` 를 만들 때 보드 문구(0.40만)가 아니라 원장 :105 의 touch 줄까지.

## 3. 감사 데스크 메모
- 레드팀 [측정]: 줄 번호는 10/17 작업 사본 기준이고 원장은 하루에도 여러 번 편집된다 — 이 표의 행 번호가 다음 편집 뒤엔 어긋날 수 있다는 것 자체가 D-10·P2-16 의 근거다.
- 복기(감사 데스크): 오전 slop 감사(치명 1/중 14/경 42)는 공개 저장소 문서만 봤고, 비공개 원장↔코드↔예약의 '상태 전이' 불일치는 범위 밖이었다 — 발단 사례는 그 사각지대에서 났다. 다음부터 감사 라운드에 E-06 검사기 결과를 포함한다.

VOC: 비공개 원장을 검사기 없이 사람이 읽고 상태를 판정하는 구조라 감사도 매번 전수 수작업이다 — P0-1 이 들어오면 감사는 예외만 본다.
요청→개발: P0-1·P0-4·P1-7 착수 여부와 기한을 보드에 등록해 달라(감사는 보드를 직접 고치지 않음).
