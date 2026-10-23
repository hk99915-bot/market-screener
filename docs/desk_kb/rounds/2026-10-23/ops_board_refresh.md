# 운영 — 작업 보드 최신화 (10/24 00시대, 겸이 "이것도 다 최신화")

기준: `ops/board.json` main a391f778 → 이 커밋. 판정 규칙 = 터미널 SYSTEM 작업 보드 맨 위 줄(apps-script/tab_system.html 52행: 결재 = 미완료 중 담당 사용자/겸이 또는 제목·메모에 '겸이 결재/결재 대기/결재 필요', 늦은 일 = 미완료 중 due < 오늘). 근거 확인 = main 커밋·산출물 존재·갱신 시각, 전체 pytest 통과(a391f778), Actions 실행 기록(gh run list). 추측으로 닫은 건 없음 — 못 확인한 건 데스크 확인 요청으로 넘김.

## 전후 숫자 (10/24 기준)
| | 결재 대기 | 늦은 일 | 진행 | 검수 | 대기 | 보류 | 완료 | 전체 |
|---|---|---|---|---|---|---|---|---|
| 전 | 4 | 68 | 9 | 65 | 93 | 2 | 55 | 224 |
| 후 | 8 | 1 | 7 | 11 | 74 | 3 | 142 | 237 |

- 남은 늦은 일 1 = `ra-sec-coverage` — PB 가 10/24 애널에 배정해 애널 작업 중(담당만 데이터→애널, 상태·마감은 애널이 바꿈).
- 결재가 4→8로 는 것은 10/23 밤 22시 규칙으로 미룬 결재 6건을 보드에 올렸기 때문(아래). 기존 4건 중 실제 결재 대상은 2건(toss-sectors 전환·부동산 키)뿐이었고, uxui-audit·hf-alphabook 은 메모 문구 때문에 잡힌 것 → 둘 다 완료.

## 닫은 것 81건 (완료 78 · 취소 3)
- 검수→완료 54: 파생 7(deriv-hist·derivs-validate·deriv-insight 등), 운용회의·추적 9(cmt-v2·us-committee-v2·tradeplan·signal-tracking·battle-scoreboard 등), 데이터·연구 9(px-adjust-unify·bt-exec-lag·semis-cap-study·lab-p1·study-hollzzak·sec-ytd-bug 등), 화면 10(index-split·macro-tab·bonds-summary·macro-popup-live·signal-scorecard 등), 운영 도구 8(watchdog-b·requests-e·pre-push-guard·repo-size-stage1·toss-md-publish 등), 기타. 근거 커밋·산출물은 각 작업 메모 '10/24 운영 점검' 줄.
- 진행→완료 2: uxui-audit(진단서 c59326fd·재진단 a7e10687 → 구현 7e1c2b3c), hf-alphabook(1차 구현·채점 규약 완료, US EPS 이력은 req-data-751d13c7 로 추적).
- 대기→완료 4: gas-sched-verify(10/23 GAS dispatch `briefing [reports] commit=true` 도착, cron 대행 건너뜀), gpt-terminal-followup-1019(freshness 10/23 22:55 late 0), secret-missing-warning(alerts.secret_health), user-cooldown-log(ops/cooldown.json + 읽기 경로).
- 승격 요청 18: 요청 장부에서 이미 done 인 req-* 17건 + req-ops-6cec6000(아래 처리).
- 취소 3: daily-duel-collapse(Top10 #5 대결 1줄로 대체), repo-cleanup(repo-size-stage1·데이터 브랜치 1단계로 대체, 이력 재작성은 별도 결재), my-rules-secret(10/21 결정 = 의도된 비활성).
- board.py 상태값에 '취소'가 없어 선례대로 `완료` + 메모 머리 `[취소·닫힘]`.

## 검수 유지 9 (남은 것 한 줄은 메모)
kr-accum(2022 백필 확인→스터디 재실행, 10/31) · tg-pick-buttons(실제 버튼 클릭 1회, 10/31) · toss-sectors(전환 결재만 남음) · my-tab-ledger-compare(B-16 문구, 10/28) · dispatch-redundancy(노트북 dispatcher 하트비트 없음, 10/31) · us-eod-toss(toss_eod_check.json 미생성, 10/28) · uxui-quant(1주 관찰, 10/28) · uxui-top10-impl(UXUI 재측정, 10/27) · quiz-key-balance(대기→검수: 셔플 78b05b61 끝, why 문장 남음, 10/31).

## 새 마감 12
dotplot-neutral-rule 10/20→10/31(미착수) · pbview-amount-wording 10/20→10/30(decisions.json pb_view 원화 금액 문장 남음) · ra-etf-holdings-full 10/23→10/31 · 10/24 마감인데 착수 흔적 없는 9건(sim-oos·etf-pdf-nav·audit-1017-minor·live-resume-gap·top3-sector-cap·ra-sector-frames·audit-ideas-basis·tradeplan-ui·guard-rest) → 10/31. tradeplan-ui 와 req-dev-516bf7e6 은 같은 일(중복) — tradeplan-ui 로 추적.

## 데스크로 넘긴 것 (ask.py, 회신 마감 10/28, 보드 '확인 요청 중')
- 데이터 `req-data-3df3066a`: mu-revenue-tag(valuation.json MU 아직 '매출 항목 없음') · close-swap-verify.
- PB `req-pb-584233b1`: 비공개 rebalance-support·sunday-review·cio-memo·frm-audit·alpha-baseline-fix·integrity-p0-3(+p0-2·p0-5·hook-per-model-rows 상태) · memproxy-line.
- 유지보수 `req-maint-baec0edf`: gas-repaste — clasp 자동 배포가 예약기 프로젝트까지 덮는지.
- 감사 `req-audit-45c91678`: ponytail-fixes 확인.
- 피어리뷰 `req-peer-fb30b165`: peer-review-valuation·peer-bear-view(산출물 0) 계속/폐기.
- 교육 `req-edu-23239703`: edu-dev-handoff 남은 스펙.

## 겸이 결재 목록 (보드 작업 id · 07시 이후)
1. `appr-frm-agenda-a` 겸이 결재 필요: FRM 안건 A — 구속 스트레스 시나리오를 7월 실측(−15.3%, 바닥 집행 시 −9.8%)으로 교체할까?
2. `appr-uxui-top10-next` 겸이 결재 필요: UXUI Top10 후속 — 남은 3건(💬 가림·표 첫 열 고정·글자 4단계)을 다음 묶음으로 진행할까?
3. `appr-pick-gate-start` 겸이 결재 필요: 대결 '나' 게이트 ①② 적용 시작을 10/23 19:00 제출분부터로 할까, 월요일부터로 할까?
4. `appr-hf-independence` 겸이 결재 필요: HF 세 북 독립성 규칙 3개 채택할까?
5. `appr-alloc-1115` 겸이 결재 필요: 자산배분 11/15 ISA 안건 Q1~Q4(비중 변경 0) 권고대로 갈까? (11/15)
6. `appr-edu-g1-g4` 겸이 결재 필요: 교육 G1~G4 승인할까?
7. `appr-toss-sectors-switch` 겸이 결재 필요: 공식 비중 한도 섹터를 GICS/WICS 1종목1섹터로 전환할까?
8. `user-realestate-keys-1023` 겸이 결재 필요(보류 11/30): 부동산 데이터 키 3종 발급·등록할까?

## 오늘(10/23) 생긴 일 반영
있음: uxui-top10-impl(검수)·user-realestate-keys-1023(보류 11/30). 없어서 사후 등록(완료): duel-me-gate-1023(efab4721) · messenger-chat-1023(사내톡·사담·프로필) · study-export-1023(8e411c58) · commodities-geo-1023(98706a6a·1e8d9b23) · public-reports-summary-1023(0e155685) · realestate-tab-1023(0c56afa3).

## 담당(desk) 없음
미완료 작업 중 desk 칸 빈 것 66건 → 전부 지정(담당 데스크 = owner, ra-sector-frames·ra-house-scoreboard 는 산출물이 애널 쪽이라 애널). ra-sec-coverage 는 owner·desk 애널(PB 배정). 애매해서 PB 로 넘긴 건 0.

## 내 앞 요청
- `req-ops-6cec6000`(감사 D5) 처리·닫음: docs/schedule_table.md §1 에 '장중 루프 취소·재시작 절차' 1조(PB 승인·보드 노트에 사유+run id·가능하면 장 마감 뒤, 긴급 시 사후 1시간 안 기록). 매매 규칙·한도·등급이 아닌 운영 절차라 22시 규칙 대상 밖으로 판단 — 겸이·PB 가 규칙으로 보면 되돌림 1커밋.

VOC: 검수 65건 중 54건이 실제로 끝났는데 '확인 후 완료' 한 줄이 남아서 쌓였다. 검수 넣은 데스크가 확인 조건에 날짜를 같이 적어 주면 watchdog 이 자동으로 물어볼 수 있다.
요청→개발: watchdog 에 '검수 7일+ & 메모의 확인 조건 날짜 지남' 감지 1줄 추가 검토(마감 10/31)
