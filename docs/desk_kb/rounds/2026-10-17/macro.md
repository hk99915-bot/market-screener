# macro 라운드1 — 2026-10-17 (STANDARD.md 적용)

## 1. 읽기
macro.md 17항목+복기 1건 · 피어 derivs.md · _scoreboard.md(채점 0건) · ops/board.json 매크로 태스크 0건 · LOCKS.md(committee.py 공유 → 잠금 커밋 1506c17c 후 편집).

## 2. 배움 (KB 정의 18, [규정] 신뢰도 상)
BLS 비농업 고용은 첫 추정 → 2개월 개정 → 연 벤치마크. 2026-09 보고서에서 7·8월 합계 −60천명 하향, 2025-03 벤치마크 −862천명(NSA), 10년 평균 |0.2%| (출처 bls.gov empsit.nr0 · cesnaicsrev · cesbmart, 10/17 확인).
우리 value/prev(2026-09: 29 − 133 = −104천명)는 개정 전 잠정치 → 문장에 '개정 전' 명시. 반대 근거: 개정 폭은 보통 바람 점수(가격 기반)에 영향 없음 — 지표 문장만의 문제.

## 3. 고침 (결재 #9) — 커밋 1fcf5124
- 무엇: 매크로 지표 문장을 `screener/calendar_ev.py` `release_line()` 1곳으로 통합. 형식 `<지표> <값> (전월 <직전> → <차이>)` 예: "CPI 전년비 4.02% (전월 3.71% → +0.31%p) · 2026-09 기준 · 발표 확인 10-15" (입력 reports/macro_releases.json, FRED CPIAUCSL yoy, seen 10/15).
- 금지어 상수 `BANNED_WORDS`(서프라이즈·컨센서스·컨센·예상 대비·예상치·상회·하회·깜짝). `committee._v2_macro` 가 이 함수를 쓰고 `macro.gap` = "코스피−S&P500 20일 격차 −15.3%p (코스피 −15.2% / S&P500 +0.1%)" (macro_view.json chg20, asof 10/17)를 `macro.note` 에 병기.
- 테스트: `tests/test_macro_release_wording.py` 3건(형식·금지어·격차 부호 라벨·시리즈 없을 때 None). 전체 pytest 178건 통과, check_functions 통과.
- 영향 범위: briefing.yml `premarket_kr`(월~금 08:50 KST)·`committee`(11:35/14:15)·`close_kr` 의 `reports/committee.json` macro.releases/note/gap + `reports/calendar.json` 매크로 이벤트 `result` 문자열. UI 변경 없음(tab_committee.html 이 note 를 그대로 표시, tab_home 이 result 표시). 알림·스케줄·시크릿 변경 없음.
- 롤백: `git revert 1fcf5124` (calendar_ev.py·committee.py 두 파일, 데이터 포맷 변경 없음).
- 뒤집는 조건: 컨센서스 소스를 수집하기 시작하면(보드 태스크로 등록 시) 금지어 중 '예상 대비' 해제 — 그 전까지 유지.

## 4. 피어 (파생) — 반대 의견 1
derivs.md "10/16 시장 베이시스 +2.89 < 이론 4.28 → 약세 괴리(심리)"에 이견: 같은 날 코스피−S&P 20일 격차 −16.6%p(macro_view 10/16)·원/달러 약세 국면이라 괴리의 일부는 외국인 선물 매도(환·지수 헤지, 매크로 요인)일 수 있음 [가정: 외국인 선물 순매도 ≥ 비차익 순매수]. 검증전 · 신뢰도 하(fut_frgn 이력 10/16~ 1일).

## 5. 복기
틀림: 10/16 KB 13번에 "직전 대비 ≠ 서프라이즈"를 오해로 적고도 코드 표기는 committee.py '직전'·calendar_ev.py '이전/전월' 로 제각각, 격차는 summary 에만. 왜: 규칙을 문서에만 쓰고 생성 함수를 한 곳으로 모으지 않음. 다음부터: 표기 규칙 = 함수 1개 + 금지어 테스트, KB '터미널에서 보는 자리'에 함수명 기재(이번에 반영).

## 6. 인수인계
VOC: 공유 작업 트리에 다른 데스크의 미커밋 변경(bonds.py·duel.py·ticket.py)이 있어 `git pull --rebase` 불가 → 직접 push 로 우회. 데스크별 worktree 분리 필요(개발 데스크).
요청→derivs: 베이시스 '약세 괴리' 문장에 외국인 선물 순매수(`fut_frgn`)·USDKRW 5일 변화를 병기해 심리 요인과 환 헤지 요인을 분리할 수 있는지 (2026-10-20 라운드2까지 답 요청).
현재 상태: ① 결재 #9 코드·테스트 main 반영(1fcf5124), 월 10/19 08:50 premarket_kr 부터 새 문장 생성 — 10/19 09:00 reports/committee.json macro.note 에 "전월"·"격차" 포함 여부 확인이 남은 일. ② committee.py 잠금은 이 수정 커밋에서 해제. ③ 미결: 고용 개정값 '개정 −Nk' 표기 추가 여부(매크로, 10/24까지 결정, KB 18).
