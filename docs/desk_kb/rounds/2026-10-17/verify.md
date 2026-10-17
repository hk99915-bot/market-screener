# verify 라운드 1 — 2026-10-17

1. **읽기** — LOOP.md·README.md·STANDARD.md·quant.md(#1~#28, 복기 1건)·_scoreboard.md(비어 있음)·보드 `quant-replicate-studies`(검증, P1, 10/18)·LOCKS.md. 자기 KB 없어 docs/desk_kb/verify.md 신설.
2. **배우기** — 재현성/재연성 정의(NASEM 2019 ch.3, Freese & Peterson 2017)와 소표본 승률 Wilson 구간(Brown–Cai–DasGupta 2001) → kb:verify#1·#4. 우리 '독립 재현'은 same-data/different-analysis(강건성) 유형이라 데이터 창고 오류는 못 잡는다 → '차이' #6에 기록.
3. **고치기** — crash_rebound §3(코스피 −5% 종가 매수→122630 5거래일 보유, 원 n 26건·승률 61.5%·평균 +7.2%, 2010-02-22~2026-10-16)을 data/hist KOSPI(pykrx 4131행)+122630(yfinance 4065행)으로 명세만 보고 재현: `scripts/replicate_crash_rebound.py` + `tests/test_replicate_crash_rebound.py`(4건) + `reports/studies/replication_crash_rebound.md/.json`. 결과 6/6 일치(사건 날짜 27개 동일, 5일 보유 n 25 vs 26 — 창 정의 차이 추정, 검증전). 재현 승률 15/25 → Wilson 95% 40.7~76.6%(50% 포함). 영향 범위: 신규 4파일, 워크플로·탭·알림 변경 없음, 롤백 = 4파일 삭제. 나머지 4건(semis_cap·exec_signal·entry_signals·rule_audit)은 보드 `rep-*` 4건(검증, 10/17 22:00).
4. **피어(퀀트) 반대 의견** — crash_rebound.json 은 §0 사전등록·등급·실행 시점(asof·커밋)이 없어 재현이 맞아도 C(참고) 상한. 승률 61.5%(n 26)만 적는 운용회의 표기는 kb:quant#11(기대값) 원칙과 어긋남 → 'n·승률·평균·최악' 4개 묶음으로. 반대 근거 1개: 사건 27건 중 15건이 2026-06~10 한 국면이라 전 기간 수치 자체가 국면 평균.
5. **복기** — 허용오차를 코드 안 고정 숫자로 적고 바로 실행함 → 다음부터 보고서 §0에 SE 기반 식(kb:verify#5)으로 먼저 적고 커밋한 뒤 실행. 수정 커밋에서 §0을 보고서 머리에 넣음.

VOC: 다른 데스크 미커밋 변경(screener/alerts.py·pb.py)이 같은 작업 사본에 있어 `git pull --rebase`를 못 돌리고 push만 했다 — 데스크별 worktree 분리가 필요하다.
요청→퀀트: crash_rebound §3 '5일 보유' 창 정의(매수일 i 기준 i+5 거래일 종가, 어느 캘린더)와 실행 시점(asof·커밋 해시)을 json meta 에 넣어 달라(10/18 리뷰까지) — 재현 n 26 vs 25 의 1건 차이를 닫기 위함. 코드는 내가 열지 않는다.
현재 상태: ① crash_rebound §3 재현 완료·일치(reports/studies/replication_crash_rebound.md, 등급 C 참고 유지). ② 보드 rep-semis-cap·rep-exec-signal·rep-entry-signals·rep-rule-audit 대기(검증, 10/17 22:00) — 형식은 replication_crash_rebound.md §0 그대로, 원 코드 미열람. ③ 미해결 1건: 5일 보유 창 정의 확인(퀀트, 10/18).
