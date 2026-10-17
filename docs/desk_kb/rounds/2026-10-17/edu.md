# edu 라운드1 — 2026-10-17 (교육 데스크 · 평가 절 포함 · STANDARD.md 적용)

## 1. 읽기
- LOOP/README/STANDARD, `_scoreboard.md`(라운드 표 0행), 피어 behavior.md(30항목·복기 5건), 보드 `edu-quiz-srs`(완료)·`study-progress`(검수). 자기 KB 없음 → `docs/desk_kb/edu.md` 신설(13항목, answers/*.md 색인).
- 월 10/19 07:10 실측(`python -m screener.study_daily --date 2026-10-19`, `reports/study_progress.json` 초기 상태 10/17): 1줄 `📚 오늘 공부: H2 … (15분) · 복습 없음 · 퀴즈 1` + ❓ H2 situation + 이슈 링크 `study H2 done` + 출석 0일 = 4줄. 결재 #9·#13('오늘 1모듈 + 퀴즈 1')대로 나간다. 신뢰도 상(테스트로 고정).

## 2. 배우기 1건
- Haladyna·Downing·Rodriguez 2002(선다형 지침 31개) + Roediger & Karpicke 2006(시험 효과) + Cepeda 2006(분산 연습) → `kb:edu#3~5` [논문]. 수치는 기억 기반 → `[확인 필요: …, 10/24]`, 신뢰도 중.
- 차이(`kb:edu#8`): 교과서 = 정답 위치 무작위 / 우리 = 1번 115/125(92%, quiz_bank.json 10/17 집계). 반대 근거: 번호 쏠림의 실제 피해는 미측정(검증전).

## 3. 고치기 1건 — `screener/study_daily.py` (+ `tests/test_study_content.py` 3건)
- (a) `pick_quiz`: srs 'situation 우선'이 정렬 후 해시라 무효 → 미답 situation 안에서만 선택. (b) 구형 시간 단위 모듈(0-1 = 6h = 360분, study.json hours)이 새 모듈로 올 때 `(360분)`·`min 360` 노출 → `daily_cap.est_min_total` 20분 상한 + `total_min`·`multi_day` 필드.
- 테스트 3: 월 10/19 메시지 고정(H2·15분·퀴즈 1·≤4줄, 진행 None/초기) / 0-1 → est 20·total 360 / situation 소진 전 knowledge 0건. `pytest tests/ -q` 전체 통과, `check_functions.py` 통과.
- 영향 범위: `study_daily.yml`(평일 07:10 텔레그램 1줄·2줄, `reports/study_daily.json` new.est_min 값, 이슈 본문 `min N`). 소리·시크릿·스케줄 변경 없음. 롤백: 이 커밋 `git revert` 1개(데이터 파일 무변경).
- 뒤집는 조건: 학습자가 10/19~10/23 5회 중 2회 이상 "퀴즈가 전부 상황문제라 지루하다"고 하면 situation 비중 70%(L8)로 혼합 선택으로 변경(담당 교육, 10/24).

## 4. 피어 1건 → 행동
- 반대 의견: `kb:behavior#3`은 Thaler & Johnson 1990을 "이익 뒤 위험추구↑ / 손실 뒤 본전 베팅↑"로 요약하지만, 원 논문은 **손실 뒤엔 본전 회복이 가능한 내기에서만 위험추구, 아니면 위험회피↑**인 조건부 결과로 기억한다 `[확인 필요: T&J 1990 §실험 결과, 10/24]`. 이 조건 누락으로 H2-b1 오답지 "손실 뒤 위험 회피"가 반쯤 참인 오답이 됐다.

## 5. 복기 1건
- 틀림: 125문항을 설계 측이 검수 없이 통과 → 정답 1번 92%, 태그만 `why` 80%. 왜: 검증기가 스키마만 보고 분포·문장은 안 봄, 교육·평가 교차 검수 생략. 다음부터: 품질 3조건(`kb:edu#7`) 검증기 경고 + 보드 `quiz-key-balance`(교육·평가 분담, P2, 10/24).

## 평가 (평가 데스크 절 — H2 3문항: 정답 근거에 KB 인용이 있는가, quiz_bank.json 10/17 기준)
| 문항 | 인용 | 대상 실재·일치 | 판정 |
|---|---|---|---|
| H2-b1 T&J 1990 결론 | consult:behavior#q3 | 있음(q3 예시 1) | △ 인용 OK · why 문장 0 · 오답지 "무관/규칙 준수" 빈 오답 · "손실 뒤 위험 회피" 조건부 참 |
| H2-b2 손실 직후 사이즈 2배 | kb:behavior#3 | 있음(정의 일치) | ○ 인용·정답 OK · why = 태그만 |
| H2-b5 일일 손실 한도 → 당일 종료 | kb:behavior#14 + rule_ref 규칙[쿨다운] | 있음(현업 관행 일치) | ○ 최선 문항(규칙 조항 인용 만점 구조) · why 문장 0 |
- 결론: 3/3 인용 있음·실재. 공통 결함 = why 태그만 + 정답 전부 1번(H2 5문항 + 모듈 내장 4문항). 조치: 교육이 H·R·D 트랙, 평가가 Q·M 트랙 + 검증기 경고, 10/24까지(보드 `quiz-key-balance`). 뒤집는 조건: 오너가 대결 형식상 'pick=answer 고정'을 원하면 셔플만 하고 pick 분리는 보류.

VOC: 네트워크 없이 돌아 외부 논문 수치를 확인 못 했다 — 라운드2에 WebSearch 10분 필요. `_scoreboard.md` 라운드 표가 비어 있어 "많이 고친 데스크가 더 맞히는가"를 아직 볼 수 없다.
요청→behavior: kb:behavior#3에 Thaler & Johnson 1990 손실 쪽 조건(본전 회복 가능 시에만 위험추구, 아니면 위험회피)을 10/24까지 확인해 한 줄 추가 — 교육이 H2-b1 오답지를 다시 쓰는 전제.
현재 상태: ① study_daily 수정·테스트 3건 main 반영, 월 10/19 07:10 첫 실전 = H2 15분 + 퀴즈 1(이슈 링크로 'study H2 done' 확인은 study-progress 태스크). ② 보드 `quiz-key-balance` 대기(교육, P2, 10/24) — 정답 셔플·why 문장·검증기 경고. ③ edu.md 13항목 중 [논문] 3건 수치 `[확인 필요: 10/24]` — 라운드2 첫 작업.
