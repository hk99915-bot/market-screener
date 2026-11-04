# data-parquet-out — parquet 을 git(main)에서 빼는 순서 (보드 `data-parquet-out`, 겸이 11/4 18:28 결재 · 개발)

공개 저장소 — 파일 이름·개수·크기만. 전수 표의 원천은 `scripts/parquet_inventory.py`(추적 parquet 전수, tests/test_parquet_inventory.py 가 표 밖 파일을 막음).

## 현황 (11/4, git 추적 parquet)
| 묶음 | 개수·크기 | 성격 | 읽는 곳 | 릴리스 전용? |
|---|---|---|---|---|
| data/hist/kr_YYYY | 16개 · 96MB | 불변(연도) | prices.load_kr(hist_from)←analysts·lab.yml, study_* | 아니오 |
| data/hist/us_YYYY | 16개 · 65MB | 불변(연도) | build_hist(업종 합성)·study_* | 아니오 |
| research·research_views·short_hist·dart·us_eps_hist·fin/us_quarterly | 6개 · 합 3MB 안팎 | 누적(매일·분기) | fin·screener·briefing 의 수집/종합 단계 | 아니오 |
| kr_prices·signals·fin/multi·full·hist/*_daily·flows/kr_inv_* | (이미 처리) | 대용량 | data_store pull 로 받음 | 예(10/21 stage1) |

핵심: 남은 크기의 98% 는 **연도별 불변 32개**(161MB) — 바뀌지 않으므로 릴리스로 한 번 올리면 끝. 매일 바뀌는 6개는 작아 용량보다 '새 저장소 main 에 안 넣는' 정합이 문제.

## 단계 (완료 조건: 읽는 워크플로 표 + 각 스텝 테스트 통과 + 스냅샷 제외 목록 반영)
1. [완료 11/4] 전수 표 + 표 밖 parquet 차단 테스트.
2. [다음] data_store GROUPS 에 `hist_year`(kr_/us_ 연도) 추가 + `all` 이 아닌 명시 pull 로 읽는 곳만 받게 — **Actions bootstrap(workflow_dispatch) 로 릴리스에 먼저 올린 뒤**(원격 세션은 릴리스 쓰기 403) manifest 커밋, 그 전엔 GROUPS 에 넣지 않는다(미등록 그룹 pull 이 경고를 늘림).
3. 읽는 워크플로 pull 스텝 확인: lab.yml(pull 있음, 그룹 인자 필요)·fin/screener/briefing(누적 6개 읽음 — pull 그룹에 추가) · tests.yml 은 pull 안 함(파일 읽는 테스트가 있으면 skip/픽스처).
4. 스냅샷 제외 목록(`*.parquet` + 위 표)과 .gitignore 에 같은 패턴 반영 → 그 다음에만 `git rm --cached`.
5. 11/6 전 pytest·ui_smoke 통과 확인. 미통과면 겸이에게 사유 보고(보드 피어 조건 ⑤).

주의: briefing.yml·live.yml 은 장중이라 손대지 않음(단계 3 의 briefing 은 장 마감 뒤 창에서).
