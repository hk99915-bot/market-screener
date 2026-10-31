# 밸류에이션 규칙 — 정의·공식·현업 vs 교과서·흔한 오해·10년차 기준

(원본: docs/desk_kb/analyst.md 해당 절을 그대로 옮김 — 2026-10-31 스킬 시범. 원본 KB 에 `#번호`가 없어 인용은 `kb:analyst#<절 이름>`. 내용 수정은 양쪽 같이.)

## 정의 (밸류에이션)
- **TTM**: 최근 4개 분기 합. 4개 미만이면 연환산(×4/n) → `검증전`. 화면 RESEARCH › 밸류에이션(reports/valuation.json). `[교과서]`
- **E/P − rf**: 이익수익률 − 무위험(US 10Y, KR 국고 3Y). 채권 대비 상대 매력이지 저평가 확정 아님(이익이 꺾이면 분자 소멸). `[교과서]` `[자체연구-검증전]`
- **멀티플/EPS 분해**: ln(P₁/P₀) = ln(PER₁/PER₀) + ln(EPS₁/EPS₀) — '배수 눌림(심리·금리)'과 '이익 하향'을 가른다. 20일 전 EPS 기록 전엔 EPS 변화 0 가정(`검증전`). `[교과서]`
- **사이클 정점 ROE 함정**: 메모리처럼 이익이 사이클을 타면 고점에서 PER 이 가장 낮아 보인다 → 정상화 ROE(사이클 평균) PER 과 같이(screener/valuation.py `정상화`). PEG 도 같은 함정(성장률 고점이면 분모 부풂). `[교과서]` `[경험]`

## 공식
- 금리 민감도(ERP·g 고정): PER′ = 1/(1/PER + Δrf). PER 20 에 +25bp → 19.05(−4.8%), PER 40 이면 −9.1% — 배수가 높을수록 금리에 민감. `[교과서]`
- 순현금 근사 = 현금 − 총부채(차입금 미수집, 보수적). EV/EBITDA 는 감가상각(da) 있을 때만, 없으면 플래그. `[자체연구-검증전]`

## 현업 vs 교과서
- **PER 분모 네 가지를 나란히**: (a) TTM (b) 런레이트(최근 분기×4) (c) 가이던스×4 (d) 정규화(10년 평균 순이익률×현재 매출) → "분모에 따라 X~Y". 한 숫자는 분모 선택을 숨긴다. 코드 valuation_daily.run_rate/guidance_per, 노트 docs/valuation_notes/2026-10-17_memory.md. `[교과서]` `[자체연구-검증전]`
- **가이던스 EPS(non-GAAP)와 GAAP TTM 을 섞지 않는다**: 대신 '가이던스 EPS×주식 수 vs 최근 분기 GAAP 순이익'이 이익률 방향(SNDK 77%→약 62%)을 보여준다. `[경험]`
- **PBR = PER × ROE**: 메모리 4종 정규화 ROE 11~18% 인데 현재 PBR 2.5~12 는 고점 ROE(26~73%)와만 짝이 맞는다. `[교과서]`
- **US 가정**: COE = 미 10Y + ERP 5.0% `[가정]`(Damodaran 2026-01 implied 4.23% 2차 인용 [확인 필요: 스턴 histimpl, 2026-10-30]), 베타 1, g 2.5%, 세율 21%. KR 은 COE 9%·g 2% 고정 → US 적정가만 금리에 연동. 금융업 DCF 제외. `[교과서]` `[자체연구-검증전]`
- **6모델은 독립 확인이 아니다**: 상대 PER·PBR-ROE·RIM·DCF 는 모두 'TTM 이익 지속' 전제 → 값이 비슷해도 확신 ×4 아님. 반대 전제 = '정상화' 묶음·`cycle_view`. `[교과서]`

## 흔한 오해
- "숫자가 너무 좋으면 데이터 버그" → 10/16~17 MU·SNDK 분기 5→14→28→38B 를 '누적치 의심' 처리했으나 8-K 원문과 일치. 휴리스틱(cumulative_smell)은 초고성장과 누적치를 구분 못 함 — 원문 대조(fin_verified.json) 우선. '이렇게 좋을 리 없다'도 편향. `[경험]`

## 10년차 기준 (2026-10-23 교육)
- 체크리스트: ① 3표(손익·재무상태·현금흐름) 연결 모델 + 베어/베이스/불 시나리오 목표 범위 `[교과서: CFA L2 Equity Valuation·Koller]` ② 의견마다 컨센서스 대비 차이(variant view)·촉매 날짜·틀리면 뒤집힐 숫자 1개 `[현업 관행]` ③ 이익의 질 — OCF/NI·발생액·일회성 조정을 PER 옆에 `[교과서: CFA L1·L2 FSA]`
- 격차: 감사 중5·경33(2회 합, 경 최다 — reports/audit/2026-10-21.json analyst 경28, 출처·기준일 누락형)·reports/valuation.json `ev_ebitda` 대부분 null(감가상각 미수집).
- 드릴 [analyst-d1]: reports/valuation.json(10/23) 삼성전자 PER TTM 9.57 vs 런레이트 5.03, 4분기 OPM 14→21→43→52%. 한 숫자로 말해도 되나? — 답·채점 키 `content/drills/analyst.json`(라운드 파일에 `드릴: analyst-d1 <내 답>` 을 먼저 쓰고 열 것, round_collect 채점 · G1 10/24)

## 코드·산출물 위치 (저장소 현행, KB 아님 — 2026-10-31 확인)
- `screener/valuation_daily.py` — 반도체 바스켓 일일 추적(`python -m screener.main --mode valuation` → reports/valuation.json·.md). TTM·런레이트(`run_rate`)·가이던스(`guidance_per`, 입력 universe/fin_guidance.json)·20일 분해(`decompose`)·금리 민감도(`rate_sensitivity`)·누적치 휴리스틱(`cumulative_smell`) → 원문 대조값 universe/fin_verified.json 이 있으면 해제(`externally_verified`).
- `screener/valuation.py` — 종목 상세의 6모델 적정가 범위(상대 PER·PBR-ROE·RIM·DCF 등)와 '정상화' 묶음.
- 노트: docs/valuation_notes/2026-10-17_memory.md (네 분모 표 a~e 의 기준 사례). 테스트: tests/test_valuation.py · tests/test_valuation_us.py.
