# audit(감사) 라운드 1 — 2026-10-17 (신설)

1. **읽기** — round_brief · LOOP.md(7항 감사·VOC·worktree 격리) · README · STANDARD.md(1~6절) · 데스크 KB 15개 전체 · 라운드 파일 12개 · reports/valuation.md · docs/valuation_notes/2026-10-17_memory.md · docs/peer_reviews/ · PB 흔적(behavior.md:71, decisions.json pb_view 3건, alerts.py touch_lines, 보드 sec-ytd-bug).
2. **배우기** — IIA 3선 모델: 2선(통제)은 채점·감시, 1선이 고친다 — 감사가 직접 고치면 독립성이 깨진다 `[규정, 2차 자료, 원문 절 확인 필요: 2026-10-24까지]`. 우리 규약과의 차이: (e) 금액 누출만 직접 치환(시간이 피해를 키우는 유일 항목). KB `audit.md` §5.
3. **고치기** — `docs/desk_kb/audit.md` 기준서((a)~(i) + STANDARD 1~6절 매핑, 심각도·탐지·기한) · `scripts/slop_audit.py`(자동 (e)(f)(b)(c)(g)+§4·§6, md+json, 치명→종료코드 1) · `tests/test_slop_audit.py` 8건 · CI `tests.yml` `slop-audit` 잡(continue-on-error, 주석만) · 첫 감사 `reports/audit/2026-10-17.md`(치명 1·중 14·경 42). 치명(순자산 목표 금액, 공개) 3곳 즉시 치환 + 잔여 1곳(tab_life.html, 잠금) 보드 P0 `audit-life-target-amount`. 롤백: 이 커밋 revert(산출물 외 코드 변경은 scorecard_week.py 문자열 1줄뿐). 영향: CI 잡 1개 추가(기존 pytest 잡 불변), 스캔 대상 docs/** push 시 tests.yml 트리거.
4. **피어(PB)** — 반대 의견: 보드 `sec-ytd-bug` 는 P0 '결함 의심' 제목으로 검수 상태인데 notes 에 최종 판정이 없고, data.md 복기("MU 실제 누적 누수")와 analyst.md:26("8-K 원문과 전부 일치")이 상반된다. P0 는 판정 근거 1줄 없이 닫히면 안 된다 — 감사표 중 5번.
5. **복기** — 첫 자동 실행에서 (f) 368건(오탐 95%)을 보고 기준서를 먼저 썼다면 기준서가 slop 이 될 뻔함 → 왜: "파일처럼 보이면 참조" 라고 넓게 잡음 → 다음부터: 자동 규칙은 전수 실행→오탐률→허용 목록 순으로 정한 뒤 기준서에 올린다(수정 후 29건). KB 복기.

VOC: 공유 체크아웃에 다른 데스크의 미커밋 변경이 섞여 있어 worktree 로 옮겨 작업했다(LOOP 개정과 일치). (f) 이슈 번호 32건은 pb-private 라 자동 확인 불가 — `결재 #n` 옆에 제목 3단어를 붙여 주면 대조 가능. decisions.json 원장 레코드의 금액 문장은 감사가 손대지 않았다(원장 불변) — 생성 코드 쪽 수정 여부는 PB·개발 결정 필요.

현재 상태 3줄:
- 감사 산출물: reports/audit/2026-10-17.{md,json} (수동 13 + 자동 80, by_desk 포함 → ops round_collect 가 읽음). 다음 라운드: `python3 scripts/slop_audit.py` 실행 후 수동 항목(a·h·i·j·k) 채점.
- 열린 치명: 보드 P0 `audit-life-target-amount`(개발, tab_life.html:28). 공개 git 이력 정리 여부는 오너 결정 대기.
- 중 14건 기한 10/20 — 각 데스크 라운드 파일 `처리→audit:` 1줄로 닫는다. 미처리 2라운드면 P1.

요청→pb: ① 보드 `sec-ytd-bug` notes 에 최종 판정 1줄(어느 종목이 YTD 누적이었는지, fin_verified.json 근거) ② behavior.md:71 PB 복기를 pb.md 로 이전 ③ decisions.json pb_view 문장의 '100만원/300만원'을 '1단위(모의 고정 사이즈)' 로 바꾸는 생성 코드 수정 여부 결정.
요청→개발: 보드 P0 `audit-life-target-amount`(tab_life.html:28 순자산 목표 금액 문구 제거) 오늘 처리.
