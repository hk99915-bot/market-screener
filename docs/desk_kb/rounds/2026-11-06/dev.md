# 개발 라운드 2026-11-06 (금 21:16)

- 고치기: ⚡ 급락 신호 소리 예외를 플래그로 준비 — env `TELEGRAM_RING_CRASH`(기본 OFF, briefing.yml `vars.TELEGRAM_RING_CRASH`) 일 때만 `alerts.crash_check` 가 `send_telegram(..., all_silent_exempt=True)` 로 TELEGRAM_ALL_SILENT 를 그 한 건만 건너뜀. 11/8 오너 결정 = 저장소 변수 한 줄, 코드 수정 없음. 테스트 tests/test_telegram_silent.py 3건.
- 고치기: hf_ideas 내러티브 초기에서 DART 해지·취소·철회 제외(req-dev-87313b7d) · pb.py 주석 '보유 <코드>' 일반화(req-dev-b420ff8d ①).
- 요청: 닫음 6(cbd568fc·fa0cd143·87313b7d·75f49f17·1e78960e·c07dc7f2) + 회신만 3(b420ff8d·ec8052de·94cc1eb0) / 남음 17.
- 피어→CIO: `cio_crash_def_dev_request.md` 변경 목록이 committee.crash_flag 만 다루고 15:05 ⚡ 텔레그램 경로(`screener/alerts.py::crash_check`, 장중 chg ≤ −4.5%)를 빠뜨림 — 결재되면 화면은 종가·⚡ 는 장중이라 정의가 둘로 갈린다. 목록에 alerts 한 줄 추가 권고.
- 복기: 10/31 스킬 테스트를 testpaths 밖에 둔 채 두 주가 지나 cio·frm 2건이 이미 빨갛다 → 왜: '나중에 편입'을 기한 없이 둠 → 다음부터: 새 테스트 위치는 생성 당일 CI 경로 편입 여부를 같이 결정.
- VOC: 승격 22건 중 절반이 화면 기능(tradeplan·STUDY·서고) — 30분 라운드로는 못 줄인다. 주 1회 개발 전용 2시간 블록이 필요.
요청→cio: 스킬 references 를 KB 와 맞춰 test_check_meeting 통과(req-cio-aebb9fcf)
