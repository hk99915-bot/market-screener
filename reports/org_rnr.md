{
 "_doc": "🗽 FREEMAN 탭 '📋 R&R' 데이터(tab_freeman freeRnr, getMarkdown('org_rnr') — Code.gs raw_('reports/org_rnr.md')·Pages SHIM 같은 경로, 새 getter 없음; 내부판 전용 화면). 원천 = docs/desk_kb/ORG.md + 각 데스크 KB 경계 줄(src) + 11/3 겸이 R&R 경계 결정. 줄 고침은 운영(ORG 소유)·각 데스크가 이 파일에서. 화면은 이 파일만 읽음(하드코딩 금지). 개인 금액·보유 금지(공개 파일).",
 "asof": "2026-11-03",
 "status": "11/3 경계 반영(데이터엔지니어 신설 반영) — 운영·각 데스크 검수 전",
 "principle": "본부는 묶음(상하 아님) — 데스크 간은 요청만, 충돌은 양쪽 기록 후 겸이 결정. 결정은 겸이, 데스크는 추천 + 뒤집힐 조건까지.",
 "layers": [
  {
   "layer": "프론트",
   "what": "판단·운용 = 1선",
   "note": "결론은 미들 점검 없이 결재로 안 감"
  },
  {
   "layer": "미들",
   "what": "통제·측정 = 2선",
   "note": "리스크본부 넷 + PM(성과·사용량) + 검증"
  },
  {
   "layer": "백",
   "what": "처리·기록·인프라",
   "note": "프론트 개발의 '프론트'는 화면 쪽이라는 뜻, 1선 아님"
  },
  {
   "layer": "3선",
   "what": "독립(내부감사)",
   "note": "감사·피어리뷰 + 검증의 독립 재현"
  },
  {
   "layer": "지원",
   "what": "연수·코칭",
   "note": "교육·평가·LIFE"
  }
 ],
 "risk_split": [
  {
   "key": "frm",
   "what": "설계 — 시나리오·VaR·한도 수치"
  },
  {
   "key": "posrisk",
   "what": "사용률 — 그 한도 대비 매일 측정"
  },
  {
   "key": "compliance",
   "what": "판정 — 결재 조항 준수·위반 로그"
  },
  {
   "key": "behavior",
   "what": "사람 — 행동 진단"
  }
 ],
 "bureaus": [
  "창구",
  "투자전략",
  "리서치",
  "리스크",
  "운영",
  "교육",
  "생활",
  "검증실"
 ],
 "desks": [
  {
   "key": "pb",
   "bureau": "창구",
   "layer": "프론트",
   "does": "겸이 질문 창구 — 데스크 산출물 종합·추천, 데스크 호출·VOC 무편집 인용",
   "dont": "데스크 발언 대필·추정 VOC, 결정(겸이 결재)",
   "src": "docs/desk_kb/pb.md · ORG.md 조직도"
  },
  {
   "key": "cio",
   "bureau": "투자전략",
   "layer": "프론트",
   "does": "자산배분 안 결재·하우스 뷰 종합, 운용회의 진행(투자전략본부 대표)",
   "dont": "매매 지시문, 미들 점검 없이 결재 올리기, 각 데스크 의견 고쳐 쓰기",
   "src": "ORG.md 본부별 역할 · STANDARD §5"
  },
  {
   "key": "alloc",
   "bureau": "투자전략",
   "layer": "프론트",
   "does": "배분 결정안 작성 — 각 데스크 의견을 모아 비중 설계(비율만), CIO 결재 상정",
   "dont": "각 데스크 판단 대신 쓰기(의견만 받음), 개별 종목 판단(리서치), 최종 결정(CIO 결재→겸이)",
   "src": "docs/desk_kb/allocation.md · ORG.md"
  },
  {
   "key": "macro",
   "bureau": "투자전략",
   "layer": "프론트",
   "does": "거시 국면·연준·선거·달러 뷰, 물가·성장·환율 지표를 채권에 입력, 지표 문장·발간물 3칸 요약",
   "dont": "한은 정책 경로·금통위 판정·국고 곡선 해석(채권 주관), 금리 bp 예측, 섹터·테마 판단(애널), 이벤트 전 방향 베팅",
   "src": "docs/desk_kb/macro.md #12·성격"
  },
  {
   "key": "bonds",
   "bureau": "투자전략",
   "layer": "프론트",
   "does": "한은 정책 경로·금통위 판정·국고 곡선·듀레이션/캐리·크레딧 경보(ai_credit 등) 주관, 매크로 입력(물가·성장·환율)을 받아 해석",
   "dont": "거시 국면·연준·선거·달러 뷰(매크로), 경보를 매매 신호로 쓰기(역할 = 경보뿐)",
   "src": "docs/desk_kb/bonds.md #5"
  },
  {
   "key": "realestate",
   "bureau": "투자전략",
   "layer": "프론트",
   "does": "정책·뉴스·서울 상급지/하급지·경기남부 집값·재개발·신도시 트래킹",
   "dont": "실제 보유·금액 공개 저장소 기재",
   "src": "docs/desk_kb/realestate.md 담당 범위(10/23)"
  },
  {
   "key": "hf",
   "bureau": "투자전략",
   "layer": "프론트",
   "does": "알파북(모의) 운용 — 알파 탐색, 운용회의 이견·trade plan·손절 기록",
   "dont": "물타기, 데이터 없는 단정",
   "src": "docs/desk_kb/hf.md 머리말·성향"
  },
  {
   "key": "quant",
   "bureau": "리서치",
   "layer": "프론트",
   "does": "시그널·백테스트·등급(A/B/C/F/검증전), 리서치본부 대표",
   "dont": "검증전을 '틀림'·F 를 '반대로'로 쓰기",
   "src": "docs/desk_kb/quant.md #19"
  },
  {
   "key": "analyst",
   "bureau": "리서치",
   "layer": "프론트",
   "does": "종목·섹터·테마 밸류에이션 노트(섹터·테마 주관), 리서치 종합",
   "dont": "거시 국면·금리 경로 판단(매크로·채권), 매매 지시문, 등급 없는 자체연구 인용",
   "src": "ORG.md 리서치 · STANDARD §2"
  },
  {
   "key": "derivs",
   "bureau": "리서치",
   "layer": "프론트",
   "does": "옵션·변동성·PCR '파생 한눈에'(흔들림 크기·위치)",
   "dont": "방향 말하기(insight 문구 규칙)",
   "src": "docs/desk_kb/derivs.md 인사이트 문구 규칙(10/20)"
  },
  {
   "key": "data",
   "bureau": "리서치",
   "layer": "백",
   "does": "수집원·정의·약관 확인, 데이터 품질·백필",
   "dont": "약관 금지 용도 사용, 원문 전문 저장",
   "src": "docs/desk_kb/data.md 못 쓰는 것·RSS 약관"
  },
  {
   "key": "data_eng",
   "bureau": "리서치",
   "layer": "백",
   "does": "수집기·백필·스키마 구현(보드 데이터 대기 구현성 21건 인수), 구현 뒤 행 수·기간·결측을 숫자로 데이터에 인계 — 온디맨드",
   "dont": "데이터 품질 판정(데이터), 화면(프론트), 장애 복구(유지보수), 수집 무관 서버·workflows(개발), 상시 라운드 참여",
   "src": "docs/desk_kb/data_eng.md · 11/3 겸이 19:25 결재"
  },
  {
   "key": "frm",
   "bureau": "리스크",
   "layer": "미들",
   "does": "시나리오·스트레스·VaR·한도 수치 설계(FRM), 리스크본부 대표",
   "dont": "매일 사용률 측정(포지션리스크)·위반 판정(컴플)",
   "src": "ORG.md 리스크본부 안 경계(10/24)"
  },
  {
   "key": "posrisk",
   "bureau": "리스크",
   "layer": "미들",
   "does": "FRM 한도 대비 매일 사용률·집중도·유동성·최대손실 측정(모의 북·ISA 노출) + 겸직(포지션리스크): 16:40 한도 점검",
   "dont": "한도 설계(FRM)·위반 판정(컴플), 금액 공개",
   "src": "docs/desk_kb/posrisk.md · ORG.md 경계"
  },
  {
   "key": "compliance",
   "bureau": "리스크",
   "layer": "미들",
   "does": "결재 조항 준수 사전·사후 점검, 위반 로그·에스컬레이션",
   "dont": "규칙 만들거나 바꾸기(규칙 = 겸이 결재)",
   "src": "docs/desk_kb/compliance.md 머리말"
  },
  {
   "key": "behavior",
   "bureau": "리스크",
   "layer": "미들",
   "does": "사람(겸이)의 행동 진단 — 처분효과·보상 직후 베팅 등",
   "dont": "한도 상향 승인(초과 상태 상향 금지 관행)",
   "src": "docs/desk_kb/behavior.md #15 · ORG.md 경계"
  },
  {
   "key": "pm",
   "bureau": "운영",
   "layer": "미들",
   "does": "팀 업무량·병목·사용량 계기판(ops/team.json), 운영본부 대표",
   "dont": "데스크 대신 일하기 — 숫자로 보여주기만",
   "src": "docs/desk_kb/pm.md 머리말"
  },
  {
   "key": "ops",
   "bureau": "운영",
   "layer": "백",
   "does": "보드·잠금·예약·수집·요청 장부 — 판단이 흐르는 길 관리",
   "dont": "컴플 판정(10/24 겸직 해제)",
   "src": "docs/desk_kb/ops.md 머리말·경계"
  },
  {
   "key": "dev",
   "bureau": "운영",
   "layer": "백",
   "does": "서버 로직·scripts·workflows·.gs·수집·배포·getter",
   "dont": "화면 구현(10/24 프론트 이관)",
   "src": "docs/desk_kb/dev.md 경계"
  },
  {
   "key": "front",
   "bureau": "운영",
   "layer": "백",
   "does": "화면(Index·tab_*)·스킨 토큰·텔레그램 UI 문구/배치·ui_smoke 구현",
   "dont": "서버·수집·배포(개발), 화면 설계 판단(UXUI), 데이터 지어내기",
   "src": "docs/desk_kb/front.md 경계"
  },
  {
   "key": "uxui",
   "bureau": "운영",
   "layer": "백",
   "does": "화면 정보 위계·가독성·조작성 설계와 검수 + 겸직(UXUI): 프론트 화면 검수",
   "dont": "구현(프론트)",
   "src": "docs/desk_kb/uxui.md 머리말 · front.md 경계"
  },
  {
   "key": "maint",
   "bureau": "운영",
   "layer": "백",
   "does": "SRE — 멈추거나 늦거나 거짓말하는 것 먼저 찾기, 작은 복구 + 겸직(유지보수): 수집기 매일 점검",
   "dont": "큰 수정(개발에 넘김)",
   "src": "docs/desk_kb/maint.md 머리말"
  },
  {
   "key": "scribe",
   "bureau": "운영",
   "layer": "백",
   "does": "일기·원장·합의 원장 기록, 결정 시각(분) 남기기",
   "dont": "겸이 말과 PB 해석 섞기, 추정 VOC",
   "src": "docs/desk_kb/scribe.md #6·#12"
  },
  {
   "key": "edu",
   "bureau": "교육",
   "layer": "지원",
   "does": "커리큘럼·모듈 설계, 전 데스크 10년차 기준 강화",
   "dont": "자기 문항 검수(출제자≠검수자 — 평가)",
   "src": "docs/desk_kb/edu.md 머리말 · LOOP 4항"
  },
  {
   "key": "eval",
   "bureau": "교육",
   "layer": "지원",
   "does": "문제은행·SRS·채점·오답 환류, 문항 검수",
   "dont": "문항 설계(교육)",
   "src": "docs/desk_kb/eval.md 머리말"
  },
  {
   "key": "household",
   "bureau": "생활",
   "layer": "백",
   "does": "순자산·뱅샐·운동 숫자 트래킹(내무)",
   "dont": "코칭(LIFE), 의료 세부 저장",
   "src": "docs/desk_kb/household.md 담당 범위"
  },
  {
   "key": "life",
   "bureau": "생활",
   "layer": "지원",
   "does": "코칭 — 목표·실행 점검(돈을 넣는 사람을 봄)",
   "dont": "숫자 트래킹(내무), 공개 터미널에 LIFE 숫자",
   "src": "docs/desk_kb/life.md #12·역할"
  },
  {
   "key": "verify",
   "bureau": "검증실",
   "layer": "3선",
   "does": "모든 연구·모델 독립 재현, 뒤집을 권한",
   "dont": "대상 데스크 산출물 편집",
   "src": "docs/desk_kb/verify.md 머리말 · ORG.md 독립 검증실"
  },
  {
   "key": "peer",
   "bureau": "검증실",
   "layer": "3선",
   "does": "반대 의견서 발행(무편집 발행권) + 겸직: 결재 건마다 반대 의견서 3줄",
   "dont": "지시 — 반대는 발행만, 채점은 검증",
   "src": "docs/desk_kb/peer.md #7"
  },
  {
   "key": "audit",
   "bureau": "검증실",
   "layer": "3선",
   "does": "전 데스크 산출물(PB 포함) slop·규정 채점",
   "dont": "직접 수정 — 요청만(§3 (e) 예외 하나)",
   "src": "docs/desk_kb/audit.md 역할"
  }
 ],
 "flow": {
  "title": "같은 사건 흐름 — 모의 북이 한도를 넘으면",
  "note": "예시(절차 설명) · 실제 사건 아님",
  "steps": [
   {
    "key": "frm",
    "what": "한도 수치는 FRM 설계값(스트레스·VaR 기준) — 넘었다는 '자'를 제공"
   },
   {
    "key": "posrisk",
    "what": "매일 사용률 측정에서 100% 초과를 먼저 발견·표시"
   },
   {
    "key": "compliance",
    "what": "어느 결재 조항 위반인지 판정 → 위반 로그 + 정해진 길로 에스컬레이션"
   },
   {
    "key": "behavior",
    "what": "넘긴 과정의 행동 진단(보상 직후 베팅·물타기 등), 초과 상태 한도 상향 금지"
   },
   {
    "key": "audit",
    "what": "넷의 산출물을 사후·독립 채점(기한·숫자 출처·판정 근거)"
   },
   {
    "key": "peer",
    "what": "판정·대응에 반대 의견서 발행(무편집) — 결정은 겸이"
   }
  ]
 },
 "src": [
  "docs/desk_kb/ORG.md",
  "docs/desk_kb/*.md 머리말·경계",
  "docs/desk_kb/STANDARD.md §5"
 ],
 "boundaries": [
  {
   "topic": "한은 정책 경로·금통위 판정·국고 곡선",
   "owner": "bonds",
   "input": "macro — 물가·성장·환율 입력",
   "dont": "macro 는 금리 bp 를 예측하지 않음"
  },
  {
   "topic": "거시 국면·연준·선거·달러",
   "owner": "macro",
   "input": "-",
   "dont": "bonds 는 거시 국면 판정 안 함"
  },
  {
   "topic": "섹터·테마",
   "owner": "analyst",
   "input": "macro·bonds — 거시·금리 배경",
   "dont": "macro·bonds 는 섹터·테마 판단 안 함"
  },
  {
   "topic": "배분 결정",
   "owner": "alloc",
   "input": "각 데스크 — 의견만",
   "dont": "결재는 cio(→겸이), alloc 은 결정 안 함·각 데스크는 의견만"
  },
  {
   "topic": "수집 파이프라인 — 판정 vs 구현 vs 복구 vs 서버",
   "owner": "data_eng",
   "input": "data — 수집원·정의·약관·품질 판정 / maint — 멈춘 수집 복구·재발 방지 요청",
   "dont": "data_eng 는 품질 판정 안 함(data)·장애 복구 안 함(maint)·수집 무관 서버·workflows 안 건드림(dev)·화면 안 만짐(front)"
  }
 ],
 "dual": [
  {
   "key": "peer",
   "what": "결재 건마다 반대 의견서 3줄"
  },
  {
   "key": "maint",
   "what": "수집기 매일 점검"
  },
  {
   "key": "posrisk",
   "what": "16:40 한도 점검"
  },
  {
   "key": "uxui",
   "what": "프론트 화면 검수"
  }
 ]
}
