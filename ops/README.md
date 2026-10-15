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
2. **잠금** — 공유 파일(`apps-script/Index.html`·`Code.gs`·`scripts/build_pages.py`·`screener/committee.py`·`screener/main.py`·`.github/workflows/*`)을 고칠 거면 [LOCKS.md](LOCKS.md) 대로 잠금 커밋을 먼저 푸시.
3. **편집** — 남의 함수·변수는 지우지 않는다. 화면은 `apps-script/Index.html` 에서만 고친다 (`index.html` 은 산출물).
   새 데이터 getter 는 `apps-script/Code.gs` **와** `scripts/build_pages.py` 양쪽에 같은 이름으로 추가.
4. **푸시 직전 다시 최신화 + 검사**
   ```bash
   git fetch origin && git rebase origin/main          # 충돌 나면 '양쪽 모두 살리는' 쪽으로 해결
   python scripts/check_functions.py                    # 사라진 함수·변수 이름 / <script> 문법 / 빌드 최신 / 잠금
   python scripts/build_pages.py                        # index.html 재생성
   python scripts/check_functions.py                    # 빌드 결과까지 다시 확인 → '통과' 여야 함
   git add -A && git commit … && git push origin HEAD:main
   ```
   - 실패 `사라진 이름: X` → 리베이스·머지 중에 남의 코드를 지웠다는 뜻. `git show origin/main:apps-script/Index.html` 에서 되살린다.
     정말 일부러 지운 것만 `--allow-removed X` 로 통과시키고 커밋 메시지에 이유를 적는다.
   - 실패 `문법 오류` → 해당 `<script>` 행 근처 수정. 푸시 금지.
   - push 가 거절되면(그새 남이 푸시) 4번을 처음부터 반복.
5. **잠금 해제 + 보드** — `python scripts/lock.py drop --owner "<내 이름>"`, `python scripts/board.py --set <id> 검수`(또는 완료) 후 함께 커밋·푸시.

## 커밋 메시지

- `영역: 한 줄 요약` (예: `bonds: AI 인프라 신용 감시 …`, `lab: …`, `ops: …`). 이 첫 줄이 변경 이력·작업내역 보고에 그대로 쓰인다.
- 보드 작업과 연결하려면 첫 줄에 `[작업id]` 를 넣는다 (예: `lab: 2라운드 가설 3개 추가 [lab-r2]`). 넣지 않아도 작업 고유 파일을 고치면 자동 연결된다(공유 파일은 연결 근거로 안 씀).
- 봇 자동 커밋 꼴(`briefing: dashboard 2026-10-15T09:16`, `live: …`, `report: KR …`, `ops: …`)은 이력에서 '자동 갱신 N회'로 접힌다 — 사람/에이전트 커밋에 이 꼴을 쓰지 말 것.
- 끝에 세션 attribution 줄 (Co-Authored-By / Claude-Session).

## 보드 쓰는 법

- 상태: `대기 → 진행 → 검수 → 완료` (막히면 `보류` + 메모에 이유). 우선순위: P0(오늘·내일 꼭) · P1(이번 주) · P2(여유) · P3(언젠가).
- 새 작업은 `ops/board.json` 에 항목 추가 → `python scripts/board.py` (검증 + BOARD.md 생성). `files` 에 고칠 경로를 적으면 '충돌 주의' 목록이 자동으로 나온다.
- 상태만 바꿀 땐 `python scripts/board.py --set <id> <상태>`.
