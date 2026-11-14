# 문헌 KB — 자산배분·행동재무

`docs/desk_kb/allocation.md` 와 `docs/desk_kb/behavior.md` 를 보는 데스크(자산배분·행동·CIO)가 **다음 라운드에 볼 방향**으로 읽는 카드. 형식·검사 규약은 `docs/desk_kb/lit/README.md`, 후보 원장은 `content/papers/index.json`.

- **Campbell·Pflueger·Viceira (2020)** Macroeconomic Drivers of Bond and Equity Risks · JPE 128(8), DOI 10.1086/707766 · [서지]
  - 결론: 주식·채권의 위험 노출은 인플레이션 민감도가 결정하고, 인플레 민감도가 큰 국면엔 주식·채권이 같이 움직여 분산효과가 사라진다.
  - 한계: 미국 중심, 민감도 추정이 실질금리·기대인플레 분해에 의존한다.
  - 적용: allocation · `reports/portfolios.json` — 60/40·주식-채권 분산 가정에 '인플레 민감도 레짐에서만 유효'라는 조건을 붙이는 근거.
  - 뒤집힐 조건: 국내 표본에서 인플레 민감도가 낮은 구간에도 상관이 함께 오르면 레짐 조건을 완화한다.

- **Moreira·Muir (2017)** Volatility-Managed Portfolios · JF 72(4) 1611–1644, DOI 10.1111/jofi.12513 · [서지]
  - 결론: 직전 변동성의 역수로 비중을 조절하면(변동성 타게팅) 팩터 포트폴리오의 샤프가 개선되고 알파가 남는다 — 변동성 상승은 이후 수익률 하락을 예고한다.
  - 한계: 예측 가능성의 상당 부분이 소표본·특정 팩터에서 나오고, 1개월 래그·거래비용을 넣은 실시간 적용에서 성과가 줄어든다.
  - 적용: allocation · `screener/portfolios.py` — 사이즈 규칙 원형(목표변동성 ÷ 최근 실현변동성). 규약에 래그·비용·비관리 벤치마크 3조건을 명시적으로 붙인다.
  - 뒤집힐 조건: 아래 Cederburg et al. (2020) 조건(래그·비용·벤치마크)을 넣었을 때 초과성과가 사라지면 등급 상한은 C로 내린다.

- **Barber·Odean (2008)** All that Glitters: The Effect of Attention and News on the Buying Behavior of Individual and Institutional Investors · RFS 21(2) 785–818, DOI 10.1093/rfs/hhm079 · [서지]
  - 결론: 개인투자자는 관심을 끈 종목(뉴스·거래량 급증)을 사고, 기관은 그렇지 않다.
  - 한계: 미국 1990년대 후반~2000년대 초 브로커리지 표본으로 앱 기반 소매투자 이전 자료다.
  - 적용: allocation · `docs/desk_kb/behavior.md` '관심도 매매' 정의 — 거래대금·검색·커뮤니티 언급 급증을 관심도 프록시로 쓰는 근거.
  - 뒤집힐 조건: 관심 급증 뒤 초과수익의 부호는 이 카드로 정하지 않는다(부호는 추격 금지 쪽 카드 소관). 국내 검정에서 부호가 반대면 프록시 정의만 남긴다.
