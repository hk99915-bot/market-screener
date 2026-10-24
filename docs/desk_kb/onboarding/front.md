# 프론트 온보딩 과정 (교육 데스크, 2026-10-24)

대상: 신입 프론트(10/24 채용, `docs/desk_kb/front.md`). 목표: **첫 주에 혼자 화면 일을 하고 아무것도 깨지 않기** — 고치기 전 잠금, 고친 뒤 두 폭·두 스킨 검사, 남의 영역은 ask.
순서: ① 이 문서(1시간) → ② 실습 3개 `front_lab.md`(난이도 순) → ③ 확인 퀴즈 8문항 `front_quiz.md`(답은 답안 파일에 먼저, 키는 `content/onboarding/front.json` — 채점은 평가). 이수 기준은 §6.
근거: 숫자는 모두 이 저장소 커밋·파일에서 (10/24 main 기준). 역방향 설계 — 목표 행동(깨지 않고 고치기) → 확인(실습 채점·퀴즈) → 활동(이 문서) `[kb:edu#10년차 ①]`.

## 1. 화면 구조 — 파일 하나 고치면 어디까지 바뀌나
- **셸 + 탭.** `apps-script/Index.html` = 공용 셸(head·CSS 토큰·탭 바·공용 도우미·`render()`·`setView()`). 탭 화면은 `apps-script/tab_*.html` 19개, 셸이 `<?!= include('tab_x') ?>` 19줄로 끼운다(순서 유지).
- **view 와 render.** 전역 `view`(기본 `'home'`)가 지금 화면. `setView(v)` → 그룹(`GROUPS`: home·my·life·mkt·daily·res·quant·study·sys)과 둘째 줄(`SUBV`) 버튼을 그리고 `render()`. `render()` 는 `#root.innerHTML` 을 `homeView()`·`marketView('KR')`… 중 하나로 통째로 바꾼다 → 화면 함수는 **HTML 문자열을 돌려주는 함수**이고, 클릭 연결은 그린 뒤 다시 건다.
- **데이터 부르기.** 화면은 `google.script.run.withSuccessHandler(f).getXxx()` 로만 데이터를 받는다. `getData()` 는 객체, 나머지 getter 는 **JSON 문자열**(화면이 `JSON.parse`).
- **두 곳에서 돈다 (GAS vs Pages).**

| | GAS 웹앱 | GitHub Pages |
|---|---|---|
| 화면 파일 | `Code.gs doGet()` 이 GitHub main 의 `apps-script/*.html` 을 읽어(5분 캐시) 템플릿 평가 — 붙여넣기 불필요(10/22) | `python3 scripts/build_pages.py` 가 include 를 인라인해 루트 `index.html` 생성 |
| `google.script.run` | 진짜 GAS — `Code.gs` 의 getter 가 `raw_()`(GitHub raw + 토큰)로 읽음 | `build_pages.py` 의 `SHIM` 이 같은 이름을 `fetch('reports/…json')` 로 흉내. 시세·운영 파일 일부는 raw 직접 |
| 반영 시점 | push 뒤 최대 5분(캐시) | push → Pages 빌드 뒤 |

- **규칙.** `index.html` 은 산출물 — 손으로 고치지 않고 잠그지 않는다, 화면을 고친 커밋엔 `build_pages.py` 로 다시 만든 `index.html` 을 같이 넣는다(`check_functions.py` 가 낡으면 경고). 새 getter 는 `Code.gs` + `build_pages.py SHIM` **짝**이고 둘 다 개발 소관·잠금 대상 → 프론트는 개발에 ask. 탭 파일 사이 같은 최상위 이름 = `check_functions.py` 실패.

## 2. 디자인 토큰 — 색·글자는 이름으로만
- **색 토큰**(`Index.html :root` → `html.xl` 이 엑셀 스킨 값으로 덮음):

| 토큰 | 기본(다크) | 엑셀 `html.xl` | 쓰는 곳 |
|---|---|---|---|
| `--bg` / `--panel` | #000 / #0b0b0b | #fff / #fff | 바탕 / 패널 |
| `--bg2` / `--bg3` | #111 / #161616 | #f3f3f3 / #f7f7f7 | 머리·겹 배경 / 표 머리·hover |
| `--amber` / `--on-amber` | #ff9a1f / #000 | **#000** / #fff | 강조 배경 / 그 위 글자 |
| `--up` / `--dn` | #2fd05a / #ff4b4b | #000 / #c00000 | 오름 / 내림(엑셀 = 음수만 빨강) |
| `--ch1` / `--ch2` | =--amber / =--blue | #4472c4 / #c55a11 | 차트 두 계열(xl 은 --amber·--blue 둘 다 #000 이라 따로) |

  함정: 엑셀에선 `--amber` 가 **검정**이다. `background:var(--amber);color:#000` = 검정 위 검정 → 글자는 반드시 `var(--on-amber)`.
- **안전망은 기대지 말 것.** `Index.html` 에 `html.xl [style*="background:#0"]{background:#fff!important}` 같은 속성 선택자 안전망이 있어 인라인 다크 색 일부를 엑셀에서 흰색으로 바꾼다. 문자열 모양이 조금만 달라도(`fill="#111"`, 그라디언트, 템플릿 계산) 안 걸리고, 걸려도 글자색은 그대로라 흰 바탕 흰 글자가 생긴다(10/24 프로필 '더보기' X2, df0a1f16). 새 코드는 토큰만.
- **글자 4단계**: `--fs-1` 11px(보조) · `--fs-2` 12.5px(본문·표) · `--fs-3` 14px(강조) · `--fs-4` 17px(제목·큰 숫자) · `--fs-icon` 24px(아이콘). 픽셀 직접 쓰기 금지 — `tests/test_font_tokens.py` 가 빨강, `python3 scripts/font_tokens.py --fix` 가 가장 가까운 단계로(같은 거리면 큰 쪽). 캔버스·SVG 속성 `font-size="11"` 은 대상 밖.
- **누르는 크기**(10/24 UXUI 결정, `docs/uxui/2026-10-24_pc44_decision.md`): 손가락 기기 `@media (any-pointer:coarse)` = **44px**(WCAG 2.5.5 AAA 목표), 마우스만 `not (any-pointer:coarse)` = **28px**(2.5.8 AA 24px + 4), 엑셀 `html.xl` 은 둘 다 제외(촘촘). 24px 미만 = 결함. 새 목록 버튼은 기존 `.sbtn` 류를 쓰면 이 규칙을 그대로 받는다.
- 대비: 본문 4.5:1, 큰 글자(24px+ 또는 18.66px+ 굵게)·기호·그래프 선 3:1 `[규정: WCAG 1.4.3·1.4.11]` — 식은 `kb:front#6`.

## 3. 검사 도구 — 무엇이 무엇을 잡나
| 도구 | 잡는 것 | 못 잡는 것 |
|---|---|---|
| `tests/test_skin_tokens.py` | 화면 파일의 다크 전용 배경 hex(`background:#111` 류)·`--amber` 위 `#000` 글자, 두 스킨 토큰 정의, 링크 점선·xl 이모지 회색·`--ch1/2` | 템플릿 삼항 속 색(`'#0a0a0a'`)·SVG `fill`·그라디언트 |
| `tests/test_font_tokens.py` | 글자 px 직접 쓰기 | 템플릿 계산 px(손으로) |
| `scripts/skin_audit.py [--skin def] [--views a,b] [--root DIR]` | 35화면 × 390·1300px: 글자 대비·넘침·잘림·11px 미만·어두운 배경 잔존·컬러 이모지·링크 구분 | canvas·svg 안, background-image 위 글자 = **자 밖** |
| `scripts/ui_smoke.py [view…]` | 뷰별 렌더·콘솔 에러 + `check_*` 20개 | 기준선 스크린샷 비교 없음, 성능(INP·CLS) 안 잼 |

ui_smoke 중 화면 담당이 꼭 아는 것:
- `check_head_clip` — 390px 머리 `.top` ≤ `HEAD_MAX`(110px)·💬/🔍 44px 같은 줄(실파일 + 늦음 배지 주입 둘 다), 연구 보드 단계 카드 ≤60px, 잘림이 `CLIP_BASE`(현재 `{390: {"re": 4}, 1300: {"home": 2}}`)보다 늘면 BAD. **기준선 숫자는 고쳐서 줄였을 때만 내린다** — 통과시키려고 올리면 검사를 지운 것과 같다.
- `check_xl` — 엑셀 스킨 390·1300 전 화면: 대비 0·넘침 0·11px 미만 0·잘림 ≤ CLIP_BASE·머리·사내톡 7구역·HF 배지 글자 구분.
- `check_xl_beyond` — skin_audit 자 밖: 색 토큰 차트 반전 없음·대결 곡선 3:1·HOME 달력 선택일 구별·프로필 더보기.
- `check_links_pcr` — 기본 스킨 1300px 문장 속 링크 밑줄(색만으로 구분 금지, WCAG 1.4.1)·PCR 두 선 `--ch1≠--ch2`.
- 전후 비교: `git worktree add <scratch>/before <커밋>` → `skin_audit.py --root <scratch>/before`. 검사 하나만 빨리 돌릴 땐 `ui_smoke` 모듈을 import 해 그 함수만 부른다(`front_lab.md` 실습 3에 예시).

## 4. 사례집 — 이렇게 하면 깨진다 (10/23~24, 실제 5건)
| # | 커밋 | 무엇을 했나 → 무엇이 깨졌나 | 누가·어떻게 찾았나 | 재발 방지(지금 있는 장치) |
|---|---|---|---|---|
| 1 | 3d6feca9 → ffb03804 | 💬 를 머리 안 44px 버튼으로 옮김 → 첫 줄(브랜드+◐+신선도 배지 143px+💬+🔍 ≈ 420px)이 390px 를 넘어 🔍 혼자 둘째 줄, `.top` 105→**151px** | UXUI 재검수(1300px 에선 한 줄이라 안 보임) | 폰 배지 짧게(`✓ 06:58`/`⚠ 늦음 2`) → 109px. `check_head_clip`·`HEAD_MAX=110` 신설. 교훈: 머리에 뭘 넣으면 390px 에서 **높이**를 잰다 |
| 2 | b466d965 | 사내톡 말풍선 `#151515`·팝업 `#0a0a0a`·머리 `#111` 하드코딩 + `background:var(--amber);color:#000` → 엑셀에서 검정 바탕 검정 글자(대비 미달 사내톡 98·팝업 101) | 겸이 제보 "톡방이 검정색" | 토큰 `--bg2/--bg3/--on-amber` 신설, `test_skin_tokens`·`skin_audit`·`check_xl`. 교훈: 스킨 2개 = 검사 2번 |
| 3 | df0a1f16 (원인 a0992379, 10/15) | 엑셀 스킨이 `html.xl canvas{filter:invert(1)}` 로 차트를 밝게 뒤집는데, 이미 `cv('--panel')` 토큰으로 밝게 그린 차트까지 또 뒤집어 채권·파생·ISA 캔버스 42개가 검정 상자(9일간) | UXUI 독립 재검수 — skin_audit 0 인데 눈으로 이상 | 토큰 차트는 반전 제외(`.tv-lightweight-charts canvas`, `canvas.tokc`), `check_xl_beyond`. 교훈: 자(검사기)가 0이어도 **자 밖**(canvas·svg)은 눈·전용 검사로 |
| 4 | 79db85cf | 데이터 스키마 변경: `geo_news` 가 약관상 제목을 `title=None` 으로 싣기 시작 → `macroview.glance()` 의 `n.get('title','')[:90]` 이 `None[:90]` TypeError → MACRO '한눈에' 전체가 '생성 실패' 1줄 | ui_smoke `check_macro_bond_top` BAD 2줄(3d6feca9 때 이미 보였음 → 매크로 장부) | 생성 코드 수정 + `tests/test_macro_glance.py`. 교훈: `.get(k, '')` 은 키가 **없을 때만** 기본값 — 값이 None 이면 None. JS 도 `(x.title||'').slice(0,90)`. 화면은 지어내지 말고 "데이터 없음(원인)" + 생성 쪽(개발·데이터·담당 데스크)에 ask |
| 5 | ffb03804 → 9b2ffd4f | #1 을 고치며 터치 전용 44px 규칙을 PC 포함 전체로 → 1300px 공시 9,063→18,922px(2.1배), 35화면 합 +13% | UXUI 측정(1300px 화면 높이 합) | 손가락 44 / 마우스 28px 절충 → 합 +3.1%. 교훈: 고친 것 옆을 잰다 — 한 회귀를 고친 커밋이 다른 폭에서 새 회귀를 만든다 |

공통: 5건 중 4건(1·2·3·5)은 기존 검사가 다 통과한 상태에서 사람(UXUI 3·겸이 1)이 찾았고, 그 뒤에 검사가 생겼다. 기계가 먼저 잡은 건 #4 하나(ui_smoke BAD 3d6feca9 22:23 UTC → 매크로 장부 → 79db85cf 23:49 UTC 수정). 새 화면 규칙을 만들면 **그 규칙의 검사도 같은 커밋에**.

## 5. 경계·협업 — 누가 무엇을
- 프론트: `Index.html`·`tab_*.html`·`build_pages.py` 화면부·CSS 토큰·`font_tokens.py`·`skin_audit.py`·`ui_smoke.py`·화면 테스트 **소유**. 텔레그램은 문구·배치만.
- 개발: `Code.gs`·`.gs`·`screener/`·`scripts/` 서버 쪽·workflows·getter 목록·배포. 데이터 칸이 없으면 화면에서 만들지 말고 개발(생성)·데이터(정의)에 `python3 scripts/ask.py --from 프론트 --to 개발 --text "…"`.
- UXUI: 설계·검수 기준(결재안 Top 10) — 프론트가 구현하고 UXUI 가 다시 잰다. 디자인 판단(예: 의도된 다크 사진 뷰어를 엑셀에서도 다크로 둘지)은 UXUI 에 묻는다.
- 데이터·담당 데스크: JSON 필드 정의·값. 사례 4처럼 화면 증상의 원인이 생성 쪽이면 그쪽 장부로.
- **잠금**(`ops/LOCKS.md`): 파일 하나가 단위. `python3 scripts/lock.py list` → `take apps-script/tab_home.html --owner 프론트 --task <보드 id>` → 작은 커밋으로 바로 push → 편집·검사·빌드·push → `lock.py drop --owner 프론트` push. 남의 잠금은 지우지 않고 기다리거나 PB 에. 6시간 넘으면 ⚠ 방치.
- **작업 규약**(`LOOP.md`): 자기 worktree, 경로 지정 `git add`(`-A` 금지), 커밋 접두 `front:`, push 전 훅 우회(`--no-verify`) 금지, 남의 KB·라운드 파일 수정 금지.
- **출제자≠검수자**: 이 과정의 퀴즈·실습 키는 교육이 냈고 평가가 검수·채점한다. 프론트가 나중에 화면 검사 기준(CLIP_BASE·HEAD_MAX)을 바꾸면 UXUI 가 검수자.

## 6. 첫 주 체크리스트 (10/24~10/31)
- [ ] D1: `front.md`·이 문서·`ops/LOCKS.md` 읽기, `sh scripts/install_hooks.sh`, 자기 worktree 에서 `python3 scripts/build_pages.py` → `python3 scripts/ui_smoke.py home` 한 번 돌려 출력 읽기.
- [ ] D1: 라운드 파일에 `드릴: front-d1 <내 답>` 먼저 쓰기(키는 그 뒤).
- [ ] D2: 실습 1(달력 색 토큰) — 잠금·빌드·검사·push 한 바퀴. **보드 `front-first-round` 의 하드코딩 2곳**(`grep -n '#111\|#151515' apps-script/tab_*.html`: `tab_market.html` 히트맵 그룹 상자 `fill="#111"`, `tab_msgr.html` 프로필 배경 기본 그라디언트)에 같은 절차 — 둘 다 skin_audit 자 밖이라 실습 1 의 '안전망 빼고 재기'와 실습 3 의 '함수 하나만 돌리기'를 같이 쓴다. 히트맵은 상자만 바꾸면 위 글자 `fill="#ddd"` 가 밝은 바탕에서 안 보인다 — 글자도 토큰. 프로필 사진 뷰어는 사진 위 흰 글자라 의도된 다크일 수 있다 → 바꾸기 전에 UXUI 에 판단 ask, 남기면 이유 주석.
- [ ] D3: 실습 2(배지), D4: 실습 3(머리 회귀 재현).
- [ ] D4: 퀴즈 8문항 — 라운드 파일에 `퀴즈: front-qN <내 답>` 8줄, 평가에 채점 요청.
- [ ] D5: 재배정 작업(`tradeplan-ui`·`edu-dev-handoff`·`req-dev-cb19b1e0`) 우선순위 운영에 회신(req-front-889551e0), 라운드 파일 VOC.
- **이수 기준**: 실습 1·3 필수 통과 + 실습 2 통과 + 퀴즈 8문항 중 6 이상 통과(문항당 키 일치 ≥60%). 판정 = 평가. 미달 문항은 이 문서 해당 절 다시 읽고 다음 라운드에 재응시.
