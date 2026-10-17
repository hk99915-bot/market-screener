# dev 데스크 KB (개발)

(형식은 README.md. 개발 데스크는 코드·CI·빌드·알림 배관을 맡는다. 재무·시세 정의는 각 데스크 KB 를 인용하고 여기엔 **배관 지식**만 적는다.)
최근 갱신: 2026-10-17 (라운드1 — 결재 #9 '⛔만 소리')

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

## 복기
- 2026-10-17 (라운드1) 틀림: 작업 사본이 내 것뿐이라 여기고 `git diff --stat` 를 보기 전까지 남의 변경(bonds·ticket·duel 60줄+)이 섞인 줄 몰랐다 → 왜: 데스크 12개가 한 체크아웃을 공유한다는 전제를 브리프의 "동시에 push 중" 에서 읽어내지 못함 → 다음부터: 편집 전 `git status -s` 를 찍고, 커밋은 파일·hunk 단위로만 올린다.
