<!-- short: 범용판 이전 시험, 막힘 7 -->
<!-- oneliner: 3,433개 옮김·범용판 pytest 0 실패 · 금액 review 7건(뉴스·시장 문맥, 감사 판정 대기) -->
# 이전 스크립트 결과 — migrate_v1 (원본 56715ffa7)

<!-- 자동 생성: python3 scripts/migrate_v1.py --report … — 값은 출력하지 않음(숫자는 9로 가림) -->

## 요약
- 추적 파일 4243개 → 범용판 3433 · 내부판 전용 627 · 개인 흔적 제외 178 · 보관 5
- A 금지 경로·비밀 파일: 통과(0건)
- B 금액·개인(비공개 지문 사용 — 개수·값 비공개): review 7건 → **막힘** · 그 밖 분류 169건(규정·시장·예시 등 허용)
- C 이름·호칭('겸이'·'누나'·'사담') 줄: 637 — 막지 않음(인벤토리 §6, 11/12 이후 문구 정리)
- D 제외 경로를 가리키는 범용판 파일: 151개 — 범용판에서 404·테스트 실패 후보
- 쓰기: 3433개 파일(index.html = 범용판 빌드) → `snap/`
- pytest(범용판 트리): 종료 0 · 실패 파일 0개

## 판별 건수(최상위 경로)
| 경로 | 범 | 내 | 제외(개인) | 보관 |
|---|---|---|---|---|
| `(루트)` | 6 | 1 | 0 | 0 |
| `.claude` | 0 | 70 | 0 | 0 |
| `.githooks` | 1 | 0 | 0 | 0 |
| `.github` | 25 | 8 | 0 | 5 |
| `apps-script` | 23 | 0 | 0 | 0 |
| `assets` | 27 | 0 | 68 | 0 |
| `content` | 0 | 52 | 0 | 0 |
| `data` | 392 | 0 | 0 | 0 |
| `docs` | 36 | 323 | 39 | 0 |
| `notes` | 0 | 1 | 0 | 0 |
| `ops` | 2 | 7 | 3 | 0 |
| `reports` | 2453 | 139 | 68 | 0 |
| `screener` | 121 | 0 | 0 | 0 |
| `scripts` | 116 | 0 | 0 | 0 |
| `tests` | 190 | 24 | 0 | 0 |
| `tools` | 25 | 0 | 0 | 0 |
| `universe` | 16 | 0 | 0 | 0 |
| `views` | 0 | 2 | 0 | 0 |

## 제외 규칙별 건수
| 판 | 근거 | 파일 |
|---|---|---|
| 내 | §1 내부판 워크플로 8 | 8 |
| 내 | §3 개인·데스크 산출 | 139 |
| 내 | §3 내부 문서 | 34 |
| 내 | §3 내부 문서(개인 규칙·결재·이전 계획) | 9 |
| 내 | §3 데스크 KB·라운드·결재 | 280 |
| 내 | §3 데스크 스킬 | 70 |
| 내 | §3 보드·팀·개인 장치 | 7 |
| 내 | §3 뷰 등록부·연구 매뉴얼 | 3 |
| 내 | §3 학습·드릴(겸이 인용) | 52 |
| 내 | 내부 기능 테스트(대상 파일 내부판) | 24 |
| 내 | 세션 규칙(데스크 루프) | 1 |
| 보관 | §1 연구 일회성(옮기지 않음) | 5 |
| 제외(개인) | §3-1 evidence 2차 누출 | 9 |
| 제외(개인) | §3-1 개인 결재·모의 북 | 6 |
| 제외(개인) | §3-1 개인 매매 행동 | 3 |
| 제외(개인) | §3-1 개인 목표 문서 | 1 |
| 제외(개인) | §3-1 애널리스트 이메일 이력 | 52 |
| 제외(개인) | §3-1 위 복사본 이력 | 1 |
| 제외(개인) | §3-1 이력에 개인 원값(L-1·L-3·L-7) | 1 |
| 제외(개인) | §3-1 캐릭터 설정(PB 11/1) | 105 |

## A 금지 경로
- 0건

## B 금액·개인 — 분류별
| 종류 | 분류 | 건 |
|---|---|---|
| account | date | 64 |
| account | self | 2 |
| account | synthetic | 2 |
| amount | edu_mock | 47 |
| amount | market | 2 |
| amount | ref | 3 |
| amount | review | 7 |
| amount | synthetic | 18 |
| birth | self | 1 |
| ctx_amount | market | 6 |
| ctx_amount | self | 4 |
| ctx_amount | synthetic | 17 |
| qty_ctx | edu_mock | 2 |
| qty_ctx | market | 1 |

### review 7건(앞 25) — 위치만(미리보기는 콘솔에만: 공개 저장소 pre-push 금액 검사와 충돌 방지)
- `reports/research_views.json:1` amount/계좌
- `reports/views/analyst_cmdty.json:286` amount/내
- `reports/views/realestate.json:89` amount/내
- `reports/views/realestate.json:89` amount/내
- `screener/sectors.py:12` amount/보유
- `scripts/replicate_qld_dca.py:109` amount/적립
- `scripts/study_laor_ib.py:334` amount/원금

## C 이름·호칭 줄 수(영역 상위)
| 영역 | 줄 |
|---|---|
| `index.html` | 61 |
| `reports/archive` | 44 |
| `reports/studies` | 34 |
| `reports/library.json` | 32 |
| `apps-script/tab_msgr.html` | 27 |
| `scripts/ui_smoke.py` | 23 |
| `docs/valuation_notes` | 21 |
| `tools/toss_md` | 14 |
| `docs/desk_kb` | 11 |
| `screener/duel.py` | 10 |
| `apps-script/tab_research.html` | 9 |
| `scripts/ask.py` | 9 |
| `.github/workflows` | 8 |
| `apps-script/Index.html` | 8 |
| `apps-script/tab_realestate.html` | 8 |
| `docs/toss_md_laptop_setup.md` | 8 |
| `reports/views` | 8 |
| `apps-script/tab_study.html` | 7 |
| `screener/dotplot.py` | 7 |
| `scripts/migrate_v1.py` | 7 |
| `scripts/msgr_feed.py` | 7 |
| `tests/test_dotplot.py` | 7 |
| `tests/test_watchdog.py` | 7 |
| `apps-script/tab_market.html` | 6 |
| `apps-script/tab_mkt_macro.html` | 6 |

## D 끊긴 참조 후보(파일 상위 25)
| 파일 | 참조(건) |
|---|---|
| `reports/library.json` | docs/desk_kb/STANDARD.md(9) · docs/desk_kb/rounds/2026-10-28/quant_profit_lock.md(4) · docs/desk_kb/rounds/2026-10-28/audit_compliance_peer_recheck(3) |
| `reports/archive/dotplot/2026-10-26.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/archive/dotplot/2026-10-27.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/archive/dotplot/2026-10-28.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/archive/dotplot/2026-10-29.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/archive/dotplot/2026-10-16.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/archive/dotplot/2026-10-19.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/archive/dotplot/2026-10-20.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/archive/dotplot/2026-10-21.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/archive/dotplot/2026-10-22.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/archive/dotplot/2026-10-23.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/archive/dotplot/2026-10-30.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `reports/dotplot.json` | reports/committee.json(28) · reports/committee_us.json(4) · reports/decisions.json(4) |
| `index.html` | reports/decisions.json(4) · reports/portfolios.json(3) · reports/committee.json(3) |
| `docs/study_spec.md` | content/study.json(3) · reports/study_progress.json(3) · content/study/quiz_bank.json(2) |
| `scripts/round_collect.py` | docs/desk_kb/rounds/(2) · ops/board.json(2) · ops/team.json(2) |
| `tests/test_migrate_v1.py` | docs/desk_kb/rounds/_requests.json(1) · reports/msgr_feed.md(1) · docs/desk_kb/OKR.md(1) |
| `apps-script/Code.gs` | reports/portfolios.json(1) · ops/research_pipeline.json(1) · ops/board.json(1) |
| `screener/dotplot.py` | reports/committee.json(4) · reports/decisions.json(2) · docs/desk_kb/rounds/(2) |
| `scripts/drill_grade.py` | content/drills/(5) · content/onboarding/(4) · docs/desk_kb/onboarding/(1) |
| `tests/test_slop_audit.py` | reports/msgr_feed.md(3) · docs/desk_kb/frm.md(2) · docs/desk_kb/rounds/_requests.json(2) |
| `scripts/build_pages.py` | reports/portfolios.json(1) · ops/board.json(1) · ops/team.json(1) |
| `tests/test_build_library.py` | docs/desk_kb/rounds/2026-10-31/quant_trend.md(3) · docs/desk_kb/rounds/2026-10-24/_xlearn_brief.md(1) · docs/desk_kb/rounds/2026-10-30/macro_gold.md(1) |
| `apps-script/tab_duel.html` | reports/decisions.json(2) · ops/renego.json(2) · reports/battle_scoreboard.json(2) |
| `apps-script/tab_system.html` | ops/board.json(3) · ops/locks.json(2) · ops/team.json(2) |

## 워크플로 메모
- .github/workflows/briefing.yml: 제외 경로 참조 reports/decisions.json
- .github/workflows/briefing.yml: 제외 경로 참조 reports/battle_scoreboard.json
- .github/workflows/data_store.yml: 제외 경로 참조 docs/desk_kb/dev.md
- .github/workflows/deriv_hist.yml: 제외 경로 참조 views/registry.json
- .github/workflows/health.yml: 제외 경로 참조 ops/team.json
- .github/workflows/library.yml: 제외 경로 참조 docs/desk_kb/rounds/
- .github/workflows/live.yml: 제외 경로 참조 reports/decisions.json
- .github/workflows/ops.yml: 제외 경로 참조 ops/runs.json
- .github/workflows/ops.yml: 제외 경로 참조 ops/board.json
- .github/workflows/ops.yml: 제외 경로 참조 docs/desk_kb/rounds/_requests.json
- .github/workflows/ops.yml: 제외 경로 참조 ops/research_pipeline.json
- .github/workflows/ops.yml: 제외 경로 참조 ops/team.json
- .github/workflows/pages.yml: 제외 경로 참조 ops/team.json
- .github/workflows/pages.yml: 제외 경로 참조 ops/locks.json

종료코드 1 (막힘 — 위 A·B 를 고친 뒤 다시)

## 개발 해석 (수기 · 11/1 · 검증전)
- **B review 7건**: 미리보기상 뉴스 본문(증권사 정보 유출 기사)·금 시세 메모·정비사업 기사 요약·섹터 전환 비율·연구 스크립트 docstring 예시 — 개인 금액 문맥으로 보이지 않음. 판정은 감사(req-audit-a7678089). 오탐이면 감사가 허용 JSON 을 만들어 `--allow` 로 넘긴다 → 막힘 0 이 11/6 스냅샷 조건(보드 mig-v1-snapshot).
- **11/6 전에 막아야 할 재유입 경로(중요)**: 워크플로 메모의 `briefing.yml`·`live.yml` 이 `reports/decisions.json`·`battle_scoreboard.json` 을 커밋한다 — 범용판에서 그대로 돌면 §3-1 제외 파일이 새 공개 저장소에 다시 생긴다. 개발 2차(mig-v1-dev-b)에서 `.edition=public` 이면 해당 경로를 커밋하지 않게(또는 pre-push 범용판 금지 경로 목록) 막는다. `ops.yml`·`health.yml`·`pages.yml`·`library.yml` 의 ops/·rounds 참조도 같은 묶음(ops.yml 분할은 11/12 이후 계획대로).
- **D 끊긴 참조**: 대부분 데이터 안 문자열(dotplot 아카이브가 원본 경로를 적어 둔 것)·내부 스크립트(round_collect·drill_grade) — 화면 404 후보는 `reports/library.json`(rounds 문서 링크) 하나. 서고 색인 rounds 제외는 개발 2차.
- **C 호칭 637줄**: 개인정보 아님 — 인벤토리 §6 대로 11/12 이후 문구 정리(11/7 전환을 막지 않음).
- 재현: `python3 scripts/migrate_v1.py --apply --dest <빈 폴더> --pytest --private-dir <pb-private> --report docs/refactor_v1_migrate_dryrun.md`
