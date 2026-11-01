# 리팩토링 v1 — 0차 이전 목록 (워크플로·외부 연결·데이터 분류·제외 목록·겸이 할 일·위험)

작성 2026-11-01 KST · 개발 데스크 · 상위 문서 `docs/refactor_plan_v1.md`(§3 출처 표·§5 차수) · 결재 11/1(§7)
범위: **목록화만** — 코드·저장소 이동 0, GitHub 저장소 생성·가시성 변경 0(겸이 확인 뒤 별도). 금액·개인정보 없음(건수·비율·이름만). 시크릿은 **이름만**(값 금지).
입력: 워크플로 37개 파일 직접 읽음 · `apps-script/Scheduler.gs`·`TelegramHook.gs`·`Code.gs` · `tools/dispatch/dispatch.py` · `docs/toss_md_laptop_setup.md` · 감사 `rounds/2026-10-27/audit_privacy.md` · GitHub REST(실행 기록 표본 1,000건 10/29 20:46~11/1 12:31 KST, 브랜치·릴리스·포크 수).
11/1 PB 추가 지시(겸이 "범용은 친구들/이력서 포폴상에도 넣게") 반영: 새 공개 저장소 = **범용판**, 옛 저장소(비공개 전환) = **내부판**.

## 상단 (STANDARD 8절)
- **What**: 워크플로 37개(계획서의 30개는 10/27 기준 — 그 뒤 연구 수집 6개·dart_biz 등 증가) · 시크릿 이름 25개 + 저장소 변수 5개 · 외부 진입점 5곳(GAS 예약기·GAS 웹앱/텔레그램 훅·노트북 dispatcher·노트북 토스 수집기·Pages) · 저장소 이름이 코드에 박힌 파일 26개. 실행 분 실측(표본): **평일 하루 약 1,800분**, 그중 `live.yml` 루프 43%·옛 방식 Pages 빌드 29%.
- **So What**: ① 옛 저장소를 그대로 비공개로 돌리면 이 분량이 비공개 Actions 한도 `[확인 필요: GitHub Free 비공개 월 한도 — 원문 대조 전 '수천 분대'로만 표기]` 를 하루 이틀에 넘긴다 → **무거운 실행기는 전부 범용판(공개)에 두고, 내부판은 문서·장부·개인 티켓 워크플로만**. ② 저장소 이름을 그대로 쓰면 바뀌는 주소가 거의 없다(아래 §0 이름 방식) — 11/12 전 완료가 현실적이 되는 핵심.
- **Now What**: 겸이 결정 2건(D1 이름 방식·D2 개인 시크릿 워크플로 위치) → 11/3~6 범용판 스냅샷 구성(제외 목록 적용·탭 숨김) → 11/7(토) 전환 → 11/9~11 병행 대조 3거래일 → 11/11 밤 옛 쪽 정리 → **11/12 이후 남는 일 = 비공개 전환 1클릭 + 범용판 다듬기(선택·소량)**. 뒤집힐 조건: D1 에서 '새 이름' 선택 시 주소 변경 26파일·GAS·노트북·텔레그램 문구가 전부 일정에 들어와 11/7 전환이 빠듯 → 병행을 11/9~13 원안으로.

## 0. 결정 필요 (겸이)
| id | 질문 | 추천(검증전) | 대안 | 왜 |
|---|---|---|---|---|
| D1 | 이름 방식 | **옛 저장소 이름 변경**(예: `market-screener-desk`) → 새 공개 저장소가 `market-screener` 이름을 받음 | 새 공개 저장소를 새 이름으로 | Pages 주소·raw 주소·GAS `REPO`·노트북 원격·dispatcher `REPO` 가 **그대로**. 이름 변경 뒤 같은 이름 새 저장소를 만들면 GitHub 의 옛 이름 자동 넘김은 끊긴다 `[규정-B: GitHub 문서 'Renaming a repository', 11/3 원문 재확인]` — 우리가 원하는 동작. 단점: 이력서 링크에 쓰기엔 이름이 덜 일반적 → 이름은 나중에도 바꿀 수 있음(그땐 넘김이 생김) |
| D2 | 개인 시크릿(`MY_HOLDINGS`·`MY_RULES`·`RISK_PCT`·`SAT_BOOK_KRW`·`RULE_DEADLINE`·`RULE_STOP_LEVEL`)을 쓰는 워크플로 | 11/7 엔 **현행 유지**(briefing·live·screener 는 범용판에서, 값은 시크릿이라 비공개 — 지금과 같음). `pick`·`pb_call` 만 내부판으로 | 전부 내부판으로 | live·briefing 이 분량 대부분 — 내부판으로 가면 비공개 분 한도 초과. 개인 규칙 코드 분리(플러그인화)는 2~3일 작업 `[추정]` 이라 11/12 이후 선택 과제 |
| D3 | 오래된 공개 브랜치 9개(`ccr-8f2e…`·`study-data/*` 6·`front-org-rnr-wip`·`data`) | 새 저장소엔 **안 가져감**(main·`toss-live` 만). 옛 쪽은 비공개 전환으로 자연 정리 | 지금 삭제 | 감사 10/27: 이 중 일부 끝에 애널리스트 이메일. 비공개 전환으로 노출은 멈춤 |

## 1. 워크플로 전수 (37개)
시각은 KST. 'GAS' = Scheduler.gs 가 주 실행(같은 시각 cron 은 +12분 대기 fallback, `scripts/slot_guard.py`). 분 = 표본 2.6일 실행 분(올림, 실행 1회 최소 1분). 판: 범 = 범용판(새 공개), 내 = 내부판(옛→비공개), 보관 = 옮기지 않음(일회성).

| 파일 | 트리거·예약 | 시크릿 이름 | 쓰는 경로 | 외부 연결·비고 | 분 | 판 | 차수 |
|---|---|---|---|---|---|---|---|
| accum.yml | 평일 18:37 | KRX_ID·KRX_PW | 릴리스 자산(data_store) | pykrx | 4 | 범 | 2 |
| ask.yml | 이슈 열림 | (GITHUB_TOKEN) | `docs/desk_kb/rounds/_requests.json`·`reports/msgr_feed.md` | 텔레그램 훅 → 이슈 | 1 | 내 | 1 |
| backfill.yml | 매일 02:00 + GAS | KRX_ID·KRX_PW | `data/hist` | pykrx | 8 | 범 | 2 |
| briefing.yml | 평일 cron 15개(08:50~07:10) + GAS 14슬롯 | DART_API_KEY·DATA_GO_KR_KEY·ECOS_API_KEY·KRX_ID·KRX_PW·MY_HOLDINGS·MY_RULES·REB_API_KEY·RULE_DEADLINE·RULE_STOP_LEVEL·TELE·TELE_CHAT·TELEGRAM_TOKEN·TELEGRAM_CHAT_ID·VWORLD_KEY | `reports/*` 다수·`decisions.json`·`battle_scoreboard.json`·릴리스 | 텔레그램 발송 · `hk99915-bot.github.io` 링크 | 85 | 범(D2) | 4 |
| dart_biz.yml | 토 11:23 | DART_API_KEY | `data/dart_biz` | DART OpenAPI | 181 | 범 | 2 |
| data_store.yml | 금 20:17 | — | 릴리스 `data-latest`·주간 `data-YYYYMMDD`·`data/data_store_manifest.json` | — | 2 | 범 | 2 |
| deriv_hist.yml | 평일 16:40 + GAS | DATA_GO_KR_KEY·KRX_API_KEY·KRX_ID·KRX_PW | `data/deriv` | KRX·공공데이터 | 7 | 범 | 2 |
| event_driven_data.yml | 수동 | — | `data/study/event` | 연구 일회성 | 0 | 보관 | — |
| fin.yml | 매일 03:30 + GAS | DART_API_KEY·SEC_USER_AGENT | `data/fin`·릴리스 | DART·SEC | 135 | 범 | 2 |
| flowq.yml | 수동 | KRX_ID·KRX_PW | `reports/flowq/` | pykrx | 0 | 범 | 2 |
| gas_deploy.yml | push `apps-script/*.gs` | CLASPRC_JSON·GAS_SCRIPT_ID·GAS_SCHED_SCRIPT_ID·GAS_DEPLOYMENT_ID | (없음 — GAS 로 배포) | Google Apps Script(clasp) | 2 | 범 | 5 |
| health.yml | 일 22:00 · 매일 08:20·20:10 | TELE·TELE_CHAT·TELEGRAM_TOKEN·TELEGRAM_CHAT_ID | `reports/health.json`·`freshness*.json` | 텔레그램 | 8 | 범 | 4 |
| heartbeat.yml | 평일 08:13~17:43 30분 | 위 텔레그램 4 | (없음) | GAS·노트북 dispatch 무소식 감시 | 4 | 범 | 4 |
| heatmap.yml | 평일 22:12~06:42 30분 | — | `reports/heatmap_US.json` | 야후 | 6 | 범 | 3 |
| hist.yml | 일 05:00 | KRX_ID·KRX_PW | `data/hist/_manifest.json`·릴리스 | pykrx | 3 | 범 | 2 |
| lab.yml | 일 23:00 | — | `reports/lab.json` | — | 0 | 범 | 3 |
| laor_ib_data.yml | 수동 | — | `data/study/laor_ib_px.csv` | 연구 일회성 | 0 | 보관 | — |
| library.yml | push(rounds·studies·valuation_notes·peer_reviews) | — | `reports/library.json` | 서고 색인 — 범용판에선 rounds 제외 필요 | 6 | 범 | 1 |
| live.yml | 08:40 · 평일 매시 :07(09~15) · 22:20·23:20 · 매시 :07(23~05) | KRX_ID·KRX_PW·MY_HOLDINGS·MY_RULES·텔레그램 4 | `reports/live.json` 등 | 네이버 금융 polling·toss-live raw | **1,433** | 범(D2) | 4 |
| msgr_feed.yml | push(_requests·`*-msg-*`·CHARACTERS·avatars) | — | `reports/msgr_feed.md` | 사내톡 | 50 | 내 | 1 |
| ops.yml | 23:47 · 00:07 | 텔레그램 4 | ops·board·team·watchdog | 신선도 감시(범) + 보드·팀(내) 섞임 → 11/12 이후 분할 | 7 | 범(분할 후보) | 1 |
| pages.yml | push main(시세 파일 제외) · 수동 | — (변수 PAGES_ACTIONS) | Pages(Actions 방식, 현재 꺼짐) | 실제 배포는 옛 방식 `pages-build-deployment`(브랜치 배포) 551회·959분 | 137 | 범 | 5 |
| pb_call.yml | 수동(텔레그램/GAS) | 텔레그램 4 | `reports/decisions.json` | PB 호출 | 8 | 내 | 1 |
| pick.yml | 이슈 열림(텔레그램 버튼) | MY_HOLDINGS·MY_RULES·RISK_PCT·SAT_BOOK_KRW·텔레그램 4 | `reports/decisions.json`·`ops/isa_buys.json` | 텔레그램 훅 | 1 | 내 | 1 |
| qld_dca_data.yml | 수동 | — | `data/study/qld_dca_px.csv` | 연구 일회성 | 0 | 보관 | — |
| re_hist.yml | 수동 | DATA_GO_KR_KEY | `data/realestate/rtms_hist`·studies | 국토부 RTMS(§3 공공누리 유형 확인 대상) | 0 | 범 | 2 |
| scorecard.yml | 일 08:30 | TELEGRAM_TOKEN·TELEGRAM_CHAT_ID | `reports/scorecard_week.*` | 데스크 적중 채점 | 2 | 내 | 1 |
| screener.yml | 평일 16:20 + GAS | DART_API_KEY·DATA_GO_KR_KEY·ECOS_API_KEY·GCP_SA_JSON·GSHEET_ID·KRX_API_KEY·KRX_ID·KRX_PW·MY_HOLDINGS·MY_RULES·REB_API_KEY·RULE_DEADLINE·RULE_STOP_LEVEL·텔레그램 4·VWORLD_KEY | `reports/*`·릴리스 | Google 시트(GSHEET) · `hk99915-bot.github.io` 링크 | 55 | 범(D2) | 3 |
| study.yml | 이슈 열림 | — | `reports/study_progress.json`·`study_wrong.json`·`_quiz_feedback.md` | 텔레그램 quiz | 1 | 내 | 1 |
| study_daily.yml | 평일 07:10 | TELEGRAM_TOKEN·TELEGRAM_CHAT_ID | `reports/study_daily.json` | 텔레그램 | 1 | 내 | 1 |
| team.yml | 매시 :17 | — | `ops/team.json`·`reports/msgr_feed.md` | 팀 업무량 | 13 | 내 | 1 |
| telegram_test.yml | 수동 | 텔레그램 4 | — | 시크릿 확인용 | 0 | 범 | 5 |
| tests.yml | push(코드·문서 경로)·PR | — | — | CI | 235 | 범 | 1 |
| us_accum.yml | 화~토 07:37 | — | `reports/us_accum.json` | 야후 | 2 | 범 | 2 |
| us_diag.yml | 수동 | — | (로그만) | 야후 진단 | 0 | 범 | 1 |
| us_spikes_data.yml | 수동 | SEC_USER_AGENT | `data/study/spikes` | 연구 일회성 | 0 | 보관 | — |
| us_spikes_intraday_data.yml | 수동 | — | `data/study/spikes_intraday` | 연구 일회성 | 0 | 보관 | — |

- 표본 합계 약 3,360분/2.6일 — 그중 내부판 몫(ask·msgr_feed·pb_call·pick·scorecard·study·study_daily·team) 약 77분(≈2%). 내부판은 비공개 한도 안 `[추정 — 월 환산 전 11/3 PM 재측정]`. msgr_feed(50) 가 내부판 몫의 대부분.
- **옛 방식 Pages 빌드(959분)**: 공개 저장소에선 무료라 문제 아님. 범용판에서도 그대로(브랜치 배포).
- 연구 일회성 6개는 범용판으로 옮기지 않음(산출 데이터는 `data/study` 가 아니라 해당 브랜치에만 — 브랜치를 안 가져가므로 필요하면 그때 다시 수집).

### 1-1. 시크릿 이름 25개 · 저장소 변수 5개 (값은 겸이만)
| 묶음 | 이름 | 개수 | 새 범용판 | 내부판 |
|---|---|---|---|---|
| 데이터 키 | DART_API_KEY·DATA_GO_KR_KEY·ECOS_API_KEY·KRX_API_KEY·KRX_ID·KRX_PW·REB_API_KEY·SEC_USER_AGENT·VWORLD_KEY | 9 | 등록 | — (기존 값 남아 있음) |
| 텔레그램 | TELE·TELE_CHAT·TELEGRAM_TOKEN·TELEGRAM_CHAT_ID (두 쌍 — 옛 이름 호환) | 4 | 등록 | 기존 유지 |
| 개인 규칙 | MY_HOLDINGS·MY_RULES·RULE_DEADLINE·RULE_STOP_LEVEL (D2 현행 유지 시) | 4 | 등록 | 기존 유지 |
| 개인 규칙(내부판 전용) | RISK_PCT·SAT_BOOK_KRW (pick 만 씀) | 2 | **등록 안 함** | 기존 유지 |
| GAS 배포 | CLASPRC_JSON·GAS_SCRIPT_ID·GAS_SCHED_SCRIPT_ID·GAS_DEPLOYMENT_ID | 4 | 등록 | — |
| Google 시트 | GCP_SA_JSON·GSHEET_ID | 2 | 등록 | — |
| 변수(vars) | DATA_BRANCH_KR·DATA_BRANCH_US·KRX_BACKEND·PAGES_ACTIONS·VWORLD_DOMAIN | 5 | 등록 | — |

- 범용판 등록 = 시크릿 23 + 변수 5. 위 이름은 **워크플로가 참조하는 이름** 기준 — 실제 등록 목록(`Settings → Secrets`)은 이 세션에서 조회 불가(프록시 거부) `[확인 필요: 겸이 화면에서 개수 대조]`.
- 비밀 값이 저장소에 있는 건 없음(.gitignore: `.env`·`toss_md/env`·`token.json`).

## 2. 외부 연결 (워크플로 밖)
| 진입점 | 지금 주소·설정 | D1=이름 변경 시 | D1=새 이름 시 |
|---|---|---|---|
| Pages | `hk99915-bot.github.io/market-screener/` · 옛 방식(브랜치 배포, `pages-build-deployment`) | 새 저장소에서 Pages 켜기만(주소 같음) | 주소 변경 + 옛 주소 넘김 페이지 필요(§5) |
| GAS 예약기 `Scheduler.gs` | `REPO = 'hk99915-bot/market-screener'` · 스크립트 속성 `GH_TOKEN`(미세 토큰, 저장소 1개 한정, Actions 읽기·쓰기) · 5분 tick · 20슬롯(briefing 14·live 2·backfill·fin·screener·deriv_hist) | 코드 그대로. **토큰만 새로 발급**(미세 토큰은 저장소 ID 에 묶임 `[규정-B, 11/3 재확인]`) | `REPO` 상수 + 토큰 |
| GAS 웹앱 `Code.gs` | 속성 `GITHUB_REPO`(기본값 같은 이름)·`GITHUB_TOKEN`(Contents 읽기) · pb-private 읽기 토큰 별도 | 토큰만 새로 | 속성·토큰 |
| 텔레그램 훅 `TelegramHook.gs` | `TG_REPO` 로 이슈 생성(ask·study·pick) · 웹훅 URL = GAS 웹앱(바뀌지 않음) | **이슈 받을 저장소를 내부판으로**: `ask`·`study`·`pick` 이슈 = 내부판 → `TG_REPO` 를 내부판 이름으로 (코드 1줄, 11/3~6 개발) · 토큰 새로(내부판 Issues 쓰기) | 같음 |
| 노트북 dispatcher `tools/dispatch/dispatch.py` | `REPO` 상수 · 작업 스케줄러 `gh_dispatch` · 미세 토큰(Actions 읽기·쓰기) | 토큰 교체 + 새 저장소 다시 받기(이력이 다르므로 `git pull` 불가 → 새로 clone) | `REPO` 상수 + 토큰 + clone |
| 노트북 토스 수집기 `tools/toss_md/*` | 작업 스케줄러 `toss_md_live`·`toss_md_sectors` · `--publish` 가 `toss-live` 브랜치로 일반 push(Git Credential Manager 로그인) | 새로 clone 한 폴더로 작업 경로가 같으면(`$HOME\market-screener`) 스케줄러 그대로 · `toss-live` 첫 push 는 부모 없는 커밋으로 자동 생성(publish.py 지원) | + 원격 주소 |
| raw 주소 상수 | `screener/toss_live.py RAW_URL`·`screener/data.py TOSS_EOD_URL` 외 저장소 이름 박힌 파일 26개 | 변경 없음 | 26개 일괄 치환 + 테스트 |
| 릴리스 자산 | `data-latest`(13개)·주간 3개 | 새 저장소로 복사(개발, 11/7 — `data_store.py` 로 받아서 올림) | 같음 |
| Claude 예약 작업·세션 환경 | 세션이 붙는 저장소 = `market-screener` | 내부판(데스크 KB·장부)을 세션 저장소에 **추가** | + 이름 |
| GAS 배포(clasp) | `gas_deploy.yml` 시크릿 4 | 새 저장소에 시크릿 재등록 | 같음 |

## 3. 데이터·문서 디렉터리 분류
범 = 범용판(새 공개, 친구 공유·포트폴리오 링크 가능) · 내 = 내부판(옛 저장소 → 비공개) · 창고 = 비공개 원자료(§1 계획서 `ms-data`, 2단계 — 11/7 엔 릴리스 자산 현행) · 제외 = 범용판 스냅샷에서 빼되 내부판엔 그대로 남음.

| 경로 | 추적 파일 수 | 판 | 근거·조건 |
|---|---|---|---|
| `screener/` | 120 | 범 | 코드. 개인 규칙 모듈 11개(`pb`·`ticket`·`renego`·`isa_lab`·`alerts`·`event_watch`·`defs`·`views`·`topline_from`·`study_progress`·`main` 일부)는 값이 시크릿이라 노출 없음 — 플러그인 분리는 11/12 이후 선택(D2) |
| `scripts/` | 108 | 범 | 단 데스크 운영 스크립트(`ask`·`board`·`round_collect`·`msgr_feed`·`team_*`·`slop_audit`·`drill_grade`)는 내부판 전용 후보 — 11/7 엔 같이 두고(테스트 의존) 11/12 이후 이동 |
| `tools/dispatch`·`tools/toss_md` | 25 | 범 | 수집기. 원본(`toss_md_data`)은 원래 저장소 밖 |
| `tests/` | 206 | 범 | 내부 경로를 읽는 테스트는 제외 목록과 함께 조정(§6 작업량) |
| `apps-script/` | 23 | 범(탭 일부 내) | 시장 탭 = 범: home·market·mkt_deriv·mkt_macro·bond·detail·research·daily·quant · 내부 탭 = 내: my·life·isalab·msgr·duel·study·committee(데스크 발언)·rboard·system · realestate 는 '🔒 내 계획' 칸만 내부 `[프론트 확인]` |
| `index.html` | 1 | 범 | 빌드 산출 — 내부 탭 숨김 플래그로 재생성 |
| `universe/` | 16 | 범 | 종목 목록·섹터 매핑(가공) |
| `data/fin`·`data/dart_biz`·`data/deriv`·`data/flows`·`data/hist`(매니페스트)·`*.parquet`(research·dart·short_hist) | — | 범(가공·공시) / 창고(원 일봉) | 큰 원 일봉은 이미 릴리스 자산. §3 '가공값만' 출처(KRX·야후)의 원 시계열 parquet 은 2단계에 창고로 `[데이터·컴플 원문 대조 뒤 확정]` |
| `data/realestate/rtms_hist` | — | 범 또는 창고 | 공공누리 유형 4 이면 집계 비율만 — 데이터 데스크 판정 대기 |
| `reports/detail/` | 2,073 | 범 | 종목 상세(가공). 원값 시계열 칸은 §3 표대로 2단계 정리 |
| `reports/` 시장 산출(heatmap·macro_*·bonds·derivs·dotplot·valuation·peers·momentum·trend·signals·public_reports·disclosures·library 등) | — | 범 | 가공 신호 |
| `reports/studies/` | 96 | 범(23개 문구 정리) | 연구 요약. 23개 파일에 '겸이' 인용 — 범용판 다듬기에서 '오너'로 |
| `reports/` 개인·데스크 산출(decisions·battle_*·alphabook·hf_*·practice_book·portfolios·isa_lab_returns·scorecard_week·study_*·msgr_feed·ideas_log·views_attrib·committee*·audit·ops·logs) | — | 내 | 개인 행동·결재·데스크 대결·사내톡 |
| `docs/valuation_notes`·`docs/peer_reviews` | 12·12 | 범(문구 정리 8개) | 분석 산출물 |
| `docs/` 시스템 문서(data_go_kr_apis·hist_warehouse·heatmap·schedule_table·data_sources_wishlist·toss_md_laptop_setup·study_spec·idea_tracking·bonds_short_duration_alts) | 9 | 범 | 일부 '겸이' 인용 문장 정리 |
| `docs/desk_kb/industry_onepager_template.md`·`STANDARD.md` | 2 | 범 | '산업 한 장 틀'·현업급 기준 |
| `docs/desk_kb/` 나머지(데스크 KB·LOOP·OKR·ORG·VISION·rounds·onboarding)·`docs/uxui`·`docs/study_consults`·`docs/realestate`·`docs/my_tab_holdings_plan`·`journal_skeleton`·`rules_terms`·`telegram_pick_buttons`·`refactor_*` | — | 내 | 데스크 운영·겸이 발언·결재 |
| `content/` (study·drills·onboarding·retest) | 51 | 내 | 학습·드릴(drills 29개 전부 겸이 인용) |
| `ops/` (board·team·locks·cooldown·renego·isa_buys·freshness*) | 12 | 내(freshness 두 개만 범) | 보드·개인 장치 카운터 |
| `assets/avatars`(약 60MB)·`assets/office_world` | — | 내 | 캐릭터 |
| `assets/realestate_geo`·`realestate_map.json` | — | 범 | 지도(중심점만) |
| `views/`·`notes/` | 3 | 내 `[프론트·애널 확인]` | 뷰 등록부·연구 매뉴얼 |
| `.github/workflows` | 37 | §1 표의 판대로 | |
| `.claude/skills` | — | 내 | 데스크 스킬 |

### 3-1. 범용판 스냅샷 제외 목록 (개인정보 흔적 — 감사 10/27 `audit_privacy.md` 기준)
| 경로 | 이유 | 감사 근거 |
|---|---|---|
| `docs/desk_kb/rounds/_requests.json` | 이력에 연봉·식대·지원 월액·순자산 원값(치명 4커밋 중 2), 현재도 개인 맥락 요청 다수 | L-1·L-3·L-7 |
| `reports/msgr_feed.md` | 위 2건 복사본 이력 | L-1·L-3 복사 |
| `reports/audit/` 전체 | evidence 칸 인용이 2차 누출(10/26 L-7 인용 4건) | 감사 So What |
| `docs/desk_kb/OKR.md` | 목표 금액 이력(현재 HEAD 지움) — 개인 목표 문서 | 83dc1d093 |
| `reports/logs/pdf_boxes.json`(이미 무시 목록)·`reports/logs/` 전체 | 애널리스트 이메일 이력 | D1 10/21 |
| `ops/cooldown.json`·`ops/renego.json`·`ops/isa_buys.json` | 개인 매매 행동 시각·횟수 | 개인 행동 |
| `reports/decisions.json`·`reports/battle_*`·`reports/practice_book.json`·`reports/portfolios.json` | 개인 결재·모의 북 | 개인 행동 |
| `docs/office_world/`·`docs/desk_kb/CHARACTERS.md`·`PERSONAS.md`·bios·`assets/avatars`·`assets/office_world` | 캐릭터 설정(PB 추가 지시) — 개인정보는 아니나 범용판 범위 밖 | — |
| 이력 전체 | 새 저장소 = HEAD 스냅샷 1커밋(이력 안 가져감) | 치명 4커밋 자연 소멸 |
| 오래된 브랜치 9개 | 안 가져감(D3) | 이메일 남은 브랜치 |

- 스냅샷 직전 검사: `scripts/privacy_history_audit.py` 를 **스냅샷 트리에 대해** 1회(약 2분) + pre-push 금액·이메일 검사 → 감사 데스크 확인(req 등록).

## 4. 겸이가 직접 할 일 (순서·소요 — D1=이름 변경 기준)
| # | 언제 | 할 일 | 소요 |
|---|---|---|---|
| 0 | 11/2(일)까지 | 이 문서 D1·D2·D3 답 (텔레그램 한 줄) | 5분 |
| 1 | 11/6(금) 밤 또는 11/7 오전 | 옛 저장소 이름 변경(`Settings → General → Repository name`, 예 `market-screener-desk`) — **장 시간 밖**. 이 순간부터 GAS·노트북 dispatch 는 실패(대상 없음) → cron fallback(+12분)이 옛 쪽에서 돎(안전) | 2분 |
| 2 | 바로 이어서 | 새 공개 저장소 `market-screener` 만들기(빈 저장소, README·라이선스 체크 해제 — 개발이 스냅샷을 올림) | 3분 |
| 3 | 개발 스냅샷 push 뒤 | 새 저장소 시크릿 23개 + 변수 5개 재등록(§1-1 표 순서대로, 옛 저장소 화면을 옆에 띄우고). **RISK_PCT·SAT_BOOK_KRW 는 등록 안 함** | 20~25분 |
| 4 | 3 뒤 | Pages 켜기: `Settings → Pages → Deploy from a branch → main / (root)` (지금과 같은 방식) | 3분 |
| 5 | 4 뒤 | 미세 토큰 3개 새로 발급(저장소 = 새 `market-screener`): ① GAS 예약기 Actions 읽기·쓰기 ② 노트북 dispatcher Actions 읽기·쓰기 ③ GAS 웹앱 Contents 읽기 · 내부판용 1개 ④ 텔레그램 훅 Issues 쓰기(저장소 = 내부판) | 10분 |
| 6 | 5 뒤 | GAS: 스크립트 속성 `GH_TOKEN`·`GITHUB_TOKEN`·(훅 토큰) 교체 → `tickTest` 실행해 로그 첫 줄·오늘 시간표 확인. 텔레그램 훅 코드(`TG_REPO`) 갱신본 붙여넣기(개발이 11/6 까지 준비) | 10분 |
| 7 | 6 뒤 | 노트북: 기존 폴더 이름 바꿔 보관 → 새로 clone(`$HOME\market-screener`) → dispatcher 토큰 교체 → 토스 수집기 `--publish` 첫 push 때 브라우저 로그인 1회 → `Get-ScheduledTask` 3개 그대로인지 확인 | 15~20분 |
| 8 | 11/7 저녁 | 옛 저장소(이름 바뀐 쪽) 변수 `ALERTS_OFF` = `1` 추가 → 텔레그램에서 새 쪽 `telegram_test.yml` 결과 1통 받기(새 쪽 시크릿 확인) | 4분 |
| 9 | 11/9~11 | 아침 1회 PM 병행 판정 한 줄 보기(할 일 없음, 이상 시 '롤백' 한 단어) | 하루 1분 |
| 10 | 11/14(토) 이후 | 옛 저장소(내부판) `Settings → Danger Zone → Change visibility → Private` | 2분 |
| 11 | 같이 | 세션 환경에 내부판 저장소 추가(Claude 설정) | 3분 |

- **합계 약 75~90분**(11/6~7 이틀에 몰림, 그중 시크릿 재등록이 가장 김). D1=새 이름이면 +GAS `REPO`·노트북 원격·북마크 변경 약 15분, 개발 쪽 26파일 치환 추가.

## 5. 위험·롤백
| 위험 | 대응 | 롤백 |
|---|---|---|
| **알림 이중 발송**(텔레그램 시크릿을 쓰는 워크플로 11개: briefing·live·screener·health·heartbeat·ops·scorecard·study_daily·pb_call·pick·telegram_test) | 지금은 전역 무음 스위치가 없음(screener 의 `no_send` 는 수동 입력만) → **개발 11/3~6: 저장소 변수 `ALERTS_OFF=1` 이면 텔레그램 발송 함수가 보내지 않고 로그만** (발송 지점 한 곳에서 확인, 테스트 포함). 11/7 옛 저장소에 변수 설정 → 옛 쪽은 산출물만 만들어 대조, 알림은 새 쪽만. 옛 쪽 pick·pb_call 은 disable(이슈·호출은 새 쪽/내부판으로만 옴). GAS·노트북 dispatch 는 이름이 새 쪽을 가리켜 자동으로 새 쪽만 | 새 저장소에 `ALERTS_OFF=1` + 옛 저장소 변수 삭제(5분). 이름까지 되돌리면 새 저장소 이름 변경 → 옛 이름 복구(+5분) |
| 옛 cron fallback 이 옛 쪽에서 돌며 커밋(병행 기간) | 정상 — 대조 재료. 슬롯 가드는 dispatch 가 없으니 +12분 뒤 실행. 데이터 쓰기는 옛 저장소 안에서만 | — |
| 옛 Pages 주소 | D1=이름 변경이면 **주소 그대로라 넘김 불필요**. 이름 변경~비공개 전환 사이 옛 쪽 Pages 는 `/market-screener-desk/` 로 옮겨 감(쓰는 사람 없음). 비공개 전환 시 옛 Pages 는 꺼짐 — 비공개 Pages 는 유료 플랜 `[확인 필요]` | D1=새 이름일 때만: 옛 저장소 비공개 전 `index.html` 을 새 주소로 보내는 `meta refresh` 한 장으로 교체 — 단 비공개 전환 순간 그것도 사라짐 → 북마크 갱신 공지가 유일한 수단 |
| 시크릿 누락(빈 문자열로 조용히 실행) | 11/7 첫 실행 전 개발이 '필수 시크릿 비었으면 실패' 한 단계 확인(이미 있는 가드 점검) + `telegram_test` | 누락분 등록 후 재실행 |
| 릴리스 자산 미복사 → 첫 실행이 원 일봉 없이 돎 | 11/7 개발이 `data_store.py` 로 13개 복사·매니페스트 해시 대조 후에만 Pages·예약 켬 | 옛 저장소 릴리스는 비공개 전환 전까지 공개 다운로드 가능 |
| 노트북 clone 실패·토스 publish 인증 | 7번을 장 없는 토요일에. 실패해도 화면은 네이버·야후 대체(설계상) | 보관해 둔 옛 폴더로 스케줄러 경로 되돌림 |
| 범용판에 내부 경로 재유입 | pre-push 훅에 '범용판 금지 경로' 목록(§3-1) 추가 — 감사 경계 검사 req | 해당 커밋 revert |
| 비공개 분 한도(내부판) | 내부판 워크플로 8개만 남기고 나머지 옛 워크플로는 비공개 전환 전 전부 disable | 초과 시 msgr_feed 를 push 트리거 → 하루 1회로 |
| 이미 퍼진 이력 | 회수 불가 — 새 저장소로 '앞으로'만 막음(계획서 §4 한계 그대로) | — |

### 5-1. 11/12(Pro 전환) 이후 남는 일 — 최소화
- **필수**: 겸이 비공개 전환 1클릭(#10) · PM 병행 판정 종료 한 줄. 개발 작업 0 이 목표.
- **선택(Pro 기준 소량씩, 기한 없음)**: 범용판 다듬기(§6) · 개인 규칙 모듈 플러그인화(D2) · ops.yml 분할 · 원자료 창고(2단계) · 데스크 운영 스크립트·KB 를 내부판으로 완전 이동.
- 11/7 이전에 끝내야 하는 개발 일(11/3~6): `ALERTS_OFF` 무음 변수 · 스냅샷 생성 스크립트(제외 목록 적용·트리 검사) · 내부 탭 숨김 빌드 플래그 · `TG_REPO` 내부판화 · 범용판 README 골격 · 내부판에서 돌릴 워크플로 8개 경로 점검 · 릴리스 복사 절차. `[추정: 개발 세션 2~3회]`

## 6. 범용판 — 캐릭터·개인 표현 걷어내기 작업량 (PB 11/1 추가)
| 영역 | 현황(줄 수, 11/1 grep) | 방법 | 추정 |
|---|---|---|---|
| 내부 탭 숨김(my·life·isalab·msgr·duel·study·committee·rboard·system) | msgr 한 탭에 '겸이' 19·'누나' 3·'사담' 13 | 빌드 플래그로 범용판 `index.html` 에서 제외 + ui_smoke 범용판 모드 | 2~3시간 · **11/7 전 필수** |
| 화면 문구(시장 탭) | '겸이' 약 50줄(market 6·mkt_macro 6·research 6·realestate 8 등), '누나' 2 | 수동 — 주어를 '오너'/생략으로, 판단 문구는 유지 | 2시간 · 11/12 이후 가능 |
| 코드 주석·문자열(screener·scripts·tools) | '겸이' 188줄·'누나' 9·'사담' 13 | 주석은 기계 치환(겸이→오너) + 사용자에게 보이는 문자열만 수동 검토 | 1~2시간 |
| 테스트 | '겸이' 62줄·'누나' 9·'사담' 5 | 문구 고정 테스트 같이 수정 | 1시간 |
| 워크플로 주석 | '겸이' 16줄 | 기계 치환 | 15분 |
| 문서(범용판에 남는 것) | studies 23·valuation_notes 6·peer_reviews 2·시스템 문서 6 파일 | '겸이 결정' → '오너 결정', 개인 맥락 문단 삭제 | 2~3시간 |
| README(소개·아키텍처·'에이전트가 한 것/내가 한 것' 칸) | 없음 | 골격은 11/7 전(30분), 본문은 겸이와 | 1시간 + 겸이 30분 |
| 개인 규칙 모듈 분리(D2) | 모듈 11개 · 시크릿 6 | 플러그인 인터페이스 + 내부판 쪽 구현 | 2~3일 `[추정]` · 선택 |

- 합계(필수 제외 다듬기): **약 8~10시간 개발 작업**(세션 3~4회) `[추정 — 실제는 화면 문구 검토 속도에 좌우]`. 캐릭터 문구는 개인정보가 아니므로 11/7 전환을 막지 않음 — 11/7 범용판은 '내부 탭 숨김 + 제외 목록' 까지만.

## 7. 요청(장부 등록, 마감 11/5)
- PM: 일정 확정(11/3~6 개발 일감·11/7 전환 순서·11/9~11 병행 판정 기준 3일 연속 불일치 0) + 비공개 분 월 환산 재측정
- 데이터: 계획서 §3 `[확인 필요]` 원문 대조(KRX·야후·DART·data.go.kr 유형·네이버) → §3 분류의 '범/창고' 확정
- 컴플라이언스: §3 재배포 '금지' 출처가 범용판 경로에 들어가는지 대조 + 제외 목록 검토
- 프론트: 탭 범/내 분류 확인 · 범용판 화면 주소(D1 결과별) · 내부 탭 숨김 플래그 범위
- 감사: 범용판 스냅샷 트리 경계 검사(privacy_history_audit 트리 모드 + 금지 경로 pre-push 목록)
