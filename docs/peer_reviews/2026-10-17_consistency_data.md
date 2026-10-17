# 정합성 감사 — 데이터·파이프라인 (검증 데스크, 2026-10-17 16:23 KST 기준)

범위: 10/17 커밋 ~130건 이후의 현재 HEAD(78809209). 기대 거래일(screener/tradecal.py): 지금은 토요일 16:23 KST이므로 KR = 10/16, US = 10/16.
방법: 파일을 직접 읽고 다시 계산했다. 코드는 고치지 않았다(보고만 함). 검사 도중 생성된 파일(reports/freshness.json, reports/audit/2026-10-17.*)은 원래대로 되돌렸다.

## 0. 요약 — 치명 0 · 중 4 · 경 8
| # | 등급 | 항목 | 담당 데스크 |
|---|---|---|---|
| M1 | 중 | chains.json·us_eps.json 이 10/15 04:13 에 멈춤(2거래일 뒤짐). CI에서 캐시가 만료되지 않음 | 개발(+데이터) |
| M2 | 중 | accum.json·us_accum.json 이 계약에 등록돼 있는데 guard.write_json 을 거치지 않음 → 계약·역행 검사를 받지 않음 | 퀀트(accum 잠금)·개발 |
| M3 | 중 | 같은 종목의 PER·PBR 이 valuation.json 과 detail 에서 다름(정의 표기 없음) | 밸류·데이터 |
| M4 | 중 | valuation.json 의 asof = 실행일(토 10/17) → 신선도 계약이 오래된 가격을 잡지 못함 | 개발 |
| L1–L8 | 경 | 아래 §5 | — |

## 1. 신선도
- 계약 검사 `screener.freshness.check()`(16:23 KST): 21/21 정상. late·regress·stale 0건. 항목별 값: detail/momentum/peers KR·US 10/16, derivs 10/16, committee(_us) 10/16, macro_series 10/16(asof_kr 가 없어 KOSPI 끝 행으로 대체), valuation 10/17, live 10-17 09:47.
- 계약 밖 산출물 중 오래된 것:
  - chains.json·chains_view.json `asof 2026-10-15 04:13`, us_eps.json `2026-10-15 04:14`. 마지막 커밋은 0e27fedb(10/15 04:15 UTC) → **M1**.
  - health.json `2026-10-15 19:01`(§4 L5 — 예약 실행이 아직 한 번도 돌지 않음).
- status=fail 인 파일 0건(accum·us_accum status=ok). asof 가 아예 없는 dict 파일: bonds_hist, committee_hist, dashboard_state(조각별 asof 있음), decisions, derivs_hist, ideas_log, macro_hist, macro_releases, study_progress, views_hist. 모두 이력·상태 파일이라 asof 가 없어도 된다.
- 비거래일 날짜가 찍힌 파일: valuation.asof 10/17(**M4**), portfolios.data_to 10/17(L2), macro_series.asof 10/17(L3), study_daily.date 10/20(L4).

## 2. 교차 정합(같은 수치가 여러 곳에 있을 때 모두 일치해야 함)
- KOSPI 10/16 종가 5,668.05: live.json(src naver, CLOSE) = macro_series 끝 행 = dashboard·dashboard_state close_snapshot = committee 본문("코스피 5,668.05 (+2.0%)"). 등락률 5668.05/5554.22−1 = +2.05%, live.chg 0.0205 와 같음. **일치.**
- KOSDAQ 794.78, SPX 7,659.44, USDKRW 1,334.20 도 live 와 macro_series 값이 같음. **일치.**
- detail: KR 1,485/1,485 개 파일이 asof 10/16이고 close = chart 끝 봉. US 580개는 10/16, 7개는 10/15(L1). _index 는 KR 10/16 · US 10/16.
- valuation.json 16행 중 가격이 있는 15행: price·price_date 가 detail 의 close·asof 와 같음(TSM 은 detail 없음, 해외 ADR). PER·PBR 은 다름 → **M3**:
  - 005930: valuation PER 9.57 · PBR 2.54 / detail.valuation per 8.4 · pbr 2.23
  - 000660: valuation PER 5.60 / detail per 9.3 (detail per_reported 5.7)
- derivs.json: date 10/16, asof 10/17 01:43(실행 시각), spot 878.16. 계약 key=date 기준으로 정상.
- accum.json ↔ data/flows/kr_inv_2026.parquet(마지막 일자 10/16, 단위 백만원): 재계산 결과
  - KOSPI(K) f5 −112,394.54억 vs accum −112,395 · tv_last 209,454.42 vs 209,454
  - KOSDAQ(Q) f5 400.03 vs 400.0
  - 종목 446070 i5 2.57 vs 2.6
  - **일치.**
- portfolios.json 새 형식(strategies[].stats/now/curve, corr, data_to, cost, base)을 쓰는 화면: apps-script/tab_quant.html:101–145, tab_my.html:353·403. 이 화면들이 읽는 필드(cagr·vol·sharpe·mdd·worst_month·curve·corr·data_to)가 파일에 모두 있음. stats.momentum* 필드는 momentum_bt.json 에서 읽는데, 그 파일에도 있음. **정상.**

## 3. 계약·가드
- contracts.check: 계약 대상 17개 파일 모두 통과.
- 그러나 schema_version 이 찍힌 파일은 daily_brief.json 하나뿐이다. 나머지는 contracts 커밋(54278e74, 10/17 04:55 UTC) 이후 아직 다시 쓰이지 않았다. 다음 정규 실행 때 찍히는지 확인이 필요하다.
- accum.json 은 계약 등록(81860fd5, 05:17 UTC) 이후인 15:00 KST 에 생성됐는데도 schema_version 이 없다. 원인: accum.py:500 `OUT.write_text`, us_accum.py:222 `OUT.write_text` 가 가드를 우회함 → **M2**. 보드 guard-rest 목록(ops/board.json:1528)에도 이 두 파일이 빠져 있다.
- guard-rest 미적용으로 남은 것(보드 notes): dashboard·research·disclosures·calendar·views·dotplot, daily md·csv, japan.py:211 의 macro_series 직접 병합(docs/desk_kb/dev.md:47).
- slot_guard: `--wf live.yml` → 단독 실행 주체. tests/test_schedule_single.py 통과. 요청에 있던 `--check` 옵션은 존재하지 않는다(사용 가능: --wf/--table/--key).
- event_watch: reports/event_state.json 이 아직 없다. 기능이 10/17 06:13 UTC 에 배포된 뒤 장중 live 루프가 한 번도 돌지 않았기 때문이며 정상이다. 첫 실운영은 월 08:40. live.yml:73·89·94 의 /tmp/ev → reports 복사·커밋 경로는 확인했다. tests/test_event_watch.py 통과.

## 4. 검사 스크립트·워크플로
- pytest: 전체 통과, XFAIL 1건(test_committee_adjusted — 보드 audit-ideas-basis 에 이미 등록됨). 대상 5개 파일(schedule_single·event_watch·guard_rest·contracts·freshness_guard) 95건 통과.
- check_functions 통과 · board --check OK(113) · check_rules_terms OK · slop_audit 치명 0 / 중 6 / 경 52(중: data 라운드 VOC 줄 누락, study_consults 등급 없는 인용 4, 76c2df3f 테스트 없는 defs 변경).
- 워크플로 최근 실행(gh run list, 07:30 UTC 기준): 마지막 실행이 실패로 끝난 워크플로 0개.
  - 실패·취소는 모두 뒤 실행으로 대체됐다: accum 04:55Z 실패 → 04:59Z·05:09Z 성공. live 17:30Z cancelled(concurrency). team·tests cancelled(같은 push 중복). pages-build-deployment 다수 cancelled(새 빌드가 앞 빌드를 대체).
  - pages.yml 은 push 28건이 전부 skipped. 의도된 동작이다(pages.yml:24·51 `vars.PAGES_ACTIONS=='1'` 조건).
  - 예약 실행 0건인 워크플로: health · lab · scorecard · study_daily · us_accum. 모두 신규이거나 cron 이 오늘 추가돼 첫 예정 시각이 아직 오지 않았다 → L5.

## 5. 경(L) 상세
- L1 US detail 10/15 잔존 7개: BKLN·JNK(_index 에 있음)와 _index 에 없는 고아 파일 5개(APLD·CIFR·CORZ·IREN·WULF). 파일 587개 vs _index 582개. 담당: 데이터.
- L2 portfolios.data_to = 2026-10-17(토). 코드 주석은 "실제 마지막 거래일"이라고 함(portfolios.py:243). 24시간 시리즈(환율)가 끝 날짜를 끌어올린 것으로 추정 [가정]. 담당: 퀀트.
- L3 macro_series: asof 가 10/17(BTC·USDKRW 기준)이고 asof_kr·schema_version 이 없다(00:48 UTC 에 쓰여 감사 M3 수정 전 파일). freshness 는 key_fallback 으로 정상 판정한다. 월 15:45 close_kr 실행 때 해소돼야 함. 담당: 개발.
- L4 study_daily.json date = 2026-10-20(화). 다음 평일은 10/19(월)인데 날짜가 하루 건너뛴 이유가 불명. [확인 필요: 공부 데스크, 10/19 07:10 실행 뒤]
- L5 첫 예약 실행이 아직 없는 워크플로: health 신선도 cron(42c4a0d6 10/17 04:51 UTC 추가, 첫 실행 오늘 20:10 KST) · scorecard 일 08:30 · lab 일 23:00 · study_daily 월 07:10 · us_accum 월 07:37 · event_watch 월 08:40. health.json 은 10/15 이후 갱신되지 않음. 담당: 운영(첫 실행 확인, 10/19 까지).
- L6 ops.yml 예약은 하루 1회만 실제로 돌았고, 실행 시각이 cron(14:47 UTC)보다 약 3.5–4h 늦음(10/15 18:41Z, 10/16 18:25Z). 00:07 cron 은 오늘 추가됨. 담당: 운영.
- L7 부작용: `freshness.check()` 와 `slop_audit.py` 를 실행하면 추적 중인 파일(reports/freshness.json, reports/audit/*)이 고쳐진다. 감사용으로 읽기 전용 실행 옵션이 없다. 담당: 개발.
- L8 slot_guard 에 `--check`(위반 시 exit≠0) 옵션이 없어, CI 밖에서는 이중 실행 여부를 수동으로만 점검할 수 있다. 담당: 운영.

## 6. 중(M) 상세·조치 제안
- M1 원인: drivers.py:205–207·730–736 의 캐시는 `CACHE.stat().st_mtime` 기준 20h TTL 이다. CI checkout 은 mtime 을 지금 시각으로 찍으므로 캐시가 늘 '신선'으로 판정돼 다시 받지 않는다(추정, 근거: 10/15 이후 briefing·screener 성공 실행이 여러 번 있었는데도 파일이 커밋되지 않음).
  - 조치: TTL 판단을 파일 안의 asof 기준으로 바꾸고, chains.json 을 ops/freshness.json 에 kind=session(US) 으로 등록. 담당 개발, 10/20 까지.
  - 반대 근거: drivers 화면이 1년 가격만 쓴다면 2일 지연의 영향은 작다.
- M2 조치: accum.py:500·us_accum.py:222 를 `guard.write_json` 으로 교체하고 guard-rest 목록에 추가. 담당 퀀트(accum 잠금 보유)·개발, 10/24 까지.
- M3 조치: detail.valuation.per 의 정의(정상화 ROE 기반인지, 시점은 언제인지)를 화면과 파일에 표기하거나, valuation.json 과 같은 원천을 쓰도록 통일. 담당 밸류, 10/21 까지.
  - 뒤집힐 조건: 두 PER 이 의도적으로 다른 지표(정상화 vs TTM)라는 문서가 있으면 경으로 낮춘다.
- M4 조치: valuation.json 에 `price_asof = min(rows.price_date)` 를 추가하고 freshness key 를 이 값으로 변경. 담당 개발, 10/21 까지.

VOC: GitHub MCP actions_list 는 100건 페이지 제한이 있어 워크플로별 조회는 gh CLI 로 했다. 결과는 같은 저장소 기준이다.
요청→개발: M1(캐시 mtime)·M4(valuation price_asof)를 guard-rest 와 같이 처리해 주세요. 요청→퀀트: M2 accum 쓰기를 가드 경유로 바꿔 주세요.
현재 상태: 계약 신선도 21/21 정상 · 교차 수치(KOSPI·수급·가격) 일치 · 남은 위험은 계약 밖 캐시(chains)와 가드 우회 2곳, 그리고 신규 예약 워크플로의 첫 실행 확인(10/19).
