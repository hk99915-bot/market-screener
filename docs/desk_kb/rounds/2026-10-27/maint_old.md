# 낡은 산출물 old/ 정리 — 유지보수 (2026-10-27 아침, 겸이 "old 수정")
기준: 2영업일 넘었고 더 새 버전이 있는 것 · 경로를 읽는 코드·워크플로·화면(glob 포함)이 있으면 이동 안 함 · rounds 는 이동 대신 정정 한 줄 · data/ 미접촉. 개인 금액 없음.

- **What**: 이동 2건 · 정정 표시 2건 · 보류(참조 있음) 11건. pb-private old 후보 14건(경로만, PB 처리).
- **So What**: 현재값처럼 남아 있던 건 '구속 스트레스 −15.17%(10/22)' 두 문서 — 최신 −15.28%(10/26 19:51)로 정정 표시. reports/studies·valuation_notes·audit 는 스크립트가 폴더째 glob(scorecard_week·trial_log·research_board·entry_why·team_stats)이라 옮기면 화면에서 빠짐 → 전부 보류.
- **Now What**: 보류 중 화면에 낡은 값이 그대로 뜨는 2건(battle_daily 10/19·isa_lab_returns asof 10/15)은 거짓 표시(#2-4) 후보 — 다음 점검에서 화면 기준일 표기 확인 후 개발 장부 / 유지보수 / 10/28.

| 구분 | 경로 | 대체본·사유 |
|---|---|---|
| 이동 | docs/terminal_audit_2026-10-19_gpt.md → docs/old/ | 대체: docs/uxui/2026-10-23_terminal_audit.md·2026-10-24_recheck.md · 참조 0 |
| 이동 | docs/cleanup_proposal_2026-10-18.md → docs/old/ | 10/16 기준 용량·건수, 대체: docs/refactor_plan_2026-10-18.md · 코드 참조 0(audit 이력만) |
| 정정 | rounds/2026-10-26/event_posrisk.md | −15.17%·−14.68% → −15.28% (pb-private risk/frm.json 10/26 19:51) |
| 정정 | rounds/2026-10-22-hf-frm-debate.md | '현재 −15.17%'·'약 −14.1%' → −15.28% |
| 보류 | reports/studies/2026-10-24_trend_events.json | rerun_us666 가 최신 · trend_discovery.py·entry_why.py·테스트 참조 + studies glob |
| 보류 | reports/battle_daily.json · reports/isa_lab_returns.json | index.html·tab_duel·tab_isalab 이 읽음 |
| 보류 | reports/flowq/*.json(asof 10/16) · reports/views/jiang_predictions.json | flowq.yml 출력 경로 · public_reports.py |
| 보류 | reports/uxui/2026-10-21_quant_tabs.md · docs/uxui/2026-10-23_terminal_audit.md·_recheck.md | ops/board.json 근거 경로 |
| 보류 | docs/valuation_notes/2026-10-17_realestate_longview.md | 대체 docs/realestate/2026-10-24_long_view.md · entry_why glob·views/realestate.json |
| 보류 | docs/refactor_plan_2026-10-18.md · docs/integrity_dev_plan_2026-10-17.md | pages.yml · rules_status.py |
| 보류 | reports/ 날짜 시계열(daily·signals·anomalies·daily_hist·english·idea_tracking·audit) | retention.py·화면이 폴더째 읽는 이력 — 대체본 아님 |

pb-private old 후보(읽기만, PB 처리): analysis/2026-10-16-frm · analysis/2026-10-16-views · analysis/2026-10-16-signals · analysis/2026-10-18-weekly · scorecard/week_2026-W42.md · lab/cases_2026-10-17.csv · lab/cases_2026-10-17.md · ops/PLAN_2026-10-16.md(테스트 참조 — 확인 필요) · ops/tech_review_2026-10-15.md · ops/rule_proposals_2026-10-18.md · ops/integrity_fixes_2026-10-17.md · realestate/seoul_midtier_views_2026-10-25.md · theses/2026-10-16_semis.md · analysis/2026-10-26-cash-commodity/event_posrisk_private.md(−15.17% 잔존 — 정정 표시 후보). analysis/index.json·latest.json 이 폴더를 나열하는지 이동 전 확인.
