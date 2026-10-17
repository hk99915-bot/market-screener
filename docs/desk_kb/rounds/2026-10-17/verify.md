# verify 라운드 1 — 2026-10-17

1. **읽기** — LOOP.md·README.md·quant.md(#1~#28, 복기 1건)·_scoreboard.md(비어 있음)·보드 `quant-replicate-studies`(검증, P1, 10/18)·LOCKS.md. 자기 KB 없어 docs/desk_kb/verify.md 신설.
2. **배우기** — 재현성/재연성 정의(NASEM 2019, Freese & Peterson 2017)와 소표본 승률 Wilson 구간(Brown–Cai–DasGupta 2001) → kb:verify#1·#4. 우리 '독립 재현'은 same-data/different-analysis(강건성) 유형이라 데이터 오류는 못 잡는다는 한계를 '차이'에 기록.
3. **고치기** — crash_rebound §3(코스피 −5% 종가 매수→122630 5일 보유, 원 n 26·승률 61.5%)을 data/hist KOSPI(pykrx)+122630으로 명세만 보고 재현: `scripts/replicate_crash_rebound.py` + `tests/test_replicate_crash_rebound.py`(3건) + `reports/studies/replication_crash_rebound.md/.json`. 6/6 일치(사건 날짜 27개 동일, 5일 보유 n 25 vs 26 — 창 정의 차이 추정). 나머지 4건(semis_cap·exec_signal·entry_signals·rule_audit)은 보드 `rep-*` 4건으로 등록(검증, 10/17 22:00).
4. **피어(퀀트)** — 반대 의견: crash_rebound.json 은 §0 사전등록·등급·실행 시점(asof·커밋)이 없어 재현해도 '참고' 이상 줄 수 없다. 또 승률 61.5%(n 26)는 Wilson 구간이 50%를 포함하므로 운용회의 머리말에 "승률"만 적는 것은 kb:quant#11(기대값) 원칙과 어긋난다 — 평균·최악과 n을 같이.
5. **복기** — 허용오차를 코드 안 고정 숫자로 적고 바로 실행함 → 다음부터 §0에 SE 기반 식으로 먼저 적고 커밋 후 실행(kb:verify#5·복기).

요청→퀀트: crash_rebound §3 '5일 보유'의 창 정의(매수일 i 기준 i+5 거래일 종가인지, 어느 캘린더인지)와 실행 시점(asof·커밋 해시)을 json meta 에 넣어 달라 — 재현 n 26 vs 25 의 1건 차이를 닫기 위함. 코드는 내가 열지 않는다.
