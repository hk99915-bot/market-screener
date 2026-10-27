# 검증 — 10/27 23시 야간 처리 (요청 2건 + 10/26 검수 결함 재확인)

기준 2026-10-27 23:50 KST · 독립 검수(타 데스크 파일 수정 없음) · 새 요청·보드 항목 없음(10/27 야간 지시)

## What
- req-verify-7829ae44 SOX 상대수익률: PB −9.6%p = 기준 10/12 종가(9개 수익률) 재현 −9.56%p · 언론 −13% = 기준 10/08 종가 비율 −13.02% 재현
- '20여 년 최악' 미재현 — 2026-07 창이 세 정의 모두 더 나쁨, 하위 분위 1.0~1.9%(`reports/studies/replication_sox_rel.md`)
- req-verify-cb391f74 금융위 V2: 종가 대조·생존편향 기준 §0 사전등록 · 미장 창고 퇴출 0/666(생존편향 확정) · 국장 944/3,641 퇴출(1차 통과)
- 10/26 검수 결함 재확인: 10항목 중 종결 2 · 처리 확인(종결 가능) 1 · 미해소 7

## So What
- SOX 두 숫자 차이 = 기준일 정의, 종가/총수익 아님(TR 차이 ≤ 0.04%p) — 정의 없이 인용하면 3%p 흔들림
- 미장 장기 백테스트는 상폐 0 창고라 낙관 편향, 금융위 API 는 국장만 보완
- 검수 미해소 7항목 중 4개는 '실데이터·운영 연결'(백필·생성기 훅·게이트 실발동) — 10/26 판단과 같은 구조

## 10/26 검수 결함 재확인 (`rounds/2026-10-26/review_verify.md` 표 기준, 10/27 23:40 직접 확인)
| 건 | 결함 | 지금 | 판정 |
|---|---|---|---|
| ra-sec-coverage | 컨센 결측 시 전분기 대용 경로 없음 | `earnings_cal.fill_proxy`·`BASIS_PROXY` 추가(cb78851c, 10/27 07:51) · `tests/test_earnings_cal_proxy.py` 통과 · 현재 49/49 컨센 있어 미발현 | **종결** |
| bok-issue-note | 03:30 Actions 수집 확인 | `reports/public_reports.json` bok_research status ok·n 20(10/27 04:25 커밋) | **종결** |
| tue-risk-events ① | 실계좌 스트레스 칸 미갱신 | 포지션리스크 10/27 종가 재측정(`rounds/2026-10-27/posrisk.md`) | **처리 확인 — 종결 가능** |
| tue-risk-events ② | 보드 files 칸 공란 | 여전히 [] | 미해소(PB 보드 반영 몫) |
| dotplot ① | '기록 거부' 문구 vs 구현 'lint 경고' 불일치 | `lint_dots` 경고 방식 그대로, 보드 제목 그대로 | 미해소 |
| dotplot ② | 중립인데 기본 확률 11% | 10/27 19:15 `dotplot.json` PB 코스피 중립 5d 10.8%·20d 11.2% | 미해소 |
| kr-accum | 2022~23 하락장 백필·스터디 재실행 | 매니페스트 flows 2024~2026 만 · accum_signals asof 10-17 | 미해소(반려 유지) |
| integrity-p0-5 ① | 생성 훅·예약 미연결 | pb `handoff_build.py --check` rc 1(10/27 23:40, 낡음) | 미해소 |
| integrity-p0-5 ② | 보드 files 칸 공란 | 여전히 [] | 미해소 |
| us-eod-toss | 실데이터 대조 0회 | toss_eod_check.json(미생성) · 섀도 대조 커밋 없음 | 미해소 |
- integrity-p0-2 '중 1'(결재 #4 → 조항 [13])은 [13] 신설이 11/01 결재로 연기(원장 10/26 18:2x ⑤) → 11/01 전 판정 대상 아님

## Now What
- PB: 위 표 '종결' 2·'종결 가능' 1 보드 반영, files 칸 2건 기재(tue-risk-events = `docs/desk_kb/rounds/2026-10-26/event_posrisk.md`·`rounds/2026-10-27/posrisk.md`)
- 미해소 5건(dotplot 2·kr-accum·p0-5 훅·toss)은 기존 요청 마감 그대로 — 다음 검수(10/31 정기)에서 미해소면 재오픈
- 애널: SOX 인용은 기준일·창 길이·차/비율 명기 · 데이터: fsc_close_check.json 미생성 원인(요청 회신으로만)

드릴: verify-d1 15/25 = 0.6 → 0.5·√(0.6·0.4/25) = 0.5·0.098 = 4.9%p, 반올림 단위(0.1%p)보다 커서 허용오차 ≈ 4.9%p
VOC: 야후 원시 HTTP 는 막혀 yfinance 라이브러리로만 받음 — 대조 출처 1개(단일 출처 한계). 금융위 키는 이 컨테이너에 없어 실호출 판정은 Actions 경로에서만 가능.
요청→데이터: (새 요청 아님 — 회신 문장으로 전달) fsc_close_check.json 미생성 원인 확인
