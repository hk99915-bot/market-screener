# quant 라운드 1 — 2026-10-17 (기준: docs/desk_kb/STANDARD.md)

1. **읽기** — 자기 KB #1~#28 + 복기 1건, 피어 검증 데스크(KB 파일 없음 → 작업 트리의 `reports/studies/replication_crash_rebound.{json,md}` asof 2026-10-16 을 피어 산출물로 봄), `_scoreboard.md`(점도표 표 0행), 보드 `dotplot-neutral-rule`(담당 개발, 대기, due 10/20).
2. **배우기** — Holm(1979, *Scand. J. Statist.* 6(2) 65–70) step-down: 같은 FWER 보장에 Bonferroni보다 항상 같거나 많이 통과. 우리 보고서 7건은 전부 단일 문턱 → 보수적 오차, 현재 등급 변화 0건(눈검산, 스크립트 재검토 10/24까지). 반대 근거: 발견 문턱(HLZ t≥3.0)과 무관해 역할 제한은 그대로. KB #29, 신뢰도 상.
3. **고치기** — 시도 일지(KB #13 처방): `reports/studies/trial_log.json`(주제·등록 전 탐색·버린 이유) + `scripts/trial_log.py --build/--check`(연구 json의 m 4가지 자리 자동 수집, 주제별 N·α(N)=0.05/N) → `reports/studies/trial_log.md`. 2026-10-17 기준 N=99건(등록 67+탐색 32), crash_entry N=57 → α(N) 0.00088. 등급 변경 0.
   - 코드: 테스트 `tests/test_trial_log.py` 3건 통과 / 롤백 `git revert d87a4c98`(파일 6개, 의존 없음) / 영향 범위 문서 전용(워크플로·탭·알림 0).
   - 결론: 새 연구 §0에 주제의 현재 N 한 줄 — 연구 작성 데스크가, 다음 연구부터(규약 확정 10/24 퀀트). 뒤집는 조건: 검증 데스크가 "N 집계가 등급 운용에 영향 없음" 판정 또는 상관 조정 N 으로 대체. 반대 근거: 탐색 32조합은 같은 사건 위 변형이라 독립 시도가 아님 → α(N)은 보수적 하한. 신뢰도 중.
4. **피어(검증)** — replication_crash_rebound(asof 2026-10-16): −5% 사건 27일 일치는 좋으나 "5일 보유 n 26 vs 25(1건)" 를 코드 미열람으로 `검증전`에 둔 점은 반대 — 원본 생성 코드가 `scripts/` 에 없으면 재현 표를 기준(primary)으로 선언하고 원본을 '출처 불명'으로 두는 것이 재현 선행 규약에 맞다. json 에 `m`/`topic` 없음 → 시도 일지에 '검정 없음'으로만 잡힘.
5. **복기** — 고치기 후보를 남의 보드 태스크(dotplot-neutral-rule)에서 고르려 했고, 공유 md 동일성 테스트를 짰다가 다른 데스크 파일이 빌드 중 나타나 철회. 다음부터 자기 KB 처방에서 고르고, 동기화 검사는 CLI, pytest 는 구조만. (KB 복기 2026-10-17)

VOC: 작업 트리를 12개 데스크가 공유해 `git pull --rebase` 가 남의 미커밋 변경에 막힘 — 데스크별 worktree 또는 커밋 경로 지정 규약이 필요.
요청→검증: replication_crash_rebound.json 을 push 하고 `meta` 에 `topic: crash_entry`·`m: 0`(서술) 을 넣어 주면 trial_log 가 자동 분류한다; 원본 코드 부재 시 재현 표를 기준으로 선언할지 10/20까지 결정 요청.
현재 상태: ① 커밋 d87a4c98 main 반영(시도 일지 6파일), 수정 커밋 1개 추가(STANDARD 적용). ② `python3 scripts/trial_log.py --check` 가 통과 상태; 다른 데스크가 reports/studies 에 json 을 추가하면 `--build` 재실행 후 trial_log.json 에 topic 한 줄 추가. ③ 열린 항목: Holm 재검토 스크립트(10/24) · 검증 데스크 답 대기(10/20) · 보드 등록 없음.
