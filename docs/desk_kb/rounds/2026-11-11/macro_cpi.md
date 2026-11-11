<!-- short: CPI 날짜표·10월 결과 -->
<!-- oneliner: 10월 CPI 전월비 +0.4%·근원 +0.3%, 전년비는 산출 불가 -->
# 매크로 — 미 CPI 날짜표·10월 결과 · 기준 2026-11-11 KST · 분석만, 매매 권고 아님
- 자료: ALFRED 빈티지(alfred.stlouisfed.org) · reports/studies/2026-11-10_event_cpi.json(BLS 아카이브 파일명) · reports/views/digest.json us_cpi_202610 · 웹검색 0회(bls.gov 접속 차단, BLS API 일일 한도 소진)

## What
- reports/cpi_releases.json 신설 — 발표 58회(2022-01-12~2026-11-10), 발표일 57회 BLS 아카이브 파일명 일치(11/10 1회는 아카이브 취득 이후)
- 10월 CPI(11/10 22:30 KST): 전월비 +0.4%(337.476/336.298) · 근원 +0.3%(339.900/338.896), 계절조정, ALFRED 11/10 빈티지
- 전년비 산출 불가 — 2025-10 지수 결측(BLS 미수집)
- 기존 macro_releases CPI 전년비 오류 확인: 9월 4.02%·10월 4.08% = 13개월 변화(행 기준 12칸 앞), 실제 9월 3.7%(원계열)
## So What
- 헤드라인 상충(+0.4 vs +0.6) 해소: +0.4가 지수와 일치, +0.6은 9월 전월비(+0.6%)와 같은 값 [가정: 웹 1곳이 9월 수치 인용]
- 컨센 대비 +0.1%p(헤드라인·근원) — 컨센은 2차 속보뿐(1차 출처 없음, 신뢰도 하~중), 과거 57회 컨센은 전부 빈칸·'출처 없음'
- 실적치는 지수 기반 확정, BLS 보도자료 원문 문구는 미대조
## Now What
- 퀀트: H4·H9 입력은 reports/cpi_releases.json(release_et·release_kst·actual) 사용, 컨센 칸은 비어 있어 서프라이즈 가설엔 못 씀
- 애널: digest us_cpi_202610 '9월 전년비 4.02%' 문장 정정 필요(실제 3.7%) — 다음 digest 갱신 때, 피어 파일이라 직접 미수정
- 뒤집힘: bls.gov 원문이 열리면 11/10 수치 대조, 다르면 원문 기준으로 교체
## 근거
- 코드: screener/calendar_ev._calc 전년비를 날짜 일치로 수정 · cpi_lines()가 CPI 이벤트 결과 우선 · tests/test_cpi_releases.py
- 재생성: python3 scripts/cpi_release_table.py
## 반대 근거
- ALFRED는 연준 재배포본 — BLS 원문과 소수 3자리 지수가 다를 가능성(낮음, 57회 날짜 전부 일치)
VOC: 컨테이너에서 bls.gov 차단·BLS API 키 없음(하루 25회 공유) — 1차 원문 대조가 매번 막힘, 컨센 무료 1차 출처도 없음
요청→애널: digest us_cpi_202610 '직전 9월 전년비 4.02%' → 3.7%로 정정(근거 reports/cpi_releases.json 2026-10-14 행)
현재 상태: CPI 날짜표 58행·캘린더 9·10월 결과 갱신 완료 / 10월 전년비 미산출 / 컨센 57회 빈칸 / BLS 원문 대조 미완
