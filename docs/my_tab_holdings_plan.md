# MY 탭 보유 관리 방안 (개발 데스크 · 2026-10-17 · 조사·설계만, 코드 변경 없음)

> 요청(겸이, 무편집): "MY 탭 보유를 어떤 방식으로 보고 있어? 브라우저저장이 직관적인데, 관리방법 찾기"
> 근거: 정합성 감사 `docs/peer_reviews/2026-10-17_integrity_audit.md`(→ docs/audits/ 이동 예정) B-16 · C-01 · C-03 · C-05 · P0-4.
> 이 문서에는 개인 수량·금액·평단을 적지 않는다. 비공개 쪽 파일은 `pb:` 접두로 경로만 적는다.

## 1. 현재 구조 (실제 코드 확인, 2026-10-17 main)

**한 줄 요약:** 화면이 실제로 읽는 건 브라우저 localStorage `mt_holdings_v1` 이고, 토큰이 있으면 MY 탭을 열 때 `pb:holdings.txt` 를 받아 그 값을 **확인 없이 덮어쓴다**. 08:50·16:20·장중 감시는 이와 별개로 Actions 시크릿 `MY_HOLDINGS` 를 읽는다. 감사 B-16 의 "어느 쪽이 현행?" 답은 **둘 다 현행** — localStorage = 작업본, holdings.txt = 토큰 있을 때의 원본.

화면 소스는 `apps-script/tab_my.html` (루트 `index.html` 은 `scripts/build_pages.py` 생성본 — 같은 코드가 index.html:739-880 에 인라인).

| 무엇 | 위치 (파일:행) | 내용 |
|---|---|---|
| 보유 텍스트 키 | apps-script/tab_my.html:6 | `MYK='mt_holdings_v1'` |
| 읽기/쓰기 | tab_my.html:18-19 | `myLoad()`/`mySave()` = localStorage get/set. 저장 시각·출처 메타 없음 |
| 수동 입력 저장 | tab_my.html:124 | '분석' 버튼 → `mySave(textarea)` |
| 비공개 원본 동기화 | tab_my.html:56-57 | `PBSRC=…/repos/hk99915-bot/pb-private/contents/holdings.txt` (GitHub API, fine-grained PAT) |
| 토큰 보관 | tab_my.html:57-58 · :61-71 | `mt_gh_tok`(localStorage 또는 sessionStorage) · `mt_gh_enc`(PIN 으로 AES-GCM 암호화, PBKDF2 25만 회) |
| 덮어쓰기 | tab_my.html:74-80 | `mySync` → 주석 줄 제거(`myClean`, :72) 후 `mySave` + textarea 교체. **로컬 수정분과 비교·확인 없음** |
| 자동 동기화 | tab_my.html:133 | 토큰이 있으면 MY 탭 첫 진입 때 1회 자동 `mySync` |
| 원장 파일 읽기/쓰기 | tab_my.html:153 · :84-85 · :111-123 | `PBAPI` 로 analysis·journal·history 읽기, 회고는 journal PUT(쓰기 권한 없으면 이슈 창) |
| 다른 탭 소비자 | tab_home.html:5,8-9,27 · tab_duel.html:106 | 같은 `myLoad()` 텍스트를 홈 요약·대결 탭이 재사용 |
| 표시 모드 | tab_my.html:14-16 | `mt_ratio_only` 기본 ON(금액 숨김) |
| 서버 쪽(별개) | screener/pb.py:503,609 · alerts.py:159 · event_watch.py:417 · .github/workflows/live.yml:58 | env `MY_HOLDINGS` (시크릿). 화면과 연결 없음 |

**결론: holdings.txt 토큰 방식은 남아 있고 동작한다.** 문서 쪽 정리 필요: `ops/README.md:93`·`pb:ops/my_holdings_format.md:3` 은 맞고, `pb:ops/HANDOFF.md:58` 'MY 탭 보유는 브라우저 localStorage' 는 절반만 맞음(작업본 설명). → B-16 정정 문구 = "작업본은 브라우저, 토큰 연결 시 holdings.txt 로 덮어씀".

### 지금 구조의 빈틈

1. **조용한 덮어쓰기** — 화면에서 고친 뒤 holdings.txt 가 안 바뀐 상태로 다시 열면 로컬 수정이 사라진다(:133 자동 동기화). 반대로 토큰 없는 기기는 holdings.txt 가 바뀌어도 모른다.
2. **휘발** — 브라우저 데이터 삭제·시크릿 창·기기 변경·iOS 사파리 ITP(7일 미방문 사이트 스크립트 저장소 삭제 가능) 때 `mt_holdings_v1` 이 사라지고, 백업·최근 저장 시각 표시가 없다.
3. **세 갈래 불일치를 아무도 모름** — 브라우저 작업본 ↔ `pb:holdings.txt` ↔ 시크릿 `MY_HOLDINGS`. 감사 C-03(시크릿 낡음)과 같은 모양이 화면 쪽에도 있다.
4. **ISA 출처** — 화면은 holdings.txt 의 `## ISA` 블록만 본다. `pb:isa_holdings.txt` 와 다르면 모름(감사 C-05, P1-9 에서 단일화 예정).

## 2. 방안 비교

| | (a) 내보내기/가져오기 + 백업 배지 | (b) holdings.txt 형식 내보내기 + '원장과 다름' 비교 | (c) 기기 간 동기화 |
|---|---|---|---|
| 하는 일 | 버튼: 복사(클립보드)·`.txt`/`.json` 다운로드 / 붙여넣기·파일 가져오기(적용 전 미리보기). 배지 '마지막 백업 N일 전', 백업 후 수정되면 '백업 안 된 수정 있음' | 내보내기 = holdings.txt 와 같은 텍스트(겸이가 PB에게 전달 → PB가 pb-private 반영). 비교 = 브라우저 안에서 정규화 텍스트 해시·줄 차이 계산 → 배지 '원장과 같음 / 다름(N줄) / 미확인(토큰 없음)'. 동기화가 로컬 수정분을 덮으려 하면 '원장으로 덮기 / 내 것 유지 / 차이 보기' 확인 | 각 기기에 읽기 전용 토큰(지금 방식) / QR·URL 조각(#) 1회 전송 / 쓰기 토큰으로 holdings.txt 직접 PUT / 비밀 gist |
| 휘발 대응 | 백업 파일로 복구. 배지가 백업을 재촉 | 원장(holdings.txt)이 백업 역할. 토큰만 있으면 어느 기기든 복구 | 토큰 방식은 복구 겸 동기화 |
| 원장 정합(C-01) | 개선 없음(파일이 하나 더 생김) | 화면이 원장과 어긋나면 바로 보임. 원장 갱신 경로는 PB 한 곳 유지 | 쓰기 PUT 은 원장 파생 규칙(C-01: 체결→unsettled→holdings)을 우회 → 비추천 |
| 기기 간 | 수동 파일 이동 | 토큰 있는 기기 = 자동, 없는 기기 = 내보내기 텍스트 붙여넣기 | 크롬·사파리 계정 동기화는 localStorage 를 옮기지 않음 → 브라우저 기능으로는 불가 |
| 겸이 수고 | 주 1회 버튼 | 차이 배지 뜰 때 PB에게 전달 | 기기마다 토큰 1회 |
| 구현 크기 | tab_my.html +40줄 | tab_my.html +70줄 (a 포함하면 +100줄) | 토큰: 0줄(이미 있음) · QR: +60줄+라이브러리 · PUT: +40줄 |

### 공개 저장소 규칙 판정 (개인 보유·금액 금지, 비율만)

| 안 | 판정 | 이유 |
|---|---|---|
| (a) 파일·클립보드 | **통과** | 데이터가 브라우저→겸이 기기로만 이동. 공개 서버·저장소 경유 없음. 주의: 다운로드 파일·클립보드를 메신저·텔레그램에 붙이지 않기(화면에 한 줄 경고) |
| (b) 브라우저 안 비교 | **통과** | 원장 텍스트는 토큰으로 비공개 저장소에서 직접 받고, 해시·차이 계산은 브라우저 메모리에서만. 공개 쪽에 아무것도 안 씀 |
| (b′) 원장 해시를 공개 저장소에 두기 | **불가(비추천)** | 수량·금액 자체는 아니지만 ① 보유 텍스트는 후보가 좁아 '이 보유가 맞나' 대입 확인이 가능 ② 해시가 바뀐 커밋 시각 = 매매 시점 노출. 소금(salt)을 비공개에 두면 그 소금을 읽는 데 다시 토큰이 필요 → 공개 해시의 이점이 사라짐. 해시는 비공개 `pb:scripts/secret_registry.json`(secrets_gen.py P0-4, 개발 중) 안에만 |
| (c) 읽기 토큰 | 통과 | 지금 방식. 토큰은 pb-private 한정·Contents Read-only·만료일 필수 |
| (c) QR/URL 조각 | 조건부 | `#` 뒤는 서버로 안 가지만 브라우저 방문 기록·스크린샷에 남음 → 1회용, 기록 삭제 안내 필요. 효용 대비 위험 커서 보류 |
| (c) 쓰기 토큰 PUT | 비추천 | 휴대폰 브라우저에 쓰기 토큰 보관 + 원장 파생 규칙 우회 |
| (c) 비밀 gist | **불가** | 비밀 gist 는 URL 만 알면 누구나 열람 — 비공개 아님 |

## 3. 추천: (a)+(b) 합친 '브라우저 주 + 원장 대조'

브라우저 작업본을 주(主)로 두고(겸이 말대로 직관적), **원장은 대조·복구용**으로만 쓴다. 쓰기는 하지 않는다.

1. **메타 키 추가** `mt_holdings_meta` = `{savedAt, source:'manual'|'sync'|'import', digest, syncedDigest, syncedAt, exportedAt}` (값 없이 시각·해시만).
2. **정규화 해시** — `myClean`(주석 제거, `## ISA` 유지, 빈 줄 제거) 후 줄 끝 공백 제거 → SHA-256 앞 16자 (`crypto.subtle.digest`). `pb:scripts/secrets_gen.py` `digest()` 와 같은 규칙으로 맞춰(빈 줄 처리 1곳 합의 필요) 화면 해시 = 시크릿 등록 해시를 눈으로 대조 가능 → C-03 의 '시크릿 낡음'도 화면에서 같이 보임.
3. **동기화 확인** — `mySync`(:74-80): 원장 해시 ≠ 로컬 해시 **이고** 로컬 해시 ≠ 마지막 동기화 해시(=로컬에서 고친 게 있음)면 덮지 않고 '원장으로 덮기 / 내 것 유지 / 차이 보기'. 차이는 줄 단위(종목 키 기준)로 브라우저 안에서만 표시.
4. **배지 2개** (MY 탭 상단 `#mysync` 옆) — '원장: 같음 · 다름 N줄 · 미확인' / '백업: N일 전 · 백업 후 수정 있음'. 7일 넘거나 수정 후 미백업이면 주황.
5. **내보내기/가져오기** — '복사'(holdings.txt 형식 텍스트) · '파일로 저장'(`holdings_YYYYMMDD.txt`) · '가져오기'(붙여넣기/파일 → 미리보기·차이 → 적용). 경고 문구: "개인 값 — 텔레그램·공개 저장소에 붙이지 말 것, PB에게는 대화로".
6. **홈 탭** — `tab_home.html` 요약 카드에 '원장과 다름' 한 줄(선택).
7. 하지 않는 것: holdings.txt 쓰기(PUT), 공개 저장소에 해시·시각 기록, 서버 전송.

### 구현 범위 (대략)

| 파일 | 변경 | 줄 수 |
|---|---|---|
| apps-script/tab_my.html | 메타·해시·차이·확인창·배지·내보내기/가져오기, `mySync` 분기 | +90~110 |
| apps-script/tab_home.html | '원장과 다름' 한 줄 (선택) | +5 |
| index.html | `python scripts/build_pages.py` 재생성 | 생성 |
| tests/test_rules_gaps.py (또는 새 tests/test_my_backup.py) | 공개 전송 없음(fetch 대상이 pb-private API 뿐, POST/PUT 은 journal 만)·메타에 수량 없음·해시 규칙이 secrets_gen 과 같음(고정 예문 비교) | +30~40 |
| ops/README.md:93 · pb:ops/my_holdings_format.md:3 · pb:ops/HANDOFF.md:58 | B-16 정정 문구(작업본=브라우저, 토큰 시 원장으로 대조) | 각 1~2줄 |

검사: `pytest` · `scripts/ui_smoke.py` · `scripts/check_functions.py` · `scripts/board.py --check`.

### 구현 시점

- 변경 대상은 Pages 화면(`apps-script/` → `index.html`)뿐. `live.yml`·cron·`screener/` 판정 경로·시크릿을 건드리지 않으므로 **'월 장 전 라이브 루프·cron 변경 금지' 범위 밖 → 장 전 구현 가능**.
- 다만 push 마다 Pages 가 재배포되고 MY 탭은 장중에 보는 화면이라, 깨지면 장중 화면이 깨진다. 권장 창: **토(10/17)·일 18:00 동결 전**(주말 원칙 추천안 🗳️ 기준) 또는 **월 장 마감 후**. 월 09:00~15:30 배포 금지.
- 해시 규칙 맞추기(2번)는 `pb:scripts/secrets_gen.py` 가 다른 개발 에이전트 작업 중이므로 그 작업 커밋 뒤에 한다(그 파일·`ops/board.json` 은 이번에 안 건드림).

## 4. 겸이가 할 일

1. 추천안(브라우저 주 + 원장 대조, 쓰기 없음) 승인 여부만 정해줘.
2. 지금 당장(구현 전): 쓰는 기기마다 MY 탭 입력칸 텍스트를 한 번 복사해서 개인 메모 등 비공개 장소에 보관 — 브라우저 데이터 지우면 사라짐.
3. 폰·집 PC 각각 읽기 전용 토큰(pb-private 한정 · Contents Read-only · 만료일 지정). 회사 PC 는 'PIN 잠금' 또는 '이 창에서만'.
4. 구현 후 배지가 '원장과 다름'이면 '복사' → PB에게 대화로 전달 → PB가 체결 기록 확인 후 holdings.txt 반영(C-01 경로 유지) → 시크릿 `MY_HOLDINGS` 는 secrets_gen 생성본으로 갱신.
