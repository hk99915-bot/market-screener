# 감사(화면) — MARKET TERMINAL 화면 정합성 감사 · 2026-10-17

- 감사 데스크: 감사(화면) · 보고 전용(수정 없음)
- 범위: 빌드된 `index.html`(= `apps-script/Index.html` + `tab_*.html`, `scripts/build_pages.py` 재생성본과 바이트 일치 확인), `reports/*.json`, `ops/*.json`, Pages 산출물(`scripts/data_branch.py site`)
- 도구: `scripts/ui_smoke.py`(기본 7뷰 + 신선도 배지 + US 상세), 별도 헤드리스 스윕(GROUPS 전체 29뷰, pageerror·console error·HTTP≥400·requestfailed 수집)
- 결과 요약: **치명 0 · 중 5 · 경 10**

## 1. 렌더·JS 에러

| 검사 | 결과 |
|---|---|
| `timeout 300 python3 scripts/ui_smoke.py` (저장소 루트) | 10/10 OK — home edu apt rep deriv bond my, 신선도배지(실파일·늦음 주입), US상세(AAPL 색인 200·파일 200) |
| 같은 스모크 `--root` Pages 산출물(`data_branch.py site`, 2,489파일) | 10/10 OK |
| 전체 29뷰 스윕 (home my life kr us heat mdkr mdus bond deriv daily cmt views brief rep val dart chain sig study lab mom pf edu apt eng sysb sysc syso) | 29/29 렌더, pageerror 0, HTTP 4xx/5xx 0 |
| 콘솔 에러 | 1건 — `unpkg.com/lightweight-charts@4.1.3` 로드 실패(이 컨테이너 프록시 터널 차단, 환경 요인). 실제 Pages 에서는 재현 안 될 가능성 높음 |

참고: `ui_smoke.py` 는 29뷰 중 7뷰만, `pageerror` 만 본다(콘솔 에러·HTTP 404 미검사) → 경-1.
MY·LIFE 는 비공개 토큰이 없으면 안내문만 렌더(444자·190자) — 정상 동작이나 반도체 밴드 패널은 헤드리스로 검증 불가.

## 2. 화면 숫자 ↔ 원천 JSON (10항목)

| # | 화면 값 | 원천 | 판정 |
|---|---|---|---|
| 1 | 티커 KOSPI 5,668.05 ▲2.05% | `reports/live.json` KOSPI last 5668.05, chg 0.0205, status CLOSE | 일치 (단 라벨은 'LIVE 10-17 09:47 KST' — 경-2) |
| 2 | 티커 베이시스 +2.89 콘탱고 | live.json K200F basis 2.89 = 881.05 − spot 878.16 | 일치 |
| 3 | 신선도 배지 '데이터 정상 · 점검 16:23' → 감사 중 '13:51' | `reports/freshness.json` checked_at, late=[] | 값 일치. 단 감사 도중 디스크 파일 checked_at 이 16:23 → 13:51 로 **되돌아감**(07:27 UTC 재작성, 커밋본은 13:51) — 경-9 |
| 4 | ACCUM 상위 유니드비티플러스: 시총 403 · 외20 −2 · 기20 +18 · 3.96%/10.76% · 52% · 1/29 · −2.2% · 0.4× | `reports/accum.json` top.accum[0] (f20 −1.6, i20 17.6, fi20_cap 3.965 …), asof 2026-10-16 확정치 | 일치(반올림) |
| 5 | ACCUM KOSPI 대금 20.95조원 · 0.98× · 외5일 −112,395 · 외20 −318,634 · 연기금20 −4,801 | accum.json market.KOSPI | 일치 (244598/250667=0.976) |
| 6 | 밸류에이션(US 종목 포함 반도체 바스켓) 중앙 PER 38.4 · PBR 12.06 · SK하이닉스 5.6/3.46 · 검증 15/16 · asof 2026-10-17 | `reports/valuation.json` basket.median_per 38.37, median_pbr 12.055, n_verified 15/16 | 일치. 'US VALUATION' 이라는 이름의 패널은 없음 — US 값은 이 바스켓과 US 상세 팝업 VALUATION(AAPL 스모크 OK)으로 표시. 미10Y 5일 변화 기준일 혼재 — 경-5 |
| 7 | 운용회의 'C·참고' 기대값 하한 줄 | `screener/committee.py:381` 이 내는 블록 | **미표시** — `committee.json`(2026-10-16 19:44 생성)에 해당 키 없음(10/17 14:09 규칙 이전 생성). 다음 회의 산출 후 재검 필요. 표시된 'C — 참고' 신호(저점 5,590 +1% 위 마감)는 dotplot 규칙 라벨과 일치 |
| 8 | 대결 쿨다운/레버리지 라벨 | `ops/cooldown.json` events=[], `reports/decisions.json` lev_cap 없음 | 쿨다운 바 미표시 = 정상(이벤트 0). 레버리지 라벨은 문제 있음 — 중-4 |
| 9 | 리서치 '국면' 배지·'기준 2026-10-17 14:06 KST' | `reports/research.json` asof 14:06, rg_k.l 분포 하락 814 / 상승 498 / 조정 83 | 일치. 용어 체계 불일치 — 경-6 |
| 10 | 파생 보드 '2026-10-17 01:43' | `reports/derivs.json` date 2026-10-16, asof 2026-10-17 01:43 | 값 일치, 단 헤더가 거래일이 아닌 생성 시각 — 경-3 |
| 11 | 채권 AI 인프라 바스켓 8종(CIFR IREN APLD ORCL WULF CRWV CORZ NBIS) · 고점대비 −65.6%… · asof 2026-10-15 | `reports/bonds.json` ai_credit.kept 8종, missing [], basket dd −0.6559… | 일치. 같은 화면 날짜 혼재 — 경-4 |
| 12 | MY 반도체 밴드 상수(상한 레짐별 35/40/40 · 발동선 45 · 하단 30 · 글라이드 35% 11-30 · VaR99 2.0/1.5%) | `screener/defs.py` | 일치 (`check_rules_terms.py` ✅). 화면 렌더 자체는 토큰 필요로 미검증 |

## 3. 라벨·단위·용어

- **분모 라벨**: 아래 중-2.
- **KST**: 티커·리서치·대결 쿨다운(`tm=t+9h`) 모두 KST 명시/환산. 파생 헤더는 시각만(KST 표기 없음) — 경-3에 포함.
- **'서프라이즈'**: 화면 코드(`apps-script/*`) 자체 사용 0. 데이터 문구로만 등장 — research.json 증권사 제목('실적 서프라이즈 예상/기대'), DAILY 뷰 PB 요약('자회사(LGES) 서프라이즈로…') — 컨센서스 수치 병기 없음 → 경-7.
- **개인 금액**: 아래 중-1. 모의 대결 금액(100만·300만)은 모의값이라 해당 없음.
- **TERMS 일치**: defs.py TERMS 는 '테마 밴드 40/45/30' 인데 화면은 '반도체 밴드 · 결재 #3' — 경-6.

## 4. fetch 경로·getter

- 탭이 호출하는 `google.script.run.getX` 는 전부 `build_pages.py` SHIM 에 있음(누락 0). GAS(Code.gs) 전용 의존 없음.
- SHIM 의 정적 경로 전부 저장소·Pages 산출물에 존재(ops/cooldown.json, ops/renego.json, studies/*, archive/{committee,committee_us}/_index.json 등). `archive/dotplot/_index.json` 은 없지만 화면이 호출하지 않음.
- 죽은 getter: `getDetail → reports/detail_{KR,US}.json` 파일 없음, 호출처도 없음 — 경-8.
- 외부 의존: `polling.finance.naver.com`(대결 청산 현재가, CORS·차단 시 폴백 문구), `raw.githubusercontent.com` live.json(실패 시 Pages 사본 폴백), `unpkg` 차트 라이브러리.

## 5. 심각도 표

| ID | 심각도 | 내용 | 근거 | 담당 데스크 |
|---|---|---|---|---|
| 중-1 | 중 | 공개 Pages 의 MY 탭이 개인 **금액**(순자산 ○○원, 주식 손익 ○○원, 하루 VaR95 ○○원, ISA 코어 ○○원)을 그림. 브라우저 내 계산·비공개 저장소 원천이지만 같은 파일 307행 '화면엔 비율만(금액 금지)'·CLAUDE.md 공개 저장소 규칙과 충돌(스크린샷 유출 경로) | `apps-script/tab_my.html:358,375` | 화면(MY)·PB |
| 중-2 | 중 | 분모 용어 3중 혼재: 화면 '(a) 투자자산/(b) 투자자산+예적금', 'D2', '순자산'. defs.py 는 D2=전체 투자자산(NAV)·D4=순자산 전체인데 화면 373행은 NAV 를 '순자산'으로, 스트레스는 NAV 를 'D2', 반도체 밴드는 NAV+예적금을 '(b)'(D코드 없음, 주석은 'D2 (b)')로 부름. `check_rules_terms.py` 는 상수값만 봐서 통과 | `tab_my.html:275-276,307,340,373`, `screener/defs.py:11-18,28` | 규칙·용어 + 화면(MY) |
| 중-3 | 중 | 대결 기록 문구 '반도체 비중 순자산 약 81%로 **상한(60%)** 초과' — 현행 SEMI_CAP 40%·발동선 45%와 다른 옛 한도, 분모도 '순자산' | `reports/decisions.json` (DAILY·시그널 뷰 표시) | 대결·PB |
| 중-4 | 중 | 🔥공격 PB 모의 베팅 'KODEX 레버리지 300만원 … 5일 뒤 종가 청산', 나스닥 '3배 레버리지' 베팅이 결재 #14(레버리지 보유 1일 상한) ⏱ 라벨 없이 표시. decisions.json 에 해당 픽이 없어 `duel.lev_cap()` 미적용. '100만 단위 표준화' 문구와 300만원도 불일치 | `reports/daily_brief.json`(asof 10-17 14:06), `screener/duel.py:202-213` | 데일리·대결 |
| 중-5 | 중(의심) | 티커 NIKKEI −4.90% vs TOPIX +1.76% 같은 스냅샷 — 6.7%p 괴리는 비정상 가능성(전일 종가 기준 오류 의심), 교차검증 없음 | `reports/live.json` NIKKEI chg −0.0490, TOPIX +0.0176 (yahoo) | 시장데이터(라이브) |
| 경-1 | 경 | `ui_smoke.py` 가 29뷰 중 7뷰, pageerror 만 검사(콘솔 에러·HTTP 404·LOAD FAILED 미검사) | `scripts/ui_smoke.py:17,40-50` | 감사(화면)·인프라 |
| 경-2 | 경 | 토요일 티커가 'LIVE 10-17 09:47 KST' 로 금요일 종가 표시 — JSON status CLOSE 인데 라벨은 LIVE, 거래일 미표기 | live.json updated_at·status | 시장데이터(라이브) |
| 경-3 | 경 | 파생 보드 헤더가 거래일(10-16) 대신 생성 시각(10-17 01:43, KST 미표기) | `reports/derivs.json` date vs asof | 파생 |
| 경-4 | 경 | 채권 탭 날짜 혼재: AI 신용 감시 asof 10-15(VIX 16.0, HYG 1개월 −1.2%) 바로 아래 ETF 표 HYG 20일 −1.6%, 상단 티커 VIX 19.99(10-16) | bonds.json ai_credit.asof vs generated_at 10-16 21:54 | 채권 |
| 경-5 | 경 | 밸류에이션 '미 10Y 5.10% (5일 −12bp)': 수준은 라이브(us10y_live), 5일 변화는 us10y_date 10-15 기준 — 기준일 미표기 | `reports/valuation.json` rates | 밸류에이션 |
| 경-6 | 경 | 레짐 용어 체계 3종: 리서치 '상승/조정/하락', MY 결재 #3 '상승장/회복확인/하락장', TERMS '테마 밴드' ↔ 화면 '반도체 밴드' | `tab_research.html:54-57`, `tab_my.html:229-234`, `defs.py:65-72` | 규칙·용어 |
| 경-7 | 경 | '서프라이즈' 가 컨센서스 수치 없이 표시(증권사 제목 인용·PB 요약) | research.json, daily_brief.json | 리서치·데일리 |
| 경-8 | 경 | 죽은 getter `getDetail`(파일·호출처 없음) | `scripts/build_pages.py:54` | 화면(셸) |
| 경-9 | 경 | 신선도 배지가 자기 점검 시각이 오래돼도 경고 없음. 감사 중 디스크 freshness.json checked_at 이 16:23→13:51 로 역행(동시 작업 재작성 추정) | `reports/freshness.json` mtime 07:27 UTC | 운영(신선도) |
| 경-10 | 경 | 티커 KR BREADTH A/D 652/92(747종목 유니버스) vs CLOSE KR KOSPI 759/135 — 티커에 유니버스 미표기. 또 `COOLDOWN_MIN=30` 이 tab_duel.html 에 중복 정의되나 check_rules_terms 는 tab_my 만 검사 | `tab_duel.html:12`, `scripts/check_rules_terms.py` | 화면·규칙 |

## 6. 재검 조건
- 다음 운용회의 산출 후 `committee.json` 에 'C·참고' 기대값 블록이 생기면 #7 재검.
- 토큰 있는 브라우저에서 MY 반도체 밴드 % 와 분모 라벨 실화면 확인(헤드리스 불가).

## 주장 (린트 양식 — PB 10/17 덧붙임, 본문 판정은 위 감사 원문 그대로)
- 10/17 기준 이 영역에 치명 결함은 없고, 위 '중' 항목이 월요일 운영 전 고칠 대상이다.

## 근거
- 위 본문 각 절(검사 스크립트 결과·교차 대조·파일:줄)과 같은 날 수정 커밋(997023ad·dda9f5fb·5999223d 등).

## 반증 가능 조건
- **R1** 10/20(월) 08:20 신선도 점검에서 이 문서가 정상이라 한 항목이 늦음으로 뜬다.
- **R2** 10/20 장중 화면 숫자가 원천 JSON과 다르게 표시된 사례가 1건 이상 나온다.
- **R3** 같은 날 수정한 항목이 다음 정합성 재점검에서 다시 '중' 이상으로 나온다.

## 채점 3항목
| 항목 | 기준 | 채점 |
|---|---|---|
| S1 | 10/20 신선도 늦음 0건 | 10/20 |
| S2 | 10/20 화면↔JSON 불일치 0건 | 10/20 |
| S3 | 재점검에서 재발 0건 | 재점검 |
