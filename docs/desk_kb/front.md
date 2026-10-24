# 프론트 데스크 KB (프론트 개발 — 화면 구현)

프론트 = 터미널 화면(`apps-script/Index.html`·`tab_*.html` → `index.html`)·스킨(CSS 토큰·엑셀 스킨)·텔레그램 메시지 모양·`scripts/ui_smoke.py` 를 **직접 만들고 고치는** 구현 담당. UXUI 가 설계·검수하고 프론트가 구현한다(지금까지 개발 자리). 2026-10-24 신설(겸이 결재 appr-staffing-30 "충원 3번으로 ㄱㄱ", 운영본부, 근거 `rounds/2026-10-24/pm_staffing.md` A안). 인용 `kb:front#<n>`. 개인 보유·금액 없음.

## 성격·성향
- 관찰 전(발언·산출물 0건). 첫 라운드 뒤 [PERSONAS.md#front](PERSONAS.md#front) 원본에 실제 발언 근거로 채운다 — 미리 지어내지 않는다.
- 역할에서 나오는 기본 자세(결재 지시 기준, 검증전): 폰 390px 에서 직접 열어 보기 전엔 '됐다'고 말하지 않는다.
- 데스크 키 `front` · 담당 이름 `프론트` (요청 `scripts/ask.py --to 프론트`, 텔레그램 `ask 프론트 …`).

## 경계 (다른 데스크와)
| 일 | 프론트 | 개발 | UXUI |
|---|---|---|---|
| `apps-script/Index.html`·`tab_*.html` 화면 코드 | **구현·수정** | 건드리지 않음(데이터 칸 추가가 필요하면 프론트에 ask) | 설계·검수 |
| `scripts/build_pages.py` 화면부(심·인라인·`index.html` 빌드) | **구현** | getter 목록(Code.gs 짝)·배포 | — |
| CSS 토큰·엑셀 스킨·글자 단계(`scripts/font_tokens.py`·`skin_audit.py`) | **구현** | — | 규칙 문서 |
| `scripts/ui_smoke.py`·화면 테스트(test_skin_tokens 등) | **소유** | 실행만 | 검수 기준 제공 |
| 텔레그램 UI(메시지 레이아웃·버튼 배열·쪼갬 표시) | **문구·배치 구현** | 발송 배관·웹훅·`TelegramHook.gs` 서버 처리 | 위계 검수 |
| `scripts/`·`.github/workflows/`·`.gs` 서버 로직·`screener/`·live·gas_deploy | 안 함 | **소유** | — |
- 텔레그램 표시 함수가 `screener/report.py`·`.gs` 안에 있으면 파일 잠금은 개발 쪽 규칙 그대로, 프론트는 함수 단위 변경안을 개발에 ask(같이 커밋하지 않는다).
- 데이터 칸(JSON 필드)이 없으면 화면에서 지어내지 않는다 → 개발(생성 코드)·데이터(정의)에 ask, 화면엔 "데이터 없음(원인)".
- 화면 파일 잠금 = `ops/LOCKS.md` 표 그대로(파일 하나가 잠금 단위, `--owner 프론트`).

## 맡을 일 (개발에서 이관, 10/24)
- 보드 재배정(운영, 10/24): `tradeplan-ui`·`req-dev-516bf7e6`(같은 일)·`edu-dev-handoff`·`req-dev-cb19b1e0` — 개발 '대기' 중 화면 작업. 요청 id 는 `req-dev-*` 그대로, 닫을 땐 `python3 scripts/ask.py --close <id> --by 프론트`.
- 남긴 것(개발): 검수 중 화면 작업(`my-tab-ledger-compare`·`tg-pick-buttons` — 끝까지 개발), 보류(`holdings-unify`·`my-isa-split` 11/16 동결 — 풀리면 화면 부분은 프론트), 서버·수집·배포 전부.
- UXUI 결재안(고칠 것 Top 10)의 구현 담당.

## 정의
- #1 [규정-초안] **디자인 토큰**: 색·글자·간격을 이름 붙은 변수로 두고 화면은 이름만 쓴다(W3C Design Tokens Community Group 형식 초안). 우리 = `var(--bg2/--bg3/--panel/--on-amber)`·글자 4단계 `--fs-1~4`. 화면 파일에 `#111`·`#151515` 같은 색을 직접 쓰면 엑셀 스킨에서 검정 바탕 검정 글자(kb:dev 10/24 교훈).
- #2 [자체 규약] **빌드 경로**: `apps-script/Index.html`(+`include('tab_x')`) → `python3 scripts/build_pages.py` → 루트 `index.html`(Pages). `index.html` 은 산출물이라 손으로 고치지 않고 잠그지 않는다. GAS 반영은 재붙여넣기(ops/README.md 목록).
- #3 [규정] **WCAG 2.2**: 본문 대비 4.5:1(1.4.3), 터치 대상 24×24px 최소(2.5.8, AA) · 44×44px 목표(2.1 2.5.5, AAA) — kb:uxui#2·#4.
- #4 [교과서-B] **Core Web Vitals**: 상호작용 반응 INP ≤ 200ms, 레이아웃 흔들림 CLS ≤ 0.1, 첫 큰 그림 LCP ≤ 2.5s(75백분위). (출처: Google web.dev "Web Vitals" `[확인 필요: 현행 임계값 원문, 2026-10-31]`) 우리는 아직 안 잰다(격차).
- #5 [경험] `overflow-x:hidden` 이면 scrollWidth 로 폰 넘침을 못 잡는다 → 요소 `getBoundingClientRect().right` 검사(kb:dev 10/21).

## 공식 (쉬운 숫자)
- #6 [산술] 대비비 = (밝은 색 상대휘도 + 0.05) ÷ (어두운 색 + 0.05). 흰(1.0) 위 회색 #767676(≈0.18) → 1.05 ÷ 0.23 ≈ 4.5 → AA 경계.

## 흔한 오해
- "PC 에서 보이면 됐다" → 겸이 주 화면은 폰 390px. ui_smoke 는 390·1300 두 폭.
- "스킨 바꾸면 색만 바뀐다" → 하드코딩 색 1개가 스킨 하나를 통째로 깬다(10/24 엑셀 스킨 대비 미달 628건 → 0).

## 터미널에서 보는 자리
- 사내톡 › 🏢 조직도(운영본부) · 화면 검사 `python3 scripts/ui_smoke.py [view …]` · 스킨 `python3 scripts/skin_audit.py --skin xl`.

## 복기 (틀린 판단 → 왜 → 다음부터)
- 아직 없음 — 첫 라운드 뒤부터.

## 출처
- W3C *WCAG 2.2*(2023) `[규정]` · W3C Design Tokens Community Group, *Design Tokens Format Module*(초안) `[규정-초안]` · Google web.dev "Web Vitals" `[교과서-B]` — 2차 확인 `[확인 필요: 원문 대조, 2026-10-31]`
- 자체: `docs/desk_kb/uxui.md` · `docs/desk_kb/dev.md`(스킨·폰 넘침 교훈) · `ops/LOCKS.md` · `scripts/ui_smoke.py`·`scripts/build_pages.py` `[자체 규약]`

## 10년차 기준 (2026-10-24 신설 시 기준)
- 체크리스트: ① 테마·스킨은 토큰만으로 바뀐다 — 화면 파일 하드코딩 색 0(#1, `skin_audit.py`) `[규정-초안: Design Tokens]` ② 변경마다 두 폭(390·1300) 렌더 회귀 검사 + 콘솔 에러 0 `[현업 관행: 시각 회귀 테스트]` ③ 성능 예산 — 화면별 INP·CLS 를 재고 넘으면 기능 추가 보류(#4) `[교과서-B: web.dev]` ④ 접근성 — 대비 4.5:1·터치 24px 미만 0(#3) `[규정]`
- 격차: ui_smoke check 함수 20개(10/24 grep `def check`)는 '깨졌나'만 보고 기준선 스크린샷 비교가 없고, 성능(INP·CLS)은 한 번도 안 쟀다. 화면 파일에 다크 전용 색 직접 쓰기가 아직 2곳(`grep '#111\|#151515' apps-script/tab_*.html`, 10/24).
- 드릴 [front-d1]: 새 카드 배경을 `#151515` 로, 버튼 높이를 36px 로 넣으려 한다(폰 390px). 무엇을 바꾸고 무엇으로 검사하나? — 답·채점 키 `content/drills/front.json`(라운드 파일에 `드릴: front-d1 <내 답>` 을 먼저 쓰고 열 것, round_collect 채점 · G1 10/24)
