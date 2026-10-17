# 운영 라운드 1 — 2026-10-17 (기준: docs/desk_kb/STANDARD.md)

## 1. 읽기
LOOP.md·README.md·STANDARD.md·_scoreboard.md·ops/LOCKS.md·ops/board.json(운영 담당 2건: ops-system 완료·rebound-alert 검수, 10/17 기준). 자기 KB 없어 신설(docs/desk_kb/ops.md). 피어 KB dev.md 는 시작 시점엔 없었고 라운드 중 개발 데스크가 작성함 — 보드의 개발 작업 13건(board.json, 10/17)으로 대신 읽음.

## 2. 배우기
[규정] GitHub Docs "Events that trigger workflows › schedule"(2026-10-17 열람): 예약은 고부하 때 지연·누락 가능, 정각이 가장 밀림, 최소 간격 5분, 기본 브랜치 최신 커밋 기준. → 우리 비정각 cron(:52·:47)·'cron 문자열로 모드 결정'·GAS 백업 예약기의 근거. 반대 근거: 비정각으로 옮겨도 누락은 0이 안 된다(ops/runs.json 지연 통계로 월 1회 확인, 신뢰도 중).

## 3. 고치기
scripts/round_collect.py 신설 — 라운드 파일 → _scoreboard.md 라운드 표(라운드|데스크|배움|고침|피어|복기|요청수|VOC|감사) + `### VOC <날짜>` 절 + 요청 장부(rounds/_requests.json) + 2라운드 연속 미처리 요청 → 보드 P1 '대기' 승격. 기본 드라이런, `--apply` 만 쓴다. 감사 열 = reports/audit/<date>.json(by_desk 또는 findings 형식)의 치명/중/경 건수, 없으면 —.
테스트: tests/test_round_collect.py 6건(파싱·표 멱등·VOC/감사 열·장부 2R 승격·응답으로 닫힘·run 드라이런/apply) 통과. 영향 범위: 워크플로·탭·알림 변화 없음(수동 실행 스크립트, 쓰는 파일 3개는 --apply 때만). 롤백: 파일 삭제 또는 커밋 revert; --apply 결과는 _scoreboard.md·_requests.json·board.json git revert.
드라이런 결과(10/17 21시대, 읽기만): 데스크 11 · 요청 11 · 응답 0 · VOC 있는 데스크 6. 실제 --apply 는 코디네이터가 모든 라운드 파일 완료 후.

## 4. 피어 (개발)
board.py 에 작업 추가 CLI 가 없어 round_collect 가 board.json 을 직접 쓴다(validate 만 공유). 쓰기 경로가 둘이면 필드 드리프트 위험 — 반대 근거: 승격은 라운드당 0~수 건이라 당장은 직접 쓰기로 충분(신뢰도 중).

## 5. 복기
틀림: 브리프의 보드 필드명 `desk` 를 그대로 쓰려 함 → 왜: 검증기(`board.py` FIELDS)는 `owner` → 다음부터: 보드 필드는 코드를 먼저 보고 쓴다.

## 현재 상태 (다음 사람 5분 인수)
1. round_collect.py 는 드라이런만 돌렸고 _scoreboard.md·_requests.json·board.json 은 미변경. 다음 행동: 운영(또는 PB)이 모든 데스크 라운드 파일 완료 확인 후 `python3 scripts/round_collect.py --date 2026-10-17 --apply` → `python3 scripts/board.py --check` → 커밋. 기한: 10/17 23:47 ops 워크플로 전.
2. 요청이 닫히려면 대상 데스크가 자기 라운드 파일에 `처리→<요청 데스크>: …` 를 써야 한다 — 이 규약은 LOOP.md 에 아직 없음(아래 요청). 2라운드(10/17→다음 라운드) 연속 미응답이면 자동 P1.
3. 감사 데스크 산출물 reports/audit/<date>.json 은 아직 없음(10/17) — 형식은 스크립트 docstring. 뒤집는 조건: 감사 데스크가 다른 형식을 내면 audit_counts() 한 함수만 고친다.

VOC: 감사 데스크 산출물 형식이 미정이라 감사 열은 2가지 형식을 추정해 받음 [확인 필요: 감사 데스크 형식, 다음 라운드까지]
요청→개발: scripts/board.py 에 작업 추가 서브커맨드(`--add <json>`, validate 통과 시에만 기록) — round_collect.py 승격 경로를 그쪽으로 옮기고 싶음
