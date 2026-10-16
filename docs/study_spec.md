# STUDY v3 — 콘텐츠 스키마 · 검증 · 복습(SRS) · Dev handoff

> 교육 데스크(교육) + 교육-후임(문제은행·복습 스케줄). 2026-10-16.
> 절차: **자문(SME) → 교육 설계(ID)**. 모듈 본문은 `docs/study_consults/answers/<desk>.md`를 1차 자료로 삼고, 모든 핵심 개념·공식·흔한 실수에 출처 태그를 붙인다. 자문에 없는 내용은 `[교육 보충]`으로 표시한다.
> 학습자 제약은 `consult:pb_learner#L1~L9`에서 왔다: 하루 1모듈 20분 상한(L5), 비유→숫자·표 4열 이하·수식 한 줄(L2·L5), 데스크와 대결하는 퀴즈·즉시 체크(L3), 중립 존댓말·설교 금지·등급 그대로(L7), 상황 판단 70%·규칙 조항 인용(L8), 첫 2주 우선 H2·R1·D1(L9).

## 1. 파일 구조

| 경로 | 역할 | 편집 |
|---|---|---|
| `content/study/index.json` | version·updated·title·intro·roadmap·tesat·`track_order` | 교육 |
| `content/study/track_<id>.json` | 트랙 1개 = `{id, title, badge, desc, modules[]}` | 교육 |
| `content/study/aptitude.json` | 인적성 문항(기존 그대로) | 교육 |
| `content/study/quiz_bank.json` | 문제은행(모듈당 ≥5, 상황 ≥70%) | 교육-후임 |
| `content/study/srs.json` | 복습 간격·선택 규칙·진행 저장 제안 | 교육-후임 |
| `content/study.json` | **빌드 산출물** — Code.gs `getStudyGuide` / `scripts/build_pages.py`가 읽는 단일 파일. 손으로 고치지 않는다 | `python scripts/study_content_check.py --build` |
| `scripts/study_content_check.py` | 검증(CI) + 빌드 + (1회성) 분할 | 교육 |
| `tests/test_study_content.py` | 검증기·빌드 동기화·터미널 호환 키·study_daily 선택 로직 | 교육 |
| `screener/study_daily.py` · `.github/workflows/study_daily.yml` | 평일 07:10 KST '오늘 공부' → `reports/study_daily.json` + 텔레그램 | 교육-후임 |

트랙 순서(`track_order`): `0 → R → H → A → D → M → P → T → Q → B → C`. 트랙 R·D·Q·H·M이 v3 신규(25모듈).

## 2. 모듈 스키마 (schema 3)

고정 섹션 순서(렌더 순서와 동일): `summary → analogy → terms → concepts → formulas → example → market_hook → pitfalls → quiz`.

| 필드 | 타입 | 규칙 |
|---|---|---|
| `schema` | 3 | 없으면 구형(2)으로 취급 |
| `id` | str | 전역 유일. `R1`·`D2`… |
| `track` | str | 파일의 트랙 id와 일치 |
| `title` | str | `주제 — 한 줄 훅` |
| `tags[]` | str | 자격시험·분야 |
| `level` | 1~3 | 난이도 ★ |
| `est_min` | int 5~20 | **20분 상한**(L5). `hours`는 빌드가 `est_min/60`으로 생성 |
| `weak` | bool | 약점 표시(선택) |
| `prereq[]` | id | 존재해야 하고 순환 금지 |
| `objectives[]` | 2~6 | 학습 목표 |
| `summary` / `analogy` | str | 한 줄 요약 / 생활 비유. 비유 끝에 출처 태그 권장 |
| `terms[{t,d}]` | | 용어 박스 |
| `concepts[]` | str | **각 항목 끝에 출처 태그 필수** `[consult:<desk>#q<n>]` `[kb:<desk>#<n>]` `[reports/studies/<id>]` 또는 `[교육 보충]`. 등급(A/B/C/F/검증전)은 문장 안에 그대로 |
| `formulas[{name, f, v[{s,m}], example, note, src}]` | | `f` = 한 줄 수식(라텍스 없음), `example` = 쉬운 숫자 예시, `src` = 출처 태그 필수 |
| `example` | str | 모듈 전체를 관통하는 숫자 예시 1개 |
| `market_hook{tab, fields[], keys[], read}` | | 터미널 어느 탭·어느 필드를 어떻게 읽나. `keys`는 Index.html `EDK` 칩 키(US10Y·ATMIV·PCR·BASIS…). 빌드가 구형 `today{keys,text}`를 생성 |
| `terminal_lookup` | str | '오늘 터미널에서 이 숫자 찾아보기' 1개(L7) |
| `rule_link` | str | '규칙 X조와의 연결' 한 줄(L9) |
| `pitfalls[]` | str | 흔한 실수. **출처 태그 필수**. 빌드가 구형 `mistakes`로 복사 |
| `quiz[]` | ≥3 | 아래 퀴즈 스키마 |
| `next_door` | str | '다음 질문으로 가는 문'(L2) |
| `srs{intervals}` | | 기본 `[1,3,7,21]` |
| `sources[]` | str | `consult:…`, `kb:…`, `reports/studies/…`, `docs/…`, `교육 보충` |

### 퀴즈 스키마 (모듈 `quiz[]`와 `quiz_bank.items[]` 공통)

```json
{"kind": "knowledge|situation", "q": "…", "choices": ["a","b","c","d"], "answer": 1, "why": "… [출처]",
 "duel": {"desk": "FRM", "pick": 1}, "rule_ref": "규칙 [11]"}
```
- `choices` 정확히 4개·서로 다름, `answer` 0~3. `kind` 필수. `duel` = 데스크 답(대결 형식, L3). `rule_ref`(선택) = 규칙 조항 인용 시 만점(L8).
- quiz_bank 추가 필드: `id`(`<module>-b<n>`), `module`, `difficulty` 1~3, `src[]`.
- 빌드가 구형 렌더용 `t`(지식/상황)·`a`(정답 문자열)를 덧붙인다.

### 구형 모듈(schema 2, 트랙 0·A·T·P·B·C 42개)
기존 필드 그대로(`hours`, `today`, `mistakes`, quiz `{t,q,a,why}`). 검증기는 필수 필드·quiz(choices가 있으면 4개·범위)·금지어만 본다. 데스크 교정은 `mistakes`/`today.text`에 출처 태그를 붙여 추가했다(0-3·0-4·0-6·A1·A3·A8).

## 3. 검증기 `scripts/study_content_check.py`

CI(`tests.yml` → `tests/test_study_content.py` → `scc.check_all`, 그리고 `study_daily.yml` 첫 단계)에서 실패 조건:
필수 필드 누락 · id 중복 · prereq 미존재/순환 · quiz choices ≠ 4 / answer 범위 밖 / kind 누락 · est_min > 20 · v3 concepts/formulas/pitfalls 출처 태그 없음 · sources 비어 있음/형식 오류 · 로드맵 order/steps에 없는 id · order에 빠진 모듈 · quiz_bank 모듈당 < 5 / 상황 비중 < 70% / 참조 모듈 없음 · srs intervals ≠ [1,3,7,21] · 금지어 · **`content/study.json`이 빌드 결과와 다름**.
빌드는 로드맵 `steps[].hours`·`total_hours`·`total_modules`를 다시 계산한다(2026-10-16: 42모듈 363h → 67모듈 369.6h; v3 25모듈 합계 약 6.6h).

## 4. 복습(SRS) — `content/study/srs.json`
간격 `[1, 3, 7, 21]`일. 통과(≥60%) → 다음 단계, 실패 → 1일로. 4단계 = 정착. 밀린 복습은 **가장 오래 밀린 1개만** 오늘로(벌점 없음). 하루 상한: 복습 1·새 모듈 1·퀴즈 1, 20분.
새 모듈 선택: `roadmap.first_two_weeks`(H2 R1 D1 H1 R2 H4 D2 R6 H6 M1)를 먼저 소진 → `roadmap.order`에서 미완료·선행 충족 첫 모듈.

**진행 저장 제안(미구현)**: 학습자가 GitHub 이슈 `study <id> done`(선택 `score=4/5`) / `study <id> review score=3/5` 생성 → `study_daily.yml`이 라벨 `study` 이슈를 읽어 `reports/study_progress.json` 갱신 후 닫음. 스키마: `{"updated","modules":{"<id>":{"done":[날짜],"stage":0..4,"next_due":날짜,"scores":[[날짜,비율]]}}}`. 현재 Index.html은 `localStorage mt_study_done`만 쓴다 — 두 저장소의 병합은 Dev handoff #4.

## 5. 교육-후임 산출물
- `quiz_bank.json`: 125문항(25모듈 × 5), 상황 판단 80%, 전 문항 `duel` 데스크 답·`src` 출처, 규칙 인용 문항 `rule_ref`.
- `screener/study_daily.py` + `study_daily.yml`(cron `10 22 * * 0-4` = 월~금 07:10 KST): 복습 1 + 새 모듈 1 + 퀴즈 1 + `reports/english/latest.json` 헤드라인 → `reports/study_daily.json`; 텔레그램 `📚 오늘 공부: <id> <제목> (<est_min>분) · 복습 <id> · 퀴즈 1` + 🔎 terminal_lookup + ❓ 퀴즈 + 🗞 영어 제목. 시크릿 없으면 조용히 생략. 네트워크 없음.

## 6. 자문 교정 반영 기록
- 파생 q16: 질의서의 'PCR F/검증전' 중 F는 오류 → 모듈 D2·A8에 '옵션 계열은 **검증전**(F는 표본 충족 후 효과 없음)'으로 명시.
- 채권 q9: 'ETF는 만기가 없다(상시 듀레이션)' 누락 → 0-6 mistakes·A3 today에 추가.
- 매크로 q9·q15: 터미널 `prev` 비교 ≠ 컨센서스 → 0-3·A1에 명시; 0-4 '밸브' 비유 보완(여수신 금리 비대칭).
- CIO: 운용회의 trigger·premortem.tell의 '5일 고점+외국인 2일'은 entry_signals F → M2·M3에 'tell로만, 게이트 아님'으로 표기(PB 검토 후 교체 예정).
- FRM 복기(VaR 2배 과소): R2·R3에 '구속 한도 = 스트레스 −15% + 테마 비중, VaR = 계기판(치유 2주)'로 반영.

## 7. Dev handoff — 일요일 Index.html 변경 요청 (개발 데스크)

읽기 전용으로 확인한 현재 코드: `apps-script/Index.html` 1136~1260행 `eduLoad / eduModule / eduView / eduProg`, 저장 `EDONE = eduGet('mt_study_done', {})`. 로더(`getStudyGuide` → `content/study.json`)는 **변경 불필요** — v3 빌드본이 구형 키를 모두 포함한다.

| # | 변경 | 위치·필드 | 상세 |
|---|---|---|---|
| 1 | **퀴즈 렌더 v3(대결 형식)** | `eduModule()` 확인문제 블록, `m.quiz[]` | `q.choices`가 있으면 4개 버튼(라디오)으로 렌더. 선택 후 정답(`q.answer`)·`q.why`·**`q.duel`("<desk>의 답: <choices[pick]>" vs "내 답")**·`q.rule_ref`를 표시. `choices`가 없으면 기존 `<details>`(t/q/a/why) 유지. 정오답은 `localStorage mt_quiz_log`에 `{id|module-idx, date, ok}`로 누적(통계 표시용, 내보내기 없음). 상황 문제(`kind:'situation'`)는 라벨 `[상황]`, 지식은 `[지식]`. |
| 2 | **SRS due 배지** | `eduModule()` summary 줄, 트랙 헤더 | `EDONE[id]`에 완료 **날짜**를 저장(현재 `true` → `{done:'YYYY-MM-DD', stage:0}`; 기존 `true` 값은 `done: 오늘`로 마이그레이션). `EDU.srs.intervals`(빌드본 최상위 `srs`)로 `next_due` 계산 → 지났으면 `<span class="tag r">복습 D+n</span>`, 오늘이면 `복습 오늘`. 로드맵 칩(`data-rchip`)에도 같은 색. 복습 완료 버튼 → stage+1·next_due 갱신. |
| 3 | **트랙 필터 + 기본 접힘 + '오늘 1개'** | `eduView()` 상단 버튼 영역(`data-trk`), 로드맵 패널 | 로드맵 패널은 `R.default_collapsed`가 true면 `<details>`로 접어서 시작하고, 상단에 **'오늘 1개' 카드**(복습 due 1 + `first_two_weeks`/order 순 다음 미완료 1 + 퀴즈 1 — `screener/study_daily.build`와 같은 규칙, 또는 `reports/study_daily.json`을 `getStudyDaily` getter로 읽어 표시; getter 추가는 Code.gs·build_pages.py 잠금 필요). 트랙 버튼은 토글 필터(선택 트랙만 표시, 다중 선택). `총 약 N시간` 표시는 기본 숨김(펼치면 표시, L5). |
| 4 | **진행 저장: 이슈 경로** | `eduModule()` 체크박스 옆 | 완료 체크 시 "이슈로 기록" 링크 생성: `https://github.com/<owner>/<repo>/issues/new?title=study%20<id>%20done&labels=study&body=score%3D…` (duel.py의 `pick` 이슈와 같은 패턴). 읽기: `reports/study_progress.json`(study_daily.yml이 생성 예정)을 선택적으로 읽어 `EDONE`과 병합(파일 날짜가 더 최신이면 우선). Code.gs getter 추가 필요(`getStudyProgress`) — 잠금 후 작업. |
| 5 | **v3 메타 표시** | `eduModule()` summary 줄·본문 | `m.est_min`이 있으면 `약 Nh` 대신 `N분`; `m.objectives` → '이 모듈이 끝나면' 리스트; `m.market_hook` → '오늘 시장에서' 제목 옆에 `[tab]` 배지와 `fields` 코드 표기; `m.terminal_lookup` → 모듈 끝 '🔎 오늘 터미널에서 찾기' 1줄; `m.rule_link` → '📏 규칙 연결' 1줄; `m.next_door` → '→ 다음 문' 링크(`data-goto`로 id 추출: 문장 안의 `[A-Z]\d+` 토큰). 출처 태그 `[consult:…]`·`[kb:…]`는 `esc()` 뒤 정규식으로 `<a href="docs/study_consults/answers/<desk>.md#q<n>">`·`docs/desk_kb/<desk>.md`로 링크(회색 소문자). |
| 6 | **quiz_bank 탭(선택)** | 새 뷰 `qb` 또는 `edu` 하단 | `content/study/quiz_bank.json` getter(`getStudyQuizBank`, 잠금 필요)로 읽어 모듈·난이도·kind 필터 + 랜덤 1문항 '데스크와 대결' 모드. 결과는 `mt_quiz_log`에 누적, 모듈별 정답률을 트랙 진행 바 옆에 표시. |

제약: 금액·보유 표시 없음(기존 설계 유지). 모바일 1열, 표 4열 이하, 수식 한 줄(L5). 모든 등급 문자열(A/B/C/F/검증전)은 그대로 노출(L7). 변경 전 `ops/locks.json`에 Index.html 잠금, 변경 후 `python scripts/check_functions.py`.
