# 블룸버그식 재설계 — 진단 · 원칙 · 위계 · 토큰 · 구현 단계 (UXUI, 2026-10-31)

> 겸이 요청(10/31 토 17시대): 「애플, 토스 다니는 친구에게 보여줬을 때 창피하지 않게 디자인, uxui 위계 다시 짜줘, 블룸버그 스타일로」.
> 이 문서는 **설계만** 담았다. 코드는 바꾸지 않았다(`apps-script/*`·`index.html` 수정 0). 겸이 결재 뒤 프론트가 아래 §6 단계표대로 구현하고 UXUI가 검수한다.
> 목업: [`2026-10-31_mockup_home.html`](2026-10-31_mockup_home.html) — HOME + MY(하단/상단 내비로 전환, `?v=my`·`?theme=light`·`?conv=kr`). **목업의 숫자는 모두 가짜 샘플이다.** 실제 지수·개인 금액·보유 종목·수량 없음.
> 결재 받을 것은 맨 아래 **§7 겸이 결정 항목 5개**다.

## 0. 어떻게 봤나 (측정 정의 — 재측정도 이 정의만 쓴다, 복기 10/23)
- 대상: main `04e3feee4` 의 빌드된 `index.html`, 10/31 17:2x KST 데이터(raw.githubusercontent 정상 로드). MY 는 비공개 토큰이 없어 **빈 상태만** 봤다.
- 환경: 헤드리스 크로미움, **390×844(DPR 2)** · **1440×900**, 기본 스킨, `setView(v)` 뒤 3.5초 대기. 캡처는 세션 임시 폴더(저장소에 안 넣음).
- 자동 측정(`#root` 안, 자기 글자를 가진 보이는 요소): 글자 크기 분포 · 고유 글자색 수 · 렌더된 이모지 수 · `.p` 패널 수와 윗변 위치 · `body` 의 `font-variant-numeric`.
- 코드 측정(`apps-script/*.html` grep): 하드코딩 색 `#[0-9a-f]{3,6}` · 이모지 문자(U+1F300–1FAFF, U+2600–27BF, ⭐, ⏳) · `style="` 인라인 수 · `letter-spacing` 값 종류.
- 목업 측정(같은 브라우저): 가로 넘침 요소 · 11px 미만 글자 · 24px 미만 누름 대상 · 글자 크기 종류.

## 1. 진단 — 지금 화면이 '창피한' 이유 Top 10
결론: 색·글자 단계·토큰은 10/23~10/24 Top 10 으로 **이미 블룸버그 뼈대(검정·앰버·고정폭)가 있다.** 창피한 이유는 스타일이 아니라 **규율**이다. 한글이 고정폭 대체 글꼴로 띄엄띄엄 찍히고, 가장 큰 숫자가 화면에 없고, 앰버가 다섯 가지 뜻을 동시에 맡는다.

| # | 문제 | 근거(측정·파일:행) | 무엇이 보이나 / 왜 창피한가 |
|---|---|---|---|
| 1 | **한글이 고정폭 대체 글꼴 + 자간으로 '타자기'처럼 찍힌다** | `Index.html:16` `--mono:"IBM Plex Mono",…,"Noto Sans Mono CJK KR"` 인데 웹폰트 로드 줄이 없음(grep `fonts.googleapis` 0) → 시스템 대체. `.p h2` 자간 `.14em`(`:51`), `.brand .12em`, 자간 값 10종 | 캡처 `cur_home_m.png` '오 늘 결 론', `cur_kr_m.png` 'M A C R O  C O N T E X T'. 토스·애플 화면과 가장 먼저 비교되는 지점 |
| 2 | **히어로 숫자가 없다 — 위계가 평평** | HOME 390px 글자 크기 분포: 12.5px 502 · 11px 177 · 14px 81 · **17px 2**. 가장 큰 글자(17px)가 '오늘 결론' 2곳뿐 | 첫 화면에서 눈이 내려앉을 숫자가 없다. 결론 3칸이 같은 크기·같은 테두리라 우선순위가 안 보임 |
| 3 | **HOME 이 10.5장, 패널 14개** | 390px 전체 8,838px(844px 화면 10.5장). 첫 화면 안 패널 1개(오늘 결론 146px), 2번째 'KR 직전 마감'은 449px 부터 860px 높이 문장 덩어리. MY PORTFOLIO 2,455px · CALENDAR 2,788px | 인지 근거표 R1(덩어리 ≤4)·Ke 2023 참고선(모듈 9+) 둘 다 초과. '할 일'·'위험 상태'가 한 칸씩일 뿐 구속 스트레스는 HOME 에 아예 없음 |
| 4 | **앰버가 다섯 가지 뜻** | `class="am"` 352곳 · `var(--amber)` 151곳. 쓰임: 패널 제목·선택 탭·링크형 종목명·'중립/약한 역풍' 상태값·확인 필요 경고 | 강조 1색 원칙이 깨져 '어디를 볼지' 신호가 사라짐(Healey & Enns 2012 — 색은 위치 신호만). 10/28 MY 스펙 §4(색 의미 2개)와도 충돌 |
| 5 | **경보 빨강 = 하락 빨강** | 시세 `.dn` 과 `⛔ 한도 초과`·`⏳ 쿨다운`·`늦은 데이터` 가 같은 `--dn #ff4b4b` 글자색(`tab_home.html:105`, `tab_my.html:280`) | 하락장 날엔 화면이 빨강으로 덮여 진짜 경보가 묻힌다. 경보는 색+모양(반전 블록)으로 달라야 함 |
| 6 | **색 남발·하드코딩** | 화면 코드 고유 하드코딩 색 **95종**, 인라인 `style="` **1,598곳**. 달력 칩만 5색(`tab_home.html:38` #c77dff·#ff9a1f·#ffcc33·#35d6e6·#666, 범례 `:54`) | 스킨이 토큰만으로 안 바뀌는 근본 원인(xl 스킨 덮어쓰기 규칙 60줄+ `Index.html:182~245`) |
| 7 | **이모지·배지 과다** | 화면 코드 이모지 **175자**(사내톡 34·대결 30·Index 29·MY 18), HOME 렌더 29개(⭐📌✓💬🔍⚠⏳) | 블룸버그·토스 모두 컬러 이모지를 UI 기호로 쓰지 않는다. 머리 💬🔍 는 폰에서 컬러 덩어리 2개로 가장 먼저 보임 |
| 8 | **숫자 정렬 기준이 없다** | `body` `font-variant-numeric: normal`, `tabular-nums` 는 MY 1곳·부동산 2곳뿐. 정렬은 '고정폭 글꼴이라 우연히' 맞음 | 1번을 고쳐 한글을 산세리프로 바꾸는 순간 표 숫자 열이 흔들린다 → 숫자 규칙을 토큰으로 먼저 고정해야 함 |
| 9 | **상위 탭 9개 · 화면 35개, 폰에서 반 잘림** | `Index.html:276` 9개(HOME·MY·LIFE·MARKET·DAILY·RESEARCH·QUANT·STUDY·SYSTEM) + `GROUPS` 35 뷰(`:487~495`). 390px 에서 5.5개 보이고 'RESEAR' 잘림(`cur_home_m.png`), 머리 140px(첫 화면 17%) | DAILY(운용회의·성적표)·QUANT·SYSTEM 의 경계가 '누가 만들었나' 기준이라 겸이 질문(무엇을 봐야 하나)과 안 맞음 |
| 10 | **움직이는 장식·영한 혼용 제목** | 시세 띠 60초 무한 스크롤(`Index.html:37~45`) + 등락 그라디언트 배경. 패널 제목 'KR BREADTH·US CLASSES·TOSS LIVE'(영문 대문자) 와 '오늘 결론·스트레스 테스트'(한글) 혼재 | 블룸버그는 시세를 **움직이지 않는 격자**로 둔다. 같은 위계의 제목이 두 언어·두 모양이면 '조립한 화면'으로 보임 |

- 잘 된 것(유지): 검정 바탕·앰버 브랜드, 글자 4단계 토큰과 `font_tokens.py` 검사(10/24), 터치 44/28px 절충(10/24), 표 첫 열 고정·'→ 더 있음', 엑셀 스킨 대비 0건. **이번 재설계는 이 위에 얹는다(뒤집지 않는다).**

## 2. 재설계 원칙 — '블룸버그의 밀도 × 애플·토스의 정돈'
| # | 원칙 | 구체 규칙 | 근거 |
|---|---|---|---|
| P1 | **검정 바탕 · 장식 0** | 배경 `#000`, 패널 1단(`surface`)·겹 1단(`raised`)만. 그라디언트·그림자·애니메이션 0(시세 띠 → 정적 격자). 둥근 모서리 2px 이하 | 블룸버그 터미널 관행 `[현업 관행]` |
| P2 | **강조 1색 = 앰버, 뜻은 '지금 볼 곳' 하나** | 앰버는 ① 선택된 탭·초점 ② 확인 필요(데이터 늦음·미작성) 두 곳만. 패널 제목·링크·상태값에서 뺀다(제목 = `text-2` 회색) | 인지 근거표 Healey & Enns 2012, Ajani 2022(강조+주석) |
| P3 | **시장색은 가격에만, 경보는 모양으로** | 상승/하락 색은 시세 칸·표의 등락 숫자에만. 판단 칸(KPI·결론)은 10/28 MY 스펙 §4 그대로 '상태 2색'. 경보(⛔ 한도 초과·위반 적용) = **빨강 반전 블록 + 흰 글자 + ⛔**(대비 5.74:1) — 하락 '글자색'과 모양으로 구분 | WCAG 1.4.1(색만으로 구분 금지) |
| P4 | **글자 = 한글 산세리프, 숫자 = 고정폭** | 본문·라벨 `IBM Plex Sans KR`, 숫자만 있는 칸·티커·시각 `IBM Plex Mono`. 한글 섞인 숫자 줄은 산세리프 + `tabular-nums`. **한글에 자간 금지**(자간은 영문 대문자 라벨에만, 0~.06em 한 값) | Google Fonts 둘 다 OFL. 토스·애플 = 산세리프 본문 + 고정폭 숫자 |
| P5 | **타이포 4단계** | 11 라벨·단위 / 13 본문·표 / 16 소제목·카드값 / 28 **히어로(화면당 1개)**. 굵기 400·500·600 셋 | 현 `--fs-1~4` 이름 유지(`font_tokens.py` 그대로) |
| P6 | **간격 8pt 그리드** | 4(글자 옆 반 단계)·8·16·24·32 만. 패널 안 여백 16, 패널 사이 16(폰 8) | 애플 HIG·머티리얼 공통 관행 `[교과서-B]` |
| P7 | **화면당 핵심 숫자 1개(히어로) + 관계 문장 1줄** | 히어로 아래에 비교 기준(한도·코스피)을 같은 줄에, 그 아래 'A → B' 관계 문장 1줄 | 인지 근거표 R1·R2·R3(Cowan 2001, Xiong Bearfield 2024, Boger & Franconeri 2024) |
| P8 | **명령줄 · 단축키** | 머리 검색창 → 명령줄 `/`(종목·화면 이름 모두 받음, 예 `005930`·`채권`·`MY`). 숫자 `1~6` 상위 그룹, `\` 스킨, `Esc` 닫기. 데스크톱 상위 내비에 키 번호 표기 | 블룸버그 `<GO>` 명령 관행 — 쉬운 말 버전 |
| P9 | **대비 WCAG AA** | 본문 4.5:1 이상. 토큰 표의 모든 글자색은 셋 바탕(bg·surface·raised) 위에서 4.5 이상으로 고름(§4 대비 열) | WCAG 2.1 1.4.3 `[규정]` |
| P10 | **터치 기준 유지** | 폰 누름 대상 44px(하단 탭 56px), 마우스 PC 28px — 10/24 결정 그대로 | `2026-10-24_pc44_decision.md` |

## 3. 정보 위계 재배치
### 3-1. 상위 그룹 9 → 6 (뷰 키는 그대로 — `setView('lab')` 같은 기존 링크·사용 기록 유지)
기준은 '누가 만들었나'가 아니라 **겸이가 그 화면에 와서 묻는 질문**이다(10/28 탭 질문 지도).

| 그룹(키) | 1순위 질문 | 들어가는 뷰(현재 키) | 바뀌는 점 |
|---|---|---|---|
| **1 홈** `home` | 지금 내가 할 일이 있나, 위험한가? | home | 첫 화면 재설계(§3-2) |
| **2 내 계좌** `my` | 내 계좌가 규칙 안에 있나? | my · life · score(성적표) | 성적표(나 vs PB)가 DAILY 에서 이동 — 내 성적이라서 |
| **3 시장** `mkt` | 시장 체력·매크로가 어떤가? | kr · us · macro · heat · bond · deriv · re · mdkr · mdus | KR/US 전종목은 KR·US 안 '전종목' 토글로(상위 칩 9 → 7) |
| **4 리서치** `res` | 오늘 새로 나온 근거는? | daily(데일리 리포트) · brief · rep · val · dart · views · chain | DAILY 그룹 해체. 공급망(chain)은 퀀트 결과물이 아니라 리서치 근거 |
| **5 데스크** `desk` | 데스크들이 무엇을 결정·검증 중인가? | cmt(운용회의) · rb(+study·lab) · sig(+mom) · pf(+isa) · msg(사내톡) · sysb(작업 보드) | QUANT + 운용회의 + 사내톡을 '조직' 하나로 |
| **6 설정·학습** `sys` | (가끔) 시스템·공부 | edu · apt · eng · sysc · syso · 스킨/색 관례 설정 | 폰에선 하단 탭에서 빼고 머리 메뉴(⋯)로 |

- 폰: **하단 고정 탭 5칸**(홈·계좌·시장·리서치·데스크, 56px) + 6번은 머리 메뉴. 지금 머리 140px → 48px(브랜드·명령줄·신선도 점·밝기) — 첫 화면 본문 +92px.
- 데스크톱: 머리 48px + 상위 내비 40px(키 번호 표기) + 하위 칩 1줄. 시세 띠는 HOME '지수' 패널로 흡수(띠 제거는 결정 D4).

### 3-2. HOME 첫 화면 = '위험 상태 · 지금 할 일 · 시장 3줄' (목업 `mockup_mobile.png`)
| 순서 | 덩어리 | 내용 | 데이터(기존 원천만, 새 판단 금지) |
|---|---|---|---|
| ① | **위험 상태(히어로)** | 구속 스트레스 값(28px) · 한도 −15% · 여유 %p · 게이지 1줄 · 관계 문장 1줄 · 상태 배지('한도 안' / ⛔ '초과') | pb-private `analysis/latest.json` `stats.stress·stress_ok`(토큰 있을 때만, MY 와 같은 `pbGet`) · 한도 `screener/defs.py STRESS_LIMIT`. 토큰 없으면 '위험 상태: 토큰 필요' 1줄 |
| ② | **지금 할 일** | 경보 행(⛔ 반전 블록, 맨 위) → 번호 목록(대결 제출 대기·마감, 쿨다운, 원장 차이, 확인 필요). 행 44px, 없으면 '할 일 없음' 1줄 | 지금 `homeConc()` 의 todo 그대로 + `viol_live` |
| ③ | **시장 3줄** | KR 국면 · US 국면 · 매크로 바람 — 줄마다 판정(16px) + 숫자(200일선 위 %, 20일 변화) + 관계 문장 1줄('한국만 약함 — 격차 %p') | `D.breadth` · `MV`(macro_view) — 지금 '시장 국면' 칸과 같은 값 |
| 접힘 | 상세 입구 줄(각 44px) | 일정 · 운용회의 결론 1줄 · 늦은 데이터 n건 · 리서치 n건 · 브리핑 | 기존 패널을 '1줄 + ›'로. 누르면 해당 뷰 또는 펼침 |
| 아래 | 지수 격자 · 다가오는 일정 3 | 시세 띠 대체(정적, 폰 4칸·PC 8칸) | 기존 tape 데이터 |

- **HOME 에서 빼는 것**(해당 뷰로 이동, HOME 엔 입구 줄만): KR/US BREADTH·CLASSES 상세(→ 시장), MY PORTFOLIO 표(→ 내 계좌, 금액 노출도 줄어듦), EVENTS 서킷 통계·CALENDAR 달력 격자(→ 시장 › 일정 또는 접힘), LATEST RESEARCH 14줄(→ 리서치), PREMARKET·CLOSE 문장 블록(→ 리서치 › 브리핑).
- 목표 측정: 390px HOME 전체 8,838px → **≤ 1,700px(2장)**, ①②③이 첫 화면(844px) 안. 목업 실측 ①~③ 끝 ≈ 710px, 전체 1,372px.

### 3-3. 다른 주요 화면의 1순위 질문 · 첫 화면 · 접을 것
| 화면 | 히어로(1개) | 첫 화면에 남길 것 | 접을 것 |
|---|---|---|---|
| 내 계좌(my) | 이번 주 vs 코스피 %p | 10/28 스펙 그대로: 결론 1줄 · 규칙 계기판 2×2(기초 이후·스트레스·반도체·위반) · 관계 문장 · 원인 2줄 | 배분 막대(비율만) · 보유 표(토큰) · 성적표 14줄 · 입력·백업 |
| 시장 KR/US | 200일선 위 % | 판정 + 20/50/200 막대 3줄 | MACRO CONTEXT(매크로 탭과 중복) → 1줄 입구, TOSS LIVE·ACCUM·JAPAN 접힘, 신호 표 5개는 탭 칩 |
| 매크로 | 바람 점수 | 점수·주 요인·격차 | 공식 문단·①~⑤ 축(이미 접힘) |
| 운용회의 | 판정 1개(관망/진입) | 결론 카드·조건 충족 n/4 | 시나리오 표·데스크 발언 |
| 리서치 | 오늘 n건 | 증권가 한 줄·상위 5 | 나머지 목록(가상 스크롤) |

## 4. 디자인 토큰 초안 (front KB #9 형식 — `$value`·`$type`·`$description`, 별칭 `{group.name}`)
대비 열 = 그 글자색의 bg / surface / raised 위 대비비(WCAG 상대휘도 식, kb:front#6). 전부 4.5 이상.

```json
{
  "color": {
    "$type": "color",
    "dark": {
      "bg":         { "$value": "#000000", "$description": "화면 바탕" },
      "surface":    { "$value": "#0d0d0d", "$description": "패널" },
      "raised":     { "$value": "#171717", "$description": "겹(hover·게이지 바탕)" },
      "line":       { "$value": "#262626", "$description": "구분선" },
      "lineStrong": { "$value": "#3a3a3a", "$description": "배지 테두리·눈금" },
      "text":       { "$value": "#f2f2f2", "$description": "본문 18.8/17.4/16.0" },
      "text2":      { "$value": "#a3a3a3", "$description": "보조·라벨 8.3/7.7/7.1" },
      "text3":      { "$value": "#8f8f8f", "$description": "최저 글자색 6.5/6.0/5.5 — 이보다 어두운 글자 금지" },
      "accent":     { "$value": "#fb8b1e", "$description": "앰버 1색: 선택·초점·확인 필요만 8.8/8.2/7.5" },
      "onAccent":   { "$value": "#000000", "$description": "앰버 위 글자" },
      "up":         { "$value": "#26c165", "$description": "상승(국제 관례) 8.9/8.2/7.6" },
      "down":       { "$value": "#ff4d4d", "$description": "하락(국제 관례) 6.4/5.9/5.5" },
      "upKR":       { "$value": "{color.dark.down}", "$description": "한국 관례 선택 시 상승 = 빨강" },
      "downKR":     { "$value": "#4c8dff", "$description": "한국 관례 선택 시 하락 = 파랑 6.6/6.1/5.6" },
      "alarmBg":    { "$value": "#c81e1e", "$description": "경보 반전 블록 바탕(⛔ 한도 초과·위반 적용)" },
      "onAlarm":    { "$value": "#ffffff", "$description": "경보 블록 글자 5.74" }
    },
    "light": {
      "bg":         { "$value": "#ffffff" },
      "surface":    { "$value": "#f6f6f4" },
      "raised":     { "$value": "#ececea" },
      "line":       { "$value": "#d9d9d6" },
      "lineStrong": { "$value": "#b8b8b4" },
      "text":       { "$value": "#111111", "$description": "18.9/17.5/16.0" },
      "text2":      { "$value": "#5c5c5c", "$description": "6.7/6.2/5.7" },
      "text3":      { "$value": "#6b6b6b", "$description": "5.3/4.9/4.5" },
      "accent":     { "$value": "#a85300", "$description": "5.4/5.0/4.6" },
      "onAccent":   { "$value": "#ffffff" },
      "up":         { "$value": "#087a36", "$description": "5.5/5.0/4.6" },
      "down":       { "$value": "#c81e1e", "$description": "5.7/5.3/4.9" },
      "upKR":       { "$value": "{color.light.down}" },
      "downKR":     { "$value": "#1d5bd6", "$description": "6.0/5.5/5.0" },
      "alarmBg":    { "$value": "#c81e1e" },
      "onAlarm":    { "$value": "#ffffff" }
    }
  },
  "font": {
    "family": {
      "$type": "fontFamily",
      "text": { "$value": ["IBM Plex Sans KR", "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", "system-ui", "sans-serif"], "$description": "한글·본문·라벨. 자간 0" },
      "num":  { "$value": ["IBM Plex Mono", "ui-monospace", "SF Mono", "Menlo", "Consolas", "monospace"], "$description": "숫자만 있는 칸·티커·시각. tabular-nums" }
    },
    "size": {
      "$type": "dimension",
      "1": { "$value": "11px", "$description": "라벨·단위·시각 (현 --fs-1)" },
      "2": { "$value": "13px", "$description": "본문·표 (현 --fs-2 12.5px)" },
      "3": { "$value": "16px", "$description": "소제목·카드 값·판정 (현 --fs-3 14px)" },
      "4": { "$value": "28px", "$description": "히어로 — 화면당 1개 (현 --fs-4 17px, §6 2단계에서 전환)" }
    },
    "weight": { "$type": "fontWeight", "regular": { "$value": 400 }, "medium": { "$value": 500 }, "strong": { "$value": 600 } },
    "lineHeight": { "$type": "number", "tight": { "$value": 1.2 }, "body": { "$value": 1.5 } },
    "numeric": { "$type": "string", "default": { "$value": "tabular-nums lining-nums", "$description": "숫자 표기 기본값 — body 에 건다" } }
  },
  "space": {
    "$type": "dimension",
    "1": { "$value": "4px", "$description": "반 단계 — 글자·기호 옆만" },
    "2": { "$value": "8px" },
    "3": { "$value": "16px", "$description": "패널 안 여백·패널 사이(PC)" },
    "4": { "$value": "24px" },
    "5": { "$value": "32px" },
    "hit":   { "$value": "44px", "$description": "터치 기기 누름 대상 (10/24 결정)" },
    "hitPC": { "$value": "28px", "$description": "마우스 PC 누름 대상" }
  },
  "radius": {
    "$type": "dimension",
    "0": { "$value": "0px", "$description": "표·패널 기본" },
    "1": { "$value": "2px", "$description": "패널·입력·배지" },
    "2": { "$value": "4px", "$description": "버튼(최대)" }
  }
}
```
- CSS 대응: `--bg/--surface/--raised/--line/--line-strong/--text/--text-2/--text-3/--accent/--on-accent/--up/--down/--alarm-bg/--on-alarm`, `--font-text/--font-num`, `--fs-1~4`, `--s-1~5`, `--r-0~2`. 한국 관례는 `html[data-conv="kr"]` 가 `--up/--down` 두 값만 바꾼다(별칭 1단 — kb:front#9 ③).
- 현 이름과의 다리(1단계에서 별칭으로 유지): `--panel→--surface`, `--bg2/--bg3→--raised`, `--txt→--text`, `--muted→--text-2`, `--amber→--accent`, `--dn→--down`, `--mono→--font-num`. 엑셀 스킨(`html.xl`)은 light 값 위에 맑은 고딕·격자만 덧씌운다.

## 5. 목업
- 파일: `docs/uxui/2026-10-31_mockup_home.html`(단일 파일, 외부 의존 = Google Fonts 2종). 밝기 전환 버튼(`\`)·색 관례 전환(INTL↔KR)·`1`/`2` 키로 HOME/MY.
- 실측(같은 정의, 390/1440 · 다크/라이트·KR 관례 5장면): 가로 넘침 0 · 11px 미만 글자 0 · 24px 미만 누름 대상 0 · 글자 크기 종류 **4개**(11·13·16·28) · 웹폰트 로드 확인. HOME 390px 전체 1,372px(현 8,838px), 첫 화면 안 = 위험 상태·할 일·시장 3줄.
- 스크린샷(세션 임시 폴더, 저장소 밖): `mockup_mobile.png`·`mockup_desktop.png`(HOME), `mockup_mobile_my.png`·`mockup_desktop_my.png`, `mockup_desktop_light_kr.png`.
- 목업이 **일부러 안 한 것**: 실제 데이터 연결, 시장·리서치·데스크 화면, 엑셀 스킨, 명령줄 동작(모양만).

## 6. 구현 단계표 (프론트용 — 단계마다 잠금 1~2파일, 단계 끝에 UXUI 검수)
| 단계 | 바꾸는 것 | 영향 파일 | 테스트·검사 | 위험 | 되돌리기 |
|---|---|---|---|---|---|
| **1. 토큰·타이포만** | ① `<head>` 에 Google Fonts 링크(IBM Plex Mono·Sans KR, `display=swap`) ② `:root` 새 토큰 추가 + 현 이름은 별칭으로 유지(§4 다리) ③ `body` 를 `--font-text` + `tabular-nums`, 표 `td/th`·시세·`.n` 만 `--font-num` ④ 한글 들어가는 제목·라벨 자간 0(`.p h2`·`.brand`·`.tabs button`) ⑤ `--fs-2` 12.5→13, `--fs-3` 14→16(`--fs-4` 는 17 유지) ⑥ `.p h2` 색 앰버→`--text-2`(앰버 뜻 하나 줄이기) ⑦ 경보용 `--alarm-bg/--on-alarm` 추가(아직 안 씀) | `apps-script/Index.html`(`:root`·`body`·`.p h2`·`.tabs` 블록만), `scripts/font_tokens.py` STEPS 값 | `pytest tests/test_font_tokens.py tests/test_skin_tokens.py` · `python3 scripts/build_pages.py` · `python3 scripts/ui_smoke.py`(전체 35뷰 + check_head_clip) · `python3 scripts/skin_audit.py --skin def` 와 `--skin xl`(대비 미달 0 유지) · 390px 전후 잘림·줄바꿈·머리 높이 비교(10/24 교훈) | 낮음 — 레이아웃 불변. 위험은 글자 폭 변화로 인한 줄바꿈·잘림 → 위 비교로 잡음 | `Index.html` 1커밋 revert. 별칭 덕에 탭 파일은 안 건드림 |
| **2. HOME·MY 레이아웃** | ① HOME `homeView()` 재배치: 위험 상태 히어로(토큰 있을 때 `latest.json stats`) · 할 일(경보 반전 행) · 시장 3줄 · 입구 줄 · 지수 격자 ② BREADTH/CLASSES/MY PORTFOLIO/EVENTS/CALENDAR/RESEARCH 를 입구 줄로 ③ 달력 칩 5색 → `text-2` 점 + 글자 표기, 이모지 ⭐📌✓ → 글자 ④ MY 는 10/28 스펙 구현분(`#myfirst`)에 히어로·경보 블록만 덧씌움 ⑤ `--fs-4` 17→28 전환: 현 `--fs-4` 24곳을 `--fs-3` 로 재분류한 뒤(히어로만 `--fs-4`) | `apps-script/tab_home.html`, `apps-script/tab_my.html`(첫 화면 블록만), `Index.html`(공통 `.hero`·`.alarm`·`.rows` 클래스), `--fs-4` 쓰는 12파일(`grep -n fs-4 apps-script/*.html`) | 위 전부 + `pytest tests/test_my_first_screen.py` · ui_smoke `check_my_first_screen`·`check_fresh` · **새 check_home_first**: 390px 에서 히어로·할 일·시장 3줄 윗변 < 844px, HOME 전체 ≤ 1,700px, 렌더 이모지 ≤ 1(⛔) · 토큰 없는 상태·있는 상태 둘 다 | 중간 — HOME 이 가장 많이 보는 화면. 기존 패널을 지우지 않고 입구 줄 뒤에 '펼치기'로 남겨 정보 손실 0 | `tab_home.html` 커밋 revert(Index 공통 클래스는 남아도 무해) |
| **3. 탭 묶기 9→6** | ① `GROUPS` 재편(§3-1) — **뷰 키 유지**, 그룹 키만 추가·변경 ② 폰 하단 탭 5 + 머리 메뉴, 머리 48px(시세 띠 제거는 D4 결재 뒤) ③ 명령줄: 검색창이 화면 이름도 받게(`GROUPS` 이름 색인 추가) ④ 단축키 `1~6`·`/` ⑤ 텔레그램 딥링크·`LASTV`·`setView` 링크 회귀 확인 | `apps-script/Index.html`(머리·`GROUPS`·내비 JS), `scripts/ui_smoke.py`(`MIN_ALL` 35 유지 확인, 그룹 수 검사 추가) | ui_smoke 전체(뷰 35개 그대로 렌더) · `check_head_clip`·`check_xl`(엑셀 하단 시트 탭과 하단 내비 충돌) · skin_audit 두 스킨 · build_pages · 2.4.11 초점 가림(하단 고정 탭 아래로 초점 숨김 — kb:front#7 R4) | 중간 — 손에 익은 위치가 바뀜. 1주 사용 뒤 탐색 시간 재측정 | `GROUPS` 블록 + 머리 마크업 revert. 뷰 키를 안 바꿨으니 링크 깨짐 없음 |

- 순서 규칙: 단계마다 **겸이 1~2일 실사용 → UXUI 재측정(§0 정의) → 다음 단계**. 22~07시엔 화면 커밋·문턱 신설 안 함(kb:front R3).
- 공수 추정(프론트 1인, `[자체연구-검증전]`): 1단계 반나절, 2단계 1~1.5일, 3단계 1일.
- 하드코딩 색 95종·인라인 1,598곳 정리는 이 3단계에 안 넣었다(범위 폭발). 2단계에서 HOME·MY 두 파일 것만 토큰으로 옮기고, 나머지는 탭 하나씩 별도 장부.

## 7. 겸이 결정 항목
| # | 질문 | 선택지 | UXUI 권고 |
|---|---|---|---|
| D1 | **상승·하락 색 관례** | A 국제(상승 초록·하락 빨강, 블룸버그) · B 한국(상승 빨강·하락 파랑, 토스·증권사 앱) · C 설정 토글(기본 A) | **C(기본 B 도 가능)**. 토스 친구 기준이면 B 가 익숙하고, B 를 고르면 경보(빨강 블록)와 상승 빨강이 겹치므로 경보는 '반전 블록 + ⛔ + 글자'로 모양 구분을 반드시 유지 |
| D2 | **HOME 히어로 숫자** | A 구속 스트레스(비전 원칙 1 생존 우선) · B 오늘 할 일 수 · C 이번 주 vs 코스피 | **A** — MY 는 C 를 히어로로 둬 중복 회피 |
| D3 | **기본 밝기** | 다크 기본(블룸버그) · 시스템 따라감 | 다크 기본 + 라이트 토큰 제공(엑셀 스킨은 따로 유지) |
| D4 | **시세 띠(움직이는 줄)** | 없앰(HOME 지수 격자로) · 정지된 1줄로 유지 | 없앰 — 움직임은 장식 0 원칙 위반, 다른 탭에선 머리 높이만 먹음 |
| D5 | **상위 그룹 이름** | 한글(홈·내 계좌·시장·리서치·데스크·설정) · 영문(HOME·MY·MKT·RES·DESK·SYS) | 한글 — 영한 혼용이 진단 #10. 영문은 티커·지수 약어에만 |

## 8. 남는 한계·다음 측정
- '창피하지 않다'는 주관 판정이다. 대리 지표로 **핵심 숫자 탐색 시간**(겸이 5초 테스트: 위험 상태·할 일·KR 국면 세 질문) 을 2단계 전후로 잰다. 현재 기준선은 아직 없음(kb:uxui 격차).
- 목업은 가짜 데이터라 실제 문장 길이(데스크 결론 60자+)에서 줄바꿈이 더 생길 수 있다 → 2단계 검수에서 실데이터로 재측정.
- 웹폰트(약 2개 패밀리) 첫 로드 지연: `display=swap` 이라 글자는 바로 보이고 모양만 바뀜(CLS 위험 작음, kb:front#8 실험실 근사로 확인 예정).
