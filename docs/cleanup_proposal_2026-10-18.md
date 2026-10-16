# 저장소 정리 제안 — 2026-10-18 일요일 확인용 (제안만, 삭제 없음)

작성 2026-10-16(금) · 개발 데스크 · 기준: `origin/main` 6ca08702 시점의 공개 저장소 `market-screener`

**먼저 알아둘 것**
- 이 저장소의 git 이력은 **2026-10-15 03:02 UTC** 부터만 보인다(얕은 복제). "90일보다 오래된 보고서", "30일 넘게 대기인 작업"은 **모두 0건** — 저장소가 이틀 된 셈이라 나이 기준 정리 대상이 아직 없다. 아래 표는 "지금 기준으로 규칙을 정해 두면 자동으로 걸릴 것"과 "지금 당장 손볼 것"을 구분해 적었다.
- 10/16 에 다른 데스크가 건드린 파일(screener/* 17개, scripts/* 12개, apps-script/*, 워크플로 9개, docs/*, data/hist/*, views/*)은 전부 **keep**. 표에는 그런 항목을 `keep(오늘 수정)` 로 표시.
- 추적 파일 총합 **287 MB** — 그중 data/ 161 MB(시세 창고·재무), reports/detail 113 MB(종목 상세 2,067개). 나머지 코드·문서·보고서는 13 MB 미만.
- 명령은 전부 **확인 후** 실행하는 것이며, 이 문서를 커밋한 시점에는 아무것도 지우지 않았다.

---

## 1. 오래된 보고서 (reports/)

| 경로 | 파일 수 | 크기 | 마지막 갱신 | 90일↑ | 판단 | 이유 / 명령 |
|---|---|---|---|---|---|---|
| `reports/archive/committee/` | 6 | 196 KB | 10-16 장후 | 0 | **keep** | 회의 아카이브. 저널 뼈대·주간 성적표가 읽음. 90일 넘으면 자동 정리할 규칙만 정하자: `find reports/archive/committee -name '*.json' -mtime +90 -delete` (워크플로 `ops.yml` 에 넣을 후보) |
| `reports/archive/committee_us/` | 3 | 24 KB | 10-16 | 0 | **keep** | 위와 같음 |
| `reports/daily_hist/` | 3 | 40 KB | 10-16 | 0 | **keep** | 일일 요약 이력(`_index.json`) — 저널 뼈대의 종가 폴백 |
| `reports/logs/*.log` (24개) | 24 | ~120 KB | 매 실행 | 0 | **keep** | `main._file_log` 가 마지막 실행분만 덮어씀(누적 안 됨). 비밀값 가림 처리 있음 |
| `reports/logs/naver_theme.html` | 1 | 32 KB | 10-15 | — | **delete 후보** | 코드 어디서도 안 읽음(디버그 덤프). `git rm reports/logs/naver_theme.html` |
| `reports/logs/naver_m_KOSPI.json` · `naver_m_KOSDAQ.json` | 2 | 12 KB | 10-16 | — | **delete 후보** | 코드 참조 없음(라이브 시세 탐침 덤프로 추정). 지우기 전에 `grep -rn naver_m_ screener scripts` 로 재확인 → `git rm reports/logs/naver_m_KOSPI.json reports/logs/naver_m_KOSDAQ.json` |
| `reports/logs/naver_list.html` · `pdf_boxes.json` · `probe.json` | 3 | 144 KB | 10-15~16 | — | **keep** | `research.py`·`probe.py` 가 쓰는 진단 출력 |
| `reports/signals/*.csv` | 5 | 616 KB | 10-16 | 0 | **keep + 보존 규칙** | `committee.py` 는 최신 KR 1개만 읽음. 하루 ~240 KB 씩 쌓이므로 **최근 10일만 보존** 규칙 제안: `ls reports/signals/*.csv \| sort \| head -n -20 \| xargs git rm` (screener.yml 커밋 단계) |
| `reports/anomalies/*.csv` · `reports/daily/*.md` | 10 | 160 KB | 10-16 | 0 | **keep + 보존 규칙** | DAILY 탭 원본. signals 와 같은 10일 규칙을 같은 자리에서 적용 |

**합계: 검토 61파일 / 1.3 MB · 지금 지울 후보 3파일 / 44 KB · 90일 초과 0.**

## 2. 중복·대체된 스크립트 (scripts/)

| 스크립트 | 출력 | registry 참조 | 화면 참조 | 마지막 수정 | 판단 | 이유 / 명령 |
|---|---|---|---|---|---|---|
| `study_playbook_signals.py` | `studies/playbook_signals.*` | 5곳 | DAILY·STUDY | 10-15 | **keep** | `exec_signal` 이 "실행 대본 신호"를 다시 검증했지만, 렌즈 5개가 아직 playbook 결과를 근거로 인용. **대체 완료가 아님.** 렌즈 근거를 exec_signal 로 옮긴 뒤에야 `git mv scripts/study_playbook_signals.py archive/` 가능 — 퀀트 데스크 확인 필요 |
| `study_exec_signal.py` | `studies/exec_signal.*` | 3곳 | STUDY | 10-16 | keep(오늘 수정) | 위 후속 |
| `study_semis_cap.py` | `studies/semis_cap.*` | 0곳 | STUDY(`content/study.json`·`index.html`) | 10-16 | keep(오늘 수정) | registry 엔 없지만 STUDY 탭·주간 성적표가 읽음 |
| `study_derivs_signals.py` | `studies/derivs_signals.*` | 0곳(gamma_regime 이 대신) | STUDY·`deriv_hist.py` | 10-16 | keep(오늘 수정) | 파생 데스크 소유. gamma_regime 과 역할이 겹치는지 파생 데스크에 질문만 남김 |
| `study_entry_signals.py` · `study_fib_levels.py` · `study_gamma.py` · `study_rule_audit.py` | 각 `studies/*` | 2~8곳 | STUDY | 10-16 | keep(오늘 수정) | 전부 registry 가 인용 |
| `view_attribution.py` | `reports/views_attrib.json` | — | DAILY › VIEWS | 10-16 | keep(오늘 수정) | 워크플로 미연결(수동 실행). 보드 `view-registry` 작업의 산출물. **연결 or 수동 유지** 를 일요일에 결정 |
| `probe_deriv_sources.py` · `ops_runs.py` · `lock.py` · `board.py` · `changelog.py` | — | — | 워크플로/운영 | 10-15~16 | **keep** | `deriv_hist.yml`·`ops.yml`·`ops/locks.json` 이 호출 |

**합계: 스크립트 15개 검토 · 지금 지울 것 0 · 조건부 보관 전환 후보 1(playbook_signals, 렌즈 이전 후).**

## 3. 안 쓰는 screener 모듈 (import 그래프)

`screener/*.py` 51개 모듈 전부가 다른 모듈·스크립트·테스트·워크플로 중 최소 1곳에서 import 된다. **미참조 모듈 0.**

| 항목 | 내용 | 판단 | 명령 |
|---|---|---|---|
| `main.py` 에만 import 되는 모듈 | `briefings`, `context`, `macroview`, `usmarket`(briefings 경유) | **keep** | 모드 진입점이라 정상 |
| `main.py --mode` 중 **어느 워크플로도 안 부르는 모드** | `calendar`, `duel_us`, `japan`, `krxfix`, `screen`, `study` | **keep, 문서화** | `duel_us`·`krxfix` 는 주석에 "수동 실행용" 명시. `screen`·`japan`·`calendar`·`study` 는 다른 모드 안에서 함수로 호출됨(`screener.yml` 은 MODE 없이 `--market` 로 screen 실행). 삭제 대상 아님 — `README.md` 에 "수동 전용 모드" 표만 추가 제안 |
| `track.py` | committee·views·detail 만 import, main 모드 없음 | **keep** | 라이브러리 성격 |

**합계: 모듈 51개 · 미참조 0 · 삭제 0.**

## 4. 한 번도 안 돈 워크플로 (`gh api …/actions/workflows/<name>/runs` → total_count)

| 워크플로 | 실행 수 | 예약 | 판단 | 이유 / 명령 |
|---|---|---|---|---|
| `lab.yml` | **0** | 일 23:00 KST(`0 14 * * 0`) | **keep** | 첫 예약이 10/19 일요일 — 아직 차례가 안 옴. 10/19 실행 확인 후 0이면 재검토 |
| `scorecard.yml` | **0** | 토 08:30 KST(`30 23 * * 6`) | keep(오늘 수정) | 첫 예약이 10/18 토요일. 10/18 실행 결과가 이 문서 확인 시점에 보임 |
| `health.yml` · `ops.yml` · `pick.yml` | 1 | 주1/일1/이슈 | **keep** | 정상 가동 시작 |
| `pb_call.yml` · `hist.yml` | 2 | 수동/일1 | keep(오늘 수정) | |
| `backfill.yml` | 3 | 1회성 | **archive 후보(나중)** | 백필 완료되면 `workflow_dispatch` 만 남기고 cron 제거: `sed -i '/cron:/d' .github/workflows/backfill.yml` — 시세 창고 완료 선언(10/16) 뒤 퀀트-데이터 데스크 확인 |
| 나머지 7개 | 7~112 | — | **keep** | |

**합계: 워크플로 14개 · 0회 2개(둘 다 첫 예약 전) · 삭제 0.**

## 5. 큰 추적 바이너리 (`git ls-files | xargs du`)

| 경로 | 크기 | 마지막 수정 | 판단 | 이유 / 명령 |
|---|---|---|---|---|
| `data/hist/*.parquet` (38개) | **135 MB** | 10-16 | keep(오늘 수정) | 시세 창고(10/16 완료). 연도별 5~7 MB 씩. 매일 바뀌는 건 `kr_sector_daily`·`us_daily`·`kr_index_daily`·`kr_etf_daily` 4개뿐 → 커밋 비대화는 제한적 |
| `data/fin/multi.parquet` · `full.parquet` | 12.3 + 4.3 MB | 10-16 | keep(오늘 수정) | 재무제표. `fin.yml` 이 갱신 |
| `data/kr_prices.parquet` | 8.2 MB | 10-16 | **keep + 감시** | 매일 재작성 → 이력이 가장 빨리 커지는 파일. 90일 뒤 저장소 크기(`git count-objects -vH`)를 보고 **Git LFS 전환** 결정 |
| `reports/detail/KR` (1,486) · `US` (581) | 86 + 30 MB | 10-16 | **keep + 감시** | 종목 상세 JSON, 매일 전부 재작성. 이력 비대화의 주범 후보. 대안: 변경 없는 파일은 쓰지 않기(`detail.py` 에서 내용 같으면 skip) — 개발 데스크 작업으로 올릴 것 |
| `data/signals.parquet` · `short_hist.parquet` · `deriv/` | 1.7 + 0.3 + 0.5 MB | 10-16 | **keep** | |

**합계: 287 MB 추적 · 지울 것 0 · 감시 대상 2(kr_prices, reports/detail).** 현재 `.git` 크기 확인: `git count-objects -vH`.

## 6. ops/board.json — 30일 넘게 '대기'인 작업

보드는 10/15 생성 → **30일 초과 0건.** 대신 '대기' 13건 중 **기한이 이번 주말(10/17~19)인 것**만 적는다. 전부 keep, 삭제 없음.

| id | 담당 | 우선 | 기한 | 판단 |
|---|---|---|---|---|
| `gas-repaste` · `my-rules-secret` | PB | P0/P1 | 10-17 | keep — 기한 당일, 일요일에 상태 확인 |
| `repo-cleanup` | 개발 | P0 | 10-18 | keep — **이 문서가 산출물**, 확인 후 '검수'로 |
| `alpha-baseline-fix` · `frm-audit` · `cio-memo` · `quant-replicate-studies` | 리스크/CIO/퀀트-재현 | P1 | 10-18 | keep |
| `gas-sched-verify` · `close-swap-verify` · `edu-dev-handoff` | PB/개발 | P0/P2 | 10-19 | keep |
| `memproxy-line` | PB | P2 | 없음 | keep — 기한 없음. 30일 규칙에 걸릴 첫 후보(11/15) |

---

## 일요일에 결정할 것 (요약)

1. **지금 지워도 되는 것 3파일 / 44 KB**: `reports/logs/naver_theme.html`, `naver_m_KOSPI.json`, `naver_m_KOSDAQ.json` — 승인하면 `git rm` 세 줄.
2. **보존 규칙 2개** 채택 여부: (a) `reports/archive/*` 90일, (b) `reports/signals·anomalies·daily` 10일 — 워크플로 커밋 단계에 한 줄씩.
3. **감시 2개** 등록: `data/kr_prices.parquet`, `reports/detail/*` 의 이력 비대화 — 11월 중순 `git count-objects -vH` 재측정, LFS/skip-unchanged 결정.
4. **조건부 1개**: `study_playbook_signals.py` 는 렌즈 5개가 exec_signal 로 근거를 옮긴 뒤 보관 브랜치로 (`git checkout -b archive/playbook-signals && git mv …`).
5. 나머지 전부 keep. 삭제 명령은 이 문서 확인 전까지 실행하지 않는다.
