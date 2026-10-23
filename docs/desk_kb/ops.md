# 운영 데스크 KB

운영 = 여러 에이전트가 한 저장소를 동시에 고치는 환경의 **보드·잠금·예약·수집** 담당. 판단이 흐르는 길을 관리한다. 개인 보유·금액 없음.
(2026-10-23 교육 정리: 10/17 기준 슬롯표 2개(37줄)는 원본 `docs/schedule_table.md`(`python scripts/slot_guard.py --table` 재생성)와 중복·노후라 삭제 — 원문 git 이력.)

## 성격·성향
- **한 줄:** 규칙을 전부 읽고 그중 몇 개가 자동 확인되는지 세는 점검자. 알림 피로·잠금 경합 같은 운영 비용을 먼저 본다.
- **맹점:** 브리프의 필드 이름을 검증기 확인 전에 따르려 함(복기 10/17). **긴장:** ↔개발 — 화면 파일 잠금 경합. 원본 [PERSONAS.md#ops](PERSONAS.md#ops)(요약, 연기 지시 아님).

## 정의
- **라운드**: LOOP.md 1~8, 파일 `docs/desk_kb/rounds/YYYY-MM-DD/<desk>.md`, 마지막 줄 `요청→<데스크>: …`. 현업급 기준은 STANDARD.md(라운드 파일 40줄 상한).
- **요청 장부** `docs/desk_kb/rounds/_requests.json`: `scripts/ask.py`(추가·`--reply`·`--close`) + 라운드 파일 `처리→` 줄. **요청일부터 2영업일(KR 휴장 제외)** 미처리 → 보드 P1 승격(`round_collect.promotions` 한 곳).
- **라운드 표**: `scripts/round_collect.py` 만 `_scoreboard.md` 에 적는다(손 기입 금지·중복 방지). 감사 열 = `reports/audit/<date>.json` 치명/중/경.
- **슬롯**: (워크플로·작업 키·KST·요일). 모드는 시각이 아니라 **어느 cron 이 울렸나**로 정한다. 산출물 하나 = 실행 주체 하나 — GAS 주 실행, GitHub cron 은 +12분 대기 후 대행(`scripts/slot_guard.py`, 표 `docs/schedule_table.md`, 검사 `tests/test_schedule_single.py`).

## 알림 원칙
- 텔레그램 슬롯 목록의 원본은 `docs/schedule_table.md`. 소리는 결재 #9 의 3종 + 신선도 ⛔ 뿐(kb 개발 정의).
- 예약이 150분 넘게 밀리면 skip, GAS 가 이미 dispatch 했으면 늦은 GitHub 예약은 skip(중복 방지). 순서 의존 슬롯(07:10 valuation 은 06:52 screen_us 뒤)은 표에 의존 표기.

## 보드 운영
- 원본 `ops/board.json`, 판 `ops/BOARD.md`(`python3 scripts/board.py`). 필드 owner(담당 이름)·priority P0~P3·status(대기/진행/검수/보류/완료)·started·due·repo·files·depends_on·notes — 코드 FIELDS 가 진실, 검증 `--check`.
- 잠금: 공유 파일(ops/LOCKS.md 표)만, 파일 단위, 작은 커밋 즉시 푸시. 남의 잠금 안 지움.
- 라운드 수집: `round_collect.py --date D`(드라이런) → 확인 → `--apply` → `board.py --check` → 커밋. 전 데스크 라운드 파일 뒤(23:47 ops 전).

## watchdog (10/21 PM 안 B·E)
- `scripts/watchdog.py` — ops.yml 00:07 KST `--apply --send`. 감지: 데이터 0건/실패 · 신선도 · 토스 live.json · 보드 마감 초과 · 대기 3일+ · 요청 2영업일 미처리 → `reports/watchdog.json`, 보드 `escalated`(⏫), 비작업 감지는 `wd-*` P1(해소 시 자동 완료), 텔레그램 하루 1통.

## 현업 vs 교과서
- `[규정]` GitHub Docs "Events that trigger workflows › schedule": 예약은 부하 시간대에 지연·누락, **매시 정각이 가장 밀림**, 최소 간격 5분 → 우리 cron 이 :52·:47 비정각인 이유. `[경험]` 누락은 남는다 → GAS 이중화, 중복은 '먼저 온 쪽이 이김'.

## 흔한 오해
- "요청은 적으면 처리된 것" → 대상 데스크의 `처리→` 줄 또는 `--close` 가 있어야 닫힌다.

## 복기
- 2026-10-17 · 브리프의 보드 필드 목록(`desk`)과 `board.py` 검증기(`owner`)가 달랐는데 처음엔 브리프를 그대로 쓰려 했다 → 검증기가 진실이다 → 다음부터 보드 필드는 코드(FIELDS)를 먼저 보고 쓴다.

## 출처
- GitHub Docs, "Events that trigger workflows — schedule" `[규정]` · docs/desk_kb/LOOP.md · ops/LOCKS.md · ops/README.md · docs/schedule_table.md `[자체 규약]`

## 10년차 기준 (2026-10-23 교육)
- 체크리스트: ① 변경관리 — 운영 영향 변경은 요청·승인·롤백 계획·사후 검토 4단 `[교과서-B: ITIL 4 Change Enablement]` [확인 필요: ITIL 4 용어 원문, 2026-10-30] ② 런북: 알림마다 '누가·무슨 명령으로 복구'가 붙어야 알림이다(`ops/freshness.json` fix 열 관행) `[교과서-B: Google SRE 온콜]` ③ 알림 예산 — 소리 알림 수·오탐률을 월 1회 세고, 1개 추가 시 1개 삭제·병합안 동반 `[현업 관행: 알림 피로 관리]`
- 격차: 복기 마지막 10/17(6일 공백)·감사 경5 — 장부 open+promoted 49건 중 데이터 19·개발 9 쏠림(rounds/_requests.json)을 watchdog 은 승격만 하고 재분배·WIP 경고는 없음.
- 드릴: _requests.json 에서 promoted(=2영업일 초과) 27건이 쌓였다. 운영이 오늘 할 일 1개는? **답:** 승격을 더 하는 게 아니라 담당별 WIP 표(open·promoted·가장 오래된 날짜)를 watchdog 메시지 1줄로 내고, 데이터·개발에 '신규 접수 중단·오래된 순 처리' 요청을 장부로 보낸다. 결정(재배정)은 PB·겸이.
