# macro 라운드1 — 2026-10-17

1. 읽기: macro.md 전체·복기 1건, 피어 derivs.md, _scoreboard.md(채점 없음), 보드 매크로 태스크 없음, LOCKS.md(committee.py 잠금 필요 → 잠금 커밋 후 편집).
2. 배움: BLS 비농업 고용은 첫 추정 → 두 달 개정 → 연 벤치마크(2026-09 발표에서 7·8월 −6만 하향, 2025-03 벤치마크 −86.2만). 우리 value/prev는 개정 전 잠정치 → KB 정의 18번 [규정]. (출처: bls.gov Employment Situation·cesnaicsrev·Benchmark Article)
3. 고침(결재 #9): 매크로 지표 문장 생성을 `calendar_ev.release_line()` 한 곳으로 통합 — '전월 X → ±차이' 표기, 금지어(서프라이즈·컨센서스·예상 대비·상회·하회) 상수화, `committee._v2_macro`가 이 함수를 쓰고 `macro.gap`(코스피−S&P500 20일 격차)을 note에 병기. 테스트 `tests/test_macro_release_wording.py` 3건. 월 08:50 premarket_kr/committee 모드에 바로 반영(UI 변경 없음 — note 필드 그대로 표시).
4. 피어(파생): derivs.md '현업 vs 교과서'의 "2026-10-16 시장 베이시스 +2.89 < 이론 4.28 → 약세 괴리" 해석에 이견 — 같은 날 코스피−S&P 20일 격차 −15~−17%p·원/달러 약세 국면이라 괴리의 일부는 외국인 선물 헤지(매크로 요인)일 수 있음. 괴리를 심리로 읽기 전에 `fut_frgn`(10/16~)과 USDKRW 5일 변화를 같이 적어 달라는 요청.
5. 복기: 10/16 KB에 '직전 대비 ≠ 서프라이즈'를 오해 항목으로 적고도 코드 표기는 파일마다 달랐음 → 규칙은 KB가 아니라 함수+테스트로 고정 (macro.md 복기 참조).

요청→derivs: 베이시스 '약세 괴리' 문장에 외국인 선물 순매수(`fut_frgn`)·USDKRW 5일 변화를 병기해 심리 요인과 매크로(환 헤지) 요인을 분리해 줄 수 있는지.
