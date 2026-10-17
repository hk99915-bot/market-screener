# quant 라운드 1 — 2026-10-17

1. **읽기** — 자기 KB #1~#28 + 복기 1건, 피어 검증 데스크(KB 파일 없음 → 작업 트리의 `reports/studies/replication_crash_rebound.{json,md}` 를 피어 산출물로 봄), `_scoreboard.md`(점도표 표 비어 있음), 보드 `dotplot-neutral-rule`(담당 개발, 대기).
2. **배우기** — Holm(1979) step-down: 같은 FWER 보장에 Bonferroni보다 항상 같거나 많이 통과. 우리 보고서는 전부 단일 문턱 → 보수적 오차. KB #29. (출처: Holm, *Scand. J. Statist.* 6(2) 1979; Harvey & Liu 2015 인용)
3. **고치기** — 시도 일지(KB #13 처방): `reports/studies/trial_log.json`(주제·등록 전 탐색·버린 이유) + `scripts/trial_log.py --build/--check`(연구 json의 m 네 가지 자리 자동 수집, 주제별 N·α(N)) → `reports/studies/trial_log.md`. 결과 N=99, crash_entry N=57(α 0.00088). 테스트 `tests/test_trial_log.py` 3건. 등급은 안 바꿈.
4. **피어(검증)** — replication_crash_rebound 는 −5% 사건 27일 일치는 좋으나 "5일 보유 n 26 vs 25" 를 코드 미열람으로 `검증전`에 둔 점은 반대: 원본 `scripts/`에 crash_rebound 생성 코드가 없다면 재현 표를 **기준(primary)** 으로 선언하고 원본을 '출처 불명'으로 강등하는 게 규약(재현 선행)에 맞다. 또 json 에 `m`/`topic` 필드가 없어 시도 일지에 '검정 없음'으로만 잡힌다.
5. **복기** — 고치기 후보를 남의 보드 태스크(dotplot-neutral-rule)에서 고르려 했고, 공유 md 동일성 테스트를 짰다가 다른 데스크 파일이 빌드 중 나타나 철회. 다음부터 자기 KB 처방에서 고르고, 동기화 검사는 CLI, pytest 는 구조만. (KB 복기 2026-10-17)

요청→검증: replication_crash_rebound.json 을 push 하고 `meta` 에 `topic: crash_entry`·`m: 0`(서술) 을 넣어 주면 trial_log 가 자동 분류한다. 그리고 재현 표를 기준으로 선언할지(원본 코드 부재 시) 결정 요청.
