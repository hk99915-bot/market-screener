# edu(교육) 데스크 KB

(자문·연구 과정에서 추가. 형식은 README.md. 인용 `kb:edu#<n>` — 번호 고정. 공개 저장소: 개인 금액·보유·종목 없음, 비율·횟수·가상 숫자만.)
교육 = 커리큘럼·모듈 설계(`content/study/*.json`, `screener/study_daily.py`). 평가 = 문제은행·SRS·출석·오답 환류(대등, 설계 vs 평가 분리). 1차 자료 = `docs/study_consults/answers/*.md`(consult:데스크#q번호) + 각 데스크 KB(kb:데스크#n).

## 정의
1. [경험] 학습자 프로필(consult:pb_learner#L1): 지식 부족보다 **실행 장치 부족**이 손실 원인. 교육 목표 = '더 아는 것'이 아니라 '아는 것을 장중에 쓰는 것'. 모든 모듈은 규칙 조항 1개(`rule_link`)와 터미널 숫자 1개(`terminal_lookup`)에 붙인다.
2. [경험] 하루 상한 = 1모듈 20분 + 복습 1 + 퀴즈 1(consult:pb_learner#L5; `srs.json rules.daily_cap`). 총량(363시간)은 기본 숨김. 첫 2주 우선 = H2·R1·D1·H1·R2·H4·D2·R6·H6·M1(L9: 이번 주 경험과 붙는 모듈 먼저).
3. [논문] 시험 효과(testing effect): 다시 읽기보다 **인출 연습(퀴즈)** 이 1주 뒤 기억을 더 남긴다(Roediger & Karpicke 2006: 재학습 집단 1주 후 ~40% vs 시험 집단 ~56% `[확인 필요: 실험 1 수치, 10/24 라운드2 WebSearch]`). 모듈 끝 확인문제·07:10 퀴즈 1문항의 근거. (출처: Roediger & Karpicke 2006 *Psych. Science* 17(3))
4. [논문] 분산 연습(spacing): 같은 총 학습 시간이면 간격을 둔 복습이 몰아치기보다 낫고, 최적 간격은 보유 기간의 약 10~20% `[확인 필요: Cepeda 2008 최적 간격 비율, 10/24]`. SRS 1·3·7·21일은 이 범위 안의 관행적 등비 간격. (출처: Cepeda, Pashler et al. 2006 *Psych. Bulletin* 132(3); Cepeda et al. 2008 *Psych. Science*)
5. [논문] 선다형 문항 작성 지침(Haladyna, Downing & Rodriguez 2002, 31개 지침 중 교육·평가 데스크가 쓰는 것): ① 정답 위치를 고르게(한 위치 쏠림 금지) ② 오답지는 그럴듯해야 하고 '무관'·'모두 아님' 같은 빈 오답 금지 ③ 가장 긴 선택지 = 정답 패턴 금지 ④ 선택지 3개로 충분(Rodriguez 2005 메타분석) ⑤ 문두에 부정어 최소화. (출처: *Applied Measurement in Education* 15(3) 309–334; Rodriguez 2005 *EM:IP* 24(2) `[확인 필요: 쪽수, 10/24]`)

## 공식
6. [경험] 모듈 스키마 v3(`docs/study_spec.md`): 한 줄 요약 → 생활 비유 → 용어 → 핵심 개념(각 줄 출처 태그) → 공식(쉬운 숫자 1개) → 오늘 시장에서(`market_hook`) → 흔한 실수 → 확인문제(상황 70%) → 다음 문(`next_door`). `est_min ≤ 20`. 검증기 `scripts/study_content_check.py`가 출처 태그·est_min·quiz 인덱스를 강제한다.
7. [경험] 문항 품질 최소 3조건(평가 데스크와 합의, 2026-10-17): (a) `src[]`에 kb:/consult: 인용 1개 이상 (b) `why`는 인용 태그만이 아니라 **한 문장 근거**(틀렸을 때 읽는 유일한 줄) (c) 정답 위치 분포 — 모듈 5문항 안에서 같은 위치 3개 이하. 현황(10/17, `content/study/quiz_bank.json` 125문항 집계): 정답 1번 115/125(92%), 태그만 `why` 100/125(80%), duel.pick=answer 125/125. 반대 근거: 학습자는 선택지 번호가 아니라 문장을 읽으므로 1번 쏠림의 실제 피해는 미측정(검증전) — 그래도 소거법 노출은 Haladyna #5 위반.

## 현업 vs 교과서
8. [현업 관행][교과서] 교과서(Haladyna)는 선택지 3~4개·정답 위치 무작위를 권하지만, 우리 터미널은 '데스크 답 vs 내 답' **대결 형식**(consult:pb_learner#L3)이라 `duel.pick`이 노출된다. 현재 125문항 모두 pick = answer → 데스크가 항상 맞는 구조는 게임성을 없앤다. 평가 데스크에 '데스크가 틀리는 문항 10~20%'(KB `[확인 필요]`·검증전 항목에서) 요청(라운드1).

## 흔한 오해
9. [경험] "모듈이 많을수록 좋다" → 이 학습자는 총량을 보면 이탈한다(L5). 노출은 '오늘 1개'. 모듈 추가는 자유, 노출은 `gate`(첫 2주 15개)와 `first_two_weeks`가 통제한다.
10. [경험] "출처 태그가 있으면 근거가 있다" → 태그는 추적용이고 근거는 문장이다. `why: "[kb:behavior#3]"`만 있는 문항은 오답자에게 아무것도 가르치지 못한다(#7b).
11. [교과서] "어려운 오답지가 좋은 문항" → 오답지는 **흔한 오해**에서 뽑아야 진단 가치가 있다(Haladyna #5). '무관'·'규칙 준수' 같은 빈 오답은 정답을 소거법으로 노출시킨다.

## 터미널에서 보는 자리
12. [경험] 평일 07:10 KST `study_daily.yml` → `reports/study_daily.json` + 텔레그램 ≤4줄(오늘 공부 / 퀴즈 / 완료 이슈 링크 / 출석). STUDY 탭 '오늘 1개' 카드는 Dev handoff #3(미구현). 진행 = 이슈 `study <id> done` → `reports/study_progress.json`. 오답 큐 = `docs/desk_kb/_quiz_feedback.md`.

## 우리 연구와의 차이
13. [경험] 교과서 SRS는 '문항' 단위 간격인데 우리는 '모듈' 단위(복습 1개/일 상한). 학습자 시간 제약(L5) 때문에 모듈 단위를 따른다 — 대신 복습 퀴즈 통과 기준 60%로 문항 수준 신호를 보완.

## 출처
- Roediger, H. L. & Karpicke, J. D. (2006) "Test-Enhanced Learning", *Psychological Science* 17(3) 249–255.
- Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T. & Rohrer, D. (2006) "Distributed Practice in Verbal Recall Tasks", *Psychological Bulletin* 132(3) 354–380; Cepeda et al. (2008) "Spacing Effects in Learning", *Psych. Science* 19(11) `[확인 필요: 호·쪽, 10/24]`.
- Haladyna, T. M., Downing, S. M. & Rodriguez, M. C. (2002) "A Review of Multiple-Choice Item-Writing Guidelines for Classroom Assessment", *Applied Measurement in Education* 15(3) 309–334.
- Rodriguez, M. C. (2005) "Three Options Are Optimal for Multiple-Choice Items", *Educational Measurement: Issues and Practice* 24(2) 3–13 `[확인 필요: 쪽수, 10/24]`.
- 자체: `docs/study_consults/answers/pb_learner.md`(L1~L9), `docs/study_spec.md`, `content/study/srs.json`, `content/study/quiz_bank.json`.
- 확인 방법: 2026-10-17 라운드는 네트워크 없이 기억 기반 → 수치·쪽수는 전부 `[확인 필요: …, 10/24]`(신뢰도 중). 라운드2(10/24)에 WebSearch 초록 수준으로 확인, 못 하면 항목을 [경험]으로 강등.

## 자문 답변 요약(1차 자료 색인 — 모듈 sources[]에서 인용)
- behavior(q1~q16, x1~x3): 처분효과·하우스머니·작위/부작위·앵커링·규칙 변경 함정·결정 피로·PGR/PLR 양식·나🔥 샌드박스 → 트랙 H.
- frm(q1~): 손실 회복 1/(1−L)−1·변동성 끌림·VaR/ES·스트레스·상관·밴드/글라이드·사이징 → 트랙 R.
- derivs(q1~q16): 베이시스 부호(F−S 채택)·백워데이션·PCR·IV→하루 폭·감마·베타 헤지 → 트랙 D.
- cio(q1~q16): 운용회의 v2 구조·시나리오 확률·프리모템·3북·SAA/TAA → 트랙 M.
- quant(q1~): 사전등록·IS/OOS·등급 A/B/C/F/검증전·Bonferroni → 트랙 Q.
- bonds·macro: 트랙 0·A·B 보강 자료(아직 v3 모듈 없음).
- pb_learner(L1~L9): 학습자 제약 전체 — 모든 설계 결정의 근거.

## 복기 (틀린 판단 → 왜 → 다음부터)
- 2026-10-17: 125문항 문제은행을 "정답 = duel.pick = 1번" 템플릿으로 일괄 생성한 것을 검수 없이 통과시켰다(정답 위치 1번 115/125 = 92%, `why` 인용 태그만 100/125) → 왜: 속도 우선, 검증기가 스키마(인덱스 범위·선택지 4개)만 보고 **분포**는 보지 않았다. 설계(교육)와 평가가 분리돼 있었는데 교차 검수를 안 했다 → 다음부터: 문항 품질 3조건(#7)을 검증기 경고로 넣고, 모듈 단위로 정답 위치 셔플 + `why` 한 문장을 평가 데스크와 나눠 고친다(보드 `quiz-key-balance`).
