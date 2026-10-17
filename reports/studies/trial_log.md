# 시도 일지 (trial log)

> `scripts/trial_log.py --build` 산출물 — 손으로 고치지 않는다. 사람이 적는 칸은 `trial_log.json`.
> 출처: `reports/studies/*.json` (날짜 열 = 파일의 generated/asof/registered, 기준일 = 그 날짜) · 단위: 건(가설·조합 수) · α = 0.05/N (식: α(N)=0.05÷N, 소수 5자리).
> 뜻: 각 연구의 Bonferroni 는 **그 연구 안의 m** 만 나눈다. 같은 질문을 여러 연구에서 다시 보면 시도 N 은 늘어나는데 p 는 그걸 모른다(Harvey & Liu 2015, kb:quant#13). 아래 'α(N)' 은 주제 전체 N 으로 나눴을 때의 문턱 — **등급은 바꾸지 않고** 얼마나 낙관적인지 보이는 용도.

## 0. 합계 — 시도 N = **99** (등록 m 합 67 + 등록 전 탐색 32) → 전부 한 가족으로 보면 α = 0.00051

## 1. 연구별

| 연구 | 날짜 | 주제 | m | 읽은 자리 | α(m) | 등록 전 탐색 | 등급 분포 | 버린 이유 |
|---|---|---|---|---|---|---|---|---|
| crash_rebound |  | crash_entry | — | 미등록 | — | — | — | 검정 없음(서술 표) — 가설 생성용 |
| derivs_signals | 2026-10-16 | derivs | 10 | m | 0.005 | — | A1 F2 검증전8 | H8 산수만 A, 나머지 F/검증전 |
| entry_signals | 2026-10-16 | crash_entry | 6 | params.m | 0.00833 | — | C1 F5 | 후보 5개 F, 급락일 종가 C → '확인 신호를 기다리지 않기' 추천 |
| exec_signal | 2026-10-16 | crash_entry | 19 | params.m1+m3+m4 | 0.00263 | — | — | S2′만 C(보정 전), 급락일 종가보다 20일 −5.7%p |
| fib_levels | 2026-10-15 | fib | 4 | m | 0.0125 | — | F1 | 렌즈 등급 F |
| gamma_regime | 2026-10-16 | derivs | 3 | m | 0.01667 | — | C1 검증전4 | IS 감마음수 17일<20 → 검증전, next_eval 대기 |
| playbook_signals | 2026-10-15 | crash_entry | — | 미등록 | — | 32 | — | 급락일 종가(B)보다 나은 신호 없음 → 다음 연구(entry_signals)로 재정의 |
| replication_crash_rebound |  | crash_entry | — | 미등록 | — | — | — | 재현 표 — m 없음, −5% 사건 27일 일치 |
| rule_audit | 2026-10-16 | rules | 18 | params.m | 0.00278 | — | C6 F12 | — |
| semis_cap | 2026-10-16 | semis_cap | 7 | prereg.m | 0.00714 | — | A1 C1 F5 | — |

## 2. 주제별 N (같은 질문의 반복 검정)

| 주제 | 연구 | 등록 m 합 | 등록 전 탐색 | N | α(N) |
|---|---|---|---|---|---|
| crash_entry | crash_rebound, entry_signals, exec_signal, playbook_signals, replication_crash_rebound | 25 | 32 | 57 | 0.00088 |
| rules | rule_audit | 18 | 0 | 18 | 0.00278 |
| derivs | derivs_signals, gamma_regime | 13 | 0 | 13 | 0.00385 |
| semis_cap | semis_cap | 7 | 0 | 7 | 0.00714 |
| fib | fib_levels | 4 | 0 | 4 | 0.0125 |

## 3. 시도 기록 (날짜 · 가설 · 파라미터 · 결과 · 버린 이유)

| 날짜 | 주제 | 가설 | 파라미터 | 결과 | 버린 이유 | 연구 |
|---|---|---|---|---|---|---|
| 2026-10-15 | crash_entry | 대본 신호(저점 지지·5일 고점 회복·분할)가 급락일 종가 매수보다 낫다 | H20/H60, raw/cut, −3%/−5% | B(급락일 종가) 우위, 신호 D/E 는 기회비용 | 유의차 없음 + 비용·복잡성 → 단순한 쪽 권고 | playbook_signals |
| 2026-10-16 | crash_entry | 외국인 순매수·회복 확인 조건이 승률을 올린다 | gap 20, win 20, exit 40, m=6 | 5개 F, 급락일 종가 C(p 0.070) | 조건 추가는 n 만 줄임(kb:quant#21) | entry_signals |
| 2026-10-16 | crash_entry | 실행 신호 5종 × 보유 3기간이 무조건 진입보다 낫다 | m1=15, m3=2, m4=2 | S2′ 만 C, 나머지 F | 급락일 종가 대비 열위 | exec_signal |

읽는 법: 주제 N 이 연구 m 의 2배를 넘으면(crash_entry 처럼) 그 주제의 C 등급은 '방향'이 아니라 '우연일 수 있는 방향'으로 읽는다. 새 연구 §0 에 그 주제의 현재 N 을 한 줄 적는다.
