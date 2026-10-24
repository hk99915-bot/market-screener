# 프론트 온보딩 실습 3개 (난이도 순)

본문 = `docs/desk_kb/onboarding/front.md`. 모든 실습은 **자기 worktree** 에서(`git worktree add <scratchpad>/wt_front origin/main`). 실습 1만 실제로 push 하고(잠금 필요), 실습 2·3은 연습용 worktree(`wt_front_lab`)에서 하고 push 하지 않는다.
제출 = 라운드 파일 `docs/desk_kb/rounds/<날짜>/front.md` 에 실습별 `실습N:` 3줄(무엇을 바꿨나 · 검사 출력 숫자 · 커밋/미커밋). 채점 = 평가(출제 교육 ≠ 검수 평가). 아래 '기대값'은 교육이 10/24 main(0bbd8339 + edu 커밋)에서 직접 돌려 얻은 숫자다 — 데이터 날짜가 바뀌면 화면 글자 수가 달라 몇 개 차이는 정상, **방향(0 유지·BAD→OK)** 이 채점 기준.

공용 도구 — 검사 함수 하나만 돌리기(전체 ui_smoke 는 20개 check 를 다 돌아 오래 걸린다). 저장소 밖 자기 scratchpad 에 `one_check.py` 로 저장:
```python
import asyncio, glob, sys
sys.path.insert(0, sys.argv[1] + "/scripts")            # 인자 1 = 검사할 worktree 경로
import ui_smoke as u
from pathlib import Path
u.SERVE = Path(sys.argv[1])
async def main(port):
    from playwright.async_api import async_playwright
    exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome") or [None])[0]
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
        return await getattr(u, sys.argv[2])(b, port)      # 인자 2 = check 함수 이름
srv = u._serve(0)
try: print("bad", asyncio.run(main(srv.server_address[1])))
finally: srv.shutdown()
```
실행: `python3 -I one_check.py <worktree> check_head_clip` (`-I` = 현재 폴더의 같은 이름 파일을 import 하지 않게). 마지막 줄 `bad 0`/`bad False` = 통과.

## 실습 1 (기초) — 하드코딩 색 1곳을 토큰으로, 기본·엑셀 skin_audit 0 유지
대상: `apps-script/tab_home.html` 의 `calPanel()` 달력 칸(`class="calc"` 줄) — `border:… '#1e1e1e'`, `background:… '#1a1408' : '#0a0a0a'`. 템플릿 삼항 안이라 `test_skin_tokens` 정규식에 안 걸리고, 엑셀에선 `Index.html` 의 속성 선택자 안전망(`html.xl [style*="background:#0"]…`)이 흰색으로 덮어서 **지금은 멀쩡해 보인다** — 안전망에 기대고 있는 코드다.
1. `lock.py take apps-script/tab_home.html --owner 프론트 --task front-first-round` → 잠금 커밋 push.
2. 세 색을 토큰으로: 테두리 → `var(--line)`, 바탕 → `var(--panel)`, 선택일 바탕 → `var(--bg3)`(선택 표시는 이미 있는 `outline:2px solid var(--amber)` 가 맡는다).
3. `python3 scripts/build_pages.py` → `python3 scripts/skin_audit.py --views home` 와 `--skin def --views home`.
4. **안전망 빼고 재기**(연습 worktree 에서만): `Index.html` 의 `html.xl [style*="background:#0"],…{background:#fff!important}` 한 줄을 지우고 빌드 → `skin_audit.py --views home --root <연습 worktree>`. 고치기 전·후 둘 다 잰다.
5. `python3 -I one_check.py <worktree> check_xl_beyond`(달력 선택일 구별) → `pytest tests/test_skin_tokens.py tests/test_font_tokens.py` → 커밋(`front:` 접두, 롤백·영향 한 줄) → push → 잠금 해제.

정답 기준(전부 충족 = 통과):
- 그 줄에 hex 색 0개(`grep -n "calc" apps-script/tab_home.html` 로 확인), `index.html` 재빌드 포함.
- skin_audit home: 엑셀 대비 미달 0·어두운 배경 0, 기본 대비 미달 0(기본 '어두운 배경' 165 는 다크 스킨이라 정상 — 늘지만 않으면 됨).
- 안전망 뺀 측정: 고치기 전 엑셀 home 대비 미달 **225**·어두운 배경 **62**(교육 실측) → 고친 뒤 **0·0**. 이 두 숫자를 라운드 파일에.
- `check_xl_beyond` 달력선택=O, 두 테스트 통과, 잠금 걸고 풀었음(`ops/locks.json` 커밋 2개).
채점 방법: 평가가 커밋 diff + 라운드 파일 숫자를 보고, 연습 worktree 에서 4번을 직접 재현(약 30초).

## 실습 2 (중간) — 새 배지를 --fs 토큰·대비 기준으로 추가 (연습 worktree, push 안 함)
과제: HOME '오늘 결론' 패널 제목(`tab_home.html` `<h2>오늘 결론<small>`)에 `검증전` 배지를 붙인다. 배지는 누르는 것이 아니다(누르는 것이면 버튼 규칙 44/28px 이 붙는다 — 왜인지 라운드 파일에 한 줄).
1. 스타일은 셸(`Index.html` `<style>`)에 클래스 하나(`.bdg`)로 — 여러 탭이 쓸 도우미는 셸, 한 탭 전용이면 그 탭 파일. 글자 `var(--fs-1)`, 바탕 `var(--amber)`, 글자색 `var(--on-amber)`.
2. 빌드 → 두 테스트 → 두 스킨 × 두 폭에서 배지의 계산된 글자 크기·대비를 잰다(브라우저 `getComputedStyle` 로 color·backgroundColor → `kb:front#6` 식).
3. **일부러 깨기**: 글자 `10px`, 글자색 `#000`(`background:var(--amber);color:#000`) 으로 바꿔 같은 검사를 다시 → 무엇이 빨강이 되는지 기록 → 되돌리기.

정답 기준:
- 바른 배지: 글자 11px(4단계 1), 대비 기본 **9.89:1**(검정 on #ff9a1f)·엑셀 **21:1**(흰 on 검정) — 둘 다 ≥4.5, `skin_audit --views home` 두 스킨 대비 미달 0, 두 테스트 통과.
- 깨진 배지: `test_font_tokens::test_no_raw_px_font_size` 와 `test_skin_tokens::test_no_dark_only_hardcoded_background[Index.html]` 둘 다 FAIL, 엑셀 대비 **1:1**, `skin_audit --views home --widths 390` 엑셀 대비 미달 1·11px 미만 1.
- 한 줄 설명: 왜 엑셀에서만 1:1 인가(`--amber` 가 xl 에서 #000).
채점 방법: 라운드 파일의 숫자 6개(바른 2 대비·깨진 대비·FAIL 테스트 2 이름·skin_audit 1/1)를 평가가 키와 대조.

## 실습 3 (심화) — 390px 머리 높이 회귀를 재현하고 ui_smoke 로 잡기 (연습 worktree, push 안 함)
배경: 사례 1(3d6feca9 → ffb03804). 지금은 `freshBadge()` 가 폰 폭(`max-width:700px`)에서 짧은 글자(`✓ 06:58`)를 넣어 머리 첫 줄이 한 줄에 들어간다.
1. 먼저 그대로 `python3 -I one_check.py <연습 worktree> check_head_clip` — 기준값 기록.
2. 회귀 만들기: `Index.html freshBadge()` 마지막의 `el.textContent=matchMedia('(max-width:700px)').matches?(…):lng;` 를 `el.textContent=lng;` 로(폰에서도 긴 문장) → 빌드 → 같은 검사.
3. 같은 변경에서 1300px 화면 `.top` 높이도 잰다(검사가 왜 390 에서만 머리를 보는지 확인).
4. 되돌리고 다시 OK 확인. 라운드 파일에 원인·발견법·재발 방지 3줄.

정답 기준:
- 1번: `OK 머리높이(390px, 실파일) .top 109px`·`늦음 주입 109px`·잘림 증가 0.
- 2번: `BAD 머리높이(390px, 실파일) .top` **>110px**(교육 실측 159px, 🔍 `t` 6→56 = 둘째 줄로 떨어짐), 마지막 줄 `bad 1`. '늦음 주입'은 OK 로 남을 수 있다 — 주입 문장('⚠ 늦은 데이터 2')이 '데이터 정상 · 점검 hh:mm' 보다 짧기 때문. 이 차이를 설명하면 가산.
- 3번: 1300px 에선 한 줄(머리 높이 거의 불변) → "PC 에서 보이면 됐다"가 틀린 이유.
- 금지 답: `HEAD_MAX` 나 `CLIP_BASE` 를 올려 통과시키기 = 0점(기준선은 고쳐서 줄였을 때만 내린다, 본문 §3).
채점 방법: 평가가 연습 worktree 에서 2번을 재현해 BAD 를 보고, 라운드 파일 3줄(원인 = 첫 줄 폭 초과 → 🔍 줄바꿈, 발견 = check_head_clip 390px, 방지 = 머리에 요소 추가 시 390 높이 측정·HEAD_MAX 유지)을 확인.

## 첫 라운드와의 연결 (보드 front-first-round · req-front-889551e0)
- 실습 1 = 첫 라운드 '하드코딩 색 토큰화'의 연습 한 바퀴(다른 곳이라 중복 아님). 보드가 지정한 2곳(`grep -n '#111\|#151515' apps-script/tab_*.html` → `tab_market.html` 히트맵 그룹 상자, `tab_msgr.html` 프로필 기본 그라디언트)은 같은 절차로 한다.
- 둘 다 **skin_audit 자 밖**(SVG `fill`, 사진·그라디언트 배경)이라 skin_audit 0 이 통과 증거가 아니다. 교육 실측(10/24): 엑셀 1300px 히트맵 그룹 상자 계산된 fill = `rgb(17,17,17)`(흰 화면 위 검정 상자), 그 위 그룹 글자 `#ddd`. 증거 = `getComputedStyle(rect).fill` 을 두 스킨에서 재서 라운드 파일에.
- 드릴 `front-d1` 은 실습 전에 먼저 푼다(`드릴: front-d1 <내 답>` 을 먼저 쓰고 키는 그 뒤, G1).
