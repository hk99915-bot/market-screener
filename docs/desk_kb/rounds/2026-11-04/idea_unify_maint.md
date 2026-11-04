# 종목 아이디어 통합운영 — 코드·데이터 통합안 (유지보수, 2026-11-04)

발단: 겸이 11/4 15:48 「…현재 종목아이디어로 뭐 스크리닝하고 관리하는게 어디에 다 산재되어있는지, 이거 통합운영으로 고도화전략좀」. 입력 = 감사 산재 지도 `idea_map_audit.md`(생성원 13·판정 7종) · `modelbook_upgrade.md`(겸이 15:45 결재 — 모델 북 병기·ev_r≤0 size 0 11/6, 사이즈 산식 11/7, req-dev-6bd21386) · `ops/board.json` · `docs/migration_checklist_1107.md` · `docs/refactor_plan_v1.md`. 범위 = 제안만(코드 수정·커밋 없음). 공개 저장소 — 금액·보유 없음.

## 상단
- **What**: 판정을 13곳에서 1곳으로 줄이는 게 아니라, 13개 생성기는 그대로 두고 **출력만 공통 레코드 1개 형식**으로 모은 뒤 **판정 키 `final` 하나**만 화면·추적이 읽게 한다. 상수(사이즈 5벌·비용 3값·시간손절 20/21일)는 `screener/trade_rules.py` 한 곳으로 — 1단계는 값 변경 0.
- **So What**: 오늘 같은 'tradeplan 보류인데 모델 북 실행 후보' 사고의 구조 원인(한 행 두 판정 + 화면·추적이 서로 다른 칸을 읽음)이 닫힌다. 단, **11/7(토) 저장소 전환·11/9~11 병행 대조 창과 겹치면 회귀 판별이 불가능**해진다 — 산출물이 바뀌는 커밋은 그 창 밖으로.
- **Now What**: 11/5~6 = 결재된 모델 북 P1만(신규 구조 작업 0) · 11/7~11 = 동결 · 11/12~ 3단계 착수(아래 ⑤). 뒤집힐 조건: 병행 대조가 11/11 전에 '불일치 0건 3일'을 채우면 착수 하루 앞당김.

## ① 단일 '아이디어 레코드' 스키마 (`idea_record` v1)
원칙: **판정(final) ≠ 수명(state) ≠ 원천 점수(src_score)**. 셋을 한 칸에 섞은 게 지금 사고의 뿌리(퀀트 패널: 확신도와 컨빅션은 다른 걸 잰다).

| 칸 | 형식 | 설명 / 지금 어디서 오나 |
|---|---|---|
| `id` | `"{src}:{mkt}:{code}:{YYYYMMDD}[:n]"` | 생성원+종목+생성일. 같은 날 같은 원천 재생성은 `:n` — 덮어쓰지 않음 |
| `src` | enum 13 | screener·modelbook·tradeplan·us_committee·alphabook_b1·hf_ideas·hf_disc·practice·duel·accum·trend·chain·lab (감사 지도 #1~13) |
| `src_ref` | 문자열 | 원본 위치(`reports/committee.json#ideas_top.items[2]`) — 되짚기용 |
| `mkt`·`code`·`name`·`side` | | side = long/short/hedge |
| `created_at`·`asof` | KST ISO | asof = 가격 기준 시각(guard-rest 규약과 같은 분 단위) |
| `src_score` | {kind, value, label} | 원천 고유 점수(확신도·매집 태그·체인 점수·Wilson 하한…). **판정에 쓰지 않음** — 선별 순위만 |
| **`final`** | enum: `실행후보`·`모의관찰`·`대기`·`보류`·`만료`·`미판정` | **유일한 판정 키**. 화면·idea_tracking·텔레그램은 이것만 읽는다. 결재안대로 tradeplan verdict에서만 파생(`보류`→보류, `관찰(모의)`→모의관찰, `채택(모의)`+ev_r>0→실행후보) |
| `judge` | {rule_v, by, at} | 어느 판정 규칙 버전이 언제 냈나(tradeplan `verdict_rule` 375행) |
| `ev_r`·`ev_grade`·`p_t1`·`p_stop`·`conviction` | | tradeplan `plan` 그대로 |
| `entry` | {ref, lo, hi, cond, valid_until} | ref = 기준가(종가), lo~hi = 진입 범위, valid_until = 만료(지금 `valid.entry_days`=1 과 tradeplan '밖이면 1일 만료' 이중 → 한 칸) |
| `stop` | {px, pct_ref, pct_worst, slip_r} | pct_worst = (entry.hi−stop)/entry.hi — FRM 결정안 3의 분모 |
| `target` | {t1, t2} | |
| `time_stop_days` | int | `trade_rules.HOLD` 에서 채움 |
| `cost_rt` | float | `trade_rules.COST` 에서 채움(프로파일명 같이 기록) |
| `size` | {risk_pct, weight, formula_v} | `trade_rules.size()` 단일 산식 결과. final≠실행후보면 weight 0 |
| `state` | `생성`→`유효`→`체결`→`청산`/`만료`/`취소` | 수명만. 판정과 분리 |
| `score` | {ret_net, r_mult, hit_t1, hit_stop, days, ledger, scored_at} | 채점 결과. ledger = 어느 장부가 채점했나 |
| `ext` | dict | 원천 고유 칸(재량 북 수기 p_win, 연습북 원문 참조 id 등) — 공통 칸으로 억지 승격 금지 |

- 파일: `reports/ideas.json`(당일 레코드) + `reports/ideas_ledger.jsonl`(추가 전용, 채점 결과 포함). 스키마 검사는 `screener/contracts.py` 확장(refactor_plan_v1 §3 과 같은 자리).
- 공개 경계: `ext` 에 겸이 원문·금액 금지 — 연습북은 비공개 저장소 참조 id만.

## ② 상수 한 모듈: `screener/trade_rules.py`
이름 근거: `screener/config.py` 는 경로·토글 전용(ROOT·REPORT_DIR·TOPLINE_TG) — 섞지 않는다. 지금 흩어진 값(이번에 grep 실측):

| 값 | 위치 | 현재 |
|---|---|---|
| 시간손절 | tradeplan.py:32 `HOLD_DAYS`·alphabook.py:37·practice_book.py:28·hf_book.py:64(stock 20/fut 10) | 20 |
| 〃 | hf_basket.py:30 | **21** |
| 왕복 비용 | tradeplan.py:38 `COST`·alphabook.py:38 `COST_RT`(주석 "tradeplan.COST 와 같음" — 복사본) | KR 0.25%·US 0.10% |
| 〃 | practice_book.py:32·hf_book.py:62 | KR 0.45%·US 0.20% |
| 〃 | decisions.py:155·177·209 (리터럴 3회) | 0.05% |
| 1회 리스크 | tradeplan.py:35 `STAGE_RISK` 0~1% · committee.py:1297(확신×payoff/2×1%) · committee.py:311 `_risk_box` 1% · alphabook.py:31 0.5% · hf_book.py:53·54 0.4%/CONV | 5벌 |

- 모듈 구성: `HOLD = {"stock":20, "fut":10, "basket":21?}` · `COST = {프로파일: {mkt: rt}}`(프로파일 `sim`=0.25/0.10, `retail`=0.45/0.20, `duel`=0.05 — **지금 값 그대로 이름만 붙임**) · `STAGE_RISK` · `size(risk_pct, stop_pct_worst, slip_r, cap=0.15, floor=0.05)` 1함수 · `stop_px(close, low20, atr)`(committee.py:306-307·tradeplan.py:300·361 두 벌 → 1벌).
- **이관 순서**(각 단계 1커밋, 앞 단계 초록 확인 후 다음):
  1. 모듈 신설 + 골든 테스트 `tests/test_trade_rules.py`(각 기존 상수 == 모듈 값, 값 변경 0).
  2. import 치환: tradeplan → alphabook → hf_book·hf_basket·practice_book → decisions(리터럴 3곳). 산출물 diff 0 확인(`reports/committee.json`·`alphabook.json` 재생성 해시 대조).
  3. committee.py:1297·311 사이즈 → `size()` — **FRM 결정안 3(11/7 산식) 확정 뒤에만.** 값이 바뀌는 첫 커밋, 플래그로 켬.
  4. 값 통일(비용 0.25 vs 0.45, 21 vs 20): 개발 결정 아님 — FRM·퀀트 결정 후 별도 커밋. 모의 성적 비교표엔 프로파일명 병기.
- 영향 파일: screener/tradeplan.py · alphabook.py · committee.py · decisions.py · scripts/hf_book.py · hf_basket.py · practice_book.py.
- 테스트: 기존 test_tradeplan · test_alphabook · test_cio_top3_v2 · test_idea_tracking · test_hf_book · test_hf_basket · test_practice_book · test_duel_trail_stop 초록 유지 + 신규 test_trade_rules. 재발 방지: `scripts/check_functions.py` 에 'trade_rules 밖 `HOLD =`·`COST =`·`0.0045` 리터럴' 경고(차단 아님) 추가 제안.

## ③ 파이프라인 '생성기 → 공통 레코드 → 단일 판정 → 장부' (빅뱅 금지, 3단계)
| 단계 | 하는 일 | 바꾸는 것 | 회귀 위험 | 완료 기준 |
|---|---|---|---|---|
| **S1 수집(그림자)** | `scripts/idea_collect.py` 가 13개 산출물을 **읽기만** 해서 `reports/ideas.json` 생성. 생성기 코드 무변경. 판정 못 붙는 건 `final=미판정` | 새 파일 1개 + 워크플로 committee 슬롯 뒤 1스텝 | 0(읽기 전용) | 13원천 커버리지 표(원천별 레코드 수·필수 칸 채움률) 3거래일 |
| **S2 단일 판정(그림자→전환)** | 수집기가 전 레코드에 `tradeplan` 판정 적용 → `final_shadow`. 원천 고유 판정과 불일치 표 매일. 20거래일 뒤 피어 기준(그림자 라벨 적중 > verdict 이면 되돌림) 통과 시 플래그 `IDEA_FINAL=1` 로 committee status·tab_committee·텔레그램이 `final` 을 읽게 전환 | committee.py status/size 파생 · tab_committee `go` | 중(_mock_gate 순서·텔레그램 건수) | 카드 건수 = 텔레그램 '모의 추적 후보' 건수(1건 차이도 실패) |
| **S3 단일 장부** | `idea_tracking.py` 가 `status=='실행'`(131-135행) 대신 `final ∈ {실행후보, 모의관찰}` 레코드 전부 채점 → `ideas_ledger.jsonl`. hf_ideas·tradeplan verdict(장부 없던 2곳) 자동 편입. 재량 북·연습북·대결은 자체 장부 유지, 레코드 id만 역참조 | idea_tracking · topline_from · 화면 1곳 | 중(ideas_log 연속성) | 기존 ideas_log 채점과 겹치는 기간 숫자 일치 |

- 대상 아닌 것: lab(가설, 종목 아이디어 아님)·chain(신호 공급원) — 레코드 대신 `src_score` 공급원으로만.

## ④ 기술 부채·위험
- **감사 정정 1건 — lab_queue.json 은 고아가 아니라 '사람 손 접수처'**: `_doc` = "전 데스크 접수처, 퀀트 11/03 … 데스크가 1줄 추가 → 퀀트가 REGISTRY 이관". 쓰는 코드·읽는 코드 모두 0(이번 grep 재확인)이 맞지만 의도된 수기 큐. 부채는 '형식 검사 없음' — lab.py 에 필수 칸 검사만 붙이면 됨(경).
- **11/7 충돌(중)**: 11/7(토) 저장소 전환 → 11/9~11 병행 대조(committee·detail 등 해시·값 '불일치 0건 3일', refactor_plan_v1 §5). 이 창에 committee/tradeplan 산출물을 바꾸는 커밋이 한쪽에만 들어가면 대조가 깨져 진짜 이전 회귀와 구분 불가. → FRM 사이즈 산식(결재 일정 11/7)은 **11/6 밤 전환 스냅샷 전에 넣거나 11/12로 이동** 권고. 보드 P0 `close-swap-verify`(11/7)는 파일이 달라 무충돌.
- **같은 파일 동시 작업(중)**: committee.py 를 만지는 열린 항목 — report-format-rollout(P1, 11/7)·guard-rest(P2, 11/11)·audit-ideas-basis(P2)·tradeplan-ui(P2, 11/26). 머지 충돌·순서 혼선 → S2 착수 전 이 넷을 개발 한 줄로 순서 고정.
- **공개 노출이 새 저장소로 이월(중, 기한 11/6)**: 새 공개 저장소는 'HEAD 스냅샷 1커밋'이라 `reports/practice_book.json:111`(겸이 원문 매매 한 줄, 감사 ⑤)이 **그대로 실려 간다** — 이력 소멸 효과가 이 파일엔 없음. 전환 전 비공개로 옮기거나 제외 목록에.
- 회귀 위험: `_mock_gate`(1565)가 `attach`(1569~1571)보다 먼저 셈 · ideas_log 조정 봉 기준 불일치(audit-ideas-basis xfail) — S3 전에 먼저 닫아야 단일 장부가 가짜 손절을 물려받지 않음 · committee.json 소비자 3곳(tab_committee·topline_from·idea_tracking) 스키마 변화.
- 수동 4종(hf_ideas·hf_book·hf_basket·practice_book) schedule_table 미등재 — S1 수집기는 이들 파일의 mtime 을 `ops/freshness.json` 계약에 '수동(기대 시각 없음)'으로 올려 최소한 '언제 마지막으로 돌았나'는 보이게.

## ⑤ 작업량·순서·기한(제안)
| 순서 | 일 | 담당 | 작업량 | 기한 |
|---|---|---|---|---|
| 0 | 결재분 P1(모델 북 병기·ev_r≤0 size 0) — 이미 진행 | 개발 | 1.5일 | 11/6 |
| 0' | practice_book.json 원문 줄 이전 제외 확인 | PB·개발 | 0.1일 | 11/6 |
| — | 동결(전환·병행 대조) | — | — | 11/7~11/11 |
| 1 | trade_rules 1~2단계(값 변경 0) | 개발 | 0.5일 | 11/12 |
| 2 | S1 수집기 + 커버리지 표 | 개발·유지보수 | 1일 | 11/14 |
| 3 | FRM 산식 → trade_rules 3단계(플래그) | 개발(FRM 결정 후) | 0.5일 | 11/14 |
| 4 | S2 그림자 판정 시작 → 20거래일 관찰 | 개발·퀀트 | 1일 + 관찰 | 시작 11/17, 전환 판정 ~12/15 |
| 5 | S3 단일 장부 + 화면 1곳 | 개발·프론트 | 2일 | 12/18 |
| 6 | 값 통일(비용·21일) | FRM·퀀트 결정 | 0.3일 | 결정일 +1 |
합계 개발 약 6.9일(관찰 기간 제외). Pro 전환(11/12) 뒤라 데스크 호출 규모는 pro-plan-round-scale 기준을 따른다.

반대 근거 1줄: 13개 중 실제로 결정에 쓰이는 건 모델 북·tradeplan·대결 정도라 나머지 10개까지 공통 레코드로 맞추면 재량 북 수기 p_win·연습북 한 줄 같은 고유 의미가 `final` 한 칸에 억지로 눌려 또 하나의 거짓 정밀도가 될 수 있다 — 그래서 S1은 읽기 전용 수집만 하고, 판정 전환(S2)은 그림자 20거래일 성적으로만 결정한다.

VOC: 유지보수 — "통합의 첫 커밋은 값이 하나도 안 바뀌어야 한다. 바뀌는 순간과 옮기는 순간이 겹치면 뭐가 깨뜨렸는지 아무도 모른다 — 11/7~11은 손 떼."
요청→ 개발: trade_rules 1~2단계·S1 수집기(11/12~14) · FRM: 사이즈 산식 투입일 11/6 밤 또는 11/12 중 택1 · PB: practice_book.json:111 전환 스냅샷 제외 확인(11/6) · 퀀트: lab_queue 필수 칸 검사 소유.

> 출처(작성 주체): 유지보수 서브에이전트(PB 세션 호출)
