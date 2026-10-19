# US heatmap automatic updates (GPT, 2026-10-20)

- GitHub Actions `.github/workflows/heatmap.yml`: UTC 13–21시 12분/42분, NYSE 달력으로 정규장부터 마감 후30분까지만 수집. 장중 목표30분, 마감 후1회. GitHub 예약은 지연될 수 있다.
- America/New_York 달력으로 DST·휴장·조기폐장 반영. 한국 날짜와 미국 거래일은 별도 표시.
- `reports/heatmap_US.json`만 자동 갱신. Yahoo 일봉의 진행 중 종가와 직전 종가로 1D 계산, 지연 가능. 당일 자료 없는 종목은 제외; 80% 미만 수집 시 실패하고 기존 게시 자료 유지.
- `peers_US.json`은 기존 마감 스크리너 소유. 5D/20D·섹터·칸 크기는 마감 기준이며, 미장1D만 새 피드 적용.
- 열린 히트맵의 미장 탭은 1분마다 새 파일 확인. 데이터 기준일·수집 KST·표본 수 표시. 수집 실패 시 최신 정상 자료와 그 시각을 유지한다.
- GPT 토큰 사용 없음. 실주문·텔레그램 발송 없음. 초기 수동 검증은 `python -m screener.heatmap --once`.
