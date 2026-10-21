# 유지보수 라운드 1 — 2026-10-21 (첫 출근, 기준: docs/desk_kb/STANDARD.md)

## 1. 읽기
maint.md(자기 KB, 복기 0건)·LOOP.md·STANDARD.md·ops.md/dev.md 경계 문구·ops/board.json(maint-heatmap P1)·rounds/_requests.json(유지보수 앞 열린 요청 0건, 10/21 11:00 기준). 피어 KB 는 운영(ops) — 신선도 계약(ops/freshness.json) 쪽만.

## 2. 배우기
[교과서] Google *The Site Reliability Workbook* 2장(2018): 데이터 파이프라인 SLI = 신선도·커버리지·정확도. 히트맵에 적용 — 신선도 = `asof`(계약 heatmap_kr 장중 30분·heatmap_us 60분), 커버리지 = `collected/expected`(80% 미만이면 안 씀). KB 정의 #4. 반대 근거: 정확도(값이 맞는가)는 아직 안 잼 — 첫 회차 삼성전자 +7.57%·SK하이닉스 +8.34% vs 같은 시각 KOSPI +4.57%(live.json 11:05)로 방향만 확인, 신뢰도 중.

## 3. 고치기
원인: KR = 히트맵 1D 가 peers_KR.json(16:20 일 1회)뿐, 장중 경로 없음(분류 #4 거짓 표시). US = heatmap.yml cron 10/20 예약 18회 중 실행 3회, 정규장 창 안 1회 → asof 02:57 고정(분류 #1, `gh run list -w heatmap.yml`).
고침(커밋 0f715f60): screener/heatmap_kr.py 신설(네이버 시총 목록→polling→basic, 80% 미달 시 이전 값 유지) · live.yml 루프 편승(KR 매 회차 약 5분, US 3회차마다 약 15분, asof 새로울 때만 커밋) · heatView KR 장중 피드 + asofTag '기준 HH:MM · 다음 갱신' + 장중 지난 값 ⚠ STALE '장중 미갱신' · 신선도 계약 2건. 테스트 7+8건, ui_smoke heat OK.
실측: 11:0x live 루프 재시작(구 실행 취소 → 수동 commit=true) → heatmap_KR.json asof 11:05 KST, 1272/1272종목, 소스 list. US 는 오늘 22:30 미장 루프에서 첫 확인. 롤백 = 커밋 revert.

## 4. 피어 (운영)
freshness 계약 `fix` 가 live.yml 재실행인데, 루프가 돌고 있으면 concurrency 대기열에 쌓이기만 한다(오늘 08:40 cron 이 10:57에 깨어나 pending). 복구 명령에 '진행 중 실행 취소 후 재실행' 1줄이 필요 — 반대 근거: 취소하면 이벤트 감시가 1~2분 끊김(신뢰도 중).

## 5. 복기
애매: KR 1·2순위 소스를 샌드박스 네트워크 차단으로 실측 없이 배포 → 왜: 검증 수단(gh 로그·파일)을 배포 뒤에만 씀 → 다음부터: 새 소스는 첫 실행 결과(소스 이름·커버리지)를 확인하고 나서 '복구'라고 말한다. 이번엔 첫 회차 list 1272/1272 로 확인됨.

## 현재 상태 (다음 사람 5분 인수)
1. KR 장중 히트맵 = live.yml 국장 루프(실행 39530935464)가 약 5분마다 reports/heatmap_KR.json 커밋 중. 내일부턴 GAS 08:40 루프가 그대로 이어받음.
2. US = 오늘 22:20 루프부터 약 15분 주기. 확인: 22:45 KST 이후 heatmap_US.json asof 가 오늘 밤인지. 아니면 `gh run list -w live.yml` 로그의 'US heatmap' 줄.
3. 화면: Pages 는 자동 반영. GAS 터미널은 apps-script/tab_market.html 재붙여넣기 전까지 KR 은 예전(전일 종가·배지 없음) — 보드 gas-repaste 에 추가.

VOC: 샌드박스에서 외부 시세 엔드포인트를 못 열어(프록시 403) 수집 코드를 배포 전 실측 못 함 — 실측은 Actions 로그로만. GAS 재붙여넣기가 겸이 손에 남는 한 'GAS 화면 = 늦은 판'이 반복된다(clasp 자동 배포 검토 필요).
요청→데이터: 토스 kr_quotes 를 peers_KR 유니버스 전체(1272)로 넓힐 수 있는지·호출 한도 회신 — 되면 heatmap_kr 1순위를 토스로 (req-data-d16cfea5)
