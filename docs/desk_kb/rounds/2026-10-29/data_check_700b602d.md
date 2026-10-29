# 데이터 점검 — req-data-700b602d (HF → 데이터, 퀀트 req-quant-ec93e2cb 의존성)

기준 2026-10-29 KST · 출처: 저장소 파일 실측(명령은 각 행) · 릴리스 자산은 `python3 scripts/data_store.py pull --groups flows,prices` 로 10/29 받은 판(sha256 = data/data_store_manifest.json)

- **What**: detail 차트 1,474종목 중 1,385종목 정확히 260봉(나머지 89 = 신규 상장 등 <260) · 상한은 screener/detail.py:391·403 `tail(260)`
- **What**: 500봉 이상 경로 저장소 안 존재 — `prices.load_kr(hist_from=2010)` = 2010-01-04~2026-10-28, 3,698종목, 000660 4,132봉(달력 4,132일과 일치, 결측 0)
- **What**: fut_frgn 실데이터 10행(2026-10-15~10-28)뿐, 그 앞 4,129행 공란 · 종목 수급은 2022-01-03~2026-10-28 1,177거래일(000660 1,177일)
- **So What**: 퀀트 ① 역케이스·③ 수급 층별은 지금 데이터로 가능, ② '선물 방향 일치/엇갈림' 층은 n=10 → 검정 불가
- **So What**: detail 유니버스 = 현재 상장 종목만(생존편향) → HF 예비 계산(97% vs 65%)은 창(260봉)·유니버스 둘 다 편향, 등급 검증전 유지
- **Now What**: 퀀트 = detail 대신 load_kr(hist_from)+data/flows 사용, 선물 층은 '데이터 없음(10행)'으로 사전등록에서 분리 — 10/31까지
- **Now What**: 데이터 = fut_frgn 과거분 소스 탐색(Actions 탐침, KRX MDCSTAT13101 파라미터) — 11/05까지, 못 찾으면 매일 적재로 60행(약 2027-01 초) 대기

## ① 봉 수 — 260 상한과 500봉+ 경로
| 항목 | 값 | 근거 |
|---|---|---|
| detail KR 파일 수 | 1,474 | `ls reports/detail/KR \| wc -l` |
| chart 봉 수 분포 | 260봉 1,385 · 250~259봉 15 · <250봉 73 · 0봉 1 | chart·c1y 길이 집계(python, 같은 분포) |
| chart 구간(260봉) | 2025-09-30 첫 봉(1,318종목) ~ 2026-10-28 | chart[0].t·chart[-1].t 최빈값 |
| 260 상한 위치 | screener/detail.py:391 `group_by("yf").tail(260)`(차트) · :403 `g.tail(260)`(c1y) | grep |
| 그 앞 단계 상한 | data/kr_prices.parquet 자체가 2025-09-09~ (000660 275행) — data_krx.py:181 `update(lookback_days=400)` 최초 백필 창, 이후 증분·잘라내기 없음 | 파일 실측 |
| 같은 260 류 | etf.py:166(ETF 차트)·alphabook.py:417 `_kr_universe_bars(n=260)`·derivs.py:509 | grep |
| **500봉+ 경로(저장소 안)** | data/hist/kr_2010~2025.parquet(git 추적, KRX 날짜별 전종목, 원주가) + kr_prices(2026분) → `screener.prices.load_kr(hist_from=연도)` 가 이어 붙이고 분할 보정 | prices.py:86 · backfill.py:1~4 |
| 이어 붙인 결과 | 2010-01-04~2026-10-28 · 3,698종목 · 10월 거래 종목 2,678 중 ≥500봉 2,456 · ≥1,000봉 2,230 · 중앙값 3,778봉 | load_kr(hist_from=2010) 실측 |
| 샘플 | 000660 4,132 · 005930 4,129 · 042700 4,112 · 035420 4,108 · 196170 2,905(2014-12 상장) · 247540 1,873(2019-03 상장) | 같은 명령 |
| 이음매 대조 | 000660 hist 2025 vs kr_prices 겹침 75일 종가 차 최대 0원 | join 실측 |
| 외부 소스 | 시도 안 함 — 저장소 안 경로로 충분 | — |

## ② fut_frgn(외국인 코스피200 선물 순매수)
| 항목 | 값 | 근거 |
|---|---|---|
| 위치 | data/deriv/daily.csv 열 fut_frgn·fut_inst·fut_indiv (단위 **계약**, 현물 spot_frgn 은 억원) | deriv_hist.py:19·51 |
| 소스 | 네이버 모바일 /api/index/FUT/integration dealTrendInfo — **당일값만**, 과거 조회 불가 | deriv_hist.py:255 fut_investor_today |
| 기간·행 | 2026-10-15~10-28 **10행** / 파일 4,139행(2010-01-04~) → 공란 4,129행 | daily.csv · reports/deriv_hist_status.json coverage |
| 결측 패턴 | 적재 시작 전 전 구간 공란(구조적), 적재 후 10거래일 연속 결측 0 · 0값 0건 | 연속 공란 구간 집계 |
| 과거분 대안 | KRX 파생 투자자별 MDCSTAT13101 = 파라미터 미확인으로 0만 옴(코드 주석) · KRX OPEN API 파생 6종은 일별매매정보(투자자별 포함 여부 미확인, KRX_API_KEY 미등록 — 보드 user-krx-openapi-key) | deriv_hist.py:20 · data.md KRX OPEN API 절 |

## ③ 종목별 외국인·기관 수급 이력
| 항목 | 값 | 근거 |
|---|---|---|
| 위치 | data/flows/kr_inv_YYYY.parquet(릴리스 자산 data-latest, gitignore) — 열 f·i·pen·trust, 단위 백만원 | accum.py:14 · data_store.py GROUPS['flows'] |
| 기간 | 2022-01-03~2026-10-28, **1,177거래일** — deriv daily 달력과 대조 결측일 0 | 날짜 집합 비교 |
| 연도별 | 2022 246일·2023 245·2024 244·2025 242·2026 200 | 파일별 실측 |
| 종목당 | 3,067종목, 중앙값 1,177일 · 10/20 이후 거래 2,765종목 중 ≥900일 2,370 | group_by 실측 |
| 000660 | **1,177일**(2022-01-03~2026-10-28, 전 거래일) | 실측 |
| 정정 | alpha_sources C1 의 '2024-11-26~' 는 옛 판 — 10/28 2022·2023 업로드로 확장 | data_store_manifest.json uploaded_at |
| 더 과거 | `python -m screener.accum backfill --since 2020-01-01`(Actions 전용, 샌드박스 KRX 차단) — 옵션 존재, 실행 미확인 | accum.py:16·525 |
| detail 안 수급 | flows 10행(1,251종목)·0행 219 — 연구용 아님 | detail.py:53·355 days=10 |

## ④ 생존편향
| 데이터 | 상폐 포함 | 근거 |
|---|---|---|
| data/hist/kr_YYYY | 포함 — 2026-10-01 전에 끝난 종목 1,020개(2010 108 … 2025 103·2026 122) | backfill.py:3 KRX 날짜별 전종목 · 마지막 거래일 연도 집계 |
| data/kr_prices | 포함 — 10/01 전 끝난 종목 150 | 같은 방식 |
| data/flows | 포함 — 10/20 전 끝난 종목 302 · ETF·ETN·스팩은 이름 규칙으로 제외 | accum.py:1·11 |
| reports/detail/KR | **미포함** — 현재 화면 유니버스 1,474종목뿐 | 파일 목록 |
| 한계 | '끝난 종목'에 종목코드 변경·장기 거래정지 섞임(구분 미확인) · 거래량 0일(정지) 행 제외 → 정지 구간 공백 · 분할 보정은 ±31% 규칙(배당·소규모 유상 미보정) | data_krx.py:56 · prices.py |

## 반대 근거·유의
- hist 2010 이전 없음, 2010 상폐 108개는 그해 이전 이력 미보유 · 코드 변경 종목은 두 개로 쪼개져 보일 수 있음(검증전)
- fut_frgn 10행 = 2주 한 국면(−9,540~+12,101계약) — 레짐 대표성 없음

VOC: 데이터 — 가격·수급은 창고에 이미 있음(퀀트가 detail 대신 창고를 읽으면 됨), 막힌 건 선물 투자자별 과거분 하나.
요청→퀀트: req-quant-ec93e2cb 에서 load_kr(hist_from)·data/flows 사용, 선물 층은 '데이터 없음(n=10)'으로 분리.
현재 상태: ①③④ 실측 완료 · ② 과거분 소스 미확보(탐침 11/05) · 수집 코드 변경 없음(제안만).
