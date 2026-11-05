# 피어리뷰 — 개발 P0 저장소 용량(dev_p0_repo_size.md) 반대 3줄 (11/5 09:54)

> 출처(작성 주체): 피어리뷰 데스크 서브에이전트(PB 세션 호출) — 원문 무편집 요약, 파일 기록은 PB

## data-parquet-out
1. 용량 효과 과대 위험: §1.3은 "이력은 그대로"만 쓰고, git rm --cached 는 신규 증가(parquet분)만 멈추며 .git 1.9G(히스토리)는 안 줄어든다는 점, 줄이려면 filter-repo·force-push·전 클론 재생성이 따로 필요하다는 점을 명시하지 않음. 기대치 정정 필요.
2. 누적 6개 parquet 은 릴리스 덮어쓰기라 fin·screener·briefing 동시 실행 시 한 판 손실 가능(락·sha 비교 push 없음). hist_year 는 OPT_IN이라 수동 연구 스크립트 약 20개는 pull 없이 돌리면 깨지는데 부재 감지 가드가 없음.
3. 롤백은 "2/2 git revert"뿐 — revert 후 릴리스에서 갱신된 누적 6개가 git 사본과 갈라짐. 릴리스 자산 삭제·bootstrap 실패·manifest 불일치 절차 없음, 2/2 이후 실질 폴백은 주간 스냅샷뿐.
- 머지 순서 수정: 심 커밋(543301704)을 ①보다 먼저 → **반영 완료(main b5ddeacee, 09:50)**. cda8542a9 머지 시 live_branch.py(미연결) 동반 유입 고지. ③ 직전 fin·screener·briefing 스케줄 없는 창 확인, ③ 후 bootstrap 자산 sha·manifest 대조.

## data-live-branch
- 11/4 조건: 전수 표 충족 · 브랜치 상수 1곳 충족 · **live.yml만 쓰기 미충족**(decisions 쓰기 주체 4개) · 주 1회 초기화 충족 · 되돌림 숫자 충족 · 11/6 테스트 충족(심 반영 후).
- '쓰는 길 1개(put)' 판정: **조건부 수용** — get→merge_decisions→put fast-forward·재시도 ≤4회는 경합 안전(테스트 10개), inbox 구조 변경보다 위험 작음. 단 11/4 조건 완화이므로 겸이·CIO 결재 필요, 병행 단계 A 불일치 0 확인 후 B, freshness 분리·Pages get() 3곳 누락 방지 테스트를 B 진입 조건으로.

피어 사담: 용량 걱정 큰 날인데 .git 1.9G 는 오늘 머지로 안 줄어든다는 말을 겸이에게 먼저 해두는 게 좋겠어요, 기대치 관리도 리뷰 몫이라고 생각해요.
