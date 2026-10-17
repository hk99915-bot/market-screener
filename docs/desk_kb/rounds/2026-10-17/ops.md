# 운영 라운드 1 — 2026-10-17

## 1. 읽기
LOOP.md·README.md·_scoreboard.md·ops/LOCKS.md·board.json(운영: ops-system 완료, rebound-alert 검수). 자기 KB 없어 신설(docs/desk_kb/ops.md). 피어 KB dev.md 는 아직 없음(개발 데스크 미작성) — 보드의 개발 작업 13건으로 대신 읽음.

## 2. 배우기
[규정] GitHub Docs "schedule" 이벤트: 예약은 고부하 때 지연·누락, 정각이 가장 밀림, 기본 브랜치 최신 커밋 기준. 우리 비정각 cron(:52·:47)·'cron 문자열로 모드 결정'·GAS 백업 예약기의 근거를 KB '현업 vs 교과서'에 적음.

## 3. 고치기
scripts/round_collect.py 신설: 라운드 파일 수집 → _scoreboard.md 라운드 표(라운드|데스크|배움|고침|피어|복기|요청수) 1줄씩, 요청 장부(_requests.json) + 2라운드 연속 미처리 → 보드 P1 승격(기본 드라이런, --apply). 테스트 tests/test_round_collect.py 5건. 실제 --apply 는 모든 데스크 파일이 끝난 뒤 코디네이터가.

## 4. 피어 (개발)
board.py 에 작업 추가 CLI(`--add JSON` 또는 `--promote`)가 없어 round_collect 가 board.json 을 직접 쓴다. 검증기(validate)만 공유 중 — 쓰기 경로가 둘이면 필드 드리프트 위험.

## 5. 복기
틀림: 브리프의 보드 필드명 `desk` 를 그대로 쓰려 함 → 왜: 검증기(`board.py` FIELDS)는 `owner` → 다음부터: 보드 필드는 코드를 먼저 보고 쓴다.

요청→개발: scripts/board.py 에 작업 추가 서브커맨드(`--add <json>`; validate 통과 시에만 기록) — round_collect.py 승격 경로가 이걸 타게 바꾸고 싶음
