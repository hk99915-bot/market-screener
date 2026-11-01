<!-- short: 보드 정리 11/1 밤 -->
<!-- oneliner: 열린 108→105 · 하루 마감 최대 6→5 · 중복 0 · 담당 이름 이미 통일 — 남은 건 결재와 실제 일 -->

# 운영 — 작업 보드 정리 (2026-11-01 21시대 KST)

겸이 11/1 21:0x 「운영보드에 쌓인거 싹한번 정리」. 변경은 `scripts/board.py`(--set·--due·--note)만, 규칙·한도·결재 내용 변경 없음. 커밋 df5cb7171·f506a274f.

## 전후 숫자 (ops/board.json 381건)
| 항목 | 전 | 후 |
|---|---|---|
| 완료 / 대기 / 보류 / 진행 / 검수 | 273 / 66 / 31 / 7 / 4 | 276 / 63 / 31 / 7 / 4 |
| 열린 작업(완료 아님) | 108 | 105 |
| 마감 지남(11/1 기준) | 0 (오늘 마감 1: leak-history-rewrite, 겸이 결정 대기라 손대지 않음) | 0 |
| 7일 넘게 '대기'(보드 첫 등록 ≤10/24, git 이력 기준) | 32 | 32 (완료한 3건은 10/28 뒤 등록분) |
| 중복(같은 제목) / 같은 파일 묶음 | 0 / 2쌍 | 0 / 2쌍(다른 일 — 아래) |
| 하루 마감 > 5건인 날 | 1 (11/09 6건) | 0 |
| 결재 대기(approval 필드, BOARD.md 기준) | 6 | 5 |

11/6~11/22 날짜별 마감: 전 11/09만 6, 나머지 매일 5 → 후 매일 5(11/06~11/22 17일 모두 5). 고정일(11/2·6·7·9·12·15·30)·depends_on 은 안 건드림.

## 한 일
- (a) 완료 3: `req-dev-34d785aa`(요청 장부 done 10/28) · `req-pb-350f1089`(장부 done 10/29, 22d79a7f5) · `freeman-okr`(결재 끝, OKR.md 상태 표기 a76ebe125).
- (b) 중복 0: 같은 제목 없음. 같은 파일 2쌍은 다른 일 — `macro-consensus-source`↔`pro-plan-round-scale`(뒤쪽 files 가 앞쪽 복사로 보여 PM 확인 메모), `live-resume-gap`↔`live-us-dst-march`. 이전 정리(11/01 PM)에서 `req-dev-516bf7e6`→`tradeplan-ui` 병합 이미 끝.
- (c) 보류 1: `live-us-dst-march` — 10/30 시작 cron 2개 상시로 3월 되돌림 사유 소멸.
- (d) 마감 1: `edu-home-track-2` 11/09→11/12(의존 없음).
- (e) 담당 이름: 열린·닫힌 381건 owner 29종 모두 정식 이름(피어리뷰·리스크·프론트 등) — 바꿀 것 0. owner 를 키로 쓰는 곳(바꾸지 않음, 목록만): `scripts/team_stats.py`(ALIASES·norm_owner — 피어→피어리뷰·FRM→리스크 등 별칭 흡수), `scripts/watchdog.py`(wd-* 작업 owner), `apps-script/tab_system.html`·`tab_msgr.html`(보드 담당 표시). 보조 필드 `desk` 는 212건 비어 있음 — FIELDS 밖이라 손대지 않음.

## 남은 것 (운영이 판정하지 않음)
- 결재 대기 5건 중 3건(`toss-md-pilot`·`dispatch-redundancy`·`user-krx-openapi-key`)은 11/1 결재로 결정이 끝났다는 PB 노트가 있음 — approval 필드 정리는 PB 확인 뒤. 결재 목록 상세는 비공개 저장소 analysis/2026-11-01-monthly/ops_pending_approvals.md.
- 7일+ 대기 32건 중 개발·데이터 쏠림은 그대로 — 재분배는 PM 소관.

VOC: board.py 에 files·depends_on 수정 옵션이 없어 잘못 복사된 files 를 못 고침.
요청→PM: `pro-plan-round-scale` files 확인, 7일+ 대기 32건 재분배 판단.
