# 종목 아이디어 통합운영 — 운영안 (2026-11-04, 운영)

발단: 겸이 11/4 15:48 「…현재 종목아이디어로 뭐 스크리닝하고 관리하는게 어디에 다 산재되어있는지, 이거 통합운영으로 고도화전략좀」. 입력: `idea_map_audit.md`(감사 지도 13개·지적 ①~⑤), `modelbook_upgrade.md`(CIO "tradeplan verdict = 유일 판정원" 확정안). 범위 = 운영 제안만(코드·schedule_table 수정 없음, 결재 전). 공개 저장소 — 금액·보유·종목명 없음.
운영 관점 한 줄: 생성원 13개는 줄일 대상이 아니라 **입력**이다. 문제는 "판정이 나오는 곳 > 1, 화면·추적이 보는 곳 ≠ 판정이 나오는 곳"이다.

## ① 단일 판정 키 · 우선순위 조항 (초안 — 최종 결정 CIO)
- **키:** `idea_key = 시장:코드:asof일자`. 행마다 `final = {verdict, size, valid_until, src, conflicts[]}` 하나만 둔다. 화면·idea_tracking·텔레그램은 `final`만 읽는다(다른 칸 직접 읽기 금지).
- **계산 위치 1곳:** committee.py 에서 `tradeplan.attach` **뒤** 한 함수(dev). 모델 북 `status`·`size` 는 `final` 에서만 파생(modelbook_upgrade CIO 안 그대로).
- **층위(위가 이김):**
  0층 구속(거부권만, 방향 생성 안 함) — FRM 스트레스 한도 · 컴플 규칙 · HF 북 손실 한도 · 추격 금지. 걸리면 `final.verdict=보류`, 사유 기재.
  1층 모델 북 판정 = tradeplan `verdict`(CIO) + `plan.size`(FRM). 확신도 = 선별 점수(판정 아님).
  2층 다른 북 — 알파북 B1·HF 재량: 자기 북 안에서만 유효(독립성 hf.md:58). 모델 북 `final` 을 바꾸지 않고 `conflicts[]` 에 `{북, 방향}` 으로만 붙는다.
  3층 기록 — 대결(PB/공격 PB/나)·연습북: 경기·교육 기록. 판정원 아님. 신호(매집·추세·체인·lab) = 1층의 입력 원천.
- **충돌 조항:** 같은 키에 반대 방향 → `final` 유지 + 화면 ⚠ '북 간 반대' 표시 → 다음 committee 슬롯 CIO 1줄 판정. 2슬롯 연속이면 운용회의 안건. 자동 상쇄·평균 금지.
- **보수 비대칭:** 아래 층의 '보류·거부'는 위 층 '채택'을 표시상 경고할 수 있으나 바꾸지 못함 — 0층만 바꾼다.

## ② 실행 주체 일원화 — schedule_table 등재안 (신설 §4-3 '세션·수동 생성원')
| 산출 | 주체 | 시각(KST) | 비고 |
|---|---|---|---|
| hf_ideas.json · hf_watch.json | **cron(신설 제안)** `hf_ideas.py` — 스크립트라 Claude 토큰 0 | 19:25 평일(19:10 reports 뒤) · 07:50 화~토(us_accum 뒤) | 세션은 읽기만 |
| hf_discretion.json mark(hf_book·hf_basket) | **cron(신설 제안)** `hf_book.py mark` 1벌(basket 포함) | 16:05 평일(15:45 close_kr 뒤) · 07:55 화~토 US | mark=가격 갱신·손절 판정, 사람 판단 없음 |
| hf_discretion.json add/close | HF 상주 세션 **단독** | 라운드 1일 1회(장후) | 수동 = 판정 행위만 남김 |
| practice_book.json | PB 세션 **단독**(겸이 발화 시) · 체결 갱신 cron 16:10 | 발화 시 + 16:10 | ⑥ 처리 뒤 등재 |
| decisions.json | **필드 소유표**로 등재: live duel 14:50–15:15(KR 픽·채점) · briefing premarket_us 20:52(US) · pick.yml(이슈, '나' 칸) · pb_call 14:42(PB 칸) | 각 시각 | briefing.yml:164-185 되돌리기 분기 → asof·필드 가드로 대체(dev) |
- 검사: `tests/test_schedule_single.py` 에 '수동 행 = 주체 1개 명시' 규칙 추가(dev). 표는 slot_guard `--table` 자동 생성 밖이라 §4-3 은 손 기입 + 테스트로 고정.

## ③ RACI (R=실행 · A=최종 책임 · 표시는 전부 dev R / 판정 A 는 ① 층위 기준)
| # | 생성원 | 생성 | 판정 | 채점 | 표시 |
|---|---|---|---|---|---|
| 1 | 스크리너 본체 | dev R · quant A | — (입력) | quant(signal_scores) | dev |
| 2 | 모델 북 ideas_top | CIO A | **CIO(final)** | CIO A · quant R(idea_tracking) | dev |
| 3 | tradeplan | quant·analyst·macro R | CIO verdict · FRM size | quant(④ 신설) | dev |
| 4 | 미장 운용회의 | CIO·macro | CIO(final US) | quant(committee_us_hist) | dev |
| 5 | 알파북 B1 | HF | HF(자기 북) | HF R · quant 검수 | dev |
| 6 | HF 아이디에이션 | HF | — (입력) | quant(④ 신설) | dev(화면 없음→카드 '다른 북' 칸) |
| 7 | HF 재량 북 | HF | HF(자기 북)·FRM 한도 | HF R · 피어리뷰 검수 | dev |
| 8 | 연습북 | PB | — (교육) | 행동 | 없음(비공개 이관 후 결정) |
| 9 | 대결 | PB·행동 | 규칙(duel) | PB(battle_scoreboard) | dev |
| 10 | 신호(매집·추세) | quant | — (입력) | quant(signal_tracking) | dev |
| 11 | 추세 탐색·편입 | quant | quant(trend_adopt) | quant | dev |
| 12 | 업종 체인 | analyst·macro | — (입력) | 미정 → 장부 보류(경) | dev |
| 13 | lab | quant | quant(등급) | quant | dev |
- practice_book 담당 KB 미기재(감사 ③) → 행동 KB 에 1줄(행동 데스크 몫, 운영은 요청만).

## ④ 채점 장부 없는 생성원 — 장부 1개로
- **새 파일 안 만든다.** `idea_tracking.json` 에 `src`(model·tradeplan·hf_ideas·us) · `mode`(체결/그림자) 필드 추가 = 장부 하나.
- tradeplan: `final.verdict` 3값 **전부** 그림자 추적(진입 없음, 기준 = plan.entry.ref, 만료·손절·1차 목표 그대로). 채택(모의)만 `mode=체결`. 판정 지표 = 채택 vs 보류 평균 R 차(verdict 판별력).
- hf_ideas: 유형 ①~⑦ 생성일 종가 기준 그림자, 5·20일 시장 대비. S4 페이드는 hf_forward 유지(중복 기록 금지 — src 로 연결만).
- 집계: 주 1회 금 19:10 reports 슬롯 안 1줄(cron, 토큰 0). 사전등록 판정 시점 = 유형·verdict별 40건 또는 30신호일(hf.md 페이드 관행과 같은 틀) — 그 전엔 "판단 근거 없음"으로 표기.

## ⑤ 하루 흐름 1장 (화면 = 종목당 카드 1장, `final` 한 줄 + '다른 북' 칸)
| KST | 무엇 | 화면 |
|---|---|---|
| 06:52–07:55 | screen_us → valuation → us_accum → hf_ideas·US mark(제안) | tab_market · tab_detail |
| 08:50 | premarket_kr committee → **KR final 첫 발표**(유효 = 당일, 범위 밖 '만료') | tab_committee · tab_home |
| 10:30·11:35·13:30·14:15 | 장중 갱신 — final 바뀌면 카드에 '변경 시각' | tab_committee |
| 14:42–15:15 | pb_call·duel — 픽 옆에 같은 키 final 병기(대결은 판정 안 바꿈) | tab_duel |
| 15:45–16:10 | close_kr: idea_tracking 체결·만료·그림자 기록 → HF·연습북 mark | tab_committee(성적) |
| 16:20–19:10 | screener KR·deriv·accum → reports(채점·ideas_attrib), 금 주간 집계 | tab_detail · tab_quant |
| 19:25 | hf_ideas KR(제안) → 다음날 08:50 입력 | (카드 '다른 북') |
| 20:52·21:52·22:52 | premarket_us·intraday_us → **US final** · US duel | tab_committee US · tab_duel |
| 23:47 | ops: 라운드 수집·보드·충돌 2슬롯 연속 건 안건 승격 | BOARD |

## ⑥ 공개 노출 처리 (운영은 판정 안 함 — 위반 여부는 컴플, 확인은 PB)
- practice_book.json:111 원문: ① 원문 필드는 pb-private 로 이관(PB), 공개 쪽은 `src_ref`(비공개 저장소 id)만 ② practice_book.py 저장 시 원문 필드 쓰기 금지 + 테스트(dev) ③ git 이력 재작성은 하지 않음 권고(강제 push 가 다른 세션 작업을 깨는 운영 비용 > 이득, 가격대만 있고 금액 없음) — 최종은 PB·겸이.
- decisions notional: 모의 고정 사이즈 상수 1개로 정규화(dev), 비고정 값 1건은 PB 확인(감사 기한 11/7) — 실계좌 연동이면 비공개 이관. 이 파일엔 값 재기재 안 함.
- 등재: `ask.py` 로 컴플(판정)·PB(확인) 각 1건.

## 토큰·작업량 (Max 5x 11/11 종료 → 11/12 Pro)
- 11/11까지(세션 여유): CIO 조항 결재 · dev 1회 구현(final 함수·idea_tracking src/mode·§4-3·테스트) — 묶어서 PR 1개.
- 11/12~(Pro): 자동화 우선 — mark·hf_ideas·집계는 cron(토큰 0). 세션은 판정 행위(HF add·CIO 충돌 1줄·PB 대결)만, HF 라운드 1일 1회. pb_call 14:42 예약 세션은 토큰 소비원이라 Pro 이후 유지 여부 PB 판단.
- 하지 않을 것: 생성원 통폐합 리팩토링, 체인 장부(경), 화면 재설계(카드 1장 병기로 충분).

반대 근거 1줄: 판정 키·RACI·장부는 생성원 13개를 그대로 둔 채 문서·필드만 늘리는 것이라, Pro 전환으로 세션이 줄면 연습북 동결·hf_basket 을 hf_book 에 흡수하는 식으로 **생성원 수 자체를 줄이는 쪽이 더 싸고**, 그림자 장부는 40건 쌓일 때까지(대략 수 주) 판단 근거가 0이다.

VOC: 운영 — "판정이 몇 개냐보다, 화면이 어느 칸을 읽느냐가 하나면 된다. 사람 손은 판정에만, 갱신은 cron 으로."
요청→ CIO: ① 층위·충돌 조항 결재 · dev: final 함수·idea_tracking src/mode·§4-3·schedule 테스트·practice 원문 필드 금지 · HF: mark·hf_ideas cron 이관 동의 · PB: ⑥ 원문 이관·notional 확인 · 컴플: practice 원문 판정 · 행동: practice_book KB 소유 1줄.

> 출처(작성 주체): 운영 서브에이전트(PB 세션 호출)
