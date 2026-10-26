# 보고 형식 통일 — 표준 확정·대상 전수·개발 작업 지시서 (PM, 2026-10-26)

> 지시: 겸이 10/26 "What so what now what 구조 퀀트보고서 + 전체 상단 보고내용 형식통일" · 보드 `report-format-rollout`(10/25 원문은 보드 notes).
> 범위: ① 표준 확정(STANDARD.md 8절) ② 대상 전수 ③ 개발 작업 지시서. **생성 코드 수정 없음** — 개발 부동산 작업 종료 후 일괄 위임. 예약(트리거) 프롬프트는 목록만(수정 = PB).
> 기준: main a1bb06f2, 2026-10-26 18시대 KST. 크기 S(≤1h)/M(반나절)/L(1일+)·토큰은 **PM 추정 [검증전]**.

## 0. 상단 3줄 (이 문서 자체)
- ① What: 상단 형식 표준 STANDARD.md 8절 확정 · 대상 34건(S 23 · M 10 · L 1) 전수 + 예약 프롬프트 10건
- ② So What: 생성 코드 22건·화면 4건은 공통 모듈 1개로 일괄 처리 가능, LLM 산출물 8건은 KB·프롬프트 문구 변경 필요
- ③ Now What: 개발 1회(묶음 A) 위임 — 부동산 작업 종료 후 · 예약 프롬프트 10건 PB 수정 · 샘플 1건씩 겸이 확인 후 일괄 적용(화 10/27 11시 이후)

## 1. 규칙 변경 기록 (rounds 기록용)
- 변경: `docs/desk_kb/STANDARD.md` **8절 '보고 상단 형식' 신설** (22시 전 반영). 기존 1~7절 문구 변경 없음.
- 내용: 칸 5종(What·So What·Now What·근거 발췌·원본 링크) 정의, 배치 2종(문서형·상단형), 명사형 종결·개조식, 길이(상단 ≤10줄·1줄 ≤90자·요약본 ≤60줄), 숫자(기준일·출처·등급 꼬리표·%/%p), 미확인 표기 4종, 3줄형(①②③ + 원본), 예시 1건(샘플 v3).
- 충돌 정리: 텔레그램 상한 4절 8줄·운용회의 v2 25줄 유지(3줄형은 그 상단). PB 텔레그램 평서체·HF 냉정 단문 합의 우선. [확인 필요: 겸이 — PB 텔레그램도 명사형으로 바꿀지, 10/27 상정 때]
- 롤백: 8절 삭제 1커밋. 영향 범위: 문서만(코드·워크플로·알림 변경 없음).

## 2. 대상 전수 (34건)
방식: **T** = 생성 코드 템플릿(Python) · **P** = LLM 프롬프트·KB 문구 · **R** = 화면 렌더(apps-script → build_pages). 우선순위 P1(겸이 명시 대상) > P2 > P3.

### 2-1. 생성 코드 (T) — 22건
| # | 대상 | 생성 위치 (파일:함수) | 현재 형식 | 바꿀 방식 | 크기 | 우선 |
|---|---|---|---|---|---|---|
| T1 | 국장 운용회의 상단 | screener/committee.py:_v2_bottom_line | 신호등 라벨 + 3줄(직전 대비/시계/할 일) — So What 칸 없음 | `top` 키 추가: ①=직전 대비, ②=판정·시나리오 확률 함의(신설), ③=할 일; 시계는 근거로 이동 | M | P1 |
| T2 | 국장 운용회의 텔레그램 | screener/committee.py:_telegram_v2·telegram_text | 라벨 + ①②③(위 3줄) + 탑다운·섹터·아이디어(25줄 상한) | 상단 3줄형 교체(render_tg3), 본문 유지 | S | P1 |
| T3 | 미장 운용회의 상단 | screener/us_committee.py:bottom_line_us | T1과 동일 구조 | T1과 같은 `top` | M | P1 |
| T4 | 미장 운용회의 텔레그램 | screener/committee.py:telegram_text_us | 라벨 + head 불릿 | 상단 3줄형 | S | P1 |
| T5 | 매크로 뷰 | screener/macroview.py:build `summary` | 1문장(바람 점수·요인·격차) | `top` 3칸(점수→함의→조치) | S | P1 |
| T6 | 채권 | screener/bonds.py:build·summary() | JSON 상단 키 없음, summary()는 금리 나열+출처 JSON | `top` 신설(금리 변화→듀레이션 함의→조치) | M | P1 |
| T7 | 파생 | screener/derivs.py:build | 상단 키 없음(PCR·맥스페인·월 숫자만) | `top` 신설(포지셔닝→변동성 함의→헤지 조치) | M | P1 |
| T8 | 부동산 | screener/realestate.py:build | 상단 키 없음, region_note | `top` 신설 — **개발 부동산 작업 머지 후** | M | P1 |
| T9 | HF 알파북 | screener/alphabook.py:telegram_tail·summary | 북별 NAV·통계 dict | `top` + 텔레그램 3줄형 | S | P1 |
| T10 | HF 아이디어 | scripts/hf_ideas.py:build | 아이디어 목록 | `top` 신설 | S | P1 |
| T11 | HF 재량 북 | scripts/hf_book.py:main(CLI) → reports/hf_discretion.json `note` | 자유 문장 note | CLI `--what/--so-what/--now-what` 인자, note 하위호환 | M | P1 |
| T12 | 증권가 일일 브리프 | screener/daily.py:build `headline`·telegram_text | 지수·수급 1줄 + 토픽 | `top` + 3줄형 | S | P1(애널) |
| T13 | 리서치 종합 | screener/research_synthesis.py:build `headline` | dict text 1문장(건수·상하향·톤) | `top` 3칸 | S | P1(애널) |
| T14 | 장전·장중·마감·미장 브리핑 | screener/briefings.py:premarket_kr·intraday_kr·close_kr·premarket_us·intraday_us·close_us·reports_alert | 지수·종목 나열 텔레그램 | 각 메시지 상단 3줄형 | M | P2 |
| T15 | 스크리너 마감 요약 | screener/report.py:telegram_summary (main.py:214) | 상태·이상치 나열 | 상단 3줄형 | S | P2 |
| T16 | 밸류에이션 데일리 | screener/valuation_daily.py:build·telegram_text | headline + 표 | `top` + 3줄형 | S | P2 |
| T17 | 원자재 | screener/commodities.py:build `summary` | 1문장(±10% 원자재 나열) | `top` 3칸 | S | P2 |
| T18 | 주간 성적표 | scripts/scorecard_week.py:telegram_line·render_md | 1줄 + md 표 | 3줄형 + md 상단 | S | P2 |
| T19 | 점도표 | screener/dotplot.py:telegram_lines·build `summary` | 자산별 매수/중립/매도 수 | 3줄형 | S | P3 |
| T20 | 퀀트 연구 생성 스크립트 | scripts/study_accum.py·study_trend_expectancy.py·study_lab_p1.py·trial_log.py:render_md | 본문 md(상단 요약 없음) | render_md 맨 앞 요약 블록(문서형) 자동 삽입 | M | P1 |
| T21 | 퀀트 연구 기존 문서 | reports/studies/*.md 40건(수기·과거 생성) | 본문만 | **요약본 상단 붙이기**: 인용 많은 5건 퀀트 수기 우선(accum_signals 완료=샘플 v3), 나머지 신규부터 | L | P1(5건)/P3 |
| T22 | 형식 검사 | (신설) scripts/check_topline.py + tests | 없음 | `top` 칸·길이·종결어미·기준일 린트, 신규 산출물만 경고 | S | P1 |

### 2-2. 화면 (R) — 4건
| # | 대상 | 위치 | 현재 | 바꿀 방식 | 크기 | 우선 |
|---|---|---|---|---|---|---|
| R1 | 공통 상단 카드 | apps-script/Index.html(공용 셸) | 탭마다 제각각(.summary·.verdict·.note) | `renderTop(top)` 공통 함수 1개(3칸 + 기준일 + 원본 링크) | M | P1 |
| R2 | 운용회의 탭 | apps-script/tab_committee.html (bottom_line 참조 5곳) | 신호등 + 3줄 | R1 적용, 신호등 라벨 유지 | S | P1 |
| R3 | 시장 탭군 | tab_mkt_macro·tab_bond·tab_mkt_deriv·tab_realestate·tab_research·tab_daily | .summary/.note 1줄 또는 없음(tab_bond) | R1 1줄 삽입(`top` 없으면 기존 표시 유지) | M | P1 |
| R4 | 홈·퀀트 탭 | tab_home·tab_quant | .verdict·.note | R1 적용 | S | P2 |

### 2-3. LLM 산출물 (P) — 8건 (예약 프롬프트는 3절)
| # | 대상 | 생성 위치 | 현재 | 바꿀 방식 | 크기 | 우선 |
|---|---|---|---|---|---|---|
| P1 | 데스크 라운드 파일 | docs/desk_kb/LOOP.md 8항 형식 | 1~5 각 3줄 + VOC·요청 | 맨 위 3줄형 추가 — LOOP.md 개정(규칙, 22시 전 별도 상정) | S | P2 |
| P2 | 애널 외부 자료 digest | reports/views/digest.json (예약 07:41) | STANDARD 4절 세 칸(내용·뷰·우리 해석) | 매핑: 내용=What·뷰+해석=So What·함의=Now What, 칸명 병기 | S | P1 |
| P3 | 밸류에이션 노트 | docs/valuation_notes/*.md 12건(애널 수기) | 자유 형식 | analyst.md KB 1줄 + 신규부터 | S | P1 |
| P4 | 매크로·원자재·지정학 뷰 | reports/views/macro_cmdty·macro_glance·analyst_cmdty·geopolitics.json | 데스크 문장 | macro.md KB 문구 | S | P1 |
| P5 | 파생 리서치 뷰 | reports/views/derivs_research.json | 데스크 문장 | derivs.md KB 문구 | S | P1 |
| P6 | 부동산 뷰 | reports/views/realestate.json | 데스크 문장 | realestate.md KB 문구 | S | P1 |
| P7 | 피어·감사 보고 | docs/peer_reviews/*.md 12건 | 결함 목록 | audit.md·peer.md KB 문구(상단 3줄) | S | P3 |
| P8 | 사내 메신저 회신 | reports/msgr_feed.md | 대화체 | 공식 회신만 3줄형(사담 제외) | S | P3 |

### 2-4. 제외 (사유)
- 경보·운영 알림(alerts·events·rebound·health·freshness·watchdog·duel 버튼): 이미 1~3줄 경보, 3칸 강제 시 지연 — 제외.
- 학습(study_daily·영어·인적성): 보고 아님. PB 개인 판단(screener/pb.py:brief·send): 비공개 PB 소관·평서체 합의 — PB 판단으로 별도.
- 종목 상세(screener/detail.py, reports/detail/*): 종목 단위 데이터 카드 — 이번 범위 밖(P3 후보).

## 3. 예약 작업 프롬프트 변경 목록 (수정 = PB, 문구만)
기준: pb-private ops/HANDOFF.md '예약 작업' 표(스냅샷 10/26 17:59, 활성 14).
| 예약 | 바꿀 문구 |
|---|---|
| HF 누나 운용회의 토론 개입 (평일 11:55·15:55) | 개입 코멘트 상단 3줄형(①②③) + 원본 링크 |
| HF 누나 장중 매매 (평일 09:05~15:05) | 매매 기록 note → What/So What/Now What 칸(T11 CLI 인자) |
| HF 누나 미장 재량 개입 (09:15 ET) | 위와 동일 |
| PB 진입·매도 타점 판단 (평일 14:42) | 텔레그램 상단 3줄형 — 평서체 합의 유지 여부 겸이 확인 후 |
| PB 미장 진입 타점 판단 (평일 21:52, 활성 상주판) | 위와 동일 |
| 애널 외부 자료 요약 digest (평일 07:41) | P2 매핑 문구 |
| 일요일 주간 회의 (일 19:43) | 회의록 상단 3줄형 + 결정 사항은 Now What |
| 데스크 강화 루프 라운드 (금 21:10) | 라운드 파일 맨 위 3줄형(P1, LOOP.md 개정 뒤) |
| 사내 메신저 처리 라운드 (평일 12:40·20:40) | 공식 회신 3줄형(P8) |
| 정기 감사 (수·토 07:53) | 감사 보고 상단 3줄형(P7) |
- 변경 불요: 기록 데스크 3슬롯(12:50·16:00·22:30), 오늘의 영어·인적성.

## 4. 개발 작업 지시서
### 묶음 A — 개발 1회 호출 (부동산 작업 종료 후)
- 범위: T22 → 공통 모듈 → T1~T7·T9~T13·T20 → R1·R2. T8 부동산은 부동산 작업 머지 직후 같은 호출 마지막 순서(충돌 시 묶음 B).
- 0단계 공통 모듈 `screener/topline.py` (신설)
  - `make(what, so_what, now_what, evidence=None, src=None, asof=None, grade=None) -> dict` — 스키마 `{"what":[..], "so_what":[..], "now_what":[..], "evidence":[..], "src":[..], "asof":"YYYY-MM-DD HH:MM", "grade":"A|B|C|F|검증전|null"}`
  - `render_tg3(top) -> str`(①②③ + 원본, HTML 이스케이프) · `render_md(top, doc=False) -> str`(doc=True면 샘플 v3 순서) · `lint(top) -> list[str]`(칸 누락·칸당 1~4줄·합계 ≤10줄·1줄 ≤90자·`습니다`/`요`/`!` 종결 금지·asof 필수)
  - tests/test_topline.py: 렌더 3종 + 린트 위반 사례 각 1건
- 1단계 생성기: 각 build 에 `out["top"] = topline.make(...)` **추가만** — 기존 키(bottom_line·summary·headline) 삭제 금지(화면 하위호환). 칸 문장은 기존 문장 재배치 우선, 새 문장은 So What 1줄만.
- 2단계 텔레그램: T2·T4·T9·T12 상단을 render_tg3 로. **스위치 `config.TOPLINE_TG`(기본 False)** — 샘플 겸이 확인 후 True(보드 notes ④ '샘플 1건씩 겸이 확인 후 일괄 적용').
- 3단계 화면: Index.html `renderTop(top)` + tab_committee 적용 → `python scripts/build_pages.py` → `scripts/ui_smoke.py`.
- 4단계 연구 문서: T20 스크립트 render_md 앞에 `render_md(top, doc=True)`. 기존 md 재생성 안 함(T21은 퀀트 수기).
- 검사: pytest · board --check · check_functions · check_rules_terms · ui_smoke. 커밋 `dev:` 단계별, `[운영]` 꼬리표는 2단계만.
- 완료 기준: committee·committee_us·macro_view·bonds·derivs·daily_brief JSON 에 `top` 존재 + lint 0건, 운용회의 탭 상단 카드 표시, TOPLINE_TG=False 상태에서 기존 텔레그램 무변화.
- 예상: 파일 약 20개, 도구 50~60회, **토큰 약 35~45만 [PM 추정, 검증전 — team.json 실측 대조 필요]**. 60회 초과 위험 시 3·4단계를 묶음 B로.
### 묶음 B — 다음 호출
- T8(미처리 시)·T14~T19·R3·R4·T21 보조(요약 블록 초안 생성), TOPLINE_TG=True 전환(겸이 확인 후).

## 5. 다음 순서
1. 화 10/27 11시 이후 'ㄱㄱ' 상정: 8절 + 이 문서 + 3줄형 샘플(운용회의 1건·매크로 1건) 겸이 확인
2. 개발 부동산 작업 종료 확인 → 묶음 A 위임(PB 호출)
3. PB: 3절 예약 프롬프트 10건 문구 수정 · 데스크 KB(P2~P7) 1줄 반영은 각 데스크 라운드에서

VOC: 개발 부동산 작업 종료 시점 미확인 — 묶음 A 착수일이 그에 종속.
요청→개발: 부동산 작업 종료 시 PM에 알림, 4절 묶음 A 수행.
현재 상태 3줄: 표준(8절)·전수(34건)·지시서 완료 / 코드 수정 0건 / 겸이 확인 대기(PB 텔레그램 문체·샘플 2건).
