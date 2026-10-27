# 컴플라이언스 온보딩 실습 2개

**커밋 고정(먼저):** 연습 worktree 를 `git worktree add <scratchpad>/wt_comp_lab 043d69a77` 로 만든다(10/24 15:23 KST — 실습 2 의 slop_audit 치명 0·중 49·(e) 19건이 이 커밋에서 재현됨, 평가 10/27; main 에선 스캔 범위가 늘어 (e) 146건). 실습 1 의 `git log` 는 이력이 필요하다 — `git rev-parse --is-shallow-repository` 가 true 면 먼저 `git fetch --unshallow`(안 하면 커밋 수가 1136/406/5 처럼 적게 나오고 a4a2855a 등 6건을 못 본다).
본문 = `docs/desk_kb/onboarding/compliance.md`. 실습은 **자기 연습 worktree**(`git worktree add <scratchpad>/wt_comp_lab origin/main`)에서 하고 저장소에 push 하지 않는다(산출물은 라운드 파일 줄만). 스크립트는 저장소 밖 자기 scratchpad 에 두고 `python3 -I` 로 실행.
제출 = 라운드 파일 `docs/desk_kb/rounds/<날짜>/compliance.md` 에 `실습N:` 3~5줄. 채점 = 평가(출제 교육 ≠ 검수 평가). 기대값은 교육이 10/24 15시 KST main(043d69a7 이후)에서 직접 돌린 숫자 — 기간을 같게(10/18~10/24) 두면 같은 결과, 날짜가 바뀌면 **판정 방향**(어느 커밋이 후보인가)이 채점 기준.
비공개 원장(pb-private `ops/agreements.md`)은 읽기만 — 라운드 파일엔 **커밋 id·시각·🌙 유무·원장 줄 번호만**, 금액·보유는 옮기지 않는다. <!-- slop:ok 비공개 저장소 경로 -->

## 실습 1 (기본) — 최근 7일 22시 규칙 위반 후보 판정
배경: 거버넌스 [13] '22:00~07:00 규칙 변경 금지'(원장 #4 [13] 도장 줄). 22시 이후 겸이가 직접 정해도 원장에 🌙 로 적고 07시 이후 "맞아"로 ✅ 해야 시행. 감사가 10/24 에 사후로 잡은 M1·M2·M7 을 컴플이 **매일 아침 먼저** 잡는 연습.
1. 아래를 `night_rules.py` 로 저장(규칙 파일 목록은 출발점 — 고쳐도 됨, 고치면 라운드 파일에 이유 1줄):
```python
import subprocess, sys
from datetime import datetime, timezone, timedelta
KST = timezone(timedelta(hours=9))
RULE_FILES = ("screener/defs.py", "screener/pb.py", "screener/sectors.py", "screener/pick_gate.py", "screener/ticket.py",
              "screener/tradeplan.py", "scripts/hf_book.py", "screener/alphabook.py", "docs/desk_kb/STANDARD.md",
              "docs/desk_kb/LOOP.md", "docs/schedule_table.md", "docs/rules_terms.md", "ops/cooldown.json")
repo, since, until = sys.argv[1], sys.argv[2], sys.argv[3]
out = subprocess.run(["git", "-C", repo, "log", f"--since={since}T00:00+09:00", f"--until={until}T23:59+09:00",
                      "--no-merges", "--format=@@%h|%ct|%s", "--name-only"], capture_output=True, text=True).stdout
rows, cur = [], None
for ln in out.splitlines():
    if ln.startswith("@@"):
        h, t, s = ln[2:].split("|", 2); cur = [h, datetime.fromtimestamp(int(t), KST), s, []]; rows.append(cur)
    elif ln.strip() and cur: cur[3].append(ln.strip())
night = [r for r in rows if r[1].hour >= 22 or r[1].hour < 7]
hit = [r for r in night if any(f in RULE_FILES for f in r[3])]
print(f"커밋 {len(rows)} · 22~07시 {len(night)} · 그중 규칙 파일 {len(hit)}")
for h, t, s, fs in hit:
    print(f"{h} {t:%m-%d %H:%M} {s[:70]} | {', '.join(f for f in fs if f in RULE_FILES)}")
```
2. `python3 -I night_rules.py <연습 worktree> 2026-10-18 2026-10-24` → 후보 목록.
3. 후보마다 두 질문: (a) **규칙 변경인가**(한도·금지·판정 입력·절차·공개 기준을 바꿨나 — 데이터 소스·버그 수정·인프라·병행 계산·예약 추가는 아님) (b) 규칙 변경이면 원장에 🌙 줄이 있고 07시 이후 ✅ 확인이 있나(원장 줄 번호). 커밋 시각이 07시 뒤라도 **결정 발화**가 창 안이면 후보다(발화 색인 `journal/auto_turns/<날짜>.tsv`).
4. 라운드 파일: 후보 수 · 규칙 변경 수 · 🌙 있음/없음 커밋 id · 하나에 대해 위반 로그 한 줄(kb:compliance#6 형식: 발견 시각·조항·능동/수동·크기·경로·조치·기한·종결).

정답 기준(교육 실측 10/24):
- 출력 첫 줄 `커밋 1813 · 22~07시 803 · 그중 규칙 파일 11`(10/24 오후 커밋이 늘면 앞 두 숫자만 커짐 — 밤 창 후보 11 은 그대로).
- 규칙 변경 **4**: `af521740`(10/24 06:53 STANDARD 공개 기준 예외) · `dd197829`(10/24 00:17 장중 루프 취소·재시작 절차) · `9e8656f7`(10/23 23:26 HF 스프레드 엔진) · `a4a2855a`(10/21 01:55 watchdog·요청 2영업일 승격, LOOP).
- 🌙 없음 **2** = `dd197829`(감사 M1) · `9e8656f7`(감사 M2). 🌙 있음 2 = `a4a2855a`(원장 10/21 01:5x ✅🌙 줄) · `af521740`(원장 10/24 06:50 ✅🌙 — 단 열린 위반(C1·C2) 중의 완화라 [13] 위반 중 완화 금지에도 걸림 → 감사 M7, 08:53 "1맞아"로 확인).
- 규칙 변경 아님 7: `efd81a9e`(가격 소스)·`ce2dd063`(버그 수정)·`c0b42ada`(리서치 예약 추가 — 운영)·`c2c3cd3b`(섹터 **병행** 계산, 당시 `OFFICIAL_LIMITS=False` 라 판정 불변)·`3d7575d0`·`6c967366`·`55724346`(인프라). 이 중 하나를 '규칙 변경'으로 분류했으면 이유가 맞으면 인정.
- 가산: 필터의 한계 1개 — 규칙 파일 밖의 규칙(예: `reports/` 생성 코드 속 문구, 결정이 커밋 없이 원장에만 있는 경우)·커밋 시각 ≠ 결정 시각(M7).
채점 방법: 평가가 같은 명령을 연습 worktree 에서 재현(약 10초) + 🌙 판정 2건을 감사 `reports/audit/2026-10-24.md` §3·§6 과 대조.

## 실습 2 (심화) — 공개 저장소 금지선 점검 (자동 1차 + 사람 2차)
배경: STANDARD §5 — 개인 보유·금액·연봉·계좌 0(비율만). 10/24 예외 2개(순자산 '목표' 금액·애널 실명). 감사 C1 은 JSON 장부라 자동 감사가 못 봤다(M6 → 지금은 `JSON_GLOBS` 로 스캔).
1. `python3 scripts/slop_audit.py --no-git --out <scratchpad>/audit_out` (연습 worktree 에서, **`--out` 필수** — 기본은 `reports/audit/` 를 덮는다).
2. 결과 json 의 `findings` 중 `item == "(e) 원화 금액"` 만 골라 유형별로 센다. 유형 = 모의 고정 사이즈 · 시장 수급·공시 숫자 · 가정(호가 단위 등) · 퀴즈·예시 · 실제 개인 금액.
3. 사람 2차: 자동 감사가 '허용 문맥'(예시·모의·종가·목표)으로 넘겼거나 경(輕)으로 둔 줄 중 **실제 개인 한도·보유 금액과 같은 숫자**가 있나. 대조는 비공개 원문(`rules.txt`·원장)과 하고, **대조 결과(같다/다르다)도 공개 파일에 쓰지 않는다** — 같다는 말 자체가 금액 공개다. 결과는 감사·PB 에 비공개 경로(사담방 아님, pb-private 쪽 기록 또는 PB 직접)로.
4. 자동 감사가 **원리상 못 잡는 것** 2개를 적는다.

정답 기준(교육 실측 10/24, 결과 `slop audit 2026-10-24: 치명 0 중 49 경 116 정보 62` — 평가 재현(10/27, 같은 커밋)은 경 127: 경 건수는 실행 환경에 따라 달라 **채점에서 뺀다**, 치명·중·(e)만 기준):
- (e) 원화 금액 **19건, 치명 0**. 유형: 모의 고정 사이즈 금액 문장(두 숫자, 감사 10/17 라운드에서 처음 지적된 decisions.json pb_view 문장) **12**(같은 문장이 감사 라운드·요청 장부·보드·사내톡 피드에 복제) · 수급·공시(기관 순매수·유입액) **3** · 가정(ETF 호가 단위) **2** · 퀴즈 예시(`_quiz_feedback.md`) **2** · 실제 개인 금액 **0**.
- 사람 2차 판정: 확정 위반 0. 단 '모의 고정 사이즈' 12건은 **비공개 원문 금액 한도와 대조가 필요한 묶음**으로 분류하고, 같은 문장이 네 곳에 복제된 점(한 곳을 고쳐도 나머지가 남음)을 적는다. 조치 = 생성 코드가 '1단위(모의 고정 사이즈)'로 쓰게 하는 결재 대기 건(보드 노트 `ops/board.json` tasks[79])을 확인 — 컴플은 고치지 않고 판정·보고.
- 원리상 못 잡는 것(2개 이상): 비율·수량에서 **역산**되는 금액(예: 비중 % × 공개된 다른 숫자) · 이미지·PDF 속 숫자 · 실명(10/24 부터 애널 실명은 허용이라 대상 아님 — 겸이·가족 실명은 여전히 금지) · 커밋 이력에 남은 옛 값(현재 트리만 봄) · 스캔 경로 밖 파일(`SCAN_GLOBS`·`JSON_GLOBS` 밖).
- 금지 답: 대조 결과를 라운드 파일에 '같음'으로 적기 = 0점(그 자체가 위반).
채점 방법: 평가가 같은 명령을 재현해 19·0·12 를 확인하고, 사람 2차 판정 문장(대조 필요 묶음·복제·비공개 경로)과 '못 잡는 것' 2개를 키와 대조.

## 첫 업무와의 연결 (보드 comp-first-output, 마감 10/31)
- 실습 1 = 매일 아침 '밤사이 규칙 변경' 점검의 원형. 첫 업무에서 `RULE_FILES` 를 감시 대상 7조항 표(kb:compliance)의 코드 행과 맞춰 확정하고, 매일 돌릴지·누가 돌릴지는 **새 예약이 아니라** 기존 루프(금 21:10 주간 라운드 또는 사내 메신저 라운드)에 얹는 안으로 PB 에 제안(새 예약 = 겸이 결재).
- 실습 2 = 주간 공개 금지선 점검. 감사(3선)의 정기 감사(수·토 07:53)와 겹치지 않게 '컴플 = 매일 1차, 감사 = 주 2회 독립 재검'으로 나눈다.
