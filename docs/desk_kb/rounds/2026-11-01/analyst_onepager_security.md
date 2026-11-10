# 애널 — 산업 한 장: 사이버보안·네트워크(SASE/ZTNA·방화벽·신원·엔드포인트·SOC·복구) · 기준 2026-11-01 KST(SEC 분기 ~2026-09-30·detail 10/30 종가) · 분석만, 매매 권고 아님
- 틀 `docs/desk_kb/industry_onepager_template.md` · 상세(체인·변천사·파생·추세·이슈·자기 반박 로그·경로) `analyst_onepager_security_appendix.md` · 자료: us_quarterly.parquet·SEC companyfacts 6사·detail US 14/KR 6·research.parquet(PDF 4)·chains_view·rounds 10/30~31·비공개 딥리서치 · 웹 10회

**So What 한 줄:** 보안 지출은 연 11~13% 크고 수요 지표는 오히려 가속 중인데, 돈은 '통합하는 쪽'(상장 플랫폼·하이퍼스케일러)으로 빨려 들어가고, 가격은 성장 감속 한 번을 못 견디는 구간이야 — 쟁점은 수요가 아니라 '누가 통합하나'와 '감속 때 배수'. 등급 C·신뢰도 중.
- **What:** 누나가 보기엔 시장(지출 +11%)보다 상장 순수 11사 매출이 훨씬 빨리 커(2020→2026 TTM CAGR 26%). 망을 갈아엎지 않고 덧대는(VPN 자리 ZTNA·신원·복구) 구독이 기본 경로가 됐어.
- **So What:** 미장은 숫자 강한데 비싸(FCF 수익률 1.5~3.4% < US10Y 4.98%), 국장은 정책·공공 예산으로 도는 별개 사이클이라 미장 체인으로 읽으면 틀려.
- **Now What:** 조치 없음. 11월 실적 순신규 ARR·RPO·제품 매출 YoY + 국장 3Q 분기보고서만. 뒤집을 숫자: CRWD 순신규 ARR YoY 마이너스.

| 축·칸 | 핵심(액션 타이틀) | 근거·출처 |
|---|---|---|
| A ① 규모 | 세계 보안 지출 2026 약 2,440~2,490억$(+11.6~12.7%) → 2030 약 3,728억$, CAGR ~10.8% · SASE 2025 ~120억달러 → 2030 240억달러(CAGR 15%) · 국내 9.3조(2025)→10.6조원(2026E) | [Gartner abstract](https://www.gartner.com/en/documents/7408930)(1차)·[개정치 2차](https://softwarestrategiesblog.com/tag/cybersecurity-spending-2026/) · [Dell'Oro](https://www.delloro.com/news/sase-is-putting-the-nail-in-the-coffin-for-access-routers-as-market-drops-25-percent-in-3q2025/) · KISIA 실태조사(IR협의회 2026-09-08 경유) · 식 (3728/2475)^(1/4)−1 [애널 환산] |
| A ② 연결 체인 | 사고 → 규제·보험 요건 → IT 예산(연 단위) → 빌링 → RPO → 매출, 옆에서 10Y(−)·하이퍼스케일러 번들(−) | 우리 체인(chains_view 0.29)은 미장 동일 사이클+CIBR+10Y만 — 국내 정책·상류 원가 고리 없음(부록 §1) |
| A ③ 이익풀 | **GAAP 영업이익은 FTNT가 95%, 현금은 플랫폼(PANW 33%·FTNT 25%·CRWD 15%)** — 차이는 주식보상(FTNT 3.9% vs 23~26%) | us_quarterly TTM 11사(영업이익 25.8억$·영업CF/매출 36.2%) · companyfacts ShareBasedComp 최근 분기 |
| A ④ 집중도 | 전체는 파편화(상위 4사 매출 ≈ 지출의 11%), 하위 시장은 과점(SASE 상위 6 = 72%, ZS 21%, 3Q24) · 국내 NAC 지니언스 75%·EDR 49%(2024 조달청) | (114.8+54.0+75.3+33.5)/2,475 [애널 환산, 기간 불일치] · [Dell'Oro](https://www.delloro.com/news/top-six-sase-vendors-own-72-percent-of-2-4-b-3q-2024-market/) · IR협의회 2026-01-27 |
| A ⑤ 전환비용·왜 | 매출총이익률 72~80%·RPO 성장 ≥ 매출(CRWD +48.6% vs +26%) = 잘 안 바꿔 · **왜:** 공격면이 옮길 때마다 새 카테고리 → 파편화 → 도구 피로 → 할인 끼운 통합(PANW GM 73.0→67.6%) | companyfacts GrossProfit·RPO(end 2026-04~09, 전년 동기 대비) |
| B ⑥⑦ 변천사·파생 | 경계·백신 → UTM/NGFW → 클라우드·EDR → 원격·ZTNA → **통합·AI**(PANW–CyberArk 250억$, GOOGL–Wiz 320억$) · 방화벽→NGFW→SASE, 백신→EDR→AI SOC, 관제→MDR, 판매→구독→크레딧 번들 | 부록 §3·§4(연대 일부 애널 기억, 1차 미대조) |
| B ⑧ 추세 | 단기: 실적 가속(CRWD 순신규 ARR 3.33억$ 최대) vs 가격 감속 공포 · 중기: 통합·SASE·교체 사이클(FTNT 제품 +52→+37%) · 장기: AI 공격/방어·머신 신원·PQC | 부록 §5 · FTNT 10-Q·CRWD IR(검색 요약 경유) |
| C ⑩ 핵심 이슈 | ① 플랫폼 vs 단일 제품(플랫폼 우세, 마진 대가) ② 클라우드 SASE vs 하이브리드 방화벽(둘 다 성장) ③ 하이퍼스케일러 번들(미확인) ④ AI = 지출↑ vs 가격 압박(검증전) ⑤ 수요 vs 배수(배수 불리) | 부록 §6 양쪽 숫자·판가름 지표 |
| D ⑪ 반대 근거 | FTNT 가이던스 3번째 상향에도 10/28 시간외 −26% · BUG–QQQ 상관 0.48 · 플랫폼 집중 = 장애 1건이 업종 전체 위험(CRWD 2024-07) | analyst_security_1031 |

| ⑫ 매핑(≠ 추천) | 밸류(분모 범위) | 상태 |
|---|---|---|
| FTNT | PER TTM 47.1 / 런레이트 41.2 / 가이던스 38.0~38.4 · 정규화 미산출 · E/P−rf −2.9%p · 20일 −24.8% 전부 배수(EPS 변화 0 가정, 검증전) | 3Q 매출 +20.5%·RPO +18.8%(1차), 교체 사이클 감속 중 |
| PANW·CRWD·ZS·OKTA·NET | P/FCF ZS 45.5·PANW 65.5(capex 미수집, 과소) · CRWD·OKTA 배수 미산출 | RPO +17~49% · 가격은 실적일 리스크 |
| 국장 안랩·지니언스·라온·윈스 | PER 안랩 46.7/44.3 · 지니언스 24.3/23.4(TTM/런레이트) · 4Q 이익 집중 50~69% | 정책 사이클 · 안랩 3Q 잠정 영업익 +38.7%(보도) |

- **확인 불가(찾은 경로 부록 §9):** 전체 보안 점유율·HHI · NRR · PANW 유기 성장 · MSFT 보안 매출 · FTNT 3Q SASE 빌링 · RBRK·CVLT·SAIL·이글루·SGA detail.
- **뒤집힘 조건:** ① CRWD 순신규 ARR YoY 마이너스 ② FTNT 제품 YoY 한 자릿수 + SASE 빌링 가속(이익풀 이동) ③ PANW 유기 NGS ARR <15%(통합 논리 약화).

VOC: 애널 데스크 실제 작업(SEC parquet·companyfacts·detail·리포트 PDF 대조, 자기 반박 2회전, 웹 10회)
요청→데이터: chains 국내 정책·상류 고리 · 미수집 6종 detail [확인 필요: 데이터 데스크, 2026-11-16]
현재 상태: 한 장+부록 완료 · 결론 C/중 · 10/31 판정 변화 없음(가격 쪽 근거만 보강)
