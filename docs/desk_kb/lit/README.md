# 문헌(lit) KB — 데스크별 논문 카드

논문을 '표준'이 아니라 **다음 라운드에 볼 방향**으로 적는 곳이다. 카드는 Pickle 주 1회 세션이 `content/papers/index.json` 상위 후보에서 쓰고, `scripts/paper_lit_check.py --ci` 가 형식·철회·경로를 검사한다.

## 어디에 무엇이 있나 (다른 에이전트가 찾는 순서)

| 찾는 것 | 위치 | 쓰는 법 |
|---|---|---|
| 데스크별 논문 카드(결론·한계·적용·뒤집힐 조건) | `docs/desk_kb/lit/{macro,quant,derivs,hf,frm,allocation}.md` | 자문·브리핑 전에 자기 데스크 파일만 읽는다. 카드의 '적용:' 이 가리키는 코드·산출물부터 확인 |
| 최신 수집 논문 원장(점수·폐기 사유·철회 플래그) | `content/papers/index.json` | 상태 `summarize`(요약 후보) / `hold`(보류) / `rejected`(폐기, 사유 있음) · `withdraw_flag=true` 는 인용 금지 |
| 수집 규칙·문턱 | `content/papers/sources.json` · `content/papers/triage_rules.json` | 점수 재현이 필요할 때 |
| 주간 요약 | `reports/papers/digest_*.md` | 60줄 상한. 상단 What/So What/Now What |
| 우리 가설로 승격된 문헌 | `ops/research_pipeline.json` (`vrp_rebound`·`night_gap` 등) | 문헌은 가설의 근거일 뿐, 등급은 우리 데이터가 정한다 |

- 데스크 매핑: 매크로·채권·한국 수급 → `macro.md`, 퀀트·ML·백테스트 규율 → `quant.md`, 파생·변동성·야간선물 → `derivs.md`, 헤지펀드·딜러 감마·선물 수급 → `hf.md`, 리스크·사이즈 → `frm.md`, 자산배분·행동재무 → `allocation.md`.
- 브리핑·운용회의 에이전트: 인용 문장에는 **카드 파일 경로와 연도**를 함께 적는다(예: `lit/derivs.md` Carr–Wu 2009). 등급 꼬리표는 붙이지 않는다(등급은 우리 연구에만).

## 쓰는 법

- 데스크별 파일 하나. 카드 하나 = 논문 하나.
- 카드 순서: 출처 → 결론 → 한계 → 적용 → 뒤집힐 조건. **5칸 모두** 채운다(빈칸이면 CI 경고).
- 수치는 원문에 있는 것만 옮긴다. 초록에 없는 숫자는 쓰지 않는다.
- 등급은 붙이지 않는다(등급은 퀀트 소관). 매매 지시문도 쓰지 않는다.

## 카드 형식

```markdown
- **저자(연도)** 제목 · 출처 DOI 또는 arXiv · [확인수준]
  - 결론: 한 줄(수치는 원문 표기 그대로)
  - 한계: 한 줄
  - 적용: 데스크 · 저장소 경로
  - 뒤집힐 조건: 한 줄
```

- 카드 상한 6줄, 파일 상한 200줄. 넘으면 다른 파일로 나눈다.
- 철회·정정 논문(`content/papers/index.json` 의 `withdraw_flag`)은 인용 금지 — CI 가 오류로 막는다.
- 금액 표기는 `slop_audit` (e) 규칙에 걸린다. 비율·bp 로 환산하거나 문맥어(거래대금·시가총액)를 함께 적는다.
- `적용:` 에 적은 경로는 실제로 있어야 한다(없으면 CI 오류). 새 파일을 먼저 만들고 인용한다.
- 서로 충돌하는 논문은 한쪽을 지우지 말고 **두 카드를 나란히** 두고 '우리 연구와의 차이'에 양쪽을 적는다(예: 0DTE 감마 — Amaya 2025 vs Dim·Eraker·Vilkov).
