# 공유 파일 잠금 규약

여러 에이전트가 같은 파일을 동시에 고치면 리베이스·머지 중에 남의 함수가 사라진다 (실제 사례: 10/15 `myRun`·`myFetch` 삭제 → MY 탭 'myRun is not defined').
아래 **공유 파일**을 고치기 전에는 반드시 `ops/locks.json` 에 잠금을 걸고, 끝나면 푼다.

## 공유 파일 (잠금 필수)

| 파일 | 이유 |
|---|---|
| `apps-script/Index.html` | 화면 전체가 한 파일. 거의 모든 작업이 건드림 |
| `apps-script/Code.gs` | 데이터 getter 목록 |
| `scripts/build_pages.py` | GitHub Pages 용 getter 목록 (Code.gs 와 짝) |
| `screener/committee.py` | 운용회의 — 여러 담당의 한 줄이 모이는 곳 |
| `screener/main.py` | 모드 분기 |
| `.github/workflows/*` | 예약·저장 로직 |

`index.html` 은 빌드 산출물이라 잠그지 않는다 (항상 `python scripts/build_pages.py` 로 다시 만든다).

## 잠금 항목

```json
{"file": "apps-script/Index.html", "owner": "퀀트 누나", "since": "2026-10-16T09:10+09:00", "task": "lab-r2"}
```

- `owner` 는 보드의 담당 이름 그대로, `task` 는 `ops/board.json` 의 작업 id.
- 한 파일에 잠금은 하나. 이미 남이 잠갔으면 **기다리거나 팀장(PB)에게 요청**한다. 남의 잠금을 지우지 않는다.

## 순서

```bash
git fetch origin && git rebase origin/main
python scripts/lock.py list                                   # 누가 잡고 있나
python scripts/lock.py take apps-script/Index.html --owner "퀀트 누나" --task lab-r2
git add ops/locks.json && git commit -m "lock: Index.html (퀀트 누나, lab-r2)"
git pull --rebase origin main && git push                     # ← 잠금은 '작은 커밋'으로 바로 푸시해야 남이 본다
# … 편집 · 검사 · 빌드 · 푸시 (ops/README.md 의 프로토콜) …
python scripts/lock.py drop --owner "퀀트 누나"               # 내 잠금 전부 해제
git add ops/locks.json && git commit -m "unlock: Index.html (퀀트 누나)" && git pull --rebase origin main && git push
```

잠금 푸시가 거절되면(동시에 다른 잠금이 들어옴) `git pull --rebase` 후 `lock.py list` 로 다시 확인한다 — 같은 파일을 남이 먼저 잡았으면 내 항목을 지우고 기다린다.

## 예외 · 정리

- 잠금은 짧게: 편집 → 검사 → 푸시까지 한 번에. 6시간 넘은 잠금은 `lock.py list` 에 ⚠ 방치로 뜨고, 일일 작업내역 보고 '열린 이슈'에 올라간다. 정리는 팀장(PB)이 한다.
- 봇(`screener-bot`) 커밋은 `reports/` 등 산출물만 바꾸므로 잠금 대상이 아니다.
- `scripts/check_functions.py --owner "<내 이름>"` 은 남이 잠근 파일을 내가 고쳤으면 실패한다.
