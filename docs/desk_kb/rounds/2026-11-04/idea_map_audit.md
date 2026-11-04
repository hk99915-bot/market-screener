# 종목 아이디어 산재 지도 + 감사 지적 (2026-11-04, 감사)

발단: 겸이 11/4 15:48 「현재 종목아이디어로 뭐 스크리닝하고 관리하는게 어디에 다 산재되어있는지, 이거 통합운영으로 고도화전략좀」. 범위 = 인벤토리·지적만(코드 수정 없음). 공개 저장소 — 금액·보유 없음.
현재 상태: ① 종목 단위 생성원 13개, 판정 체계 7종(확신도·verdict·E[R]·컨빅션·IC·Wilson/t·대결 승패). ② 같은 행에 두 판정(모델 북 status/conv ↔ tradeplan verdict)이 붙고 화면은 한쪽만 보여 줌. ③ 세션 수동 실행 4종이 schedule_table 에 없음.
참고: 지시문이 인용한 `docs/desk_kb/rounds/2026-11-04/modelbook_upgrade.md` 는 이 시점 저장소에 없음(디렉터리에는 derivs_election_sensitivity·ops_meeting_election·ops_meeting_kr·prereg_alpha_transfer 4개만) — 깨진 참조(f), 경.

## 1. 산재 지도

| # | 이름 | 생성 코드 | 산출 파일 | 실행 주체·시각 | 판정·점수 기준 | 화면 | 추적·채점 장부 | 담당(KB) |
|---|---|---|---|---|---|---|---|---|
| 1 | 스크리너 본체 | screener/main.py(KR·US 모드), scoring.py | latest_KR/US.md · watchlist_KR.json · peers_KR/US.json · detail/ | screener KR 16:20 평일(GAS), briefing screen_us 06:52 화~토(schedule_table:92-93) | 점수(scoring) | tab_detail·tab_market | signal_scores.json(track.py IC·5분위, 5/20/60일) | dev·quant |
| 2 | 모델 북(운용회의 ideas_top) | committee.py:_v2_ideas_top 1249~, 확신도 1292, 사이즈 1297, status 1301 | committee.json ideas_top · ideas_log.json · ideas_attrib.json | briefing 08:50~19:10 7슬롯(GAS, schedule_table:97) | 확신 점수 Σ원천가중 → 높음/중간/낮음, status 실행/대기, 사이즈 = 확신×손익비/2×1%÷손절폭 | tab_committee:39-44(확신도·사이즈) | idea_tracking.json(+ reports/idea_tracking/일자, 'status 실행'만 체결, idea_tracking.py:131-135) · ideas_attrib(원천 성적 보정) | CIO(cio.md:19) |
| 3 | tradeplan(매매 계획 표준) | tradeplan.py:build_plan 286~, verdict 356, attach 498~ | committee.json 각 행 `plan`(ideas_top items·candidates·stance.exec.cands·sim_fresh) | committee 호출(committee.py:1569-1571 KR, 1820 US) — 같은 슬롯 | verdict 보류/관찰(모의)/채택(모의), E[R](보정 calib), 컨빅션 A~D, 크기 = 단계리스크×컨빅션×필터÷손절폭 | tab_committee 직접 키 없음(grep "plan" 0건, 할 일 줄로만 노출) | 전용 장부 없음 — 보정은 study_tradeplan.py(연구) | 다중: quant prob·analyst t2·macro filter·CIO verdict·FRM size(tradeplan.py:8, 376) |
| 4 | 미장 운용회의(us_committee) | us_committee.py · committee.build_us 1706~ | committee_us.json · committee_us_hist.json | briefing 20:52·21:52·22:52·03:52(GAS, schedule_table:98) | 섹터 점수(이익신호+0.6×추세), ideas_top 동일 틀 | tab_committee:316~ | committee_us_hist(5·20일 S&P 대비·브라이어) + idea_tracking market=US(committee.py:1837-1839) | CIO·macro |
| 5 | 알파북 B1(체계 북) | alphabook.py:update 470~, B1 495 | alphabook.json · committee.json `hf` | committee 뒤 호출(committee.py:751-755) | 통과 소스(alpha_sources B) + 소스 OOS E[R] > 기준선, 크기 0.5%×컨빅션×시장배수÷손절폭 | tab_committee(HF 카드) | alphabook.json 자체 NAV·IR | HF(hf.md:38-45) |
| 6 | HF 아이디에이션 | scripts/hf_ideas.py(유형 ①~⑦) | hf_ideas.json · hf_watch.json | **세션 수동**(hf.md:67 라운드 순서) — workflow·schedule_table 없음 | 유형별 검증 상태(B/F/검증전) | 화면 없음(topline_from 만 읽음) | **없음**(⑥⑦ 포함) — S4 페이드만 hf_forward.py → studies/2026-10-21_hf_desk_signals_forward.json | HF |
| 7 | HF 재량 북 | scripts/hf_book.py add/mark, hf_basket.py, hf_spread.py | hf_discretion.json(open·closed·baskets) | **세션 수동** — workflow 없음 | 수기 stop/t1/conv/p_win, RISK_1 0.4%(hf_book.py:53) | 화면 없음 | hf_discretion.json 자체(mark·show) | HF(hf.md:50-58) |
| 8 | 연습북 | scripts/practice_book.py | practice_book.json | **세션 수동** — workflow 없음 | 겸이 한 줄 → 체결·손절·목표·20일(HOLD 28행) | 화면 없음 | practice_book.json 자체(show 성적표) | 행동·HF('HF 개미 교실' 독스트링, KB 소유 미기재) |
| 9 | 대결(PB/공격 PB/나) | duel.py(14:55 KR·22:00 US), pick_gate.py, decisions.py | decisions.json → battle_scoreboard.json · battle_daily | live 14:50–15:15 · briefing premarket_us · pick.yml(이슈) · pb_call 14:42(schedule_table:101) | 규칙 판정(duel 독스트링) / 나 = 계획 칸 게이트 '나🔥' | tab_duel·tab_home | decisions.score(main.py:747) · battle_scoreboard | PB·행동 |
| 10 | 신호 종목(매집·추세) | accum.py · us_accum.py · detail.sim_signals | accum.json · us_accum.json · sim_signals_KR/US.json | accum 18:37 평일 · us_accum 07:37 화~토(schedule_table:47,71) | 매집 태그, 정식 추세 Wilson 하한>0.5·t 하한>0 | tab_committee·tab_market·tab_duel | signal_tracking.json(5·20·60일, signal_tracking.py 독스트링) | quant |
| 11 | 추세 탐색·편입 | trend_discovery.py, scripts/trend_adopt_judge.py | trend_discovery_KR/US.json · trend_adopt.json | committee 경유 + ops.yml:73,100 | 탐색 상한 C, not_for_orders | tab_committee | signal_tracking disc_kr/us | quant |
| 12 | 업종 체인 | drivers.py | chains.json · chains_view.json | briefing 경유 | 체인 점수 | tab_detail·tab_my·tab_quant | 연구만(study_chain_corr.py) — 운영 장부 없음 | analyst·macro |
| 13 | 연구소(lab) | lab.py REGISTRY | lab.json · lab_queue.json(쓰는 코드 grep 0건) | lab.yml 일 23:00 | Bonferroni IS→OOS→HOLDOUT, A/B/C/F | tab_quant 등 | lab.json 자체 등급 | quant |

없는 것(지시 후보 중 미확인): pb-private `analysis/scout` — 디렉터리 없음(analysis/ 하위 2026-10-15·10-16 계열만). topline_from.py 는 생성원이 아니라 상단 3칸 어댑터(재배치만).

## 2. 감사 지적

**① 중복 판정원**
- 치명 · committee.py:1301(status 실행/대기·확신도) ↔ tradeplan.py:356(verdict 보류/관찰/채택) — 같은 ideas_top 행(tradeplan.py:511-512)에 두 판정이 붙는다. 화면 tab_committee:44 는 확신도·사이즈만, idea_tracking.py:131-135 는 status '실행'만 체결 → tradeplan '보류' 종목이 '실행'으로 추적·표시될 수 있음(오늘 정반대 사례의 구조 원인). 결정에 쓰이는 숫자라 치명.
- 중 · alphabook.py:495(B1 통과 소스) · hf_book(재량) · duel PB 판정이 같은 종목에 각자 방향을 냄 — hf.md:92·96 '세 눈이 한 표' 7/7 동일 방향 기록, 독립성 장치(hf.md:58)는 있으나 충돌 시 우선순위 조항 없음.
**② 정의 이원화**
- 중 · 사이즈: committee.py:1297(확신 1·.7·.4 × 손익비/2 × 1%) vs committee.py:311(_risk_box 1%÷손절폭) vs tradeplan.py:337(STAGE_RISK 단계 0~1%×컨빅션×필터) vs alphabook.py:31(0.5%) vs hf_book.py:53(0.4%). 같은 행에 committee size 와 plan.size.weight 가 동시 존재.
- 중 · 진입가·만료: committee.py:1305 entry=종가·entry_max=종가+0.5ATR, 1312 entry_floor(idea_tracking.py:93-95) vs tradeplan.py:338-360 구간 lo~hi·'밖이면 1일 만료' vs decisions(결정일 종가/시가) vs practice_book(다음 시가). 유효기간이 모델 북 필수 5칸(idea_tracking.py:98-99)에도 있어 이중.
- 경 · 손절: committee.py:306-307 과 tradeplan.py:300·361 문언은 같으나(max(20일 저점, 종가−2ATR), 최소 1ATR) 구현 2벌 — decisions trail은 −8%·20일선(decisions.py 독스트링), hf_book 은 수기. 시간 손절 20일은 4곳 하드코딩(tradeplan:32·alphabook:37·practice_book:28·hf_book:64), hf_basket 21일.
- 경 · 비용: tradeplan/alphabook 국장 0.25%(tradeplan:38) vs practice_book·hf_book 0.45%(practice_book:32·hf_book:62) vs battle 0.05% — 같은 모의 성적 비교가 비용 기준이 다름.
**③ 담당 미정·실행 주체 이중화**
- 중 · tradeplan verdict 소유 = CIO, 크기 = FRM, 확률 = 퀀트(tradeplan.py:376) — 모델 북 확신도는 CIO KB(cio.md:19) 단독. 둘 중 무엇이 최종인지 조항 없음.
- 중 · hf_ideas·hf_book·hf_basket·practice_book = 세션 수동(workflow 0건), schedule_table 미등재 — 실행 주체 일원화 규약(schedule_table) 밖.
- 경 · decisions.json 쓰는 주체 4개(live duel·briefing·pick.yml·pb_call, schedule_table:101) — 필드 병합 방식으로 관리 중이나 briefing.yml:164-185 에 되돌리기 분기가 따로 있음.
- 경 · practice_book 담당 데스크 KB 기재 없음.
**④ 채점 장부 없는 생성원**
- 중 · hf_ideas.json(유형 ①~⑦) — 읽는 곳 topline_from 1곳, 성적 장부 없음(S4만 hf_forward).
- 중 · tradeplan verdict — '채택(모의)' 판정의 사후 적중 장부 없음(보정 입력만 존재).
- 경 · chains.json 체인 점수 — 운영 추적 없음(연구 1건). lab_queue.json — 쓰는 코드 grep 0건(고아 파일 의심).
**⑤ 공개 저장소 노출**
- 중 · reports/practice_book.json:111 — 겸이 원문 매매 한 줄이 종목·원화 가격대와 함께 그대로 저장(개인 매매 의도). 금액(e) 아님(가격)이나 본인 발화 기록은 비공개 쪽이 맞음.
- 경 · reports/decisions.json 'notional' 100만·186만·200만·300만 등 혼재 — '모의 대결 고정 사이즈' 허용 범위를 벗어난 비고정 값(186만 1건)은 실계좌 연동 여부 확인 필요[확인 필요: PB, 11/7까지].
- 경 · hf.md:69 '가상 1,000억' 표기 — 모의 명시라 허용, 유지.

VOC: 감사 — "판정원이 13개인 건 문제가 아니라, 한 행에 판정 두 개가 붙고 화면·추적이 서로 다른 쪽을 보는 게 문제다. 통합은 '최종 판정 키 하나'부터."
요청→ CIO: ideas_top 행의 최종 판정 키 단일화(status vs plan.verdict) 조항 · dev: 사이즈·진입·시간손절·비용 상수 한 모듈로 · HF: hf_ideas 전진 채점 장부 · PB: practice_book 원문 저장 위치·decisions 비고정 notional 확인 · ops: 수동 4종 schedule_table 등재.

> 출처(작성 주체): 감사 서브에이전트(PB 세션 호출)
