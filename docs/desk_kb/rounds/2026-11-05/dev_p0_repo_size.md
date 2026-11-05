# 개발 P0 설계 — 새 저장소 용량: data-parquet-out · data-live-branch (11/5)

> 출처(작성 주체): 개발 데스크 서브에이전트 · 기준 origin/main `6c5272c5d`(11/5 09:13 KST) · 브랜치 `dev-p0-repo-size` · 겸이 11/4 18:28 「미루지말구 확실히」 결재
> 공개 저장소 — 파일 이름·개수·크기·시각만. 개인 금액·보유 없음.
> 장중 규칙: 15:40 전엔 설계·테스트만, main 머지는 15:40 이후. 이 문서의 '완료'는 worktree 브랜치 기준(main 미반영)이다.

## 0. 한눈에
| 항목 | 읽는 곳 | 쓰는 곳 | 오늘(장중) 한 것 | 15:40 이후 |
|---|---|---|---|---|
| data-parquet-out | 워크플로 3(fin·lab·hist)+자동 수집 3(fin·screener·briefing 누적 6개) · 수동 스크립트 약 30 | 연도 32개는 쓰는 곳 없음(불변) · 누적 6개는 fin·screener·briefing | 그룹 `small`·`hist_year`(opt-in) + 워크플로 6 + 추적 해제 준비 + 테스트, pytest 전체 통과(parquet 38개 없앤 트리에서) | ① 1/2 머지 → ② Actions bootstrap → ③ 2/2 머지 |
| data-live-branch | 화면 URL 5종·GAS 4·Pages 3·파이썬 35파일·스크립트 | 명시 6 워크플로 + `reports/` 통째 커밋 워크플로 약 20(freshness 부수) | `scripts/live_branch.py`(put·get·squash·check)+테스트 10개, 미연결 | 설계 승인 뒤 단계 A(병행) |

## 1. data-parquet-out
### 1.1 현황 (이미 된 것 / 남은 것)
- 10/21 stage1: 큰 11개(kr_prices·signals·fin/multi·full·hist/*_daily·flows/kr_inv_*)는 이미 릴리스 `data-latest` 전용, pb_call·pick·live·accum·briefing·fin·hist·lab·screener·us_accum·deriv_hist 가 `data_store.py pull`.
- 남은 git 추적 parquet **38개 / 약 164MB**: 연도 불변 32개(kr 16·us 16, 161MB) + 누적 6개(research·research_views·short_hist·dart·fin/us_quarterly·reports/us_eps_hist, 약 3MB). 전수 원천 = `scripts/parquet_inventory.py`.

### 1.2 읽는 곳 전수 (파일:행)
| 묶음 | 읽는 곳 | 받는 스텝(교체 후) |
|---|---|---|
| hist_year (kr_YYYY) | `screener/analysts.py:27` load_kr(hist_from) ← fin.yml:46 | fin.yml:46 `pull --groups all,hist_year` |
| 〃 | `screener/momentum.py:74` hist_from=0 ← fin.yml:58 | 〃 |
| 〃 | `screener/lab.py:130` hist_from=0 ← lab.yml:40 | lab.yml:36 `pull --groups all,hist_year` |
| hist_year (kr·us) | `scripts/build_hist.py:164,188` ← hist.yml:43 | hist.yml:37 `pull --groups all,hist_year` |
| hist_year 수동 연구 | study_us_long_sort:176 · study_us_accum:37 · study_exec_signal:208 · study_playbook_signals:44 · study_trend_rule:194,238 · study_fib_levels:32 · study_multiple_compression_2022:14,113 · study_chain_corr:35,157 · study_dotplot_tilt:43 · study_ict_hdj1:46 · study_us_r20_reversal:81 · study_bond_regime · study_profit_lock:49 · study_flow_streak_entry:37 · study_winner_ex_ante(2):29,52 · study_winner_regime:25 · study_hollzzak:239 · study_lab_p1:102 | 워크플로 없음 — 돌릴 때 `python scripts/data_store.py pull --groups hist_year` 1줄(dev.md 에 추가) |
| small research | `screener/dashboard.py:104`(screener·briefing) · `research_synthesis.py:402`(fin.yml:63·briefing.yml:139) · 쓰기 `research.py:31`(fin·screener·briefing) | 기본 pull(all)에 포함 — 변경 없음, 저장만 push `small` |
| small research_views | 쓰기 `research_views.py:33`(fin.yml:61) · 읽기 research_synthesis | fin.yml:73 push `fin,small` |
| small dart | 쓰기 `dart.py:27`(screener·briefing) · 읽기 `entry_why.py:85`·`prices.py:104`·`scripts/hf_ideas.py:312,405` | screener.yml:105·briefing.yml:160 push |
| small short_hist | `shorts.py:16`(screener·briefing 수집) | 〃 |
| small us_quarterly | 쓰기 `sec.py`(fin.yml) · 읽기 `scripts/build_company_links.py:36` | fin.yml push |
| small us_eps_hist | `screener/us_eps_hist.py:19` ← detail.py:432,481(US 상세→drivers, screener·briefing) | screener·briefing push |
| 읽는 곳 아닌 곳 | tests.yml 은 pull 안 함 → **parquet 없는 트리에서 pytest 전체 통과를 직접 확인**(§1.4) · pages·ops·health·heatmap·pick·pb_call 은 이 38개를 안 읽음 | — |

### 1.3 구현 (브랜치 `dev-p0-repo-size`, 커밋 2개 + 아래 live 1개)
1. `ea045ed03` **1/2** `scripts/data_store.py` 그룹 `small`(누적 6) · `hist_year`(연도 32, **OPT_IN** = `all` 에서 제외 → 기본 pull·주간 스냅샷이 161MB 를 매번 받지 않음) · `data_store.yml` bootstrap `groups` 입력(기본 `all,hist_year`) · `.gitignore` 패턴 8줄 · 테스트. **동작 변화 없음**(릴리스에 자산이 없으면 pull 은 아무것도 안 받음; 이미 추적 중인 파일은 ignore 영향 없음).
2. **2/2**(커밋 대기) 워크플로 6(fin·screener·briefing·lab·hist push/pull 그룹, 커밋 대상 목록에서 parquet 경로 제거) + `git rm --cached` 38개 + `parquet_inventory.py`/테스트(추적 0개 강제·표 패턴=릴리스 그룹·읽는 워크플로가 그룹 pull·git add 목록에 parquet 재유입 차단).
- 폴백: pull 실패 → 로컬 → 주간 스냅샷 → git 마지막 커밋본(manifest `git_rev`). **이력은 그대로**이므로 파일이 git 이력에 남아 폴백 가능(추적만 해제).

### 1.4 검증 (장중 완료분)
- parquet 38개를 트리에서 치운 채 `pytest` 전체 통과(종료 0). 같은 상태에서 `python3 scripts/board.py --check` OK · `check_functions` 통과 · `check_rules_terms` OK.
- `ui_smoke`: origin/main 그대로는 **4항목 BAD**(cmt·운용회의 미장 v2·점도표 기울기 띠·UXUI 남은3건) — 원인 `google.script.run…getDeskMeeting is not a function` = 3db30717a 가 Pages 심(`scripts/build_pages.py`)에 `getDeskMeeting` 을 안 넣음(parquet 와 무관). 심 1줄 + `index.html` 재생성으로 해결(§4 ④, 프론트 협업).

### 1.5 15:40 이후 절차 (순서 고정 — 순서가 틀리면 데이터가 한 판 뒤로 간다)
1. `ea045ed03` 만 main 에 머지(push). tests.yml 통과 확인.
2. Actions → data_store → mode=bootstrap, groups=`all,hist_year`, commit=true (원격 세션은 릴리스 쓰기 403 이라 Actions 로만). 끝나면 `data_store.py status` 로 자산 38+11개·sha 확인, manifest 커밋 확인.
3. **bootstrap 을 groups=`small` 로 한 번 더**(그 사이 누적 6개가 갱신됐을 수 있음) → 곧바로 2/2 머지(몇 분 안). 누적 6개는 같은 날 두 번 갱신되면 한 판 손실 가능성이 있어 이 간격을 좁힌다.
4. 2/2 머지 직후 fin·lab·hist 를 workflow_dispatch(commit=false)로 1회씩 돌려 pull 로그(`pull same/ok`)와 결과 확인. 이상 → 롤백 = 2/2 `git revert`(파일은 이력에 있음).

## 2. data-live-branch
### 2.1 쓰는 곳 전수 (피어 조건 ①: '8개' 정정 포함)
피어 목록 8개 중 **heartbeat 는 안 씀**(watchdog `--executor`, 커밋 없음)·**pages 는 읽기만**(paths-ignore 목록). 실제 명시 쓰기는 6개이고, `freshness.json` 은 `screener/guard.py:143,163,181,222`(regress_blocked·stale·source) 부수 기록이라 `reports/` 를 통째 커밋하는 워크플로 약 20개가 따라 쓴다.
| 파일 | 쓰는 워크플로:행 | 비고 |
|---|---|---|
| live·events·events_stats·event_state | live.yml:107,109,116 (`git add` :116) | event_watch 60초 루프는 /tmp 에서 작업(live.yml:85) |
| heatmap_KR·heatmap_US·intraday_last | live.yml:106,114,116 · heatmap.yml:30-43(US) | live.yml 이 asof 새로울 때만 얹음 |
| decisions | live.yml:108,115 · briefing.yml:164-190 · pick.yml:60-66 · pb_call.yml:45-49 (모두 `merge_decisions.py` 병합) | **쓰는 주체 4** — 단일화 최대 난관 |
| health·freshness·freshness_alert_state | health.yml:64-67 | 일 1~3회 |
| freshness (부수) | `reports` 통째 커밋: briefing·screener·fin·us_accum·accum·lab·deriv_hist·backfill·dart_*·… 약 20 | guard.py 가 어디서든 씀 |
| 읽기만 | heartbeat.yml:37(watchdog) · pages.yml:13(paths-ignore) · tests.yml | — |
- 규모(origin/main, 11/4 00:00 UTC~11/5 00:14 UTC 약 1일): 전체 커밋 319 중 `live:` 155(49%).

### 2.2 읽는 곳 전수
| 구분 | 위치(파일:행) | 읽는 경로 |
|---|---|---|
| **직접 URL (브라우저 → raw main)** | `apps-script/tab_detail.html:444` intraday_last.json · `tab_market.html:251` `reports/`+file(heatmap_KR/US, :243,:375) · (btc.json `tab_detail.html:146` 은 범위 밖) · 빌드본 `index.html:792,6471` | `raw.githubusercontent.com/…/main/reports/…` 하드코딩 3곳 → `LIVE_BASE` 1곳으로 |
| 직접 URL 패턴 이미 있음 | `tab_market.html:8` `TOSS_BASE = …/toss-live/` (+`index.html:549`) | live-data 도 같은 모양(`LIVE_BASE`) |
| Pages 심 `raw()` | `scripts/build_pages.py:53,58` getLive(live.json) | main → LIVE_BASE |
| Pages 심 `get()` (같은 출처 사본) | `build_pages.py:85` events_stats · `:113` decisions · `:122` freshness | **Pages 빌드에 live-data 를 덮어야 함**(또는 raw 로) — 이 3곳이 빠지면 화면이 옛 판을 읽는다 |
| GAS `raw_()` main 고정 | `Code.gs:62`(공통) · getLive `:78` · events_stats `:119` · decisions `:147` · freshness `:157` | `raw_` 에 브랜치 인자 1개 |
| 화면 소비(가져온 값 사용) | Index.html:330,458,462,479,505,521,527 · tab_home:87,150 · tab_duel:1,301 · tab_market:5-59(live.json; `TOSS_BASE` 쪽 live.json 은 별개 파일) · tab_mkt_deriv:35 · tab_system:136 · tab_detail:177,179 | API 이름 그대로면 변경 없음 |
| 파이썬(Actions 안, 작업 트리 읽기) | alerts·battle_scoreboard·bonds:600·btc·committee:473·contracts:46-47·daily:74·dashboard:29·dotplot·duel·entry_why:23·event_watch·events·freshness·guard·health:53·heatmap(_kr)·intraday_last·live·main·pb:597·regress_git·ticket·trend_discovery·valuation(_daily)·views:404 (총 35파일, studies 제외) | **스텝 앞에 `live_branch.py get`** 필요한 곳: decisions 를 읽는 pick·pb_call·briefing·verify_weekly·scorecard_week·ticket·duel, live.json 을 읽는 watchdog(heartbeat) |
| 스크립트 | watchdog:7,359 · three_lines:8,75 · scorecard_week:8,12 · verify_weekly:28,59 · pick_gate_audit:5 · view_attribution:2,30 · ui_smoke:115,421,675 | ui_smoke 는 fixture 라 영향 없음 |
- 이름 충돌 주의: `screener/toss_live.py`·`heatmap_kr.py:13` 의 live.json 은 **toss-live 브랜치**(별개).

### 2.3 설계 (피어 조건 ②③④ 반영)
- **② 브랜치 상수 1곳**: 파이썬 `scripts/live_branch.py` `LIVE_BRANCH="live-data"`, 화면 `LIVE_BASE`(TOSS_BASE 옆 한 줄). `tests/test_live_branch.py` 가 `LIVE_BASE` 가 같은 이름인지·워크플로가 이름을 직접 쓰지 않는지 검사.
- **③ 쓰는 길 1개**: `live_branch.py put` 만이 live-data 에 쓴다(fast-forward push, 강제 아님, 경합 시 다시 받아 얹기 ≤4회 — 테스트로 확인). 쓰는 주체 단일화 **의견 필요**: decisions 는 4개 워크플로가 쓰므로 '주체 live.yml 하나'를 지키려면 pick·pb_call·briefing 을 live.yml 이 대신 받는 inbox(디스패치/이슈 경유)가 필요 — 큰 구조 변경. 개발 제안 = *쓰는 길 하나(put) + 읽기-병합-쓰기(get→merge_decisions→put)*, 주체는 여럿(피어 판정 칸).
- **주 1회 초기화**: `live_branch.py squash`(force-with-lease, 부모 없는 커밋 1개) — 일요일 장 밖 `ops.yml` 한 줄. 매일 force-push 없음. 이력 = 1주분(`live:` 약 155커밋/일 기준)만 남아 저장소가 안 붇는다.
- **마감 1커밋**: 15:50(KR)·익일 06:15(US) 마감에 live.yml 이 최종본을 main 에 `live: close` 1커밋(기록용, `pages.yml` paths-ignore 유지).
- **④ 되돌림 숫자**: `live_branch.py check` — 병행 기간 main 사본과 불일치 ≥1건 **또는** live-data 신선도 > 20분 1회 → 종료코드 1 → 그날 main 복귀(워크플로 변수 `LIVE_BRANCH_ON` 해제; 읽기 쪽 폴백은 `LIVE_BASE` fetch 실패 → 기존 main raw). heartbeat.yml(30분)에 편승 가능.
- **단계(제안)**: A) 병행 쓰기(main+live-data 둘 다, 읽기는 main) 1영업일 + `check` 로 불일치 0 확인 → B) 읽기를 live-data 로(화면 3곳·GAS 5곳·Pages 3곳 + Actions get 스텝) → C) main 쓰기 중단 + 마감 1커밋. **freshness.json 은 A/B 에서 제외**(약 20 워크플로가 부수로 씀 → guard 가 /tmp 에 쓰고 put 하도록 바꾸는 별도 소작업 필요) — 11/6 목표엔 live·events*·event_state·heatmap·intraday_last·decisions 까지.
- **프론트 협업(프론트 데스크)**: `tab_detail.html:444`, `tab_market.html:251`(+8줄 LIVE_BASE), `build_pages.py:53-58,85,113,122`, `Code.gs:62` — 개발이 `scripts/`·워크플로·테스트, 프론트가 화면 상수·`ui_smoke` 확인. 오늘은 화면 파일을 건드리지 않음.

### 2.4 검증 (장중 완료분)
- `tests/test_live_branch.py` 10개 통과: put 최초 생성→이력 쌓임·같으면 커밋 없음 / 역행·축소 차단 / **경합 시 재시도로 남의 파일 보존** / get 이 더 새로운 로컬을 안 덮음 / 브랜치 없으면 main 유지 / squash 부모 없음 / check 3종 트리거(신선도·main 더 새로움·같은 시각 다른 내용) / 브랜치 없음=롤백.
- 아직 안 한 것: 워크플로 연결 0건(장중 live.yml·briefing.yml 불가), 실제 원격 브랜치 생성 0건, 브랜치 보호·권한 확인 불가(§4).

## 3. 피어 '반대 3줄' · PB 독립 판단 (비워 둠 — 작성 주체는 각자)
### 3.1 data-parquet-out
- 피어 반대 3줄: `peer_dev_p0.md` 참조(피어리뷰 데스크 11/5 09:54).
- PB 독립 판단 (작성: PB 본인, 11/5 09:56): **조건부 동의 — 머지는 하되 두 가지를 먼저.** ① 피어 반대 2의 '연구 스크립트 약 20개 깨짐'은 겸이가 직접 돌리는 경로라 문서 1줄로는 부족 → `data_store` 부재 감지 시 "python scripts/data_store.py pull --groups hist_year" 안내를 내는 공통 가드 1곳을 ③ 전에 추가(없으면 ③ 보류). ② 피어 반대 3의 롤백 공백은 절차 4줄(릴리스 자산 백업 태그·manifest sha 기록·revert 후 재bootstrap·스냅샷 복구)을 이 문서에 먼저 쓰고 머지. 반대 1(.git 1.9G 불변)은 PB가 겸이에게 이미 고지(09:5x) — 히스토리 축소는 11/14 옛 저장소 보관 계획으로 처리, filter-repo·force-push 는 하지 않음(규약).

### 3.2 data-live-branch
- 피어 반대 3줄: `peer_dev_p0.md` 참조 — '쓰는 길 1개(put)' 조건부 수용.
- PB 독립 판단 (11/5 09:56): 피어와 같은 결론이되 근거 다름 — inbox 구조 변경은 pick·pb_call·briefing 3곳 동시 수정이라 장중 산출물 경합 위험이 더 큼. 단 11/4 '쓰는 주체 live.yml 하나' 조건을 바꾸는 것이므로 **겸이 ㅇㅇ 필요**(CIO 확인). 승인 전 연결 금지. 
- PB 독립 판단 (작성: PB 본인): 특히 §2.3 '쓰는 주체 1개 vs 쓰는 길 1개', freshness 단계 분리 두 가지.

## 4. 막힌 것 · 리스크 · 스냅샷 제외 목록
- **겸이/PB 가 할 일**: ① 15:40 이후 Actions 에서 bootstrap 2회 실행(원격 세션은 릴리스 쓰기 403) ② live-data 브랜치: 새 브랜치 보호 규칙 없음 확인·`GITHUB_TOKEN` push 허용(Actions → Settings → Workflow permissions: Read and write) ③ 새 저장소에서도 같은 설정·`PAGES_ACTIONS`/`LIVE_BRANCH_ON` 변수 생성.
- **④ 11/6 미통과 → 스냅샷 제외 목록**: pytest 미통과 **0건**(parquet 없는 트리 기준, 전체 종료 0). ui_smoke: origin/main 그대로 4항목 BAD → 심 1줄(`scripts/build_pages.py` getDeskMeeting)+`index.html` 재생성 후 **전체 94항목 OK·BAD 0, 종료 0**. 즉 현재 브랜치 기준 제외 항목 없음. 단 심 수정 커밋이 main 에 들어가기 전(15:40 이전)까지 main 의 ui_smoke 는 4항목 BAD 이므로, 머지가 11/6 전에 안 되면 제외 목록 = 운용회의 카드 관련 4항목(cmt·운용회의 미장 v2·점도표 기울기 띠·UXUI 남은3건), 사유 = Pages 심 누락(프론트 협업, 3db30717a), 겸이에게 보고.
- 리스크 1: 누적 6개 parquet 은 릴리스 덮어쓰기(마지막 쓴 쪽이 이김)라 fin·screener·briefing 이 같은 시각에 돌면 한 판 손실 가능 — 이전에도 `-X theirs` 로 같은 성질이었음(§1.5-3 으로 창 최소화).
- 리스크 2: live-data 로 읽기를 옮기는 B 단계에서 Pages `get()` 3곳 누락 시 화면이 옛 값을 읽음 — 병행 1영업일 + `check` 로 막음.
