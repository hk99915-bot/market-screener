# 공유 파일 잠금 규약

여러 에이전트가 같은 파일을 동시에 고치면 리베이스·머지 중에 남의 함수가 사라진다 (실제 사례: 10/15 `myRun`·`myFetch` 삭제 → MY 탭 'myRun is not defined').
아래 **공유 파일**을 고치기 전에는 반드시 `ops/locks.json` 에 잠금을 걸고, 끝나면 푼다.

## 공유 파일 (잠금 필수)

| 파일 | 이유 |
|---|---|
| `apps-script/Index.html` | 화면 공용 셸 (head·CSS·탭 바·공용 도우미·render·탭 전환). 탭을 고칠 땐 잠그지 않는다 — 아래 탭 파일만 |
| `apps-script/tab_*.html` | 탭별 화면 (아래 표). **파일 하나가 잠금 단위** — 서로 다른 탭이면 두 담당이 동시에 고쳐도 된다 |
| `apps-script/Code.gs` | 데이터 getter 목록 |
| `scripts/build_pages.py` | GitHub Pages 용 getter 목록 (Code.gs 와 짝) |
| `screener/committee.py` | 운용회의 — 여러 담당의 한 줄이 모이는 곳 |
| `screener/main.py` | 모드 분기 |
| `.github/workflows/*` | 예약·저장 로직 |

`index.html` 은 빌드 산출물이라 잠그지 않는다 (항상 `python scripts/build_pages.py` 로 다시 만든다).

### 탭 파일 (각각 따로 잠금)

| 파일 | 화면 |
|---|---|
| `apps-script/tab_market.html` | MARKET › KR·US·히트맵·전종목 |
| `apps-script/tab_home.html` | HOME |
| `apps-script/tab_daily.html` | DAILY › 데일리 리포트·VIEWS·브리핑 기록 |
| `apps-script/tab_my.html` | MY |
| `apps-script/tab_life.html` | LIFE |
| `apps-script/tab_research.html` | RESEARCH › 리서치·밸류에이션·공시 |
| `apps-script/tab_quant.html` | QUANT › 공급망·시그널·스터디·연구소·모멘텀·모의 포트폴리오 |
| `apps-script/tab_isalab.html` | QUANT › ISA 실험실 (비중 슬라이더 백테스트) |
| `apps-script/tab_bond.html` | MARKET › 채권 |
| `apps-script/tab_study.html` | STUDY › 커리큘럼·인적성·영어 |
| `apps-script/tab_committee.html` | DAILY › 운용회의 (점도표 띠 포함) |
| `apps-script/tab_duel.html` | 대결·주문표 (DAILY·시그널 화면에 끼워짐) |
| `apps-script/tab_mkt_deriv.html` | MARKET › 파생 |
| `apps-script/tab_mkt_macro.html` | MARKET › MACRO |
| `apps-script/tab_system.html` | SYSTEM › 작업 보드·변경 이력·운영 상태 |
| `apps-script/tab_detail.html` | 종목 상세 서랍·차트 (모든 탭 공용) |

- 새 탭 함수는 해당 `tab_*.html` 에, 여러 탭이 같이 쓰는 도우미는 `Index.html` 셸에 둔다. 파일 사이에 같은 최상위 이름이 있으면 `check_functions.py` 가 실패한다.
- 탭 파일을 새로 만들면 `Index.html` 의 `<?!= include('tab_x') ?>` 줄과 이 표, `ops/README.md` 의 GAS 붙여넣기 목록에 함께 올린다.

## 잠금 항목

```json
{"file": "apps-script/tab_quant.html", "owner": "퀀트", "since": "2026-10-16T09:10+09:00", "task": "lab-r2"}
```

- `owner` 는 보드의 담당 이름 그대로, `task` 는 `ops/board.json` 의 작업 id.
- 한 파일에 잠금은 하나. 이미 남이 잠갔으면 **기다리거나 팀장(PB)에게 요청**한다. 남의 잠금을 지우지 않는다.

## 순서

```bash
git fetch origin && git rebase origin/main
python scripts/lock.py list                                   # 누가 잡고 있나
python scripts/lock.py take apps-script/tab_quant.html --owner "퀀트" --task lab-r2   # 고칠 탭 파일만
git add ops/locks.json && git commit -m "lock: tab_quant.html (퀀트, lab-r2)"
git pull --rebase origin main && git push                     # ← 잠금은 '작은 커밋'으로 바로 푸시해야 남이 본다
# … 편집 · 검사 · 빌드 · 푸시 (ops/README.md 의 프로토콜) …
python scripts/lock.py drop --owner "퀀트"               # 내 잠금 전부 해제
git add ops/locks.json && git commit -m "unlock: tab_quant.html (퀀트)" && git pull --rebase origin main && git push
```

잠금 푸시가 거절되면(동시에 다른 잠금이 들어옴) `git pull --rebase` 후 `lock.py list` 로 다시 확인한다 — 같은 파일을 남이 먼저 잡았으면 내 항목을 지우고 기다린다.

## 예외 · 정리

- 잠금은 짧게: 편집 → 검사 → 푸시까지 한 번에. 6시간 넘은 잠금은 `lock.py list` 에 ⚠ 방치로 뜨고, 일일 작업내역 보고 '열린 이슈'에 올라간다. 정리는 팀장(PB)이 한다.
- 봇(`screener-bot`) 커밋은 `reports/` 등 산출물만 바꾸므로 잠금 대상이 아니다.
- `scripts/check_functions.py --owner "<내 이름>"` 은 남이 잠근 파일을 내가 고쳤으면 실패한다.
- 리베이스 충돌은 이제 탭 파일 단위로만 난다. 같은 탭을 둘이 고쳐야 하면 잠금 순서대로 한 명씩.
