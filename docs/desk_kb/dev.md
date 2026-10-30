# dev 데스크 KB (개발)

(형식 README.md. 코드·CI·빌드·알림 배관만 — 재무·시세 정의는 각 데스크 KB 인용. 2026-10-23 교육 정리: 처리 끝난 대체 지점·변경 기록 본문 압축, 상세는 git 이력·커밋 메시지.)

## 성격·성향
- **한 줄:** 가장 많이 만들고, 그래서 먼저 부서질 자리를 스스로 아는 실행가. "하루만 멈추게 해 달라, 지은 걸 세어 보게."(TH:dev §5)
- **맹점:** 공유 체크아웃에서 남의 변경 혼입을 늦게 인지(복기 10/17). **긴장:** ↔교육·평가 — 화면 연동 handoff 대기. 원본 [PERSONAS.md#dev](PERSONAS.md#dev)(요약, 연기 지시 아님).

## 경계 — 화면 구현 이관 (2026-10-24 겸이 결재 appr-staffing-30, 프론트 신설 · 운영 등록)
- 정정: 화면·스킨·텔레그램 UI(메시지 레이아웃·버튼 배열)·`scripts/ui_smoke.py` 는 10/24부터 **프론트**(`front.md`). `apps-script/tab_*.html`·`Index.html`·`build_pages.py` 화면부(심·인라인·`index.html` 빌드) = 프론트 / `scripts/`·`.github/workflows/`·`.gs` 서버 로직(Code.gs getter·TelegramHook 처리·Scheduler)·`screener/`·수집·live·gas_deploy = 개발 / UXUI = 설계·검수.
- 화면에 새 데이터 칸이 필요하면 개발이 생성 코드를 만들고 프론트가 표시한다(요청은 `scripts/ask.py`). 텔레그램 표시 함수가 `screener/report.py`·`.gs` 안에 있으면 파일은 개발 소유, 프론트가 함수 단위 변경안을 ask.
- 보드 재배정(운영 10/24): 대기 중 화면 작업 `tradeplan-ui`·`req-dev-516bf7e6`·`edu-dev-handoff`·`req-dev-cb19b1e0` → 담당 프론트. 검수 중인 화면 작업(`my-tab-ledger-compare`·`tg-pick-buttons`)은 개발이 끝까지, 보류(`holdings-unify`·`my-isa-split`)는 풀릴 때 화면 부분만 프론트.

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
- [경험] 토스 Open API 는 Actions 에서 못 부른다(허용 IP 등록제 + 클라이언트당 토큰 1개 — 재발급 시 이전 토큰 즉시 무효) → 수집 주체는 노트북 1대, 서버 쪽은 toss-live 브랜치 live.json 을 읽어 신선할 때만 덮는다(10/24).
- [경험] 스킨은 토큰만 바꾼다 → 화면 파일에 다크 색(#111·#151515)을 직접 쓰면 엑셀 스킨에서 검정 바탕 검정 글자(10/24 톡방). 새 색은 var(--bg2/--bg3/--panel/--on-amber), 검사는 test_skin_tokens·check_xl.
- [경험] KR 픽은 종가 진입이라 제출 때 기준가가 없다 → 손절·목표를 % 로 받으면 R:R 계산 가능(10/23 pick_gate).

## 점도표 기울기 5단 · 바람 라벨 (10/26 보드 `dotplot-neutral-rule` — 임계값 전부 **검증전**, 퀀트·매크로 검수 대기)
- 배경: 10/26 dotplot.json 점 32개 중 중립 27(84%) — 규칙 미달 = 중립으로 떨어지는 구조. 겸이 10/16 "운용회의에서 모르겠다고 할래?", 10/26 "맨날 중립이야 점도표도".
- 규칙: 점마다 `lean`(−2 강매도~+2 강매수)·`confidence`·`p_up`·`base_prob`(기본 시나리오 확률)·`flip_up`·`flip_down`(숫자 포함). 기존 `stance`·`conv`·`summary.counts` 유지(하위 호환, stance = lean 부호).
- 규칙 미달이어도 근거 부호는 유지 → 약매수/약매도(확신 낮음, p_up = 0.5 ± 1/12). 순수 중립은 base_prob·flip 두 개 다 있을 때만 — `lint_dots` 위반은 dotplot.json `lint`·상단 ③에 노출.
- 데스크 규칙이 없는 자산·입력 없음 = `해당없음`(na) — 집계·채점 제외(중립으로 세지 않음).
- 기울기 임계값(표시 로직, 검증전): 매크로 바람 |s| ≥ 0.05 · CIO 강세−약세 |d| ≥ 5%p · 미10Y 5일 |Δ| ≥ 2bp · 퀀트·리스크 = 200일선 부호 · 파생 = 백워데이션(−1) + 음감마×5일 추세 부호.
- 전환 조건 어댑터: `rounds/<3일 내>/event_macro.md` 트래킹 트리거 표(코스피·VIX→S&P·코스피200 IV→반도체·미 10Y) + `event_cio.md` So What 신호등(🔴 → CIO 국내 −1, 시나리오 과반 없을 때만). 없으면 시세(50일선·20일 고저, 미10Y ±15bp).
- 매크로 바람 라벨(`macroview.wind_label`): |s| < 0.05 중립 · 0.05~0.15 약한 역풍/순풍 · 0.15~0.4 역풍/순풍 · ≥ 0.4 강한. 0.05 = 가중 평균 점수 일간 흔들림 수준으로 잡은 표시 구간(근거 표본 없음, 검증전).
- 채점: 약매수/약매도 = lean 부호로 방향 채점, Brier 는 점의 p_up, `by_lean` 단계별 성적 추가. 옛 아카이브(lean 없음)는 stance·conv 로 환산.
- 검수 요청: 퀀트(기울기 p_up 1/12·200일선 부호 근거) · 매크로(바람 0.05 중립 폭·US10Y 2bp) — 채점 표본 20거래일 쌓인 뒤 by_lean 으로 재검토.

## 변경 기록 (테스트 · 롤백 · 영향 — 상세는 커밋 메시지)
- 10/17 [운영] 기본 무음(결재 #9): tests/test_telegram_silent.py · 롤백 기본값 False · 알림 소리만.
- 10/17 [운영] 신선도 계약·가드·배지: tests/test_freshness_guard.py · revert · briefing·screener·health 저장 단계·헤더.
- 10/20 [운영] 대결 인라인 버튼 + GAS 웹훅: tests/test_tg_pick_buttons.py · GAS `tgDeleteWebhook` · duel 메시지(docs/telegram_pick_buttons.md).
- 10/21 [운영] 영어 v2 화면(test_english_v2_fixture) · 릴리스 자산 이전(test_data_store) · 지표 팝업(ui_smoke check_macro_popup) — 모두 revert 롤백. 미처리: #fresh 배지 390px 넘침.
- 10/23 [운영] 캘린더 실적 결과 1단계(test_calendar_earn·test_streak) · '나' 게이트(test_pick_gate) · US STALE 08:52 재시도·CI 빨강 게이트·소켓 차단·BTC(test_us_stale_check·test_prepush_ci_gate·test_no_external_socket·test_btc) — 모두 revert 롤백.
- 10/24 UXUI 남은 3건(💬 머리 버튼·표 첫 열 sticky·글자 4단계 토큰 `scripts/font_tokens.py`): tests/test_font_tokens.py·ui_smoke check_uxui_rest · revert · 모든 탭 글자 크기. 10/24 [운영] 공식 섹터 전환 `sectors.OFFICIAL_LIMITS=True`: test_sectors · 롤백 False · MY 반도체 밴드·한도 알림 입력(docs/sectors_switch_2026-10-24.md).
- 10/24 [운영] 종목 상세 장중 오늘 일봉 reports/intraday_last.json schema 2(KR 네이버 polling 당일 O·H·L·V·전일 종가 5분, US 야후 정규장 일봉 15분, 갭·메움) + 히트맵 polling 먼저·토스 폴백(정규장만) + 장 밖 토스 지수 덮기 금지·15:30~15:45 provisional: tests/test_intraday_last.py · revert · live.yml 커밋 목록·히트맵 출처 문구·프론트 차트(장부).
- 10/24 문장 속 링크 점선 밑줄(a.il)·엑셀 이모지 회색(.xe)·PCR 차트 --ch1/--ch2(req-dev-3d26f6e6·06b280d5): Index decoInline(MutationObserver, 그려진 DOM 에 붙임) · tests/test_skin_tokens.py·ui_smoke check_links_pcr·check_xl emoji · revert · 모든 화면 링크 모양·엑셀 이모지·파생 PCR 색.
- 10/24 엑셀 스킨 전수(req-dev-0d1eee58): 다크 전용 하드코딩 배경 → 토큰 --bg2·--bg3·--panel·--on-amber, xl 대비 미달 628→0(390·1300 합): tests/test_skin_tokens.py·ui_smoke check_xl·scripts/skin_audit.py(측정 정의) · revert · 사내톡·연구 보드·부동산·MY·STUDY·HOME·대결 색.
- 10/24 UXUI 재검수 회귀(req-dev-26f063bc): 폰 머리 151→109px(신선도 배지 폰 짧게, 💬·🔍 44px)·달력 K/S 두 줄·연구 보드 두 줄·단계 카드 56px·목록 44px PC 확대: ui_smoke check_head_clip(머리 ≤110·잘림 기준선 CLIP_BASE) · revert · 모든 탭 머리·공시/인적성 PC 길이(+13%).
- 10/24 [운영] 텔레그램 'quiz <qid> <답>' → 이슈 'study quiz'(G3, TelegramHook.gs tgParseQuiz_): tests/test_tg_quiz.py(node 대조) · revert · 텔레그램 답장·study.yml. gas_deploy 대상 분리(감사 M3 — 시크릿 GAS_SCHED_SCRIPT_ID 가 다른 ID 면 웹앱=Code.gs·예약 실행기=Scheduler·TelegramHook, 미설정=한 프로젝트로 보고 셋 다): tests/test_gas_deploy.py · revert · GAS 배포. slop_audit JSON 장부 스캔·'종가'·순자산 목표 허용(M6): tests/test_slop_audit.py · revert · 감사 집계.
- 10/25 watchdog 새 것/밀린 것 구분(🆕 오늘 새로 N · 원래 밀린 것 M, 데스크별 '새 n')·마감 변경 횟수(board.json git 이력, 얕은 클론은 보이는 구간만)(req-dev-8d80aab2): tests/test_watchdog.py · revert · reports/watchdog.json 필드 new_today·backlog·due_changed·findings.new 추가, 텔레그램 하루 1통 본문 2줄.
- 10/25 부동산 탭 '🔒 내 계획(비공개)'(realestate-private-viewer): pb-private realestate/web_manifest.json({updated,items[{path,title,note,order}]}) → order 순 목록 → 항목 md 를 MY 탭 pbGet(토큰 mt_gh_tok, 이 브라우저만)으로 읽어 작은 렌더러(제목·표·목록·강조, esc 선행 XSS 방지, 표 overflow-x 감쌈, `../` 경로 거절): ui_smoke check_re_private(가짜 데이터) · revert · 부동산 탭 맨 아래 섹션. [경험] Playwright route 핸들러에 기본값 인자를 달면 request 가 채워진다 → 클로저로.
- 10/27 [운영] 국제금융센터(KCIF) 보고서 자동 수집(겸이 10/27 "앞으로 저것도 트래킹할 수 있나?"): `public_reports` 소스 `kcif`(group 정부·연구기관) — 특별일보(`/annual/dailyList`, 시리즈 = '특별일보·<주제 탭 pe>', 예: 주가 급락 해외시각)·분석보고서(`/analysis/analysisList`)·이슈브리핑(`/brief/briefList`) 목록 각 10행, 링크 = 상세 `…View?rpt_no=N&mn=..&pe=..`(꼬리 제거). 제외: 국제금융속보(매일 뉴스 요약)·주간·월간(양). `/annual/reportList`(전체) 는 mn·pe 와 무관하게 전 게시판 섞임(10/27 확인). PDF 는 목록에 암호화 토큰뿐 → 저장 안 함. robots.txt `User-Agent : * / Disallow: : /`(형식 깨짐, 검색엔진만 허용 의도로 보임) → 하루 1회 목록 3장만. digest 연결: `digest_index`/`digest_for` 가 id 외에 **같은 원문 링크**로도 찾음 → 수집 전에 사람 읽는 id 로 쓴 요약(kcif_kospi_vol_20261027 = rpt_no 37642)이 '요약 대기'로 중복되지 않음(pending·public_card 공통). 첫 수집 날 30일 안 행 ≈ 28건이 `--pending` 에 올라옴(애널 07:41 부담). tests/test_public_reports.py(kcif 5건, 픽스처 tests/fixtures/public_reports/kcif_*.html) · 롤백 = SOURCES 의 kcif 항목에 `"manual": "<사유>"` · 영향 public_reports.json·공공 리포트 카드·`--pending`.
- 10/27 밤 배치(PB 브리프 night1027): [운영] KRX 1회 자동 재시도(유니버스 60초·일별 30초, test_krx_retry) · [운영] BTC ±5% 무음 알림 하루 1회(btc_alert.json, test_btc) · 토스 EOD 섀도 대조 매 US 실행(mode=shadow, test_toss_eod_gate) · 브이월드 노트북 CLI·3회 재시도·Actions 연속 실패 생략(docs/realestate/vworld_laptop.md) · 점도표 조건 없는 중립 = 기록 거부(na·refused)·보합 빈도 '기본' 표기 금지(base_text) · 묶음 C(macro_series provisional·calendar tentative·peers_hist/US.csv·trail 재현·hf_risk 테스트) · 영어 복습 tainted · rulebook 결재 ③(pb-private risk/rulebook.stress_buy_gate·frm.py check_buy/--buy, 커밋은 PB) — 모두 revert 롤백.
- [경험] 테스트가 실제 reports/ 를 쓰면 pre-push pytest 서브셋 뒤 작업 사본이 더러워져 `pull --rebase` 가 막힌다(10/27: calendar build→policy_rates, 섀도 대조→toss_eod_check). 새 쓰기 경로를 만들면 그 함수를 부르는 기존 테스트까지 monkeypatch 확인. 회귀 수리는 수리 커밋만 따로 `[ci-fix]` 로(내 다른 커밋과 섞지 말 것).
- [경험] Actions 수집 결과 확인(컨테이너는 로그 blob 403): `gh run list -w fin.yml -L 3` → `gh api repos/hk99915-bot/market-screener/actions/runs/<run>/jobs -q '.jobs[].id'` → `gh api repos/hk99915-bot/market-screener/check-runs/<job>/annotations` 의 '공공 리포트 소스 표'(id:status:n)·'진단'(ok 아닌 소스만 URL·바이트·hit). 실패 소스는 status error·reason 만 남고 나머지 수집은 계속(fin.yml `|| echo ::warning`).
- 10/30 [운영] 미 서머타임 종료: live 미장 시작 cron 22:20·23:20 **둘 다 상시** + in_window ET(09:15–16:15 America/New_York) — 계절마다 cron 손 교체 없음, 겨울 22:20 은 1분 빈 실행(tests/test_dst_winter.py · revert · live 미장 루프 시작 시각). pre-push 'index.html 낡음' 검사(head 커밋 원본 빌드 ≠ index.html 이면 차단, scripts/prepush_check.pages_check) + tests.yml paths 에 apps-script/**·index.html(tests/test_prepush_check.py · revert · push 훅·CI 트리거).
- [경험] UTC cron 은 서머타임을 모른다 → 시각에 묶인 시작 트리거는 **두 계절 시각을 다 두고 판정을 tz 코드로** 하는 쪽이 '날짜 분기'·'계절마다 교체'보다 안전(교체 시점의 하루가 늘 위험 구간).

## 출처
- Telegram Bot API sendMessage(core.telegram.org, 원문 미확인) · ops/LOCKS.md · ops/README.md · .github/workflows/tests.yml

## 복기
- 2026-10-17 (사고 3) 틀림: 토 09:46 KST 수동 detail_us(커밋 9ea9efbd)가 US 580파일을 10/16→10/15 로 덮음 → 왜: ① Yahoo 가 그 호출(금 20:47 ET)에서 **종목 523개 전부 10/16 봉을 빼고** 줌 — 종목당 행 273.4 vs 직전 275.4(시작일 1일 이동 −1, 마지막 봉 누락 −1), 같은 실행의 지수(^GSPC·^IXIC)는 10/16 있음(macro_series). Yahoo 측 원인은 네트워크 차단으로 재현 못 함[확인 필요: 다음 금요일 20~24시 ET 에 yf.download 로 재현, 2026-10-24]. ② 코드엔 "지금이면 어느 봉이 있어야 하나"가 없어 최빈 날짜(10/15)를 그대로 기준일로 삼고 `_status` 는 시계만 보고 CONFIRMED. ③ 모든 쓰기가 무조건 덮어쓰기, 저장 단계 `-X theirs` 는 늦은 실행을 이기게 함 → 다음부터: tradecal.expected_session 으로 기대일 계산·재시도, 게시본보다 과거면 중단, 가드·regress_git 이중 차단. 재현 테스트 tests/test_freshness_guard.py::test_saturday_us_regress_is_refused. 덤: main.run 인자 `live`(bool)가 모듈을 가려 `live.patch_macro` 가 매 실행 실패하던 것도 수정.
- 2026-10-17 (라운드1) 틀림: 작업 사본이 내 것뿐이라 여기고 `git diff --stat` 를 보기 전까지 남의 변경(bonds·ticket·duel 60줄+)이 섞인 줄 몰랐다 → 왜: 데스크 12개가 한 체크아웃을 공유한다는 전제를 브리프의 "동시에 push 중" 에서 읽어내지 못함 → 다음부터: 편집 전 `git status -s` 를 찍고, 커밋은 파일·hunk 단위로만 올린다.
- 2026-10-30 (서머타임 1차) 애매→틀림: 오후 1차 대응(35e057343)에서 live 미장 cron `20 13`(22:20 KST)을 `20 14` 로 **교체**해, 아직 EDT 인 10/30(금) 밤 22:30 개장의 시작이 구버전 GAS 한 줄에만 걸렸다(오너가 오늘 새 GAS 를 붙이거나 GAS 가 빠지면 23:07 백업까지 37분 공백) → 왜: '11/02부터'를 바꿀 시각으로만 보고 '바꾼 순간부터 11/01 까지 남은 여름 장'을 계산하지 않음 → 다음부터: 시각 변경은 적용 시점~발효 시점 사이 장 일정을 표로 먼저 쓰고, 가능하면 두 시각 공존(+판정 코드)으로. 21시 라운드에서 `20 13` 복원(8ee30c28d).

## 10년차 기준 (2026-10-23 교육)
- 체크리스트: ① 흐름 4지표(배포 빈도·리드타임·변경 실패율·복구 시간)로 스스로 잰다 `[교과서-B: Forsgren 외 *Accelerate* 2018 / DORA]` ② 장애마다 무책 포스트모템 — 타임라인·근본 원인·재발 방지 액션(오너·기한) `[교과서-B: Google *SRE* 2016 15장 'Postmortem Culture: Learning from Failure' — sre.google/sre-book 목차 10/30 확인]` ③ 신선도를 SLO(산출물별 허용 지연)+에러 버짓으로 운영, 버짓 소진 시 신규 기능 중단 `[교과서-B: 같은 책 4장 'Service Level Objectives'·3장 'Embracing Risk'(에러 버짓) — 10/30 확인]`
- 격차: 보드 개발 미완 P0/P1 44건 — 그중 '검수' 26건(P0 7·P1 19)·마감 경과 27건(ops/board.json, 10/23 기준) + 밀린 요청 9건. 만드는 속도보다 '끝내기(검수)'가 병목.
- 드릴 [dev-d1]: 위 44건을 오늘 밤 어떻게 줄이나? — 답·채점 키 `content/drills/dev.json`(라운드 파일에 `드릴: dev-d1 <내 답>` 을 먼저 쓰고 열 것, round_collect 채점 · G1 10/24)
