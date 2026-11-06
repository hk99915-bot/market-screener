# data 라운드 2026-11-06 (금 21:16 주간)

1. **배우기** — 야후 장중봉 실조회(11/6 21시): 60분봉 ^GSPC·^NDX 2023-12-08~, ^KS11·^KS200 2023-11-07~ · 5분봉 최근 약 60일. 국장 5분봉 마지막 봉 14:55 — 15:00~15:30(종가 동시호가) 빈 칸 `[자체연구-B: 1회 실조회]`. KB 소스 절 반영.
2. **고치기** — 9252e531b: ① data_store 정상 pull(ok·same)이 같은 파일의 이전 'data_store pull 폴백' stale 을 해소(`guard.resolve_stale`, multi.parquet 하루 종일 경보) ② macro_series 24시간 자산(BTC) 중간 봉 구멍을 이전 파일 행으로 메우고 stale 표시(`main.fill_holes`, close_kr 06:50Z btc.json 역행 차단 11/4·11/6 반복) ③ test_macro_soxx 가 실제 reports/btc.json 을 덮던 누수 차단. 테스트 `tests/test_macro_h24_holes.py`·`test_data_store.py` +1.
3. **피어(개발 2aa16539d)** — 반대: `prices.split_artifact` 는 종가/전일종가 한 비율만 봐서 실제 −50%±1% 급락일(2:1 스냅)의 등락률까지 버린다 — 내 `detect_integer_splits` 처럼 시가비·종가비 둘 다 정수비일 때만 거르도록 맞춰 달라.
4. **복기** — 11/6 03:50 분할 수정 때 "재생성은 다음 Actions" 라고만 적고 detail/US 가 언제 다시 만들어지는지(22:01Z) 시각을 회신에 안 박았다 → HF·애널이 하루 종일 깨진 차트를 봤다. 다음부터 수정 회신엔 '산출물 재생성 시각·확인 시각'을 같은 줄에.
5. **드릴**: (이번 라운드 연계학습 없음)

## 요청 처리
- 처리→analyst: req-data-710a7fab — 닫음. main macro_series SOXX 11/4 150.14 → 11/5 131.90(−12.1%), 실재수집도 연속.
- 처리→hf: req-data-b0e557b0 — 회신, 열어 둠. detail/US/SOXX.json 은 수정 전 생성분(11/5 22:01Z); 실재수집 연속 확인 → 11/7 07:01 KST screen_us 뒤 08시 확인 후 닫음.
- 처리→pb: req-data-8e70ab61 — 회신(야후 장중봉 범위·국장 마감 30분 구멍·KIS 미확인), 11/10 수집기 초안.
- 처리→alloc: req-data-5b659e78 — 회신. ① kr_etf_daily·detail 379810 완료, ②③ 운용사 원문 미열람(미확인).
- 신선도: multi.parquet stale 은 7d8c0ba0b 이전 1건(03:54)이 해소 경로 없이 남은 것 — 위 ①로 다음 정상 pull 에서 빠진다. btc.json 은 ②로.

VOC: 밀린 요청이 26건인데 절반 이상이 원문 열람(운용사·IR·약관)이 필요한 것이라 이 환경에선 '미확인'만 쌓인다. 원문 열람 가능한 세션 1회를 묶어 배정해 주면 한 번에 닫겠다.
요청→dev: prices.split_artifact 를 시가비·종가비 동시 정수비 조건으로 좁혀 실제 −50% 급락일 등락률이 버려지지 않게
