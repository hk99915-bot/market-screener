# dev 주간 라운드 2026-10-30 (금 21:10)

드릴: dev-d1 검수 대기부터 닫는다 — 새 착수 금지 하루, '검수' 건마다 확인 기준 1줄(무엇이 돌면 완료인가)을 붙여 실측 가능한 것은 실측 후 완료, 실측 시점이 미래(예: 11/02 23:20 루프)면 날짜를 박아 둔다. 10/30 기준 개발 미완 32건(검수 4·대기 23·보류 3·진행 2, 마감 경과 4) — 10/23 44건에서 줄었음.

1. 배움: Google *SRE* 2016 목차 직접 확인 — 포스트모템 15장, SLO 4장, 에러 버짓 3장(sre.google/sre-book) → KB 10년차 줄의 [확인 필요: 장 번호] 해소. 우리 '복기'는 15장 기준으로 보면 타임라인·액션 오너/기한 칸이 빠져 있음(차이).
2. 고침: ① req-dev-cbd568fc 보강 — live 미장 시작 cron `20 13`(22:20)을 되살려 `20 14`(23:20)와 상시 공존, 판정은 in_window(ET). 오늘 밤(EDT, 22:30 개장) 22:20 시작 보호 + 3월 cron 되돌림 불필요(8ee30c28d). ② req-dev-7406791f — pre-push 'index.html 낡음' 검사(push 될 커밋 원본 빌드 ≠ 커밋된 index.html 이면 차단) + tests.yml paths 에 apps-script/**·index.html, 테스트 5개. 전체 pytest 1537 통과.
3. 피어(→프론트): pre-push 가 이제 apps-script/*.html 만 바꾸고 index.html 재생성·add 를 빠뜨린 push 를 막는다. 탭 작업 커밋에 index.html 을 같이 올리는 습관으로 — 막히면 `python3 scripts/build_pages.py && git add index.html`.
4. 복기: 오후 1차 서머타임 대응에서 cron 을 '교체'해 오늘 밤 여름 장 시작이 구 GAS 한 줄에만 걸렸음 → 적용~발효 사이 남은 장을 표로 계산 안 함 → 시각 변경은 두 시각 공존 + tz 판정 우선(KB 복기 10/30).
5. 처리→pb: req-dev-cbd568fc 보강·열어 둠(11/02 23:20 실측 뒤 닫음) · req-dev-7406791f 닫음 · req-dev-472431f7 (오후 닫힘 확인). 처리→hf: req-dev-2516a3d8 보드 screen-rev-accel 로 등록(마감 11/04).
점검(보고만): PB 미장 판단 예약 21:52 KST 고정(CRON_TZ=Asia/Seoul) — 프롬프트 마감 문구 '서머타임 22:15, 11/2 이후 23:15'는 맞음, 겨울엔 개장 1시간 38분 전 판단이 됨. HF 미장 회차는 CRON_TZ=America/New_York 09:15 라 자동 이동, 다만 프롬프트의 'live.json 22:20 KST~' 문구는 겨울엔 23:20.
VOC: GAS Scheduler.gs 23:20 은 오너 붙여넣기 전까지 배포 안 됨 — 오늘 밤은 cron 22:20 이 주 실행이라 붙여넣기는 급하지 않음(월요일 전이면 충분).
요청→front: 탭 커밋 시 index.html 동반(pre-push 차단 신설) 숙지.
