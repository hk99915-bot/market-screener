# edu(교육) 데스크 KB

(자문·연구 과정에서 추가. 형식은 README.md. 인용 `kb:edu#<n>` — 번호 고정. 공개 저장소: 개인 금액·보유·종목 없음, 비율·횟수·가상 숫자만.)
교육 = 커리큘럼·모듈 설계(`content/study/*.json`, `screener/study_daily.py`). 평가 = 문제은행·SRS·출석·오답 환류(대등, 설계 vs 평가 분리). 1차 자료 = `docs/study_consults/answers/*.md`(consult:데스크#q번호) + 각 데스크 KB(kb:데스크#n).

## 성격·성향
- **한 줄:** 지은 분량보다 "열렸는가"를 묻는 설계자(확장 지향·근거 태그 중시). "월요일 07:10에 그 15분이 열리지 않으면 내가 오늘 한 일은 교육이 아니라 건축이다."
- **맹점:** 문제은행 정답 위치 쏠림(1번 92%)을 검수 없이 통과(복기 10/17). **긴장:** ↔평가 — 알림 분량. 원본 [PERSONAS.md#edu](PERSONAS.md#edu)(요약, 연기 지시 아님).

## 정의
1. [경험] 학습자 프로필(consult:pb_learner#L1): 지식 부족보다 **실행 장치 부족**이 손실 원인. 교육 목표 = '더 아는 것'이 아니라 '아는 것을 장중에 쓰는 것'. 모든 모듈은 규칙 조항 1개(`rule_link`)와 터미널 숫자 1개(`terminal_lookup`)에 붙인다.
2. [경험] 하루 상한 = 1모듈 20분 + 복습 1 + 퀴즈 1(consult:pb_learner#L5; `srs.json rules.daily_cap`). 총량(363시간)은 기본 숨김. 첫 2주 우선 = H2·R1·D1·H1·R2·H4·D2·R6·H6·M1(L9: 이번 주 경험과 붙는 모듈 먼저).
3. [논문] 시험 효과(testing effect): 다시 읽기보다 **인출 연습(퀴즈)** 이 1주 뒤 기억을 더 남긴다(Roediger & Karpicke 2006 실험 2: 1주 뒤 SSSS(4회 읽기) 약 40% vs STTT(1회 읽기+3회 회상) 약 61% — 2차 자료 다수 일치, 원문 Fig.1 미열람 `[확인 필요: 원문 Fig.1, 2026-10-30]`; 5분 뒤엔 다시 읽기가 앞선다). 모듈 끝 확인문제·07:10 퀴즈 1문항의 근거. (출처: Roediger & Karpicke 2006 *Psych. Science* 17(3))
4. [논문] 분산 연습(spacing): 같은 총 학습 시간이면 간격을 둔 복습이 몰아치기보다 낫고, 최적 간격 비율은 보유 기간이 길수록 줄어 1주 보유 ≈ 20~40%, 1년 보유 ≈ 5~10%(Cepeda 2008 초록, 10/23 확인 — 10/17 의 '10~20%'는 틀림). SRS 1·3·7·21일은 1~2개월 보유용 관행 간격이고, '1년 뒤 장중에 쓰기'엔 30~60일 단계가 비어 있다(edu_self W5). (출처: Cepeda, Pashler et al. 2006 *Psych. Bulletin* 132(3); Cepeda et al. 2008 *Psych. Science*)
5. [논문] 선다형 문항 작성 지침(Haladyna, Downing & Rodriguez 2002, 31개 지침 중 교육·평가 데스크가 쓰는 것): ① 정답 위치를 고르게(한 위치 쏠림 금지) ② 오답지는 그럴듯해야 하고 '무관'·'모두 아님' 같은 빈 오답 금지 ③ 가장 긴 선택지 = 정답 패턴 금지 ④ 선택지 3개로 충분(Rodriguez 2005 메타분석) ⑤ 문두에 부정어 최소화. (출처: *Applied Measurement in Education* 15(3) 309–334; Rodriguez 2005 *EM:IP* 24(2) 3–13)

## 공식
6. [경험] 모듈 스키마 v3(`docs/study_spec.md`): 한 줄 요약 → 생활 비유 → 용어 → 핵심 개념(각 줄 출처 태그) → 공식(쉬운 숫자 1개) → 오늘 시장에서(`market_hook`) → 흔한 실수 → 확인문제(상황 70%) → 다음 문(`next_door`). `est_min ≤ 20`. 검증기 `scripts/study_content_check.py`가 출처 태그·est_min·quiz 인덱스를 강제한다.
7. [경험] 문항 품질 최소 3조건(평가 데스크와 합의, 2026-10-17): (a) `src[]`에 kb:/consult: 인용 1개 이상 (b) `why`는 인용 태그만이 아니라 **한 문장 근거**(틀렸을 때 읽는 유일한 줄) (c) 정답 위치 분포 — 모듈 5문항 안에서 같은 위치 3개 이하. 현황(10/17, `content/study/quiz_bank.json` 125문항 집계): 정답 1번 115/125(92%), 태그만 `why` 100/125(80%), duel.pick=answer 125/125. **10/23 셔플 후**(`scripts/quiz_shuffle.py`): 0·1·2·3번 = 31·31·32·31, 모듈 안 같은 자리 최대 2, 검증기가 (c) 위반·전체 40% 초과를 실패로 막는다. 남은 것: 정답이 유일하게 가장 긴 선택지 112/125(90%)·why 한 문장 미만 109/125(검증기 경고). 반대 근거: 학습자는 선택지 번호가 아니라 문장을 읽으므로 1번 쏠림의 실제 피해는 미측정(검증전) — 그래도 소거법 노출은 Haladyna #5 위반.

## 현업 vs 교과서
8. [현업 관행][교과서] 교과서(Haladyna)는 선택지 3~4개·정답 위치 무작위를 권하지만, 우리 터미널은 '데스크 답 vs 내 답' **대결 형식**(consult:pb_learner#L3)이라 `duel.pick`이 노출된다. 현재 125문항 모두 pick = answer → 데스크가 항상 맞는 구조는 게임성을 없앤다. 평가 데스크에 '데스크가 틀리는 문항 10~20%'(KB `[확인 필요: 원문 대조, 2026-10-30]`·검증전 항목에서) 요청(라운드1).

## 흔한 오해
9. [경험] "모듈이 많을수록 좋다" → 이 학습자는 총량을 보면 이탈한다(L5). 노출은 '오늘 1개'. 모듈 추가는 자유, 노출은 `gate`(첫 2주 15개)와 `first_two_weeks`가 통제한다.
10. [경험] "출처 태그가 있으면 근거가 있다" → 태그는 추적용이고 근거는 문장이다. `why: "[kb:behavior#3]"`만 있는 문항은 오답자에게 아무것도 가르치지 못한다(#7b).
11. [교과서] "어려운 오답지가 좋은 문항" → 오답지는 **흔한 오해**에서 뽑아야 진단 가치가 있다(Haladyna #5). '무관'·'규칙 준수' 같은 빈 오답은 정답을 소거법으로 노출시킨다.

## 터미널에서 보는 자리
12. [경험] 평일 07:10 KST `study_daily.yml` → `reports/study_daily.json` + 텔레그램 ≤4줄(오늘 공부 / 퀴즈 / 완료 이슈 링크 / 출석). STUDY 탭 '오늘 1개' 카드는 Dev handoff #3(미구현). 진행 = 이슈 `study <id> done` → `reports/study_progress.json`. 오답 큐 = `docs/desk_kb/_quiz_feedback.md`(미생성).

## 우리 연구와의 차이
13. [경험] 교과서 SRS는 '문항' 단위 간격인데 우리는 '모듈' 단위(복습 1개/일 상한). 학습자 시간 제약(L5) 때문에 모듈 단위를 따른다 — 대신 복습 퀴즈 통과 기준 60%로 문항 수준 신호를 보완.

## 기출 활용 원칙 (저작권·공개 저장소)
14. [규정][경험] 기출 활용 원칙(2026-10-17, 오너 요청 "인적성 기출로 반영"): ① PSAT(국가직 7급 1차) 기출은 공식 PDF(공공데이터포털 15060914 — 포털 표기 '이용허락범위 제한 없음')가 있어도 **공공누리 유형을 원 페이지에서 직접 확인하기 전엔 원문 발췌 0건** — 인사혁신처 저작권 정책은 공공누리 표시 기준 확인, 표시 없으면 사전 협의를 요구한다(https://www.mpm.go.kr/mpm/useinfo/copyrightPolicy/). 1유형 확인 후에도 문항당 1문장 이내 + 출처. ② 저장소엔 메타데이터(연도·책형·번호·영역·유형)와 우리말 유형 전략·함정·권장 시간만, 원문은 화면의 "원문 보기 ↗" 링크로. 번호는 2차 해설 목록과 대조해 확인된 것만(지어내기 금지 — 2026년분은 확인 자료 없어 제외). ③ GSAT·SKCT는 공식 기출 비공개, 시중 '복원 기출'은 출판사 저작물 → 사용 금지. 공개 설명(2차 자료 2곳 이상 일치)으로 **유형 지도**를 만들고 우리가 새로 쓴 '유형 대응' 문항만 둔다. ④ 지원 기업 전형에 인적성이 없으면 이 트랙은 하루 10분 유지(직무 과제 우선). 반대 근거: 메타만으로는 실제 지문 난이도를 체감하기 어렵다 — 그래서 링크를 문항 단위로 붙였다. 신뢰도 중 `[확인 필요: data.go.kr 15060914 공공누리 유형, 2026-10-24]`. (`content/study/aptitude.json` sources·past·type_map)

## 출처
- Roediger, H. L. & Karpicke, J. D. (2006) "Test-Enhanced Learning", *Psychological Science* 17(3) 249–255.
- Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T. & Rohrer, D. (2006) "Distributed Practice in Verbal Recall Tasks", *Psychological Bulletin* 132(3) 354–380; Cepeda, Vul, Rohrer, Wixted & Pashler (2008) "Spacing Effects in Learning: A Temporal Ridgeline of Optimal Retention", *Psych. Science* 19(11) 1095–1102 (PubMed 19076480).
- Haladyna, T. M., Downing, S. M. & Rodriguez, M. C. (2002) "A Review of Multiple-Choice Item-Writing Guidelines for Classroom Assessment", *Applied Measurement in Education* 15(3) 309–334.
- Rodriguez, M. C. (2005) "Three Options Are Optimal for Multiple-Choice Items", *Educational Measurement: Issues and Practice* 24(2) 3–13 (2차 1곳 확인).
- 10/23 자기 고도화 연구 근거(Dunlosky 2013·Kirkpatrick·Black & Wiliam 1998·Hattie & Timperley 2007·문항 분석 기준·가장 긴 선택지 결함·CFA LES·SRS 알고리즘) 3칸 요약 = `docs/desk_kb/rounds/2026-10-23/edu_self.md` §2.
- 자체: `docs/study_consults/answers/pb_learner.md`(L1~L9), `docs/study_spec.md`, `content/study/srs.json`, `content/study/quiz_bank.json`.
- 확인 방법: 10/17 라운드는 네트워크 없이 기억 기반 → 수치·쪽수 `[확인 필요: 원문 대조, 2026-10-30]`(신뢰도 중). 미확인으로 남으면 [경험]으로 강등.

## 자문 답변 색인 (모듈 sources[] 인용)
- behavior q1~q16·x1~x3 → 트랙 H · frm → R · derivs q1~q16 → D · cio q1~q16 → M · quant → Q · bonds·macro → 0·A·B 보강(v3 모듈 없음) · pb_learner L1~L9 = 모든 설계 결정의 근거. 원문 `docs/study_consults/answers/*.md`.

## 복기 (틀린 판단 → 왜 → 다음부터)
- 2026-10-17: 125문항 문제은행을 "정답 = duel.pick = 1번" 템플릿으로 일괄 생성한 것을 검수 없이 통과시켰다(정답 위치 1번 115/125 = 92%, `why` 인용 태그만 100/125) → 왜: 속도 우선, 검증기가 스키마(인덱스 범위·선택지 4개)만 보고 **분포**는 보지 않았다. 설계(교육)와 평가가 분리돼 있었는데 교차 검수를 안 했다 → 다음부터: 문항 품질 3조건(#7)을 검증기 경고로 넣고, 모듈 단위로 정답 위치 셔플 + `why` 한 문장을 평가 데스크와 나눠 고친다(보드 `quiz-key-balance`).
- 2026-10-23: 그 셔플을 6일 미뤘다(남의 KB 기준 쓰기가 더 눈에 띄는 일이었음, 실제론 1시간 일) — 그리고 보드에 `quiz-key-balance` 항목은 실제로 없었다(KB 만 언급). 셔플을 해 보고서야 더 큰 결함(정답 = 가장 긴 선택지 90%)을 셌다 → 다음부터: 처방 전에 검증기에 **측정 줄**부터 넣고, 숫자가 있는 격차만 적는다. 학습자 측정도 0(study_progress done·quiz 0건, 6일) — 보내기만 하고 재지 않았다.

## 10년차 기준 (2026-10-23 교육)
- 체크리스트: ① 역방향 설계 — 목표(장중에 쓸 행동) → 평가(확인 문항) → 활동(모듈) 순서로 짓는다 `[교과서: Wiggins & McTighe *Understanding by Design*]` ② 효과는 4수준으로 잰다: 반응·학습(퀴즈)·행동(규칙 준수·주문표)·결과(성적표) `[교과서: Kirkpatrick 4수준]` ③ 문항 분석 — 난이도 p·변별도·정답 위치 분포를 배포 전 검사(#5·#7) `[논문: Haladyna 2002]`
- 격차(10/23 갱신, 숫자 = `python scripts/study_content_check.py` 경고 줄): ① 정답 위치 — **해소**(1번 115/125 → 31/125, 모듈 quiz 84/95 → 23/95, 검증기 실패 규칙). ② 정답 = 유일하게 가장 긴 선택지 quiz_bank 112/125(90%)·모듈 quiz 75/95(79%) — '가장 긴 것'만 골라도 약 90% 맞힌다 = 정답률이 지식을 못 잰다. ③ why 한 문장 미만 109/125. ④ **측정 0** — 겸이 응답 0건(reports/study_progress.json, 10/17 이후 커밋 0)·데스크 드릴 응답 0(27개 KB 드릴의 답이 문제 바로 뒤에 있어 인출이 아니라 복사)·문항 실측 p·변별도 0. ⑤ 판단 1인 — 출제·검수 모두 교육 계열, 평가 교차 검수 기록 없음. 고도화 안 Top 7 = `rounds/2026-10-23/edu_self.md` §4.
- 드릴(답은 아래 접힌 줄 — 먼저 풀고 볼 것): 4지선다 125문항에서 정답이 유일하게 가장 긴 비율이 90%다. (a) 무작위로 길이를 정했을 때 기대 비율은? (b) 응시자 1명이 '가장 긴 것 고르기'만 해서 얻는 기대 점수와, 그 점수로 겸이 실력을 말할 수 없는 이유 한 줄? (c) 변별도 rpbis 를 계산하려면 최소 무엇이 필요한가?
- 드릴 답: (a) 약 25%(동률 없을 때 4개 중 하나 — 우리 기준선 ≤35%). (b) 약 90% → 지식 없이도 나오는 점수라 정답률-지식 상관이 깨진다(Haladyna #3, 테스트와이즈니스). (c) 같은 문항을 푼 응시자 여러 명의 문항 점수와 총점 — 겸이 1명으론 불가 → 데스크 블라인드 응시(edu_self §4 안 3)로 표본을 만든다.

