# 문헌 KB — 파생·변동성·한국 야간선물

`docs/desk_kb/derivs.md` 를 보는 데스크(파생·CIO)가 **다음 라운드에 볼 방향**으로 읽는 카드. 형식·검사 규약은 `docs/desk_kb/lit/README.md`, 후보 원장은 `content/papers/index.json`. 우리 가설 2건(VRP 반등 필터·야간선물 갭)의 문헌 앵커가 이 파일에 있다.

- **Carr·Wu (2009)** Variance Risk Premiums · RFS 22(3), DOI 10.1093/rfs/hhn038 · [서지]
  - 결론: 내재분산 − 실현분산이 분산 리스크 프리미엄(VRP)이고, 주식시장에는 체계적으로 음(-)의 분산 수익(보험 매도 프리미엄)이 존재하며 VRP는 시장 위험의 대리변수다.
  - 한계: 합성 분산 스왑 복제 가정(점프·이산화 오차), 미국 지수 중심, 쪽수 미대조(Crossref 발행일 2008은 온라인 선공개).
  - 적용: derivs · `screener/vrp_filter.py` · `reports/studies/derivs_signals.json` — VRP 정의를 IV²−RV²로 통일하고 'IV−RV' 표기와 구분해 적는 기준.
  - 뒤집힐 조건: VRP 부호가 반등 성과를 가른다는 우리 검정(`reports/studies/2026-11-14_vrp_rebound_filter.md`, 등급 F)이 뒤집히지 않는 한, VRP는 방향 신호가 아니라 '보험료'로만 쓴다.

- **Amaya·Garcia-Ares·Pearson·Vasquez (2025)** 0DTE Index Options and Market Volatility · SSRN 5113405, DOI 10.2139/ssrn.5113405 (Cboe 리서치 게시) · [원문 발췌]
  - 결론: 2020-07~2023-06 SPX 1분 단위 복원에서 딜러 감마는 통상 양(+)이라 변동성을 −0.08%p(중앙값) 낮추지만, 음(-)으로 돌 때 연율 변동성을 일 +3.3%p·30분 +6.4%p까지 키웠다.
  - 한계: Cboe 독점 거래내역 의존(재현 불가), GARCH 계열 반사실 시뮬레이션 가정, 2020~23 표본.
  - 적용: derivs · `reports/studies/gamma_regime.json` — 0DTE 만기일(월·수·금) 장중 판단에 '당일 감마 부호'를 필수 칸으로 두는 근거. 우리는 딜러 포지션 데이터가 없어 프록시임을 명시한다.
  - 뒤집힐 조건: 아래 Vilkov (2025) 처럼 감마 부호가 반대로 추정되는 표본이 나오면 '변동성 확대' 단정을 빼고 부호 조건부로만 쓴다.

- **Dim·Eraker·Vilkov (2024 preprint)** 0DTEs: Trading, Gamma Risk and Volatility Propagation · SSRN 4692190, DOI 10.2139/ssrn.4692190 · [초록]
  - 결론: 0DTE 거래량 급증이 지난 변동성을 증폭한다는 증거는 없고, 만기 2일 이상 옵션에서 미결제약정 감마가 큰 날은 당일 실현변동성이 오히려 낮다(헤지자가 순매수 감마). 0DTE 와 기초시장의 장중 결합도는 2021년 전 0.25~0.30 에서 2023년 0.59 로 올랐다.
  - 한계: 포지션 추정이 미결제약정 감마 프록시에 의존하고, 워킹페이퍼(동료심사 전)이며 RFS 재투고 판이 따로 있다.
  - 적용: derivs · `reports/studies/gamma_regime.json` — 위 Amaya 카드와 정면 충돌하므로 두 카드를 나란히 두고 '차이' 절에 양쪽을 기록한다. 0DTE 를 '변동성 확대 원인'으로 단정하지 않는 쪽의 근거.
  - 뒤집힐 조건: 동료심사 판본에서 표본·추정이 바뀌어 부호가 뒤집히면 Amaya 쪽을 기본값으로 되돌린다.

- **이우백·우민철 (2013)** KOSPI200선물 글로벌 야간시장의 장중 가격발견 효율성 · 선물연구 21(2) 169–202 · KCI https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001772336 · [초록]
  - 결론: 2009-11~2011-11 틱데이터에서 야간 가격발견은 비대칭 'W'자이고, 전일 폐장→당일 개장 구간이 24시간 가격발견을 주도하며 야간장 정보는 CME보다 미국 뉴욕 증시 변동에 반응한다.
  - 한계: 표본 2년(2011년까지)으로 2025-06 KRX 자체 야간시장 개설(Eurex 연계 종료) 이후 구조를 반영하지 못한다.
  - 적용: derivs · `screener/deriv_hist.py` · `data/deriv/daily.csv` — 야간 세션 필드(`night_vwap`·`night_vol`)를 정의할 때의 원형. 갭 가설(`reports/studies/2026-11-14_night_gap_guard.md`)의 출발점.
  - 뒤집힐 조건: 2025년 이후 야간 세션에서 개장 전 구간의 정보 비중이 유의하게 낮아지면(구조 변경) '야간이 방향을 만든다'는 전제를 다시 본다.
