# dev 라운드1 — 2026-10-17 (STANDARD.md 적용)

## 1. 읽기
LOOP·README·STANDARD·_scoreboard(라운드 표 빈 칸)·ops/LOCKS·보드 개발 태스크 11건(10/17 ops/board.json: repo-cleanup P0 대기, tests-pytest·dotplot·index-split 검수)·피어 데이터 KB+라운드 파일(retention.py 요청). 자기 KB 없어 `docs/desk_kb/dev.md` 신설.

## 2. 배우기 1건
텔레그램 Bot API `sendMessage.disable_notification`(Boolean) = 소리·진동 없이 전달, 메시지 상한 4,096자 [규정-공식문서 core.telegram.org/bots/api, 확인 필요: 원문 링크 재확인 → 10/20 라운드2까지]. 우리 코드는 이 필드를 보낸 적이 없어 10/17 이전 알림 전부가 소리였다(screener/report.py 10/17 코드).

## 3. 고치기 1건 — 결재 #9 '⛔만 소리'
- 변경: `screener/report.py send_telegram(text, *, disable_notification=True)` 기본 무음 + `loud(text)`(⛔/⚡ 포함 여부). 호출부 5곳 수정, 나머지 17곳은 기본값(무음).
- 테스트: `tests/test_telegram_silent.py` 7건(기본 무음·명시 소리·3,800자 분할 시 플래그 유지·loud 판정·규정 알림 ⛔ 조건부·⚡ 급락·14:25 반등일). 전체 `pytest tests/ -q` 통과(10/17 185건).
- 롤백: `send_telegram` 기본값을 `False` 로 바꾸면 10/17 이전(전부 소리)과 동일. 호출부는 그대로 둬도 됨.
- 영향 범위 [운영]: briefing.yml 전 모드·pick.yml(대결)·lab.yml(성적표)·health.yml 의 텔레그램 알림 소리. 스케줄·시크릿 변경 없음.
- 결론: 10/20(월) 첫 거래일에 14:25 반등일·16:20 규정 알림 소리 여부를 오너가 확인 → 무음이어야 할 브리핑이 울리거나 ⛔ 가 안 울리면 뒤집음(개발, 10/20 22:00 까지). 신뢰도 상(단위 테스트가 payload 직접 확인).
- 반대 근거: `events.py` 서킷·급락 경보(🚨)는 ⛔/⚡ 가 아니라 무음이 됐는데, 실무상 서킷은 소리가 맞다는 반론 가능 — 결재 문구 밖이라 코드 안 바꾸고 오너 결정 대기.

### 호출부 분류표 (grep send_telegram, 10/17)
| 호출부 | 알림 | 소리 | 근거 |
|---|---|---|---|
| rebound.py run | 14:25 반등일 ✅/❌ | 소리(False 명시) | 집행 창 14:30~15:20 |
| alerts.py run | 📏 규정 알림(⛔ 손절 2일·터치 / ⚠️ 1일·D-n·발동선) | ⛔ 포함 때만 | ⛔=즉시 집행 |
| alerts.py crash_check | ⚡ 급락일 종가 매수 신호 | 소리(False 명시) | 15:20 동시호가 전 |
| pb.py send · duel.py record_pb | PB 아침 점검 · 주문표 판정 | ⛔ 포함 때만 | 한도 도달·거부만 |
| main.py 127·129·467·468·600·601 · briefings.py 170·340·394·433·517·522 · duel.py 115·221 · dotplot.py 570 · events.py 147 · health.py 162 · valuation_daily.py 489 · study_daily.py 172 · scripts/scorecard_week.py 400 | 스크리너·운용회의·브리핑·대결·점도표·이벤트·점검·밸류·스터디·성적표 | 무음(기본) | 정보성 |

## 4. 피어 1건 (→ 데이터)
- retention.py 설계 의견: ops.yml 매일 1회 드라이런(목록을 `reports/logs/retention_YYYY-MM-DD.json` 에 커밋, 삭제 0건), `--apply` 는 수동 `workflow_dispatch` 입력 `apply=true` 로만, 그리고 삭제 전 `git ls-files` 추적 파일만 대상(미추적은 건드리지 않음). 승인 경로 = 드라이런 로그를 오너가 본 뒤 dispatch. 초안은 데이터가 쓰고 테스트·워크플로 연결은 개발(라운드2).
- 반대: 반등일 판정이 `live.kr_naver()` KOSPI `chg` 하나로 `prev=last/(1+chg)` 역산 — 네이버 분모가 KRX 확정 전일 종가와 같은지 데이터 KB 에 없다. 어긋나면 14:25 알림이 소리까지 내며 틀린다.

## 5. 복기 1건
틀림: 공유 체크아웃을 내 것으로 여기고 작업, `git diff --stat` 에 남의 bonds·ticket·duel 변경이 섞여 있었다 → 왜: "12개 동시 push" 를 원격 경쟁으로만 읽음 → 다음부터: 편집 전 `git status -s`, 커밋은 내 파일·hunk 만, `git add -A` 금지.

VOC: 외부망(core.telegram.org) 차단으로 공식 문서 원문을 못 열었고, 공유 체크아웃이라 `git pull --rebase` 가 남의 미커밋 변경에 막힌다(--autostash 로 우회).
요청→데이터: 네이버 KOSPI `chg` 분모(전일 종가) 정의 1줄 + 반등일용 KRX 확정 전일 종가 필드 제공 여부 회신, retention.py 초안 때 위 설계 3조건 반영.
현재 상태: ① send_telegram 기본 무음·호출부 5곳 분류 완료, 테스트 7건 통과. ② events.py 🚨 소리 여부는 오너 결정 대기(코드 무변경). ③ retention.py 는 미착수 — 데이터 초안 후 개발이 테스트·ops.yml 연결.
