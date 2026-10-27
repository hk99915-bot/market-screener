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
- #2 [자체 규약] **빌드 경로**: `apps-script/Index.html`(+`include('tab_x')`) → `python3 scripts/build_pages.py` → 루트 `index.html`(Pages). `index.html` 은 산출물이라 손으로 고치지 않고 잠그지 않는다. GAS 반영 자동: HTML 은 Code.gs 가 GitHub 직접 읽음, .gs 는 gas_deploy.yml(clasp) — 수동 붙여넣기 없음.
- #3 [규정] **WCAG 2.2**: 본문 대비 4.5:1(1.4.3), 터치 대상 24×24px 최소(2.5.8, AA) · 44×44px 목표(2.1 2.5.5, AAA) — kb:uxui#2·#4.
- #4 [교과서-B] **Core Web Vitals**: 상호작용 반응 INP ≤ 200ms, 레이아웃 흔들림 CLS ≤ 0.1, 첫 큰 그림 LCP ≤ 2.5s(75백분위). (출처: Google web.dev "Web Vitals" `[확인 필요: 현행 임계값 원문, 2026-10-31]`) 우리는 아직 안 잰다(격차).
- #5 [경험] `overflow-x:hidden` 이면 scrollWidth 로 폰 넘침을 못 잡는다 → 요소 `getBoundingClientRect().right` 검사(kb:dev 10/21).
- #7 [규정] **WCAG 2.2 2.5.8 Target Size (Minimum, AA)·2.4.11 Focus Not Obscured (Minimum, AA)** (부스팅 10/27, req-front-b433cc36) — ① 내용: 2.5.8 = 누르는 대상은 24×24 CSS px 이상, 예외 = 24px 원 간격이 겹치지 않는 작은 대상·문장 속 링크·브라우저 기본 컨트롤·크기가 본질인 경우. 2.4.11 = 키보드 초점이 간 요소가 작성자가 만든 고정 헤더·띠·팝업에 **완전히** 가려지면 안 됨(일부 가림은 AA 허용, 2.4.12 AAA 는 일부도 금지). ② W3C 뷰: 2.5.5(44px)는 AAA 로 남기고 2.5.8 을 AA 최소로 새로 둔 것은 '밀도 높은 화면도 지킬 수 있는 바닥'을 주려는 것. ③ 우리 해석: 바닥 = 24(규정), **프로젝트 기준 = 터치 기기 44 / 마우스 PC 28**(UXUI 10/24 `docs/uxui/2026-10-24_pc44_decision.md`, `Index.html` any-pointer:coarse 블록) — 드릴·검수는 프로젝트 기준으로 본다. 2.4.11 은 우리 고정 탭 바·상세 서랍 머리에 해당하나 아직 검사 없음(격차 ③). 등급 [규정] · 신뢰 상.
- #8 [교과서-B] **Core Web Vitals 임계값** (web.dev, 부스팅 10/27) — ① 내용: 좋음 기준 LCP ≤ 2.5s · INP ≤ 200ms(나쁨 > 500ms) · CLS ≤ 0.1(나쁨 > 0.25), 페이지 방문의 75백분위로 판정. INP 는 2024-03 FID 를 대체(모든 클릭·탭·키 입력 중 최악에 가까운 반응). ② Google 뷰: 실사용자 측정(필드)이 기준이고 실험실 측정(Lighthouse·헤드리스)은 원인 찾기용. ③ 우리 해석: 겸이 혼자 쓰는 화면이라 필드 표본이 없다 → 헤드리스 390px 에서 `PerformanceObserver('layout-shift')` 합과 탭 전환 클릭→다음 그림 시간을 '실험실 근사'로 재고, 숫자 옆에 '실험실 근사'를 붙인다(필드값 아님). 등급 [교과서-B] · 신뢰 중 `[확인 필요: web.dev 원문 임계값 대조, 2026-10-31]`.
- #9 [규정-초안] **Design Tokens Format Module** (W3C Community Group 초안, 부스팅 10/27) — ① 내용: 토큰 = JSON 객체에 `$value`·`$type`(color·dimension·fontFamily 등)·`$description`, 다른 토큰 참조는 `{group.name}` 별칭, 묶음(group)이 `$type` 을 물려줌. ② CG 뷰: 디자인 도구↔코드가 같은 파일을 읽게 하려는 교환 형식이며 아직 '권고'가 아닌 커뮤니티 초안. ③ 우리 해석: 우리 토큰은 CSS 변수(`Index.html :root`·`html.xl`)뿐이라 교환 파일은 과잉 — 지킬 것은 '화면 파일은 이름만 쓴다'(#1)와 별칭 1단(스킨이 토큰 값만 바꿈). 등급 [규정-초안] · 신뢰 중.

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
- 격차(10/27 갱신): ① 기준선 스크린샷 비교 없음 — ui_smoke check 30개(10/27 grep `^async def check`)는 '깨졌나'(에러·넘침·글자)만 본다. ② INP·CLS 미측정(#8). ③ 2.4.11 초점 가림 검사 없음(#7). ④ 다크 전용 색 직접 쓰기 1곳(`tab_msgr.html`, 10/27 grep — 10/24 2곳에서 1 감소).
- 규칙(격차 → 할 일, 10/27 부스팅): R1 화면을 바꾼 커밋은 바뀐 패널을 390px 로 `element.screenshot` 해 눈으로 보고, 해당 ui_smoke check 를 추가·통과시킨 뒤 커밋(기준선 이미지 저장·픽셀 비교는 저장소 용량 문제로 보류 — 도입은 UXUI·개발 합의 후). R2 새 기능 패널은 외부 iframe·큰 JSON 을 **누를 때** 불러온다(다시 그리기마다 재로딩·CLS 방지 — 예: 파생 K200 선물 차트 기본 접힘, 10/27). R3 CLS·INP 실험실 근사 측정은 ui_smoke check 로 넣되 첫 측정값을 기준선으로만 기록하고 문턱(#8 0.1·200ms)은 UXUI 검수 뒤 건다(22~07시 문턱 신설 금지). R4 고정 머리(탭 바·서랍 머리) 아래로 초점이 완전히 숨는지(#7 2.4.11)는 다음 화면 변경 때 check_head_clip 확장으로.
- 체크리스트 보강: ⑤ 터치 대상 = 프로젝트 기준 44px(터치 기기)·28px(마우스 PC), 규정 바닥 24px(#7) — 드릴·검수는 프로젝트 기준 ⑥ 외부 위젯(TradingView 등)은 표시 전용·대체 링크 같이(값 추출 금지).
- 드릴 [front-d1]: 새 카드 배경을 `#151515` 로, 버튼 높이를 36px 로 넣으려 한다(폰 390px). **우리 프로젝트 기준으로** 무엇을 바꾸고(버튼 높이는 몇 px 로?) 무엇으로 검사하나? (WCAG 규정 최소와 프로젝트 기준을 구분해서) — 답·채점 키 `content/drills/front.json`(라운드 파일에 `드릴: front-d1 <내 답>` 을 먼저 쓰고 열 것, round_collect 채점 · G1 10/24)
- 드릴 [front-d2]: 파생 탭에 TradingView 위젯 iframe 패널을 새로 넣는다. 탭은 장중 시세가 올 때마다 통째로 다시 그려진다(innerHTML). 폰 390px 에서 생길 문제 2가지와 막는 방법, 그리고 무엇으로 검사하나? — 답·채점 키 `content/drills/front.json`
