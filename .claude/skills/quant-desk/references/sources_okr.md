# 출처·터미널·10년차 기준·OKR·기타

(원본: docs/desk_kb/quant.md 해당 절을 그대로 옮김 — 2026-10-28 스킬 시범. 내용 수정은 양쪽 같이.)

## 출처
- Harvey, Liu & Zhu, "…and the Cross-Section of Expected Returns", RFS 29(1) 2016, 5–68 — t≥3.0 권고, 316개 팩터 (검색 확인 2026-10-16, 원문 쪽수 미확인)
- Harvey & Liu, "Backtesting", JPM 41(1) 2015, 13–28 — 샤프 헤어컷, Bonferroni/Holm/BHY (검색 확인, 세 방법 명칭은 R `profitHurdle` 문서 기준 `[확인 필요: 명칭, 2026-10-30]`)
- Bailey & López de Prado, "The Deflated Sharpe Ratio", JPM 40(5) 2014, 94–107 — PSR·기대 최대 샤프·왜도/첨도 (2차 자료로 확인 `[확인 필요: 첨도 정의 convention, 2026-10-30]`)
- López de Prado, *AFML*, Wiley 2018 — 7장 purging/embargo · 11장 · 12장 walk-forward/CPCV (목차 확인) · CFA L1 Quantitative Methods 가설검정 `[확인 필요: 절 번호, 2026-10-30]`
- 자체: reports/studies/entry_signals.md · rule_audit.md · semis_cap.md · exec_signal.md · fib_levels.md · derivs_signals.md · gamma_regime.json · views/registry.json grades_doc · scripts/study_rule_audit.py

## 터미널에서 보는 자리
- #22 [자체] VIEW 탭 '렌즈 전체' 표: 등급/상태/재검토(review_by) — 배지 색은 근거의 세기이지 좋음/나쁨 아님. #23 [자체] DERIV 탭 '검증 현황': 가설별 등급·n·p(IS/OOS), 탐색 가설 `exploratory: true`(상한 C).
- #24 [자체] 하루 1분 체크: ① 근거 렌즈 C 이하면 경보로만 ② review_by 경과 ③ 각주 α와 p 직접 비교 ④ §0 커밋이 결과보다 앞서는지.

## 10년차 기준 (2026-10-23 교육)
- 체크리스트: ① 문턱은 연구 안 m 이 아니라 **주제 전체 시도 N** 으로 함께 보고(#13·#30), 새 팩터 주장은 t ≥ 3.0 `[논문: Harvey–Liu–Zhu 2016 RFS, #12]` ② 채택 전 Deflated Sharpe·과최적화 확률(PBO) 중 하나를 붙인다 `[논문-B: Bailey & López de Prado 2014(#5), Bailey et al. 2017 PBO]` [확인 필요: PBO 논문 서지(J. Comput. Finance), 2026-10-30] ③ 비용·용량·체결 가정과 OOS 기간을 §0 에 먼저 고정 `[교과서: CFA L2 Quant·AFML 11장]`
- 격차: 감사 '중' 6건(2회 합 최다 — reports/audit/2026-10-17.json·2026-10-21.json, 등급 꼬리표 누락형)·시도 N 1150 중 등록 전 탐색 748(reports/studies/trial_log.md §0) — 탐색이 등록보다 많다.
- 드릴 [quant-d1]: trial_log 전체 N 1150 일 때 Bonferroni α 와 accum_signals pen h20(t 3.47) 통과 여부는? — 답·채점 키 `content/drills/quant.json`(라운드 파일에 `드릴: quant-d1 <내 답>` 을 먼저 쓰고 열 것, round_collect 채점 · G1 10/24)

## 비전·OKR
- 비전 연결: 프리맨 5원칙 중 ①생존 우선·⑤실측 판단 — 퀀트는 '희망'과 '착시'를 숫자로 걸러 실계좌 진입 자격을 정하는 문지기 (docs/desk_kb/VISION.md)
- O: 실전 적용 가능한 전략과 통계적 착시를 구분해 실계좌 진입 자격을 숫자로 정함 (리서치 본부 O = 진입·보류·기각 실측 판정)
- KR1: 12/31까지 2개+ 전략의 표본 외·모의북 성과를 비용 반영 벤치와 비교, 청산 n·기대값 하한 공개 (reports/alphabook.json·verify_weekly)
- KR2: 11/1 이후 전략 평가 100%에 누수·생존편향·다중검정(주제 N α) + DSR 또는 PBO 첨부, 12월 감사 '중' 이상 0건 (trial_log.md·reports/audit)
- 확정본·본부 KR: docs/desk_kb/rounds/2026-10-26/okr_quant.md (2026-10-26 퀀트 직접 확정, OKR.md 본문 취합은 PB)
## 라운드 추가 (2026-10-17 강화 루프 R1)
- #31 [자체연구-B] 세액공제 계좌 vs 일반계좌는 '쓸 수 있는 결정세액'부터: 공제는 결정세액까지만 → 여력 0이면 이득은 과세이연+저율 연금세뿐(부트스트랩: 55세 유지 시 +수%~+10%대, 중도 해지 ±1%p). 처방: 여력 구간 확인 → 납입=여력÷공제율. 반대 근거: 세법 30년 불변 가정. 신뢰도 중. (출처: pb-private 분석 2026-10-17, 금액 없음)

