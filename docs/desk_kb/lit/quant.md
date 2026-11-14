# 문헌 KB — 퀀트·ML·백테스트 규율

`docs/desk_kb/quant.md` 를 보는 데스크(퀀트·검증·연구소)가 **다음 라운드에 볼 방향**으로 읽는 카드. 형식·검사 규약은 `docs/desk_kb/lit/README.md`, 후보 원장은 `content/papers/index.json`. 카드는 5칸(출처·결론·한계·적용·뒤집힐 조건)을 모두 채우고 6줄을 넘기지 않는다.

- **Moskowitz·Ooi·Pedersen (2012)** Time series momentum · JFE 104(2) 228–250, DOI 10.1016/j.jfineco.2011.11.003 · [서지]
  - 결론: 58개 선물의 과거 1~12개월 수익 부호가 다음 달 수익을 예측하고, 12개월을 넘기면 부분적으로 반전한다(TSMOM의 표준 정의).
  - 한계: 선물 중심 표본, 최근 10년 성과 약화 논쟁, 롤·비용 처리 가정에 의존한다.
  - 적용: quant · `screener/lab.py` — lab 가설 접수 때 horizon 칸에 '12−1 모멘텀 / 1개월 반전'을 구분해 적게 만드는 근거.
  - 뒤집힐 조건: 우리 KR 표본에서 horizon 구분 없이 같은 신호가 나오면(구분이 정보를 안 주면) horizon 강제를 푼다.

- **Gu·Kelly·Xiu (2020)** Empirical Asset Pricing via Machine Learning · RFS 33(5) 2223–2273, DOI 10.1093/rfs/hhaa009 · [서지]
  - 결론: 트리·신경망이 선형 팩터 모형보다 OOS 예측력을 높이지만 월간 OOS R² 개선은 1% 미만이고, 이득은 비선형 상호작용·유동성·변동성 변수에서 나온다.
  - 한계: 미국 1957~2016 표본, 데이터 스누핑 위험, 피처 정의 의존.
  - 적용: quant · `scripts/study_rule_audit.py` — ML 신호 도입 시 'R² 몇 %p 개선' 목표를 사전등록하게 만드는 기대치 상한.
  - 뒤집힐 조건: 우리 데이터에서 선형 모형 대비 OOS R² 개선이 사전 목표를 못 넘으면 ML 트랙을 접는다.

- **Haddad·Kozak·Santosh (2020)** Factor Timing · RFS 33(5) 1980–2018, DOI 10.1093/rfs/hhaa017 · [원문 발췌]
  - 결론: 마켓뉴트럴 팩터 수익은 강하게 예측 가능하다 — 상위 5개 주성분으로 축소해 BM 비율로 예측하면 OOS R² 약 4%, 팩터 타이밍 포트폴리오 샤프 0.71, SDF 분산 1.66→2.96.
  - 한계: 미국 50개 anomaly 포트폴리오, 예측변수 1개(BM)로 제한, 다중검정 부담은 차원 축소로 완화했을 뿐 제거가 아니다.
  - 적용: quant · `reports/studies/trial_log.md` — 팩터 50개 개별 예측 대신 주성분 축소 후 예측으로 사전등록해 시도 N을 아끼는 처방.
  - 뒤집힐 조건: 축소 후 예측이 개별 예측보다 OOS에서 나쁘면(샤프 기준) 축소 처방을 폐기한다.

- **Bailey·Borwein·López de Prado·Zhu (2016)** The Probability of Backtest Overfitting · Journal of Computational Finance 19(4), DOI 10.21314/jcf.2016.322 · [서지]
  - 결론: CSCV(조합적 대칭 교차검증)로 'IS 최고 전략이 OOS에서 중앙값 이하일 확률'(PBO)을 측정한다. 시도 수가 늘면 PBO가 급격히 오른다.
  - 한계: 계산량이 크고 전략 집합 정의에 민감하며, 표본이 짧으면 추정이 불안정하다.
  - 적용: quant · `scripts/study_rule_audit.py` — `quant.md` '10년차 기준'의 PBO 서지 확인 필요 항목을 이 서지로 종결하고, DSR 대안과 함께 선택지로 구현한다.
  - 뒤집힐 조건: 우리 연구 표본 길이(대부분 60~240거래일)에서 CSCV 조합 수가 10 미만이면 PBO 대신 DSR만 쓴다.

- **Lopez-Lira·Tang (2023)** Can ChatGPT Forecast Stock Price Movements? · arXiv 2304.07619 · [서지]
  - 결론: 뉴스 헤드라인을 LLM에 주면 다음 날 수익 방향을 예측하고, 그 신호로 만든 롱숏이 비용 후에도 유의한 성과를 낸다(GPT-3.5 초기 버전에서도 나타남).
  - 한계: 2021-10~2022-12 표본, 모델·프롬프트 버전 의존, 소형주 편중과 유동성 제약.
  - 적용: quant · `reports/lab_queue.json` — 뉴스·공시 텍스트를 알파 소스로 쓰는 실험의 첫 근거. 무료 플랜이라 상시 호출 대신 주 1회 배치로만.
  - 뒤집힐 조건: 학습 컷오프 이후 OOS에서 신호가 사라지면(아래 Li et al. 2025 참조) 배치 실험을 중단한다.

- **Anic·Barbon·Seiz·Zarattini (2025)** ChatGPT in Systematic Investing · arXiv 2510.26228 · [원문 발췌]
  - 결론: 뉴스 점수로 모멘텀 후보를 조건화하면 2024-01~2025-03 OOS 샤프가 0.79에서 1.06으로 오르고 알파 3.26%p(유의수준 10%), 턴오버는 0.48→0.80(비용 2bp 가정).
  - 한계: OOS 15개월, 하이퍼파라미터를 검증구간에서 선택(그 자체가 다중검정), 2bp 비용 가정은 낙관적이고 뉴스 API에 의존한다.
  - 적용: quant · `ops/research_pipeline.json` — LLM 보조 신호의 현실적 기대치. 우리 규약상 등급 상한은 C이고 모의 60거래일 관문을 그대로 통과해야 한다.
  - 뒤집힐 조건: 비용을 10bp로 올렸을 때 알파가 사라지면 이 카드를 채택 근거로 쓰지 않는다.

- **Li·Kim·Cucuringu·Ma (2025)** Can LLM-based Financial Investing Strategies Outperform the Market in Long Run? · arXiv 2505.07078 · [서지]
  - 결론: LLM 타이밍 전략의 우위는 횡단면을 넓히고 기간을 늘리면 사라진다 — 단기·좁은 유니버스 백테스트 성과는 생존·선택 편향의 산물일 수 있다.
  - 한계: 유니버스·비용 설계에 결론이 의존하고, 부정 결과 자체도 벤치마크 선택에 민감하다.
  - 적용: quant · `reports/lab_queue.json` — 위 두 LLM 카드의 반대 근거. 채택 조건을 '학습 컷오프 이후 OOS · 유니버스 확장 · 비용 후' 3개로 고정하는 근거.
  - 뒤집힐 조건: 유니버스를 넓히고 기간을 늘린 재검정에서 LLM 우위가 유지되면 3조건 중 '유니버스 확장'을 완화한다.
