# 유지보수 라운드 — 2026-10-23(금) 21:10 주간 루프 (기준: STANDARD.md)

## 0. 요청 처리
처리→pb: req-maint-a38820c6 사이드카 알림 지연 — GitHub MCP 로 live 실행 39518753409 로그 직접 열람. 뉴스 시각 10:53 → `screener.events: 새 이벤트 1건` 10:55:11 → `텔레그램 전송 완료` 10:55:12 KST = **약 1분 12초~2분 12초 늦음**(뉴스 분 단위 기준, 거래소 실제 발동 시각 미확인이라 하한). 경로 = 뉴스(quotes 루프 5분 주기, 10:50:03 회차엔 기사 없음). 선물 프록시 = **기여 0**: event_watch 가 FUT 를 매 회차 '오래된 시세 — 알림 보류'(10/21 로그 83/83, 10/23 330/330). live 재시작 영향 = **없음**(구 실행 취소 11:04:32 → 새 루프 11:05:24, 발송 9분 뒤).
점검(오늘 변경 live·rebound·calendar_ev·committee): 최근 실행 전부 success — briefing 282(12:08Z)·reports 278(10:13Z, calendar 19:22·committee 19:23 산출)·screener 24(07:23Z)·live 53. 단 rebound 새 코드는 다음 14:25 슬롯(월), live.py 새 코드는 오늘 22:20 미장 루프가 첫 실전. 경고 1: reports 실행에서 calendar_ev FRED 4계열 각 60초 read timeout(4분 지연, 실패 아님).

## 1. 배우기
[교과서] Google *SRE Workbook* 5장 *Alerting on SLOs* — 알림 품질 = 정밀도·재현율·**감지 시간**·해제 시간. KB #5 로 추가: 감지 시간 = `sent_at` − 사건 시각. 차이: 교과서는 조건 성립부터 재지만 우리는 거래소 발동 시각 소스가 없어 뉴스 시각부터 → 과소 측정.

## 2. 고치기
① screener/main.py: main() 끝 `from .config import REPORT_DIR` 가 함수 전체를 지역 변수로 만들어 quotes 분기 `live.json events_checked_at` 쓰기가 10/21부터 매 5분 UnboundLocalError('이벤트 추적 실패', 10/23 58회) → 중복 import 제거. HOME '오늘 · HH:MM 확인'이 지난 값 보이던 거짓 표시(#4) 복구.
② 영구 계측: events.json 새 이벤트에 `seen_at`(잡은 시각)·`sent_at`(텔레그램 성공 시각). event_watch 보류 로그에 FUT `ts` 값 표시(원인 확인용).
테스트 3건(test_events_valid: 계측 2·REPORT_DIR 그림자 1) + 전체 pytest 통과.

## 3. 피어
금요일 — 주간 검증·감사와 겹쳐 생략.

## 4. 복기
틀림: 10/21·10/22 두 라운드 'Actions 로그 열람 불가'로 보류 → 왜: gh 실패만 보고 MCP 경로를 안 시도 → 다음부터: 로그 근거 요청은 MCP → gh → 상태 파일 세 경로를 다 시도한 뒤에만 '불가'.

## 5. 제안(주말 전 변경 금지 — 제안만)
뉴스 확인(events.check)을 event_watch 60초 루프로 옮기면 뉴스 경로 지연 상한 5분 → 약 1분. live.yml·event_watch 구조 변경이라 개발 앞 요청. FUT 보류 원인은 월요일 장중 로그 `FUT(ts=…)` 로 확정.

VOC: MCP 로 로그가 바로 열렸는데 이틀을 '불가'로 둔 건 내 탓. 선물 프록시가 출시(10/17) 뒤 한 번도 안 돈 걸 아무도 몰랐다 — 'N회 보류' 같은 조용한 실패를 신선도 배지처럼 화면에 올리는 게 다음 숙제.
요청→개발: event_watch FUT 시세가 장중 매 회차 '오래된 시세'로 보류(선물 프록시 0회 작동) — 월 장중 로그 `FUT(ts=…)` 보고 원인 수정 + 뉴스 확인을 60초 루프로 옮기는 안 검토(지연 상한 5분→1분)
