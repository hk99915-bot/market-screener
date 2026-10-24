# dev 데스크 KB (개발)

(형식 README.md. 코드·CI·빌드·알림 배관만 — 재무·시세 정의는 각 데스크 KB 인용. 2026-10-23 교육 정리: 처리 끝난 대체 지점·변경 기록 본문 압축, 상세는 git 이력·커밋 메시지.)

## 성격·성향
- **한 줄:** 가장 많이 만들고, 그래서 먼저 부서질 자리를 스스로 아는 실행가. "하루만 멈추게 해 달라, 지은 걸 세어 보게."(TH:dev §5)
- **맹점:** 공유 체크아웃에서 남의 변경 혼입을 늦게 인지(복기 10/17). **긴장:** ↔교육·평가 — 화면 연동 handoff 대기. 원본 [PERSONAS.md#dev](PERSONAS.md#dev)(요약, 연기 지시 아님).

## 정의
- [규정-공식문서] 텔레그램 `sendMessage` `disable_notification`: 알림은 뜨고 소리·진동만 없음. 길이 상한 4096자(우리는 3800자에서 쪼갬), `parse_mode=HTML` 은 제한 태그만. (https://core.telegram.org/bots/api#sendmessage — 원문 재확인 못 함)
- [경험] 소리 정책 = 함수 기본값 + 호출부 분류: `screener/report.py send_telegram(..., disable_notification=True)` 기본 무음, 날마다 바뀌는 알림은 `report.loud(text)`(⛔/⚡).
- [규정-내부] 결재 #9(2026-10-17): 소리 알림은 ⛔(손절 2일·발동선·한도) · ⚡(15:05 급락일 종가) · 14:25 반등일 판정 **셋뿐** + 신선도 ⛔(오너 10/17 예외). 나머지 무음.

## 작업·잠금·CI
- 공유 파일(`apps-script/Index.html`·`tab_*.html`·`Code.gs`·`scripts/build_pages.py`·`screener/committee.py`·`screener/main.py`·`.github/workflows/*`)은 `python scripts/lock.py take <파일> --owner <담당> --task <보드id>` → 잠금 커밋 먼저 push. 작업은 데스크별 worktree, `git add -A` 금지(LOOP.md).
- `.github/workflows/tests.yml`: push·PR 마다 `python -m pytest -q`(네트워크 없는 순수 로직, 루프백 외 소켓 차단 — `@pytest.mark.net`/TESTS_ALLOW_NET=1). 푸시 전: pytest → `scripts/check_functions.py` → (보드 변경 시) `board.py --check` → 화면 고쳤으면 `build_pages.py`. pre-push 훅은 origin/main CI 빨강이면 `[ci-fix]` 커밋만 통과.
- 알림 배관: `briefing.yml` cron → `screener/main.py --mode <mode>` → `run(send=…)` → `report.send_telegram`. 테스트는 `report.CFG.telegram_*`·`report.requests.post` monkeypatch(tests/test_telegram_silent.py).

## 신선도·asof 가드 (10/17 재발방지대책 — 오너 "다시는 이런 일 없도록")
- **계약** `ops/freshness.json`: 산출물별 {경로, 날짜 키, kind, 준비 시각, 허용 지연, 담당 모드, 복구 명령}. 거래일 = `screener/tradecal.py`([확인 필요: 2027 KR 음력·대체공휴일 KRX 공지 대조, 2026-12-31]).
- **점검** `screener/freshness.py check(now)` → `reports/freshness.json`{late, regress_today, stale_today, regress_blocked}; health.yml 08:20·20:10 KST 에 늦음·역행이면 ⛔ 1통(항목·기대일당 하루 1회).
- **가드** `screener/guard.py`: 일 단위 비교, 과거면 안 쓰고 `regress_blocked` 기록(백필만 `SCREENER_ALLOW_REGRESS=1`) + 저장 단계 `screener.regress_git`(원격보다 과거 파일은 원격 판으로) + `screener/contracts.py` 스키마 검사(`contract_violation`). 규칙 상수 단일 원천 `screener/defs.py`(검사 `check_rules_terms.py`).
- **남은 조용한 대체 지점**(10/17 grep, 나머지 5곳은 처리): committee `_flows` 외국인 수급 7일 뒤로 · universe.py KRX 목록 · shares.py 상장주식수 · drivers.py US EPS 캐시 · macroview 요약 재사용 · japan.py 가드 우회(→ 보드 `guard-rest`).
- **보존** `scripts/retention.py`: 기본 드라이런, `--apply` 는 workflow_dispatch 로만(결재 #10 ②).

## 큰 데이터 = 릴리스 자산 (repo-size-stage1, 10/21 겸이 승인)
- [경험] parquet 는 이미 압축이라 git 이 차이를 못 저장 → 통째 누적(10/14~20 실측: 옮긴 11파일 276.7MB = 7일 증가의 49%).
- 대상(git 밖 릴리스 자산 — 미생성 in git: `data/kr_prices.parquet`·`data/signals.parquet`·`data/fin/*`·`data/hist/*_daily`·`data/flows/kr_inv_*`) → 릴리스 `data-latest`, git 엔 `data/data_store_manifest.json` 만. `scripts/data_store.py pull|push|snapshot|status`: pull 폴백(로컬→주간 스냅샷→git_rev), push 차단(같은 sha·asof 역행·절반 미만·폴백). 'push 하는 워크플로는 pull 먼저'를 tests/test_data_store.py 가 강제. 주간 스냅샷 금 20:17 KST `data-YYYYMMDD`(8개).
- [경험] claude.ai 원격 세션은 릴리스 생성 403 — 업로드는 Actions 로만. 로컬은 `python3 scripts/data_store.py pull`.

## 흔한 오해·현장 교훈
- [경험] "무음이면 안 보인다" ✕ — 소리만 없다. 호출부마다 토큰 체크 반복 ✕ — `send_telegram` 이 RuntimeError, 호출부는 try/except 로그.
- [경험] GAS 웹앱 doPost 는 요청 헤더를 못 읽는다 → secret_token 대신 URL `?s=` 검증(10/20 tg-pick-buttons).
- [경험] `overflow-x:hidden` 이면 scrollWidth 로 폰 넘침을 못 잡는다 → 요소 `getBoundingClientRect().right` 검사. Playwright route 는 나중 등록이 먼저 매칭(10/21).
- [경험] 실적 이어받기를 '< 오늘−1' 로 두면 발표 다음날 야후가 다음 분기로 넘어가 이벤트가 사라진다 → '< 오늘' 전부 + 30일 안 재일정만 버림(10/23).
- [경험] 스킨은 토큰만 바꾼다 → 화면 파일에 다크 색(#111·#151515)을 직접 쓰면 엑셀 스킨에서 검정 바탕 검정 글자(10/24 톡방). 새 색은 var(--bg2/--bg3/--panel/--on-amber), 검사는 test_skin_tokens·check_xl.
- [경험] KR 픽은 종가 진입이라 제출 때 기준가가 없다 → 손절·목표를 % 로 받으면 R:R 계산 가능(10/23 pick_gate).

## 변경 기록 (테스트 · 롤백 · 영향 — 상세는 커밋 메시지)
- 10/17 [운영] 기본 무음(결재 #9): tests/test_telegram_silent.py · 롤백 기본값 False · 알림 소리만.
- 10/17 [운영] 신선도 계약·가드·배지: tests/test_freshness_guard.py · revert · briefing·screener·health 저장 단계·헤더.
- 10/20 [운영] 대결 인라인 버튼 + GAS 웹훅: tests/test_tg_pick_buttons.py · GAS `tgDeleteWebhook` · duel 메시지(docs/telegram_pick_buttons.md).
- 10/21 [운영] 영어 v2 화면(test_english_v2_fixture) · 릴리스 자산 이전(test_data_store) · 지표 팝업(ui_smoke check_macro_popup) — 모두 revert 롤백. 미처리: #fresh 배지 390px 넘침.
- 10/23 [운영] 캘린더 실적 결과 1단계(test_calendar_earn·test_streak) · '나' 게이트(test_pick_gate) · US STALE 08:52 재시도·CI 빨강 게이트·소켓 차단·BTC(test_us_stale_check·test_prepush_ci_gate·test_no_external_socket·test_btc) — 모두 revert 롤백.
- 10/24 UXUI 남은 3건(💬 머리 버튼·표 첫 열 sticky·글자 4단계 토큰 `scripts/font_tokens.py`): tests/test_font_tokens.py·ui_smoke check_uxui_rest · revert · 모든 탭 글자 크기. 10/24 [운영] 공식 섹터 전환 `sectors.OFFICIAL_LIMITS=True`: test_sectors · 롤백 False · MY 반도체 밴드·한도 알림 입력(docs/sectors_switch_2026-10-24.md).
- 10/24 엑셀 스킨 전수(req-dev-0d1eee58): 다크 전용 하드코딩 배경 → 토큰 --bg2·--bg3·--panel·--on-amber, xl 대비 미달 628→0(390·1300 합): tests/test_skin_tokens.py·ui_smoke check_xl·scripts/skin_audit.py(측정 정의) · revert · 사내톡·연구 보드·부동산·MY·STUDY·HOME·대결 색.
- 10/24 UXUI 재검수 회귀(req-dev-26f063bc): 폰 머리 151→109px(신선도 배지 폰 짧게, 💬·🔍 44px)·달력 K/S 두 줄·연구 보드 두 줄·단계 카드 56px·목록 44px PC 확대: ui_smoke check_head_clip(머리 ≤110·잘림 기준선 CLIP_BASE) · revert · 모든 탭 머리·공시/인적성 PC 길이(+13%).
- 10/24 [운영] 텔레그램 'quiz <qid> <답>' → 이슈 'study quiz'(G3, TelegramHook.gs tgParseQuiz_): tests/test_tg_quiz.py(node 대조) · revert · 텔레그램 답장·study.yml. gas_deploy 대상 분리(감사 M3 — 시크릿 GAS_SCHED_SCRIPT_ID 가 다른 ID 면 웹앱=Code.gs·예약 실행기=Scheduler·TelegramHook, 미설정=한 프로젝트로 보고 셋 다): tests/test_gas_deploy.py · revert · GAS 배포. slop_audit JSON 장부 스캔·'종가'·순자산 목표 허용(M6): tests/test_slop_audit.py · revert · 감사 집계.

## 출처
- Telegram Bot API sendMessage(core.telegram.org, 원문 미확인) · ops/LOCKS.md · ops/README.md · .github/workflows/tests.yml

## 복기
- 2026-10-17 (사고 3) 틀림: 토 09:46 KST 수동 detail_us(커밋 9ea9efbd)가 US 580파일을 10/16→10/15 로 덮음 → 왜: ① Yahoo 가 그 호출(금 20:47 ET)에서 **종목 523개 전부 10/16 봉을 빼고** 줌 — 종목당 행 273.4 vs 직전 275.4(시작일 1일 이동 −1, 마지막 봉 누락 −1), 같은 실행의 지수(^GSPC·^IXIC)는 10/16 있음(macro_series). Yahoo 측 원인은 네트워크 차단으로 재현 못 함[확인 필요: 다음 금요일 20~24시 ET 에 yf.download 로 재현, 2026-10-24]. ② 코드엔 "지금이면 어느 봉이 있어야 하나"가 없어 최빈 날짜(10/15)를 그대로 기준일로 삼고 `_status` 는 시계만 보고 CONFIRMED. ③ 모든 쓰기가 무조건 덮어쓰기, 저장 단계 `-X theirs` 는 늦은 실행을 이기게 함 → 다음부터: tradecal.expected_session 으로 기대일 계산·재시도, 게시본보다 과거면 중단, 가드·regress_git 이중 차단. 재현 테스트 tests/test_freshness_guard.py::test_saturday_us_regress_is_refused. 덤: main.run 인자 `live`(bool)가 모듈을 가려 `live.patch_macro` 가 매 실행 실패하던 것도 수정.
- 2026-10-17 (라운드1) 틀림: 작업 사본이 내 것뿐이라 여기고 `git diff --stat` 를 보기 전까지 남의 변경(bonds·ticket·duel 60줄+)이 섞인 줄 몰랐다 → 왜: 데스크 12개가 한 체크아웃을 공유한다는 전제를 브리프의 "동시에 push 중" 에서 읽어내지 못함 → 다음부터: 편집 전 `git status -s` 를 찍고, 커밋은 파일·hunk 단위로만 올린다.

## 10년차 기준 (2026-10-23 교육)
- 체크리스트: ① 흐름 4지표(배포 빈도·리드타임·변경 실패율·복구 시간)로 스스로 잰다 `[교과서-B: Forsgren 외 *Accelerate* 2018 / DORA]` ② 장애마다 무책 포스트모템 — 타임라인·근본 원인·재발 방지 액션(오너·기한) `[교과서-B: Google *SRE* 2016, 2차 요약 일치]` [확인 필요: 장 번호, 2026-10-30] ③ 신선도를 SLO(산출물별 허용 지연)+에러 버짓으로 운영, 버짓 소진 시 신규 기능 중단 `[교과서-B: 같은 책]`
- 격차: 보드 개발 미완 P0/P1 44건 — 그중 '검수' 26건(P0 7·P1 19)·마감 경과 27건(ops/board.json, 10/23 기준) + 밀린 요청 9건. 만드는 속도보다 '끝내기(검수)'가 병목.
- 드릴 [dev-d1]: 위 44건을 오늘 밤 어떻게 줄이나? — 답·채점 키 `content/drills/dev.json`(라운드 파일에 `드릴: dev-d1 <내 답>` 을 먼저 쓰고 열 것, round_collect 채점 · G1 10/24)
