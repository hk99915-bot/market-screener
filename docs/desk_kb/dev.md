# dev 데스크 KB (개발)

(형식은 README.md. 개발 데스크는 코드·CI·빌드·알림 배관을 맡는다. 재무·시세 정의는 각 데스크 KB 를 인용하고 여기엔 **배관 지식**만 적는다.)
최근 갱신: 2026-10-17 (재발방지대책 — 신선도 계약·asof 가드)

## 성격·성향
- **한 줄:** 가장 많이 만들고, 그래서 먼저 부서질 자리를 스스로 아는 실행가.
- **판단 성향:** 공격(빠른 구축) 뒤 정지 요청 · 사실 위주 보고.
- **말버릇:** "하루만 멈추게 해 달라, 지은 걸 세어 보게."(TH:dev §5) · "나는 오늘 기분이 좋고, 동시에 바닥났다."(TH:dev 머리말)
- **맹점:** 공유 체크아웃에서 남의 변경 혼입을 늦게 인지(KB:dev 복기).
- **긴장:** ↔교육·평가 — 화면 연동 요청(handoff) 대기(TH:edu §3, TH:edu_junior §3).
- 원본: [PERSONAS.md#dev](PERSONAS.md#dev) — 이 절은 요약, 갱신은 원본 먼저.

## 정의
- [규정-공식문서] 텔레그램 Bot API `sendMessage` 의 `disable_notification`(Boolean): 메시지를 **조용히** 보낸다 — 받는 쪽에 알림은 뜨지만 소리·진동이 없다. 메시지 길이 상한 4096자(우리는 3800자에서 쪼갬), `parse_mode=HTML` 은 `<b><i><a>` 등 제한된 태그만. (https://core.telegram.org/bots/api#sendmessage — 이 세션 네트워크에서 원문 재확인 못 함, 링크로 대체)
- [경험] 소리 정책은 **함수 기본값 + 호출부 분류** 둘로 나눈다: `screener/report.py send_telegram(text, *, disable_notification=True)` 는 기본 무음, 소리는 호출부가 `False` 로 명시. 내용이 날마다 바뀌는 알림(규정 알림·PB 아침 점검·주문표 판정)은 `report.loud(text)`(본문에 ⛔/⚡) 로 결정한다.
- [규정-내부] 결재 #9(2026-10-17): 소리 나는 알림은 ⛔(규정 집행: 손절 2일·발동선 터치·한도 도달) · ⚡(15:05 급락일 종가 매수 신호) · 14:25 반등일 판정 **셋뿐**. 나머지(브리핑·점도표·대결·운용회의·밸류·스터디·점검·성적표)는 무음.

## 잠금 규약 (ops/LOCKS.md 요약)
- 공유 파일(`apps-script/Index.html`·`tab_*.html`·`Code.gs`·`scripts/build_pages.py`·`screener/committee.py`·`screener/main.py`·`.github/workflows/*`)은 `python scripts/lock.py take <파일> --owner <담당> --task <보드id>` 로 잠그고 **잠금 커밋을 먼저 푸시**한 뒤 고친다. `screener/` 의 나머지 모듈은 잠금 대상이 아니다.
- [경험] 여러 데스크가 **같은 체크아웃**(작업 사본)에서 동시에 편집·커밋한다 — `git add -A` 금지. 내 hunk 만 `git add <파일>` 또는 `git diff | 필터 | git apply --cached` 로 올린다. 남의 미커밋 변경이 내 파일에 섞여 있으면 그 hunk 는 두고 간다.

## CI · 빌드 파이프라인
- `.github/workflows/tests.yml`: main push(`screener/** scripts/** tests/** requirements.txt`)·PR 마다 `python -m pytest -q` (네트워크 없는 순수 로직만, 수 초). `pytest.ini` testpaths=tests.
- 푸시 전 로컬: `python3 -m pytest tests/ -q` → `python3 scripts/check_functions.py`(화면 파일 최상위 이름 소실·`<script>` 문법·`index.html` 신선도·남의 잠금) → (보드 바꿨으면) `python3 scripts/board.py --check`. 화면 파일을 고쳤으면 `python scripts/build_pages.py` 로 `index.html` 재생성(산출물, 잠금 없음).
- 알림 배관: `briefing.yml` cron → `screener/main.py --mode <mode>` → 모듈별 `run(send=…)` → `report.send_telegram`. 호출부 목록은 라운드 파일 `rounds/2026-10-17/dev.md` 의 분류표.
- 테스트에서 텔레그램을 흉내 낼 땐 `report.CFG.telegram_token/chat` 과 `report.requests.post` 를 monkeypatch (tests/test_telegram_silent.py).

## 보존 규칙 (결재 #10 ②, 데이터 요청 10/17)
- 설계: `scripts/retention.py` — 기본 드라이런(삭제 후보만 `reports/logs/retention_YYYY-MM-DD.json` 에 기록), `--apply` 때만 삭제, 대상은 `git ls-files` 추적 파일 중 archive 90일·signals/anomalies 10일 초과분. ops.yml 은 드라이런만 매일, `--apply` 는 `workflow_dispatch` 입력으로만. 상태: 미착수(데이터 초안 → 개발 테스트·연결, 라운드2). 반대 근거: 드라이런 로그가 매일 커밋되면 reports/ 잡음이 늘어난다 → 변경 있을 때만 커밋으로 완화.

## 신선도·asof 가드 (10/17 재발방지대책 — 오너 "다시는 이런 일 없도록")
- **계약** `ops/freshness.json` 21항목: 산출물별 {경로, 날짜 키, kind(session/intraday/team), 준비 시각, 허용 지연, 담당 모드, 복구 명령}. 거래일 달력 = `screener/tradecal.py`(KR·US 휴장일 2026~27, [확인 필요: 2027 KR 음력·대체공휴일 KRX 공지 대조, 12/31까지]).
- **점검** `screener/freshness.py check(now)` → `reports/freshness.json`{late, regress_today, stale_today}. 실행: briefing.yml 모든 모드 끝(`--mode freshness`, 무음) · health.yml 08:20·20:10 KST(`--mode freshness_alert`, 늦음·역행·대체가 있으면 ⛔ **소리** 1통, 같은 항목·기대일은 하루 1회 — `reports/freshness_alert_state.json`). 소리 정책 예외는 오너 10/17 직접 지시(결재 #9 의 3종 + 이것).
- **가드** `screener/guard.py` write_json/write_text/allow: 일 단위 비교, 같은 날 허용, 과거면 안 쓰고 `regress_blocked` 기록. 백필만 `SCREENER_ALLOW_REGRESS=1`.
- **저장 단계** briefing·screener.yml: `pull --rebase -X theirs` 뒤 `python -m screener.regress_git` — 원격보다 과거 날짜 파일은 원격 판으로 되돌리고 amend(수동·주말 dispatch 포함, 상세는 폴더 통째).
- **화면** 상단 헤더 `#fresh` 배지(⚠ 늦은 데이터 n / 데이터 정상 · 점검 hh:mm) → 클릭 시 서랍에 파일·기대·실제·담당·복구 명령. `scripts/ui_smoke.py` 가 실파일 + 늦음 주입 2경우를 검사.
- **데이터 계약** `screener/contracts.py`(14 산출물: schema_version·필수 키·형·날짜 키) — `guard.write_json` 이 쓰기 직전 검사, 위반이면 안 쓰고 `contract_violation` 기록. 저장소 현재 파일도 테스트가 같은 계약으로 검사(tests/test_contracts.py).
- **규칙 상수 단일 원천** `screener/defs.py`(분모 D1~D5·한도·판정·주문표 상수) — rebound·alerts·committee·pb·ticket 이 import. `check_rules_terms.py` 가 숫자 재정의·화면(tab_my) 불일치·용어표 미등록을 잡음.
- 가드 적용(16 호출부): detail KR·US(색인 판정, 폴더 통째) · peers_* · sim_signals_* · latest_*.md · momentum_* · derivs(date) · committee(date, 3곳) · committee_us · valuation(json·md·이력) · bonds · daily_brief(json·md) · macro_view · japan(date) · macro_series + main.run 시세 기준일 판정. **미적용**: 보드 `guard-rest` 참조.

### 조용한 대체 지점 (grep: 뒤로 걷는 날짜 루프·"이전 값 유지", 10/17)
| # | 위치 | 동작 | 조치 |
|---|---|---|---|
| 1 | screener/derivs.py build | 목표일 실패 → 전일 KRX 옵션 | PB stale 플래그 + 이번: KRX 휴장일 반영·freshness 기록 |
| 2 | screener/main.py run | 시세 최빈 기준일 < 기대 거래일 | 이번: 재시도 3회(90초) → [STALE] 표시·기록, 게시본보다 과거면 중단 |
| 3 | screener/bonds.py ai_credit | 야후 실패 → 이전 블록 | 이번: o.stale.ai_credit + 기록 |
| 4 | screener/bonds.py etf·corr·credit_us | 야후 실패 → 이전 블록 | 이번: o.stale.etf + 기록 |
| 5 | screener/main.py write_macro_series | 빠진 지표 → 이전 시계열 / 2년 실패 → 200일 | 이번: macro_series.stale{지표: 마지막일} + 기록(JGB10Y 제외 — japan 이 채움) |
| 6 | screener/committee.py _flows | 전일 외국인 수급을 7일까지 뒤로 | 미처리(라벨 '전일' 이 더 과거일 수 있음) |
| 7 | screener/universe.py:45·283 | KRX 목록 8·10일 뒤로 | 미처리(유니버스, 영향 낮음) |
| 8 | screener/shares.py:107 | 상장주식수 8일 뒤로 | 미처리 |
| 9 | screener/drivers.py:736 | US EPS 캐시 재사용(max_age) | 미처리 |
| 10 | screener/macroview.py:181 | 같은 라벨이면 이전 요약 재사용 | 미처리(문구만) |
| 11 | screener/japan.py:211 | macro_series 에 직접 병합(가드 우회) | 미처리 → guard-rest |
| 12 | screener/shorts.py:47 | 30일 뒤로 누적 수집 | 해당 없음(빠진 날 채우기) |

## 흔한 오해
- [경험] "무음이면 안 보인다" → 아니다. 메시지·배지는 그대로 오고 **소리만** 없다. 그래서 정보성 알림을 무음으로 돌려도 손실이 없다.
- [경험] 호출부마다 `if CFG.telegram_token and CFG.telegram_chat:` 를 반복하지 않는다(dotplot 에 남아 있음) — `send_telegram` 이 미설정이면 RuntimeError 를 내고, 호출부는 `try/except` 로 로그만 남기는 것이 현재 관행.

## 우리 연구와의 차이
- (없음 — 개발 데스크는 자체연구 등급을 내지 않는다. 다른 데스크의 연구는 `검증` 데스크가 재현한다.)

## 출처
- Telegram Bot API, sendMessage — core.telegram.org/bots/api (2026-10-17 링크, 원문 미확인)
- ops/LOCKS.md · ops/README.md 푸시 프로토콜 · .github/workflows/tests.yml (2026-10-17 코드 기준)

## 변경 기록 (테스트·롤백·영향)
- 2026-10-17 [운영] send_telegram 기본 무음(결재 #9): 테스트 tests/test_telegram_silent.py 7건 · 롤백 = 기본값 `disable_notification=False` · 영향 = briefing/pick/lab/health 워크플로의 알림 소리만, 스케줄·시크릿 불변. 뒤집는 조건: 10/20 첫 거래일에 ⛔·⚡·14:25 가 안 울리거나 정보성 알림이 울리면.

- 2026-10-17 [운영] 신선도 계약·asof 가드·역행 검사·헤더 배지: 테스트 tests/test_freshness_guard.py 29건 + ui_smoke 배지 2경우 · 롤백 = 해당 커밋 revert(가드는 쓰기만 막으므로 revert 시 예전 덮어쓰기로 복귀) · 영향 = briefing·screener·health 워크플로(저장 단계·08:20/20:10 cron 추가·⛔ 소리 알림), 상단 헤더, GAS 는 Code.gs 재붙여넣기 전엔 배지 숨김.

## 복기
- 2026-10-17 (사고 3) 틀림: 토 09:46 KST 수동 detail_us(커밋 9ea9efbd)가 US 580파일을 10/16→10/15 로 덮음 → 왜: ① Yahoo 가 그 호출(금 20:47 ET)에서 **종목 523개 전부 10/16 봉을 빼고** 줌 — 종목당 행 273.4 vs 직전 275.4(시작일 1일 이동 −1, 마지막 봉 누락 −1), 같은 실행의 지수(^GSPC·^IXIC)는 10/16 있음(macro_series). Yahoo 측 원인은 네트워크 차단으로 재현 못 함[확인 필요: 다음 금요일 20~24시 ET 에 yf.download 로 재현, 10/24까지]. ② 코드엔 "지금이면 어느 봉이 있어야 하나"가 없어 최빈 날짜(10/15)를 그대로 기준일로 삼고 `_status` 는 시계만 보고 CONFIRMED. ③ 모든 쓰기가 무조건 덮어쓰기, 저장 단계 `-X theirs` 는 늦은 실행을 이기게 함 → 다음부터: tradecal.expected_session 으로 기대일 계산·재시도, 게시본보다 과거면 중단, 가드·regress_git 이중 차단. 재현 테스트 tests/test_freshness_guard.py::test_saturday_us_regress_is_refused. 덤: main.run 인자 `live`(bool)가 모듈을 가려 `live.patch_macro` 가 매 실행 실패하던 것도 수정.
- 2026-10-17 (라운드1) 틀림: 작업 사본이 내 것뿐이라 여기고 `git diff --stat` 를 보기 전까지 남의 변경(bonds·ticket·duel 60줄+)이 섞인 줄 몰랐다 → 왜: 데스크 12개가 한 체크아웃을 공유한다는 전제를 브리프의 "동시에 push 중" 에서 읽어내지 못함 → 다음부터: 편집 전 `git status -s` 를 찍고, 커밋은 파일·hunk 단위로만 올린다.
