# 운영 (ops)

여러 AI 에이전트(퀀트·채권·리스크·백테스트·LIFE·자산배분·운영 누나, 팀장 PB)가 이 저장소를 동시에 고친다.
이 폴더는 **누가 무엇을 고치는지(보드)**, **누가 어떤 파일을 잡고 있는지(잠금)**, **무엇이 바뀌었는지(이력)** 를 한곳에 둔다.

> 이 저장소는 **공개**다. 보유 종목·수량·거래·금액·급여·건강 등 개인 데이터는 보드·메모·커밋 메시지 어디에도 쓰지 않는다.
> private 저장소(pb-private) 작업은 보드에 `repo: "private"` 로 제목만 올리고, 그쪽 커밋 메시지는 절대 가져오지 않는다.

## 파일

| 경로 | 내용 | 갱신 |
|---|---|---|
| `ops/board.json` | 작업 보드 원본 (id·제목·담당·우선순위 P0~P3·상태·시작·기한·파일·선행·메모) | 사람·에이전트가 직접 |
| `ops/BOARD.md` | 사람이 읽는 판 | `python scripts/board.py` |
| `ops/locks.json` | 공유 파일 잠금 | `python scripts/lock.py` — 규칙은 [LOCKS.md](LOCKS.md) |
| `reports/changelog.json` | 날짜별·영역별 변경 이력 (봇 자동 커밋은 '자동 갱신 N회'로 접음) | `python scripts/changelog.py` |
| `reports/ops/daily/YYYY-MM-DD.md` | 작업내역 보고 (바뀐 것·보드 변동·열린 이슈) | 〃 |
| `reports/ops/runs.json` | 최근 24h 워크플로 실행 통계·예약 지연·백업 예약기(GAS) 도착 | `python scripts/ops_runs.py` |

`.github/workflows/ops.yml` 이 매일 23:47 KST 에 위 세 스크립트를 돌려 커밋한다 (수동 실행 가능). 웹은 **SYSTEM** 탭(작업 보드 · 변경 이력 · 운영 상태).

## 에이전트 작업 프로토콜 (필수)

```
fetch → rebase → (잠금) → 편집 → check_functions → build → check_functions → push → (잠금 해제) → 보드 갱신
```

1. **최신화**
   ```bash
   git fetch origin && git rebase origin/main
   ```
2. **잠금** — 공유 파일(`apps-script/Index.html`·`apps-script/tab_*.html`(고칠 탭만)·`Code.gs`·`scripts/build_pages.py`·`screener/committee.py`·`screener/main.py`·`.github/workflows/*`)을 고칠 거면 [LOCKS.md](LOCKS.md) 대로 잠금 커밋을 먼저 푸시.
3. **편집** — 남의 함수·변수는 지우지 않는다. 화면은 `apps-script/tab_*.html`(탭별) 과 `apps-script/Index.html`(공용 셸) 에서만 고친다 (`index.html` 은 산출물).
   탭 함수는 그 탭 파일에, 여러 탭이 쓰는 도우미는 셸에. 파일 사이에 같은 최상위 이름을 두지 않는다 (`check_functions.py` 가 잡는다).
   새 데이터 getter 는 `apps-script/Code.gs` **와** `scripts/build_pages.py` 양쪽에 같은 이름으로 추가.
4. **푸시 직전 다시 최신화 + 검사**
   ```bash
   git fetch origin && git rebase origin/main          # 충돌 나면 '양쪽 모두 살리는' 쪽으로 해결
   python scripts/check_functions.py                    # 사라진 함수·변수 이름 / <script> 문법 / 빌드 최신 / 잠금 / 충돌 표시·JSON
   python scripts/build_pages.py                        # index.html 재생성
   python scripts/check_functions.py                    # 빌드 결과까지 다시 확인 → '통과' 여야 함
   git add -A && git commit … && git push origin HEAD:main
   ```
   - 실패 `사라진 이름: X` → 리베이스·머지 중에 남의 코드를 지웠다는 뜻. `git show origin/main:apps-script/Index.html` 에서 되살린다.
     정말 일부러 지운 것만 `--allow-removed X` 로 통과시키고 커밋 메시지에 이유를 적는다.
   - 실패 `문법 오류` → 해당 `<script>` 행 근처 수정. 푸시 금지.
   - push 가 거절되면(그새 남이 푸시) 4번을 처음부터 반복.
5. **잠금 해제 + 보드** — `python scripts/lock.py drop --owner "<내 이름>"`, `python scripts/board.py --set <id> 검수`(또는 완료) 후 함께 커밋·푸시.

## GAS 웹앱에 붙여넣기 (화면 파일 분리 후)

script.google.com 프로젝트에는 **폴더가 없다**. 아래 파일을 각각 같은 이름으로 만들어 붙여넣는다 (HTML 파일은 `파일 추가 → HTML`, 이름은 확장자 없이 `tab_daily` 처럼 — 처음 한 번만 만들고, 그 뒤로는 바뀐 파일만 덮어쓴다).
`Index.html` 의 `<?!= include('tab_x') ?>` 를 `Code.gs` 의 `include()` 가 같은 이름의 파일 내용으로 바꾼다. 파일 하나라도 빠지면 웹앱이 `No HTML file named tab_x` 오류로 열리지 않는다.

| # | 파일 (GAS 이름) | 종류 | 내용 |
|---|---|---|---|
| 1 | `Code.gs` | 스크립트 | 데이터 getter · `doGet` · `include` |
| 2 | `Scheduler.gs` | 스크립트 | 예약기 (쓰는 경우만) |
| 3 | `Index` | HTML | 공용 셸 (head·CSS·탭 바·도우미·render) |
| 4 | `tab_market` | HTML | MARKET › KR·US·히트맵·전종목 |
| 5 | `tab_home` | HTML | HOME |
| 6 | `tab_daily` | HTML | DAILY › 데일리 리포트·VIEWS·브리핑 기록 |
| 7 | `tab_my` | HTML | MY |
| 8 | `tab_life` | HTML | LIFE |
| 9 | `tab_research` | HTML | RESEARCH › 리서치·밸류에이션·공시 |
| 10 | `tab_quant` | HTML | QUANT › 공급망·시그널·스터디·연구소·모멘텀·모의 포트폴리오 |
| 11 | `tab_bond` | HTML | MARKET › 채권 |
| 12 | `tab_study` | HTML | STUDY › 커리큘럼·인적성·영어 |
| 13 | `tab_committee` | HTML | DAILY › 운용회의 (점도표 띠 포함) |
| 14 | `tab_duel` | HTML | 대결·주문표 (DAILY·시그널 화면에 끼워짐) |
| 15 | `tab_mkt_deriv` | HTML | MARKET › 파생 |
| 16 | `tab_system` | HTML | SYSTEM › 작업 보드·변경 이력·운영 상태 |
| 17 | `tab_detail` | HTML | 종목 상세 서랍·차트 (모든 탭 공용) |

붙여넣은 뒤 `배포 → 배포 관리 → 새 버전` 으로 갱신. GitHub Pages(`index.html`) 는 `python scripts/build_pages.py` 가 include 를 인라인해 한 파일로 만든다.

## 커밋 메시지

- `영역: 한 줄 요약` (예: `bonds: AI 인프라 신용 감시 …`, `lab: …`, `ops: …`). 이 첫 줄이 변경 이력·작업내역 보고에 그대로 쓰인다.
- 보드 작업과 연결하려면 첫 줄에 `[작업id]` 를 넣는다 (예: `lab: 2라운드 가설 3개 추가 [lab-r2]`). 넣지 않아도 작업 고유 파일을 고치면 자동 연결된다(공유 파일은 연결 근거로 안 씀).
- 봇 자동 커밋 꼴(`briefing: dashboard 2026-10-15T09:16`, `live: …`, `report: KR …`, `ops: …`)은 이력에서 '자동 갱신 N회'로 접힌다 — 사람/에이전트 커밋에 이 꼴을 쓰지 말 것.
- 끝에 세션 attribution 줄 (Co-Authored-By / Claude-Session).

## 보드 쓰는 법

- 상태: `대기 → 진행 → 검수 → 완료` (막히면 `보류` + 메모에 이유). 우선순위: P0(오늘·내일 꼭) · P1(이번 주) · P2(여유) · P3(언젠가).
- 새 작업은 `ops/board.json` 에 항목 추가 → `python scripts/board.py` (검증 + BOARD.md 생성). `files` 에 고칠 경로를 적으면 '충돌 주의' 목록이 자동으로 나온다.
- 상태만 바꿀 땐 `python scripts/board.py --set <id> <상태>`.

## 보유 입력 형식 (MY_HOLDINGS 시크릿 = pb-private/holdings.txt, 같은 텍스트)

보유 수치는 저장소에 두지 않는다. 런타임에만 읽는다: 웹 MY 탭은 비공개 저장소 `holdings.txt` 를 토큰으로, 08:50 아침 점검·16:20 규정 알림은 Actions 시크릿 `MY_HOLDINGS` 로. 두 곳에 **같은 텍스트**를 붙여넣는다 (아래는 자리표시 숫자).

```
005930 10 70000          # 위성 북: 종목코드·티커·이름 수량 평균단가
TIGER 200 IT 5 30000
MU 2 100.0
현금 1000000
USD 1000
## ISA                   # 이 줄 아래 = ISA 코어 북 (같은 형식)
360750 100 20000
133690 20 100000
069500 30 40000
148070 40 110000
132030 50 20000
현금 500000
```

- 분모는 항상 **순자산 = 위성 + ISA + 현금(원화·달러)**. 반도체 비중은 '반도체(전기 제외)' 가 기본, '반도체+전기(상관 테마)' 가 보조.
- 지수 ETF(KODEX 200·S&P500·나스닥100 …) 속 반도체 룩스루는 한도 계산에서 빼고 '참고 경보' 한 줄로만. 섹터 ETF(TIGER 200 IT·KODEX 반도체·SOXX·SMH·PSI)는 전액 반도체.
- ISA 코어 목표: S&P500 40 · NDX 10 · K200 15 · 국고채 20 · 금 15 (±5%p 밴드, 적립으로 맞춤).
- `MY_RULES` 시크릿(선택): `SEMI_CAP 0.40` · `SEMI_BAND 0.45`(발동선) · `LOSS_LIMIT 0.12` · `종목코드 가격`(2일 종가 이탈 경고).
- 규정 알림(`screener/alerts.py`, 16:20·14:25): `RULE_STOP_LEVEL`(코스피 손절선, 없으면 20일 저점) · `RULE_DEADLINE`(YYYY-MM-DD) 시크릿. 상태는 `reports/alerts_state.json`. 텔레그램에는 비율만.

