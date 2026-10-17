# verify(검증) 데스크 KB

(모든 데스크 연구·모델의 독립 재현. 결정 전 재현 선행 원칙, 뒤집을 권한. 형식은 README.md. 항목 번호 `kb:verify#<n>`. 2026-10-17 신설 — 강화 루프 라운드 1.)

## 성격·성향
- **한 줄:** 결과보다 먼저 '뒤집힘 기준'과 '뒤집을 권한'을 서면으로 달라는 재현자.
- **판단 성향:** 중립 · 사전등록 우선.
- **말버릇:** "결과를 본 뒤 유리한 쪽이 기준을 정한다"(TH:quant_replicate §3) · "맞는 결과를 내고도 '그래도 결정은 그대로'라는 말을 듣는 것이다."(TH:quant_replicate §5, 일부)
- **맹점:** 재현 허용오차를 파일로 사전등록하지 않고 고정값으로 둠(KB:verify 복기).
- **긴장:** ↔퀀트(재현 대상) · ↔PB·겸이 결정(뒤집을 권한).
- 원본: [PERSONAS.md#verify](PERSONAS.md#verify) — 이 절은 요약(과거 행동 기록이지 연기 지시가 아님), 갱신은 원본 먼저.

## 정의
- #1 [규정] **재현성(reproducibility) vs 재연성(replicability)**: NASEM(2019) 정의 — 재현성 = **같은 데이터·같은 방법**으로 같은 결과(계산 재현), 재연성 = **새 데이터**로 같은 질문에 일관된 결과. 우리 '독립 재현'(같은 데이터 창고, 명세만 보고 **다른 코드**)은 그 사이의 **강건성 재현(robustness)** — Freese & Peterson(2017) 분류의 'same data, different analysis'. 코드 미열람이 핵심: 코드를 보면 버그까지 같이 재현한다. (출처: NASEM *Reproducibility and Replicability in Science* 2019 ch.3 · Freese & Peterson, *Annual Review of Sociology* 43, 2017)
- #2 [자체연구-규약] **재현 판정 3단계**: ① 사건 집합 일치(날짜 목록 대조 — 숫자보다 먼저) ② 통계 일치(n·승률·평균이 사전 허용오차 안) ③ 불일치 원인 분류(데이터 출처 / 창 정의 / 비용 가정 / 코드 버그). ①이 맞고 ②가 어긋나면 창·비용 정의, ①부터 어긋나면 데이터·필터 정의를 의심한다. (출처: reports/studies/replication_crash_rebound.md 첫 사례)
- #3 [자체연구-규약] **재현 산출물**: `scripts/replicate_<id>.py`(simulate·compare 함수, 합성 데이터 테스트 1건) + `reports/studies/replication_<id>.md/.json`(원 vs 재현 표, 민감도, 판정). 불일치 시 원 보고서 등급 한 단계 강등 요청(보드 quant-replicate-studies 규약). 재현은 **원 숫자가 아니라 재현 숫자**를 기준으로 삼는다.

## 공식
- #4 [논문] **소표본 승률의 신뢰구간은 Wilson 구간**으로: 정규근사 p̂±1.96√(p̂(1−p̂)/n)은 n<40·p̂가 0.5에서 멀면 커버리지가 95% 아래로 떨어진다(Brown–Cai–DasGupta 2001). 쉬운 숫자(원 보고서 16/26승, 2026-10-16 기준): 정규근사 61.5%±1.96·√(0.615·0.385/26) = 42.8%~80.2%, Wilson(scripts/replicate_crash_rebound.py `wilson(16,26)`) = 42.5%~77.6%. 어느 쪽이든 **50%를 포함** → "승률 61.5%"는 동전 던지기와 구분 안 됨. (출처: Brown, Cai & DasGupta, *Statistical Science* 16(2) 2001 · 적용 replication_crash_rebound.md)
- #5 [자체연구-규약] **허용오차는 SE 기준으로 사전 고정**: 승률 허용오차 = max(반올림 단위, 0.5·√(p(1−p)/n)). n 26이면 ≈4.9%p(그래서 5%p), n 1,000이면 ≈0.8%p. 고정 숫자 '5%p'를 모든 연구에 쓰면 큰 표본에서 진짜 불일치를 놓친다. (출처: 2026-10-17 복기)

## 현업 vs 교과서
- #6 [논문] 모델검증(SR 11-7, 미 연준·OCC 2011)은 검증팀의 **독립성**(개발자와 보고 라인 분리)·**효과적 도전(effective challenge)**·**결과 분석(outcome analysis, 백테스트)** 3요소를 요구한다. 우리 구조: 검증 데스크는 퀀트와 피어(지시 없음)이고 뒤집을 권한이 있음 — 독립성은 충족, 다만 같은 데이터 창고(data/hist)를 쓰므로 데이터 오류는 양쪽에 공통 → 데이터 데스크 매니페스트(_manifest.json 출처·행수)를 재현 보고서에 적는다. (출처: Federal Reserve SR 11-7 / OCC 2011-12 "Supervisory Guidance on Model Risk Management" `[확인 필요: SR 11-7 절 번호 — 검증 데스크, 2026-10-24 라운드까지]`)

## 흔한 오해
- #7 [자체연구-규약] "재현 일치 = 등급 상향" → 아니다. 재현은 **숫자가 맞는지**만 확인한다. 등급(A/B/C/F/검증전)은 사전등록·Bonferroni·OOS 규약(kb:quant#4)으로 정해지며, crash_rebound 처럼 사전등록 §0이 없는 연구는 재현이 맞아도 **참고(C 상한)**다.
- #8 [자체연구-규약] "원 코드를 보고 검산하면 빠르다" → 빠르지만 재현이 아니라 코드 리뷰다. 같은 off-by-one(창 i+5 vs i+4)을 그대로 따라간다. 명세가 모자라면 **명세를 보완해 달라고 요청**하지 코드를 열지 않는다.

## 터미널에서 보는 자리
- #9 [자체] QUANT › 스터디 탭의 연구별 등급 옆에 재현 여부는 아직 없음 — `reports/studies/replication_<id>.json` 의 `rows[].verdict` 를 읽어 '재현 n/m 일치' 배지를 붙이는 것이 다음 고치기 후보(탭 파일 tab_quant.html 잠금 필요).

## 우리 연구와의 차이
- #10 [자체연구-C(참고), 재현 일치·신뢰도 중] **crash_rebound §3 (코스피 −5% 종가 매수 → 122630, 5거래일 보유, 왕복비용 0.05%, 데이터 2010-02-22~2026-10-16)**: 원 n 26건·승률 61.5%·평균 +7.2% vs 재현 n 25건·60.0%·+6.8%(Wilson 95% 40.7~76.6%). 사건 날짜 27개 완전 일치, 6/6 항목 허용오차 안 **일치**. 결론: 인용 시 'n·승률·평균·최악' 4개 묶음 + 등급 C — 퀀트·CIO, 10/18 리뷰까지; 뒤집는 조건 = §0 사전등록 후 Bonferroni B 이상. 반대 근거: 사건 27건 중 15건이 2026-06~10 한 국면. 1건 차이는 마지막 사건의 '5거래일 뒤 종가' 유무(창 정의 또는 실행 시점) — 코드 미열람이라 `검증전`. 데이터 출처(pykrx KOSPI vs 야후 ^KS11)·close/adj_close·비용 0 민감도 모두 결론 불변. (출처: reports/studies/replication_crash_rebound.md, 2026-10-17)

## 출처
- NASEM, *Reproducibility and Replicability in Science*, National Academies Press 2019 — 3장 정의 (공개 PDF, 확인 2026-10-17)
- Freese & Peterson, "Replication in Social Science", *Annual Review of Sociology* 43, 2017, 147–165 — 재현 유형 2×2 (데이터 같음/다름 × 분석 같음/다름)
- Brown, Cai & DasGupta, "Interval Estimation for a Binomial Proportion", *Statistical Science* 16(2), 2001, 101–133 — Wald 구간 커버리지 결함, Wilson 권고
- Federal Reserve SR 11-7 / OCC Bulletin 2011-12, "Supervisory Guidance on Model Risk Management", 2011 — 독립 검증·효과적 도전 `[확인 필요: 절 번호, 2026-10-24까지]`
- 자체: scripts/replicate_crash_rebound.py · tests/test_replicate_crash_rebound.py · reports/studies/replication_crash_rebound.md · docs/desk_kb/quant.md #4·#10·#11

## 복기 (틀린 판단 → 왜 → 다음부터)
- **2026-10-17 · 재현 허용오차를 결과 보기 직전에 코드 안에 고정 숫자로 적음** — 틀린/애매한 판단: n≤2·승률 5%p·평균 1%p를 결과를 보기 전에 적긴 했지만 파일(§0)로 사전등록하지 않았고, 표본 크기와 무관한 고정값이었다. → 왜: 첫 사례라 '일단 돌려보자'가 앞섰다. 고정 5%p는 n 26에서는 0.5·SE 수준이라 우연히 적절했지만 n 수백이면 너무 느슨하다. → 다음부터: 재현 보고서 §0에 허용오차를 **SE 기반 식(kb:verify#5)**으로 먼저 적고 커밋한 뒤 실행한다. 또 사건 날짜 목록 대조(#2 ①)를 통계 비교보다 먼저 표에 넣는다.
