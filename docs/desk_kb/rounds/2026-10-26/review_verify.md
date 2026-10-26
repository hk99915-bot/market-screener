# 검수 결과 — 검증 데스크 (2026-10-26 장후, 보드 '검수' 9건)

> 기준 2026-10-26 20:00 KST 전후 · 출처 ops/board.json notes·커밋·직접 실행(pytest·스크립트·산출물) · 독립 검수(수정 없음)

- **What**: 9건 검수 — 통과 2 · 조건부 6 · 반려 1(kr-accum). 관련 pytest 106건 통과(공개 88·public_reports 18) + pb-private 34건 통과
- **What**: 직접 재현 — SEC 바스켓 49 중 ok 43·rules_status 치명 0·중 1·경 9·한은 bok_research 실조회 20행 ok
- **So What**: 코드·테스트는 9건 모두 정상, 결함은 '실데이터·운영 연결' 쪽 — 백필 미완·게이트 실발동 0회·생성기 미연결
- **So What**: 조건부 6건은 완료 처리하되 결함 요청 미해소 시 다음 검수에서 재오픈 대상(해석, 표본 = 1회 실행)
- **Now What**: kr-accum → '진행' 환원, 퀀트에 2022~2023 백필·스터디 재실행 요청(10/31)
- **Now What**: 조건부 6건 결함은 담당 데스크 요청 장부로 전달(아래 표 '결함') · 뒤집힐 조건 = 요청 마감 내 미회신 시 재오픈

## 건별 표

| id | 판정 | 확인한 것(직접 실행) | 결함 |
|---|---|---|---|
| ra-sec-coverage (애널) | ⚠ 조건부 | tests/test_sec_rotation.py 통과 · universe/semis_basket.json n 49 · data/fin/sec_progress.json 바스켓 ok 43·ifrs 3·no_data 3(TSM·ASML·ASX·UMC·STM·NVMI = 20-F, 데이터 요청 기재) · reports/earnings_cal.json asof 10-26 03:36 rows 49·컨센 결측 0 · valuation.json 바스켓 49/49 가격 채움 | 완료 기준 '컨센 없으면 전분기 대비 대용·표기' 경로 코드 없음(earnings_cal·valuation_daily·sec grep 0) — 현재 49/49 컨센 있어 미발현 |
| dotplot-neutral-rule (개발) | ⚠ 조건부 | tests/test_dotplot.py 통과(중립 불허 lint 포함) · reports/dotplot.json lint 0 · 중립 점 2개(PB 코스피·리스크 S&P) 모두 기본 확률·flip_up·flip_down 보유 · 텔레그램 줄 '기본 X% · 위 · 아래' 확인 · 6328dd3f 문구 교체 확인(코드 내 '라운드 판단 차이' 잔존 0) | ① 보드 문구는 '조건 없는 중립은 기록 거부'인데 구현은 기록 후 lint 경고 — 둘 중 하나로 정합 필요 ② PB 코스피 중립 '기본 11%' — 중립인데 기본 시나리오 확률이 11%면 '기본'으로 읽히지 않음(정의 점검) |
| quiz-key-balance (교육) | ✅ 통과 | scripts/study_content_check.py → 73 모듈 경고 0 · 정답 위치 0/1/2/3 = 31/31/32/31(n 125) · why 태그만 0건(최단 why도 계산 근거 포함) · 검증기 '같은 위치 >3'·WHY_MIN_CHARS 15 규칙 존재 · tests/test_study_content.py 통과 | 없음(duel.pick = answer 125/125 는 보드상 별도 논의) |
| kr-accum (퀀트) | ❌ 반려 | tests/test_accum.py 통과 · data/data_store_manifest.json flows = 2024(첫 행 11-26)·2025·2026(~10-23)만 · reports/studies/accum_signals.json asof 10-17·data 2024-11-26~2026-10-16(458일) · accum.json 최신 10-23 | 보드 '남은 것' 미충족: 2022 하락장(2022·2023) 백필 없음 → 스터디 재실행 없음. 부수: accum.log log1p divide-by-zero 경고 |
| integrity-p0-2 (개발) | ✅ 통과 | tests/test_rules_status.py 통과 · rules_status.py --check(pb 읽기) 치명 0·중 1·경 9, rc 0 · pb integrity_check (g) G-rules 동일 findings 출력(읽기 전용 실행) · pb rules.txt 맨 위 생성 블록 존재 | 개발 결함 없음. 중 1(결재 #4 → 조항 [13] 미반영)·경 9(조항 토큰)는 원장 쪽 — 기록 데스크 기존 요청으로 처리 |
| integrity-p0-5 (개발) | ⚠ 조건부 | pb scripts/handoff_build.py 미리보기·--check 실행(파일 미기록) · scripts/tests/test_handoff_build.py 포함 34건 통과 · HANDOFF gen 구간 7개 | 훅·예약 미연결 → 18:02 생성 후 19:49 이미 --check rc 1(낡음, 🗳️ 24→25줄) · 보드 files 칸 공란(pb:scripts/handoff_build.py 미기재) |
| tue-risk-events (포지션리스크) | ⚠ 조건부 | rounds/2026-10-26 event_*.md 8개(755줄) 열람 — 실적·이스라엘 총선·미 중간선거·포지션 노출 신호등·HF 알파 모두 포함 · 공개본 비율만(개인 금액·실보유 종목명 없음) · What/So What/Now What 칸 존재 | 실계좌 스트레스 '−15.17%(10/22)·레거시 매도 반영 재계산 미실시' = 핵심 칸이 미갱신 · 보드 files 칸 공란 |
| bok-issue-note (데이터) | ⚠ 조건부 | tests/test_public_reports.py 18건 통과 · fetch_source(bok_research) 실조회 status ok·20행(최신 10-26 이슈노트 제2026-27호) · 실행 불가 — 완료 기준인 '다음 03:30 Actions 수집'이 아직 미도래(cd74f592 = 10/26 18:45 KST, public_reports.json 에 bok_research 없음) | 10/27 03:30 Actions 후 public_reports.json bok_research ok 확인 필요 |
| us-eod-toss (개발) | ⚠ 조건부 | tests/test_us_eod_toss.py·test_toss_eod_gate.py 통과 · 게이트 호출부(screener/main.py us_toss_fill)·briefing.yml reports 커밋 경로 확인 · reports/toss_eod_check.json **없음**(10/22 이후 실발동 0회) | 실행 불가 — 게이트는 야후 STALE 때만 돌아 실데이터 대조 결과 0회. 섀도 대조(STALE 아니어도 매일 prev 봉 대조 기록)로 일치율 증거 축적 필요 |

## 원본
- ops/board.json · docs/desk_kb/rounds/_requests.json(이번 검수 요청) · 커밋 3123505a·6328dd3f·f8857741·cd74f592·13677317·b8bdba65
