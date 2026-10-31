# 정의·공식·흔한 오해·터미널 (kb:cio#1–9·#17–19)

(원본: docs/desk_kb/cio.md 해당 절을 그대로 옮김 — 2026-10-31 스킬 시범. 번호 `kb:cio#<n>` 동일. 내용 수정은 KB 먼저, 이 파일은 따라 고친다.)

## 정의
1. [교과서] 코어-새틀라이트: 코어 = 전략 배분(SAA) 지수 보유·밴드 리밸런싱, 새틀라이트 = 전술(TAA)·종목 베팅. 한도·손절·집중도 규칙은 새틀라이트에만. (출처: CFA L1 'Basics of Portfolio Planning and Construction' SAA/TAA `[확인 필요: 절 제목, 2026-10-30]`, Swensen 개정판)
2. [현업 관행] 3북 구조: 코어(적립 전용·매도 금지) / 위성(새 매매 돈, 상한) / 레거시(기존 보유, 매도만·대금은 코어로 일방통행). 위험은 북 크기가 아니라 **매매하는 돈의 크기와 상관·변동성**에서 온다. 레거시는 '열린 보유'가 아니라 **축소 일정이 있는 보유**(테마 한도·손절 백스톱·초과이익 절반 이전·분기 스트레스 관문 승계). (출처: CIO 내부 검토 메모 2026-10-16, 개념만)
3. [자체연구-C] 시나리오 확률 = 1999~ 코스피에서 오늘과 같은 조건(`scenario_basis.basis`: 평상시/급락일/20일 −15%/둘 다)이던 날의 20거래일 뒤 결과 빈도 — 기저율이지 예측 아님. 표본 수십~수백이라 ±7~15%p는 소음. (출처: `reports/studies/crash_rebound.json` buckets20, registry `scenario_base_rate` C)
4. [현업 관행] 프리모템 = wrong(틀리는 길)·p·tell(관측 가능한 신호)·cost(기다린 비용)·action(수량·시한). 비관이 아니라 탈출 지도. (출처: `screener/committee.py` `_v2_premortem`; Klein HBR 2007 `[확인 필요: 권호, 2026-10-30]`)
5. [교과서] 레짐 라벨: 하락장 = 200일선 아래 또는 20일 고점 대비 ≤ −15% / 회복 확인 전 = 200일선 위·20일선 아래 / 상승장 = 둘 다 위. 실패 모드: 휩소(200일선 왕복)·지연(2026-03-09 뒤 60일 +55% 구간을 반만 보유)·회복 정의가 F 신호에 묶임. (출처: registry `kr_regime` C, `exec_signal.md` H4)

## 공식
6. [교과서] 현금흐름 리밸런싱: 비중 w 자산이 r 수익, 나머지 0이면 새 비중 = w(1+r)/(1+wr). 예 0.6·+10% → 0.66/1.06 = 62.3%. 밴드(±5%p) 안이면 적립분을 뒤처진 자산에만 넣어 되돌린다(매도 0). (출처: 산술; Swensen 리밸런싱 절 `[확인 필요: 쪽, 2026-10-30]`)
7. [교과서] Grinold-Kahn 기본 법칙 IR ≈ IC × √BR. BR = 독립 판단 수(종목 수 아님). IC 0.05·BR 100 → 0.5, BR 1 → 0.05. 같은 테마·같은 촉매·같은 동의 원천이면 하나로 센다. 가정(IC 일정·독립)은 현실에서 거의 깨지고 제약 포트폴리오에선 과대평가(transfer coefficient). (출처: Grinold & Kahn 2판 5·6장 — 2차 자료 CFI·AnalystPrep·New Frontier 2019로 확인)
8. [자체연구-검증전] ideas_top 확신 점수 = Σ동의 원천 가중 − Σ반대 원천 가중, 가중 = 등급(A 1·B .8·C .6·검증전 .3·F 0) × 원천 실제 성적 보정(ideas_attrib, n≥10부터, 0.5~1.5배). 점수는 IC가 아니라 **등급 합** — 수익 확률로 읽지 않는다. (출처: `screener/committee.py` `_ideas_top` formula, `GRADE_W`)
9. [교과서] 손실 복구 비대칭: −15% → +17.6%, −8% → +8.7% 필요. 꼬리 보험(손익비 2.2, p 1.7%)은 기대값이 음수여도 '다음 달 규칙을 지킬 수 있는 상태'를 산다. (출처: 산술; `reports/committee.json` asymmetry)

## 흔한 오해
17. [경험] "확률 높은 시나리오 = 확정" → 행동 열쇠는 `scenarios[].trigger`. "프리모템 = 비관" → action은 '추격 금지·1차만'이지 '사지 마'가 아님. "코어는 안 건드려도 된다" → 매매 안 함 ≠ 방치(밴드·적립 리밸런싱). "score 0.9 = 90% 확률" → 등급 합. (출처: `consult:cio#q10·q12`)
18. [자체연구-F] 운용회의 `scenarios[0].trigger`·`premortem.tell`의 '5일 고점 + 외국인 2일 순매수'는 entry_signals 대조군 꼴찌(F). tell(관측)로는 쓰되 진입 허가 게이트로 읽지 않는다. 대체 후보 '급락일 종가'는 C(entry_trigger)/B(crash_day_close) — 코드 반영은 PB 검토 후. (출처: `entry_signals.md`, registry `confirm_signals` F·`entry_trigger` C·`crash_day_close` B)

## 터미널에서 보는 자리
19. [자체연구-검증전] 3분 루틴: `bottom_line` → `bottom_line.clock`(약세 경보선·강세 전환선 거리) → `premortem.tell` → `ideas_top[].status/kill` → `track.summary.h5/h20`·`track.brier`(n 두 자릿수 전엔 기록 중). (출처: `screener/committee.py` `_v2_clock`/`_v2_track`)
