<!-- short: 범용판 스냅샷 경계 검사, review 0 -->
<!-- oneliner: migrate_v1 review 7→0(허용 6건 목록) · 개인 북·원장 분석 6파일 제외 추가 · 코드 주석 1곳 수정필요(개발, 11/5) -->
# 감사 — 리팩토링 v1 범용판 스냅샷 경계 검사 (2026-11-01, 보드 mig-v1-audit)

> 도구: `python3 scripts/migrate_v1.py --private-dir <pb-private>`(dry-run, 쓰기 없음) + 스냅샷 대상 파일 전수 grep(스크래치, 커밋 안 함). 돌린 패턴: 비공개 저장소 경로(`pb-private`·`holdings.txt`·`ledger/`·`household/`), 시크릿 꼴(ghp_·github_pat_·AKIA·텔레그램 봇 토큰·PRIVATE KEY·AIza·sk-·xox·키=값), 연봉·월급·급여·성과급, 계좌번호·예금주·숫자-숫자-숫자 계좌꼴, 의료어(병원·진단서·질병·처방·수술·복용·입원·의료비), 이메일, 오너 문맥+원화, '내/나의/겸이 보유·평단', 비공개 보유 종목코드·종목명 ±50자 개인 문맥. 값은 메모리에서만, 이 문서엔 건수·경로만.
> 기준: 원본 7974beeec(검사) → 재실행 origin/main 762700a86. 판정 원칙 = audit KB §2 (e)·§3-1, 10/24 오너 예외(순자산 '목표' 금액·애널리스트 실명) 그대로.

- **What**: dry-run review 7건 → 전부 원문 확인 결과 오탐(뉴스·시세·연구 가정) → 허용 목록 6항목(같은 줄 2건 묶음). 자동 표에 안 잡힌 **개인 북·원장 분석 문서 6개**(금액 없음, 개인 보유 종목명·개인 매매 통계·체결 이력 구조)를 grep 으로 찾아 스냅샷 제외 규칙에 추가. 시크릿 0건, 계좌번호·의료·연봉(개인) 0건.
- **So What**: 재실행 종료코드 0 — A 0건 · B review 0건(아래). 11/6 스냅샷 조건 중 '감사 확인 끝' 충족. 단 코드 주석 1곳(아래 표 ★)은 제외할 수 없는 파일이라 개발 수정 필요(비차단 아님 — 11/5까지).
- **Now What**: 11/6 재실행 때 새 review 가 뜨면(봇이 매일 바꾸는 views·research 파일) 허용 목록은 문장 단위(`preview`)라 자동 통과 안 됨 → 감사 재판정. 스캐너 사각 2곳은 요청으로.

## 판정표
| 경로 | 판정 | 근거 |
|---|---|---|
| `reports/research_views.json:1` (amount/계좌) | 허용 | 증권사 해킹 보도 요약의 유출 고객 수 — 오너 계좌 아님 |
| `reports/views/analyst_cmdty.json:286` (amount/내) | 허용 | 금 달러 시세 메모, '상반기 내' 오탐 |
| `reports/views/realestate.json:89` ×2 (amount/내) | 허용 | 정비사업 이주 가구 수 보도, '2~3년 내' 오탐 |
| `screener/sectors.py:12` (amount/보유) | 허용 | 섹터 전환 종목 수 + 보유 기준 비중(비율만) |
| `scripts/replicate_qld_dca.py:109` · `scripts/study_laor_ib.py:334` | 허용 | 연구 가정 금액 docstring, 비공개 지문 불일치 |
| `reports/studies/2026-10-23_frm_replay_2026-07.md` | 제외 | 개인 북 재생 손실·개인 위성 종목명 표(§3) |
| `reports/studies/2026-10-28_frm_core_lookthrough.md` | 제외 | 보유 상품 코드·개인 위성 종목 대조(:7-8) |
| `docs/peer_reviews/2026-10-17_integrity_audit.md` | 제외 | 비공개 원장·체결·ISA 매수 구조를 줄 번호까지 서술 |
| `docs/peer_reviews/2026-10-17_legacy_book.md` | 제외 | 개인 규칙 결재·손실 귀속 서술 |
| `docs/peer_reviews/2026-10-17_recheck.md` | 제외 | 개인 반도체 비중·종목별 예외·사전등록 종목 수(:15-16) |
| `docs/valuation_notes/2026-10-17_cio_lab_review.md` | 제외 | 오너 매매 사례 승/패 통계(§3) |
| ★ `screener/pb.py:198` 주석 | 수정필요 | 개인 보유 상품 코드를 '보유'로 명시 — 코드라 제외 불가, 문구만 바꿀 것 |
| `reports/views.json` evidence_src(:900·:984 등) | 허용·문구정리 | 본인 원장 근거 표기, 값은 비율만 — 11/12 문구 정리(인벤토리 §6) |
| `docs/valuation_notes/2026-10-17_lab_p1_prereg.md:5` · `reports/studies/lab_p1.md:48` · `trial_log.json:96` | 허용 | 가설 출처를 '개인 원장 사례'라고만 표기, 통계·종목 없음 |
| `apps-script/tab_my.html`·`apps-script/tab_life.html`·`apps-script/Code.gs` 등 `pb-private` 참조 206줄 | 허용 | 저장소·파일 이름(토큰으로 브라우저에서 읽는 코드), 값 없음. 범용판 화면에선 숨김 |
| `apps-script/tab_life.html:32` '목표' 금액 | 허용 | 10/24 오너 예외(순자산 목표) |
| `reports/public_reports.json:1` 공무원 연락처 | 허용(경) | 정부 보도자료 원문의 담당 부서 전화 — 오너 개인정보 아님 |
| `data/`·`reports/detail/`(스캐너 제외)·200k자 초과 줄 5파일 | 허용 | 비공개 지문 일치 전부 공시·목표가 안의 10만 단위 반올림 숫자 우연 일치, 개인 문맥 0 |

## 재실행 결과 (dry-run, origin/main 762700a86, 허용 목록 = `docs/refactor_v1_migrate_allow.json` 기본 로드)
- 추적 4,665 범용 · 631 내부 · 184 개인 제외(+6 감사 11/1) · 5 보관 / A 0건 / **B review 0건 → 통과** / C 636줄(비차단) / D 147파일 / 종료코드 0.

- 복기: 10/27 감사는 자동 표(금액) 0건이면 통과로 봤다 → 이번 6파일은 금액이 없어 자동 표에 영영 안 뜬다 → 다음부터 경계 검사엔 비공개 보유 종목명 ±문맥 grep 을 항상 같이 돌리고 돌린 패턴을 같은 줄에 적는다.
- VOC: privacy_history_audit 이 200k자 넘는 줄과 시장 경로를 통째로 건너뛴다 — 이번엔 손으로 봤지만 11/6 재실행 땐 사각. 종목명 지문이 코드 기준이라 한글 종목명은 못 잡는다.
요청→개발: 범용판 경계(mig-v1-audit): screener/pb.py:198 주석에서 개인 보유 상품 코드를 '보유'로 적은 표기를 일반 표현으로 바꿔 줘(11/6 스냅샷 전) — 장부 req-dev-b420ff8d, 마감 11/5
