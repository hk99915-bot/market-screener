# 현업 vs 교과서·거버넌스·우리 연구와의 차이·출처 (kb:cio#11–16·#20–21)

(원본: docs/desk_kb/cio.md 해당 절을 그대로 옮김 — 2026-10-31 스킬 시범. 번호 `kb:cio#<n>` 동일. 내용 수정은 KB 먼저, 이 파일은 따라 고친다.)

## 현업 vs 교과서 (확률→노출·코어/위성·구속 한도·게이트·거짓 정밀도·거버넌스 주기)
11. [교과서 vs 현업 관행] 확률→노출: 교과서(Merton 기대효용) = 연속값 ∝ 기대초과수익/(위험회피×분산). 현업(우리) = **레짐이 상한, 시나리오가 그 안의 계단**(예: 100/70/50 상한 × 약세 ≥30% 신규 0 / 20~30% 1차 비중 / <20% 2차). 이유: 확률 오차가 커서 연속값은 거짓 정밀도, 행동 제어가 우선. (출처: Ilmanen 1·2장 `[확인 필요: 쪽, 2026-10-30]`, `rule_audit.md` #12, `semis_cap.md` H3 F)
12. [교과서 vs 자체연구] Swensen·Ilmanen: SAA + 밴드, 레짐으로 노출 안 바꿈. 우리: 위성에만 레짐 상한(C, 위험 축소 근거만·알파 근거 없음 — DUAL_MOMENTUM F). **코어는 레짐을 보지 않는다** — 넣는 순간 코어가 위성이 된다. (출처: registry `kr_regime` C·`personal.satellite_cap` B)
13. [현업 관행] 스트레스 '−15%'는 **구속 한도**, VaR은 **대시보드**: 스트레스는 시나리오 하나로 재현 가능·논쟁 여지 없음, VaR은 분포·창 가정에 따라 흔들려 "모형이 틀렸다"는 재협상의 입구가 된다. 구속 규칙은 재현 가능하고 재량이 0인 것만. (출처: CIO 메모 §2-2·§3, FRM 데스크 R3 교차)
14. [현업 관행] 게이트 설계 3원칙: 측정 가능(성적표에서 바로 읽힘) · 게임 불가(아무것도 안 해도 자동 충족 ✕, 손절 −1R이면 '결과 −1R 이내'는 동어반복 ✕, 매매 0건 달 자동 증액 ✕) · **과정 조건**(주문표·손절 동시 설정·보고)이지 결과 조건이 아님(결과는 운). (출처: CIO 메모 §3)
15. [현업 관행] 거짓 정밀도 판별: 두 후보 숫자의 차이가 **한 주 가격 변동 안**에 들어오고 백테스트 곡선이 그 구간에서 평평하면(테마 한도 30~70% 평평) 결정이 아니라 다이얼이다 → 숫자 하나로 줄이고 레짐은 '매수 허용 여부'만 바꾼다. (출처: `semis_cap.md` H1 C·H3 F, CIO 메모 §2-2)
16. [현업 관행] 거버넌스 주기: 1단계 파라미터(주간) / 2단계 구조(월간, 사전등록 필수) / 3단계 전면(분기). 위반 중(또는 5거래일 내 위반 예상)인 규칙을 완화하는 변경은 그 리뷰에서 불가 → 다음 리뷰 이월. 재상정은 새 데이터 있을 때만. 22:00~07:00 결정 금지. (출처: CIO 메모 §5)

## 우리 연구와의 차이
20. [자체연구-C(역방향)] 급락 뒤 비반도체 섹터: 덜 빠진 상위 1/3 − 많이 빠진 하위 1/3 = 60일 **−3.4%p**(p 0.075, n=9, IS 2·OOS 7 같은 방향) — 사전 가설(방어 우위)과 반대, 평균회귀 방향. 24개 비반도체 업종 전부 60일 코스피 이하. 오늘 rotation '주도'(음식료·운송)는 과거 급락 뒤 중하위~최하위 → 주도 업종 추격 근거 없음. rotation 블록은 5일 수익률 서술이지 판단 근거가 아님. (출처: `reports/studies/exec_signal.md` H4, registry `sector_postcrash` C)
21. [자체연구-C/F] 하락장 노출 50% 제한(`kr_regime` C): 위험 축소 효과 소폭(연 2~3%p), 알파 없음. 하락장 하드캡을 더 낮추는 것은 F(semis_cap H3). 반등 구간 비용은 실재(2026-03 사례) — 규칙은 비용을 알고 지킨다. (출처: `rule_audit.md` #12 T5, `semis_cap.md`)

## 출처
- 교과서: Grinold & Kahn *Active Portfolio Management* 2판 5·6장 / Swensen *Pioneering Portfolio Management* 개정판 자산배분·리밸런싱 절 / Ilmanen *Expected Returns* 1·2장·growth/inflation 장 / CFA L1 Portfolio Management 'Overview', 'Basics of Portfolio Planning and Construction'(IPS, SAA/TAA). 전부 목차·2차 자료 확인, 원문 `[확인 필요: 원문 대조, 2026-10-30]`.
- 자체: `screener/committee.py`(머리말·`_stance`·`_scenarios`·`_ideas_top`·`_v2_*`), `reports/committee.json`(2026-10-16), `reports/studies/{crash_rebound,entry_signals,playbook_signals,rule_audit,semis_cap,exec_signal}`, `views/registry.json`.
- 내부(개념만): CIO 검토 메모 2026-10-16(3북·거짓 정밀도·게이트·거버넌스).
