# analyst 라운드 2026-10-23 (겸이 22시대 지시: 외부 자료 '링크만' 금지)

1. 배움: 외부 자료 다이제스트 세 칸(내용·뷰·우리 해석) — STANDARD §4 에 1줄 추가(10/23 겸이 근거). 재료 없으면 '요약 재료 없음' 표시, 원문 대량 복제 금지. `[규정-내부]`
2. 고침: reports/views/digest.json 신설(6건) → research_synthesis.digest_card(세 칸 중 하나라도 비면 안 내보냄) → 공공 리포트·지정학 뷰 카드에 펼침(tab_research.html) · ui_smoke '요약펼침' · Jiang RSS media:description 발췌(desc ≤500자) 수집. 테스트 tests/test_public_reports.py 3건. 롤백 = 이 커밋 revert(카드는 digest 없으면 '아직 없음'만).
3. 피어(퀀트): study_ktb_vs_ust.py 한은 기준금리 표가 2025-05 2.50% 에서 멈춤 — 10/22 결정문은 3.00%·'두 차례 인상'. ISA 채권 슬리브 연구의 UST-H·인상기 레짐이 틀어짐 → req-quant-00175d13.
4. 복기: 10/21 공공 리포트 트래커를 만들며 "Jiang 은 제목만 추적"을 원칙처럼 KB 에 적었다 — 틀림. 제목만으론 겸이가 판단 못 함. 왜: 저작권·검증 부담을 '요약 안 함'으로 피했다. 다음부터: 요약은 하되 등급·재료 출처·'재료 없음'을 정직하게.
5. 첫 digest 결과: 6건 중 내용 요약 가능한 건 한은 통화정책방향 1건뿐(RSS 500자). 나머지 5건은 '재료 없음' — 이 컨테이너에서 youtube·bok·fss·mofe 모두 차단, 웹검색도 미색인.

## 매일 요약 루틴 — 예약 작업 프롬프트 초안 (PB 가 생성, 제안: 평일 07:41 KST, 03:30 수집 뒤)
```
너는 market-screener 애널 데스크야. docs/desk_kb/analyst.md·STANDARD.md §4 를 읽고 worktree 에서 일해.
1) reports/public_reports.json·reports/views/jiang.json 에서 digest.json 에 id 가 없는 항목 중 최근 7일, 공공 최대 5건·영상 최대 2건 고른다
   (운용 함의 낮은 감독기관 홍보성 보도는 1줄로 닫음). 이미 '재료없음'인 항목은 재료가 새로 생겼을 때만 다시 쓴다.
2) 재료 = public_reports summary · jiang desc · (개발 req-dev-d08bcc86 완료 후) data_store pull --groups digest_src 의 자막/본문 발췌 · 웹검색 공개 요약.
3) 항목마다 {id,src,date,title,link,status,summary[3~5줄 핵심 주장·숫자],view(입장·근거·과거 예측 적중),our_take(우리 포트·운용회의 함의),
   grade(요약 등급·해석 등급),material(재료 출처·기준일),by:'애널',written_at}. 재료 없으면 summary[0]='요약 재료 없음 — <무엇> 수집 후', 지어내지 말 것.
   원문 복제 금지(짧은 인용만). 매매 지시 금지. Jiang 의 기한 있는 명시 예측은 jiang_predictions.json 후보로 검증 데스크에 ask.
4) python3 -c 로 research_synthesis.digest_card 를 reports/research_synthesis.json 'digest' 에 반영(또는 다음 03:30 재생성 대기),
   pytest tests/test_public_reports.py · board --check · check_rules_terms → 커밋 'analyst: digest <날짜> N건' push.
5) PB 에게 5줄: 새 요약 제목·한 줄씩, 재료 없음 건수, 우리 해석 중 운용회의 안건 후보.
```

VOC: 요약 재료가 없다. 자막·본문이 들어오기 전까지 digest 는 '재료 없음' 목록이고, 그건 겸이가 원한 게 아니다 — 개발 마감 10/30 이 사실상 이 기준의 시행일.
현재 상태: digest 6건(ok 1·재료없음 5) · 카드 펼침 반영(research_synthesis.json 수동 주입, 내일 03:30 부터 자동) · 자막 수집은 개발 대기.
요청→개발: 자막·발간물 본문 → 데이터 릴리스 digest_src (req-dev-d08bcc86, 10/30) · 요청→퀀트: 한은 기준금리 표 갱신 (req-quant-00175d13, 10/27)
