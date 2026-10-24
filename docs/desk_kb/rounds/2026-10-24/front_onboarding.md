# 프론트 온보딩 답안 (2026-10-24, req-front-1e6ffe44 · 채점 = 평가)

키(`content/onboarding/front.json`)는 열지 않고 썼다(블라인드). 측정 = 이 세션 10/24 origin/main(99870a09 이후) worktree, Chromium(playwright) · 화면 데이터 10/24 기준.

## 실습
실습1: tab_home.html calPanel() `.calc` 줄 `#1e1e1e`·`#0a0a0a`·`#1a1408` → `var(--line)`·`var(--panel)`·`var(--bg3)`(선택일은 기존 outline var(--amber)), index.html 재빌드 포함, 그 줄 hex 0개.
실습1: 안전망(`html.xl [style*="background:#0"]…` 한 줄) 뺀 엑셀 home 390·1300 — 고치기 전 대비 미달 225·어두운 배경 62 → 고친 뒤 0·0. 안전망 있는 실제: 엑셀 대비 0·어두운 0 / 기본 대비 0·어두운 배경 165(불변). check_xl_beyond 달력선택=O(bad False), test_skin_tokens·test_font_tokens 통과.
실습1: 커밋 6c85fb7c(+ 잠금 7de190a5 take, drop 은 라운드 마감 커밋) — push 함.
실습2: 셸 Index.html 에 `.bdg{font-size:var(--fs-1);background:var(--amber);color:var(--on-amber)}`, '오늘 결론' h2 에 검증전 배지. 계산값 11px · 대비 기본 9.89:1(rgb(0,0,0) on rgb(255,154,31)) · 엑셀 21:1(흰 on 검정), 두 폭 동일. skin_audit home 두 스킨 대비 미달 0(엑셀 '어두운 배경' 2 = 배지 자체 검정 바탕), 두 테스트 통과.
실습2: 깨기(10px + color:#000) → FAIL `test_font_tokens::test_no_raw_px_font_size`·`test_skin_tokens::test_no_dark_only_hardcoded_background[Index.html]`, 엑셀 대비 1:1(기본은 9.89 그대로), `skin_audit --views home --widths 390` 엑셀 대비 미달 1·11px 미만 1. 되돌림, 미커밋.
실습2: 엑셀에서만 1:1 인 이유 = html.xl 에서 `--amber` 가 #000 이라 검정 바탕에 하드코딩 #000 글자. 배지는 누르는 것이 아니라 44/28px 버튼 규칙(WCAG 2.5.8·2.5.5 = 포인터 대상 크기) 대상이 아님 — 누르게 만들면 .sbtn 류로.
실습3: 기준값 `OK .top 109px`(실파일·늦음 주입 둘 다)·잘림 증가 0·bad 0. 회귀(`el.textContent=lng;`) → `BAD .top 159px`, 🔍 t 6→56(둘째 줄), 늦음 주입은 OK 109px, bad 1. 1300px `.top` 91→91px(불변). 되돌린 뒤 bad 0, 미커밋.
실습3: 원인 = 폰에서도 긴 배지('데이터 정상 · 점검 hh:mm')로 첫 줄 폭이 390px 를 넘어 🔍 가 둘째 줄로 떨어짐(.top 159px). 늦음 주입이 OK 인 건 주입 문장 '⚠ 늦은 데이터 2' 가 정상 문장보다 짧아 한 줄에 들어가서.
실습3: 발견 = check_head_clip(390px 실파일) — 1300px 는 폭이 남아 한 줄이라 안 보임("PC 에서 보이면 됐다"가 틀린 이유). 방지 = 머리에 요소·글자 추가 시 390px .top 높이 측정, HEAD_MAX 110 유지(올려서 통과 금지 — 안 올림).

## 퀴즈
퀴즈: front-q1 ① lock.py list → take apps-script/tab_home.html --owner 프론트 --task <보드 id> → 잠금 커밋 push ② 자기 worktree 에서 색을 토큰(var(--line/--panel/--bg3))으로 편집 ③ python3 scripts/build_pages.py 로 index.html 재빌드 ④ pytest tests/test_skin_tokens.py tests/test_font_tokens.py ⑤ skin_audit.py 엑셀·기본(--skin def) 두 스킨 × 390·1300 대비 미달 0 + ui_smoke(check_xl_beyond 달력선택) ⑥ 경로 지정 git add(tab_home.html·index.html) → 'front:' 커밋(롤백·영향 한 줄) → pull --rebase → push(pre-push 훅, --no-verify 금지) ⑦ lock.py drop --owner 프론트 → push. index.html 은 build_pages.py 가 include 를 인라인해 만드는 산출물이라 손으로 고치면 다음 빌드에 덮여 사라지고 원본(Index.html·tab_*.html)과 어긋난다(check_functions.py 가 낡으면 경고).
퀴즈: front-q2 GAS 웹앱 = 진짜 google.script.run → Code.gs getMacroView() 가 raw_('reports/macro_view.json')(GitHub raw + 토큰)로 읽어 JSON 문자열 반환. Pages = build_pages.py 의 SHIM 이 같은 이름을 fetch('reports/macro_view.json')(get())로 흉내. 새 getter 는 Code.gs + build_pages.py SHIM 짝으로 고쳐야 하고 둘 다 개발 소관(잠금 대상) → 프론트는 scripts/ask.py --to 개발 로 요청.
퀴즈: front-q3 엑셀(html.xl)에서 --amber 가 #000 이라 검정 바탕(#000)에 검정 글자(#000) = 대비 1:1, 글자가 안 보임. color:var(--on-amber)(기본 #000·엑셀 #fff → 엑셀 21:1)로 고친다. tests/test_skin_tokens.py(--amber 위 #000 글자·다크 전용 hex 검사)가 막고, skin_audit·check_xl 이 대비 미달로 잡는다.
퀴즈: front-q4 13px → --fs-2(12.5px, 본문·표)과 --fs-3(14px) 중 가까운 쪽 = 12.5(거리 0.5) vs 14(거리 1) → var(--fs-2). tests/test_font_tokens.py::test_no_raw_px_font_size 가 빨강, 자동 수정 python3 scripts/font_tokens.py --fix(가장 가까운 단계, 같은 거리면 큰 쪽).
퀴즈: front-q5 손가락 기기 @media (any-pointer:coarse) 44px(WCAG 2.5.5 AAA 목표 44×44), 마우스만 not (any-pointer:coarse) 28px(WCAG 2.5.8 AA 최소 24px + 4), 엑셀 html.xl 은 둘 다 제외(촘촘, 24px 미만만 결함). PC 까지 전부 44px 로 했을 때(ffb03804) 1300px 공시 화면 높이 9,063→18,922px(2.1배), 35화면 합 +13% → 9b2ffd4f 절충 후 +3.1%.
퀴즈: front-q6 10/23 회귀(3d6feca9 → ffb03804)에서 390px .top 105→151px, 지금 상한 HEAD_MAX = 110px(실측 109px). 보는 함수 = ui_smoke check_head_clip(390px 실파일 + 늦음 배지 주입). 1300px 에선 첫 줄(브랜드+◐+신선도 배지+💬+🔍 ≈ 420px)이 폭 안에 한 줄로 들어가 🔍 가 안 떨어져 높이가 안 변함(실습 3 실측 1300px 91px 불변).
퀴즈: front-q7 엑셀 스킨의 html.xl canvas{filter:invert(1)} 가 이미 cv('--panel') 토큰으로 밝게 그린 차트까지 또 뒤집어 채권·파생·ISA 캔버스 42개가 검정 상자(원인 a0992379 10/15, 9일간). skin_audit 는 글자 대비 자라서 canvas·svg 안과 background-image(그라디언트·사진) 위 글자는 못 잰다(자 밖). 대신 ui_smoke check_xl_beyond(토큰차트반전없음·대결곡선3:1·달력선택·프로필더보기)가 보고, 수정은 토큰 차트 반전 제외(.tv-lightweight-charts canvas, canvas.tokc).
퀴즈: front-q8 스키마 변경: geo_news 가 약관상 title 을 None(null)으로 싣기 시작 → 키는 있고 값이 None 이라 n.get('title','') 이 기본값 '' 이 아니라 None 을 돌려줘 None[:90] TypeError → macroview.glance() 전체 예외 → '한눈에' 통째 '생성 실패'. .get(k,'') 는 키가 없을 때만 기본값이라 안전하지 않음 → (n.get('title') or '')[:90], JS 는 (x.title||'').slice(0,90). 프론트 할 일: 화면에 "데이터 없음(원인)" 표시 + 생성 쪽(개발·데이터·매크로)에 ask.py 장부. 하지 말 일: 화면에서 제목·값을 지어내 채우기, 생성 코드(screener/) 직접 고치기.
