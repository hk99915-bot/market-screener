# 유지보수 독립 검수 — 검수 적체 8건 (코드·화면·인프라)

기준 2026-10-26 19:50 KST · 출처 ops/board.json · 검수인 유지보수(독립, 직접 수정 없음)

- **What**: 검수 8건 직접 실행 — 완료 2·조건부 6·반려 0
  - pytest 12파일 전부 통과, ui_smoke --only 5종 390·1300px 라이트·다크 결함 0
- **So What**: 코드·화면 결함 없음, 남은 것은 문서 정정 1·관찰 기간 1·외부 조건 4(키·설치·실토큰·US 장)
  - 유의: 다크는 color_scheme 강제 래퍼로 확인(ui_smoke 기본 미포함), Pages Source 전환 여부 미확인(API 403)
- **Now What**: 조건부 6건 요청 장부 접수(아래 표 req-id) / 담당 데스크 / 각 마감
  - 뒤집힐 조건: 조건 충족 회신 시 담당이 완료, 미회신 마감 경과 시 watchdog P1 승격

## 건별 판정

| id | 실행 확인 | 판정 | 남은 것 · 요청 |
|---|---|---|---|
| my-tab-ledger-compare | check_my_ledger 라이트·다크 OK, test_my_backup 통과 | ⚠ 조건부 | B-16 정정 문구 미반영(ops/README.md:96·pb HANDOFF 113행 ❓) · req-dev-333106f2 |
| tg-pick-buttons | 이슈 #14(10/22)·#16(10/23) 본문 '(텔레그램 버튼)' = TelegramHook.gs:231 경로, pick.yml run success·결과 댓글, test_tg_pick_buttons 통과 | ✅ 완료 | 실제 버튼 클릭→pick 이슈 기록 확인 |
| uxui-quant | check_research_board 390(첫 화면 하단 775px)·1300 라이트·다크 OK, test_research_board 통과 | ⚠ 조건부 | 1주 관찰(10/21~28) 미종료 — research_pipeline.json 커밋 1회(검증 2319da02), 퀀트 0 · req-uxui-c742b844 |
| ponytail-fixes | test_merge_decisions·test_data_branch·test_events_valid 통과, pages.yml paths-ignore 6종·team.yml cron 17분 파싱 OK, 감사 회신 통과(req-audit-45c91678 done) | ✅ 완료 | #6 2단계(main KR 제거)는 별건 보류, Pages Source 전환 미확인(API 403) |
| dispatch-redundancy | test_dispatch·test_watchdog 통과, heartbeat.yml cron 13·43분 장중 OK | ⚠ 조건부 | 실행 불가 — live.json dispatcher_heartbeat 없음(노트북 미설치, 겸이 가이드 ⑧) · req-dev-b8bc0009 |
| intraday-bar | KR 78회 갱신(09:00 LIVE~15:26), 15:37 CLOSE 잠정, 16:47 report KR EOD 교체(000020 OHLCV 일치), test_intraday_last 통과 | ⚠ 조건부 | 실행 불가 — US 15분 미관측(검수 시점 개장 전) · req-dev-34d785aa |
| tue-realestate-drill | fb7df209·3355a903 — check_re_drill·check_re_zoom 390 터치·1300·수집 전, 다크 스샷(구→동 확대·한강) OK, pytest realestate·coords·geo_zoom 통과 | ⚠ 조건부 | 실행 불가 — 단지 점: realestate_coords.json pts 0건(VWORLD_KEY 미등록) · 보드 files [] · req-realestate-f99b5f73 |
| realestate-private-viewer | 5528ed3e check_re_private 라이트·다크 OK(잠금·호출 0·이스케이프·404), 공개 저장소 비공개 사본 0 | ⚠ 조건부 | 실행 불가 — 실토큰 열람은 겸이 브라우저 전용 · req-front-4ca0eec3 |

## 근거 데이터 발췌
- pytest: test_dispatch·intraday_last·merge_decisions·my_backup·realestate·realestate_coords·realestate_geo_zoom·research_board·tg_pick_buttons·watchdog·data_branch·team_run·events_valid — 실패 0
- ui_smoke --only: check_my_ledger·check_research_board·check_re_private·check_re_drill·check_re_zoom — 라이트·다크 모두 OK

## 원본
- ops/board.json · docs/desk_kb/rounds/_requests.json · reports/intraday_last.json · reports/realestate_coords.json · .github/workflows/{heartbeat,pages,team,pick}.yml
