# 프론트 첫 라운드 (2026-10-24, front-first-round · req-front-889551e0)

드릴: front-d1 배경 #151515 직접 쓰기 금지 → 색 토큰 var(--bg3)(겹 배경, 엑셀 #f7f7f7; 패널이면 var(--panel)) — 하드코딩 다크 hex 는 엑셀 스킨에서 검정 바탕 검정 글자. 버튼 36px 고정 금지 → 기존 .sbtn 류 클래스로: 손가락 @media (any-pointer:coarse) 44px(WCAG 2.5.5 AAA 목표)·마우스만 28px(2.5.8 AA 24px+4)·엑셀 html.xl 제외, 24px 미만 결함. 글자는 --fs-1~4 토큰(px 금지). 검사: tests/test_skin_tokens.py·tests/test_font_tokens.py → build_pages.py 재빌드 → skin_audit.py 기본(--skin def)·엑셀 두 스킨 × 390·1300 두 폭 대비 4.5:1 미달 0 → ui_smoke.py(check_xl·콘솔 에러 0) → 폰 390px 에서 직접 열어 getBoundingClientRect 넘침·터치 크기 확인. 잠금 lock.py take/drop.
(드릴 답은 위 줄을 먼저 쓴 뒤 키를 열지 않고 제출 — 채점 round_collect·평가)

- 고침1(실습 1·push): HOME 달력 `.calc` #1e1e1e·#0a0a0a·#1a1408 → var(--line/--panel/--bg3) — 안전망 뺀 엑셀 home 대비 미달 225→0·어두운 배경 62→0, 실제 상태 두 스킨 대비 0 유지(6c85fb7c). 온보딩 숫자 전부 `front_onboarding.md`.
- 고침2(히트맵·push): tab_market 그룹 상자 fill="#111"·stroke #000·제목 #ddd·등락% hex → style 토큰(--bg2·--bg·--txt·--up/--dn/--blue). skin_audit 자 밖이라 getComputedStyle 직접 측정(heat KR·US × 390·1300): 엑셀 상자 rgb(17,17,17)→rgb(243,243,243), 제목 대비 13.9→18.93, 등락% 최저 대비 기본 5.72·엑셀 5.84(c0a6b5b6).
- 고침3(프로필 그라디언트): 안 고침 — 사진 위 흰 글자 뷰어라 의도된 다크일 수 있어 UXUI 판단 대기(req-uxui-2ca21d0b, 10/28).
- 검사(push 전, 10/24): ui_smoke 65줄 OK·BAD 0, skin_audit 전 화면 엑셀·기본 대비 미달 0, pytest·board·check_functions·check_rules_terms 통과.
- 배움: WCAG 2.2 1.4.11 비텍스트 대비 3:1 `[규정]` — 히트맵 상자는 '그림 구역'이라 글자 4.5:1 과 따로 상자↔패널을 봐야 함. 엑셀 상자↔흰 패널 1.11:1 은 경계선 역할이 아니라(틈 stroke 가 구분) 통과로 판단 `검증전 — UXUI 확인 필요, 10/28`.
- 피어→교육: 실습 1 기준 '잠금 커밋 2개'는 파일 2개를 한 커밋에 잠그면 1+1 이 됨 — '잠금·해제 커밋 있음'으로 / 실습 2 '바른 배지'도 엑셀 skin_audit '어두운 배경' 2 가 뜸(배지 자체 검정 바탕) — 기대값에 적어 두면 응시자가 헷갈리지 않음.
- 피어→UXUI: 히트맵 등락% 색을 타일 관례(KR 오름 빨강)로 두면 엑셀 '음수만 빨강'과 KR 에서 어긋남 — 어느 쪽인지 검수 부탁.
- 복기: 잠금 해제·재잠금을 한 커밋에 묶다 dev 의 live.yml 잠금과 rebase 충돌 → JSON 을 손으로 합쳐 해결. 다음부터 잠금 커밋은 pull 직후 바로, 한 동작씩.
- 처리→교육: 온보딩 이수 제출(실습 1 push·2·3 연습 worktree 되돌림, 퀴즈 8줄) — 채점은 평가.
- 처리→운영: 재배정 우선순위 = ① req-dev-cb19b1e0(MY 손절선 두 칸, P1·10/30) ② tradeplan-ui(=req-dev-516bf7e6, P1·10/31, UXUI 배치 협의 먼저) ③ edu-dev-handoff(P2, req-edu-23239703 회신 10/28 뒤 — Code.gs 부분은 개발). 단 겸이 한도 절약(PB 10/24)으로 화 11시 이후 착수.
- 보류(PB 10/24 절약 지시): 사내톡 📋 RnR = 구현 끝·미배포(브랜치 front-org-rnr-wip, 보드 org-rnr), 팝업 오늘 봉 = 보드 popup-intraday-bar(개발 계약 대기).
VOC: 화면 일이 '자 밖'(SVG·그라디언트)이면 측정 스크립트를 매번 새로 짜야 함 — 그룹 상자 fill 측정을 ui_smoke 에 넣을지 다음 라운드에 판단.
요청→UXUI: 프로필 뷰어 기본 그라디언트 다크 유지 여부(req-uxui-2ca21d0b) + 히트맵 등락% 색 관례 검수.
현재 상태: ① 달력·히트맵 토큰화 main 반영, 잠금 0 ② 프로필 그라디언트만 UXUI 답 대기 ③ RnR WIP 브랜치·팝업 봉은 화 11시 이후.
