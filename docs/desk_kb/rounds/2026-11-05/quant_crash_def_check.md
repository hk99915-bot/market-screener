# 급락일 정의 원문 대조 (퀀트, 2026-11-05) — req-quant-ed68ea9f (cio→quant)

> 출처: `scripts/study_playbook_signals.py` events()·`reports/studies/playbook_signals.md` §0-2·§2, `scripts/replicate_crash_rebound.py`·`reports/studies/replication_crash_rebound.md`, `screener/study.py`(crash_rebound), `screener/committee.py` crash_flag, `views/registry.json` crash_day_close, `reports/studies/2026-11-04_crash_close_intraday.md`. 코드·등급 변경 없음(제안 + 결재 필요). 투자 권유 아님.

## 결론 (What)
- **n=55 는 종가 기준이고 dd20 ≤ −10% 를 포함한다 — 정의 원문 일치.** 단 **임계는 −3%** 다: events() 는 `r1 = c[i]/c[i-1]−1 ≤ thr and c[i]/max(c[i-20:i+1])−1 ≤ −0.10`(종가만, 장중 저가는 손절 레벨에만 사용). thr=−3% → 57일, 청산일 확보분 H20 **55건**(독립 19묶음), thr=−5% → 21일·H20 **19건**(8묶음)·H60 14건.
- **불일치 1 (registry):** `crash_day_close` 에 등급 B·n=55 한 줄이 달렸는데 55 는 '급락일(−3%)' 상태의 표본이다. '급락일(−5%)' 은 그 부분집합(n=19, 클러스터 8)이고 단독 검정은 없다(playbook 은 −5% 에서 방향 동일 확인만). 코드·신호표가 B 를 −5% 에 인용하면 표본이 3분의 1 이하.
- **불일치 2 (replication n=27):** `replication_crash_rebound` n=27 은 **코스피 종가 −5% 이하 모든 날**(dd20 조건 없음, `kret ≤ t` 만)을 122630 레버리지로 사서 다음날 시가·종가·5일 보유한 표(crash_rebound §3). 등록 정의(−5% & dd20 ≤ −10%)와 다른 표본이고 등급 B 의 근거도 아니다(자체연구 C·참고). playbook −5%+dd20 은 21일이라 27 과의 차이 6일은 dd20 미충족 날로 추정 — 날짜 대조는 `[확인 필요: 27일 vs 21일 날짜 차집합, 퀀트, 11/9]`.
- **불일치 3 (11/4 연구):** crash_close_intraday ① 는 −5%≤r≤−3% **dd20 조건 없음**(비중첩 39건)이라 이것도 B 표본과 다른 정의 — F 판정은 'B 를 뒤집는 것'이 아니라 별 표본의 검정.
- CIO 가 짚은 코드 사실 확인: `crash_flag` 는 min(종가수익, 장중 저가수익) ≤ −5% 이고 dd20 를 읽지 않는다 → 등록 정의(종가·dd20)와 두 군데 다르다.

## 정정 제안 (결재 필요 — PB 경유)
1. registry `crash_day_close` evidence 문구에 "n=55 는 급락일(−3%)·종가·dd20≤−10% 표본, −5% 는 n=19(8묶음) 부분집합이라 단독 검정 없음" 명기. **등급 B 자체는 결과를 본 뒤 바꾸지 않는다**(−5% 단독 하향·상향 모두 새 사전등록 필요).
2. 신호표·`crash_flag` 의 B 인용은 '종가 ≤ −5% **및 dd20 ≤ −10%**' 일 때만(CIO 제안 1·2 와 같은 방향, 11/6 전향). dd20 미충족 −5% 날은 등급 없음(표본 밖) 표기.
3. 브리핑·운용회의가 replication n=27 을 B 근거로 인용하지 않도록 `[자체연구-C]` 라벨 유지.
- 뒤집는 조건: 퀀트가 −5%(dd20 포함) 독립 사건을 사전등록으로 누적해 단독 판정(현재 n=19/8묶음은 검출력 부족)하면 등급 재산정. 반대 근거: dd20 를 빼도 −5% 급락의 반등이 비슷하다면 정의가 과특이일 수 있다 — 검증전(미검정).
