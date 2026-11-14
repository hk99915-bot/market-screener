# 문헌 KB — 리스크·사이즈(FRM)

`docs/desk_kb/frm.md` 를 보는 데스크(리스크·CIO)가 **다음 라운드에 볼 방향**으로 읽는 카드. 형식·검사 규약은 `docs/desk_kb/lit/README.md`, 후보 원장은 `content/papers/index.json`. 카드는 5칸(출처·결론·한계·적용·뒤집힐 조건)을 모두 채우고 6줄을 넘기지 않는다.

- **Cederburg·O'Doherty·Wang·Yan (2020)** On the performance of volatility-managed portfolios · JFE 138(1) 95–117, DOI 10.1016/j.jfineco.2020.04.015 · [서지]
  - 결론: 실시간(1개월 래그·거래비용 반영)으로는 변동성 관리가 대부분 팩터에서 비관리 전략을 이기지 못한다 — 초과성과는 표본·타이밍 가정에 민감하다.
  - 한계: 팩터 정의·표본 기간 의존, ETF 시대 이전 데이터 비중이 크다.
  - 적용: frm · `docs/desk_kb/frm.md` 리스크 한도 문장 — 변동성 타게팅 규칙에 래그·비용·비관리 벤치마크 3조건이 없으면 등급 상한 C로 두는 근거.
  - 뒤집힐 조건: 우리 표본에서 3조건을 넣고도 초과 샤프가 유지되면 상한을 B로 올린다.

- **Thorp (2006)** The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market · Handbook of Asset and Liability Management(Elsevier), DOI 10.1016/S1872-0978(06)01009-X · [서지]
  - 결론: 성장률을 최대화하는 베팅 비중 f*의 성질과 부분 켈리(1/2·1/4)의 실무 근거를 제시한다 — 추정오차·비정규 수익률 때문에 full Kelly는 과도한 변동성과 파산 위험을 낳는다.
  - 한계: 기대·분산 모수를 안다고 가정하고, 다자산·동적 일반화는 별도 문헌이다.
  - 적용: frm · `docs/desk_kb/frm.md` — 사이즈 상한에 'f* 추정오차 → 1/2~1/4 켈리' 1줄을 두고, 켈리 계산은 등급 B 이상 신호에만 허용하는 규약의 근거.
  - 뒤집힐 조건: 우리 표본에서 1/2 켈리가 full Kelly보다 위험조정 성과가 유의하게 나쁘면 상한 배수를 다시 정한다.
