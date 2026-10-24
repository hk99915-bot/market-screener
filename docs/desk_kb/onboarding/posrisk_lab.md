# 포지션리스크 온보딩 실습 2개

본문 = `docs/desk_kb/onboarding/posrisk.md`. 실습은 **자기 연습 worktree**(`git worktree add <scratchpad>/wt_posrisk_lab origin/main`)에서, 스크립트는 저장소 밖 scratchpad 에 두고 `python3 -I` 로 실행. push 하지 않는다(산출물은 라운드 파일 줄만).
**ISA·스트레스 계산은 pb-private `holdings.txt` 를 읽는다 — 출력은 비율·%p 만**(print 에 금액·수량 변수 금지, 라운드 파일에도 비율만). 제출 = 라운드 파일 `docs/desk_kb/rounds/<날짜>/posrisk.md` 에 `실습N:` 줄. 채점 = 평가.
기대값 = 교육이 10/24 15시 KST(알파북 KR last_bar 10/23 · 재량 북 asof 10/24 09:47 · 토요일이라 주말 동안 불변)에 직접 돌린 숫자. 데이터가 바뀐 날엔 **식과 신호등 방향**이 채점 기준.

## 실습 1 (기본) — 오늘 한도 사용률 표 (북 3개 + ISA + 스트레스)
1. 알파북(`reports/alphabook.json` `books.KR`): 포지션별 비중 wᵢ = qty × mark ÷ nav(nav = `nav[-1].nav`), 총노출 Σwᵢ(파일 `nav[-1].gross` 와 대조), 단일 사용률 = max wᵢ ÷ 15%, 총노출 사용률 = Σwᵢ ÷ (시장 배수 0.25 × 100%) — 배수는 `summary.KR.lines` '시장 배수' 또는 pending `formula`, HHI = Σ(wᵢ/Σw)², 유효 종목 수 = 1/HHI. 대기 주문(pending weight)을 넣은 총노출도 한 줄.
2. 재량 북(`reports/hf_discretion.json`): 열린 리스크 = open 중 `hedge_of`·`pair` 아닌 줄의 risk 합 + baskets.open risk 합 → ÷ 2.0% · 건수 = open + 바스켓 → ÷ 8 · 최대 단일 weight ÷ 15% · limits.dd ÷ (−3%).
3. ISA·스트레스(pb-private, 비율만 출력):
```python
import sys; sys.path.insert(0, sys.argv[1])            # 인자: <market-screener worktree> <pb-private>
from pathlib import Path
from screener import pb
from screener.defs import ISA_TARGET, ISA_BAND, STRESS_LIMIT
P = Path(sys.argv[2])
ev = pb.evaluate((P/"holdings.txt").read_text(encoding="utf-8"), (P/"rules.txt").read_text(encoding="utf-8") if (P/"rules.txt").exists() else "")
for k, t in ISA_TARGET.items():
    d = ev["isa_w"].get(k, 0.0) - t
    print(f"ISA {k}: 이탈 {d*100:+.1f}%p · 밴드 사용률 {abs(d)/ISA_BAND:.0%}")
s = ev["stress"]["2026-07"]
print(f"스트레스 2026-07 ({ev['stress_denom']}): {s*100:+.2f}% · 사용률 {abs(s)/STRESS_LIMIT:.1%}")
print(f"반도체(ex) {ev['semi_ex']*100:.1f}% · 상한 {ev['band']['ex']['cap']*100:.0f}% 대비 {ev['semi_ex']/ev['band']['ex']['cap']:.0%}")
```
4. 표 한 장: 북 | 한도 | 현재 | 사용률 | 신호등(<75 녹 · 75~90 황 · 90~100 적 · >100 초과, kb:posrisk#1) | 원천 파일. 그리고 `python3 scripts/hf_book.py show` 의 1선 숫자(열린 리스크·가동률)와 내 숫자가 다르면 둘 다.

정답 기준(교육 실측 10/24):
| 북 | 한도 | 현재 | 사용률 | 신호등 |
|---|---|---|---|---|
| 알파북 KR 총노출 | 25% (배수 0.25) | 7.25% (대기 DB 0.9% 포함 8.15%) | 29% (33%) | 녹 |
| 알파북 KR 최대 단일 | 15% | KT&G 3.76% | 25% | 녹 |
| 알파북 KR 집중 | — | HHI 0.412 → 유효 2.43개(노출 안 비중 KT&G 52%) | — | 참고 |
| 알파북 US | — | 0 | 0% | 녹 |
| 재량 북 열린 리스크 | 2.0% | 0.625% (1선 show 0.62%) | 31% | 녹 |
| 재량 북 건수 | 8 | 3 (2 + 바스켓 1) | 38% | 녹 |
| 재량 북 최대 단일 | 15% | ES 숏 7.56% | 50% | 녹 |
| 재량 북 고점 대비 | −3% | −0.116% | 4% | 녹 |
| ISA 최대 이탈 | ±5%p | K200 +1.7%p (나머지 0.4~0.9%p) | 33% | 녹 |
| 구속 스트레스 D2 | −15% | −14.87% | **99.1%** | **적** |
| 반도체(ex) | 상한 35%(하락장) | 15.4% | 44% | 녹(하단 30% 아래 — 재매수 허용, 의무 아님) |
- 필수 문장 2개: ① 북 표는 거의 녹인데 **스트레스 하나가 적** — 포트 위험의 결론은 '녹 다수'가 아니라 가장 높은 사용률 ② 스트레스 사용률 99% 의 뜻(한도까지 0.13%p — 반도체·코어가 조금만 더 빠져도 ⛔, 판정은 컴플).
- 감점: 금액·주식 수·계약 수를 표에 씀(공개 금지선) · 헤지 다리 risk 를 열린 리스크에 더함 · 알파북 총노출 한도를 100%로 둠(시장 배수 빠뜨림).
채점 방법: 평가가 같은 파일로 재계산(약 1분) — 숫자 ±0.5%p 허용, 신호등 일치.

## 실습 2 (심화) — 기준 대조: 같은 테마 두 한도, 고아 헤지
(a) **섹터 전환이 어느 한도에 들어갔나.** 10/24 07:10 `sectors.OFFICIAL_LIMITS=True`. 같은 보유로 스위치를 껐다 켜며 반도체 비중과 스트레스를 같이 잰다:
```python
import sys; sys.path.insert(0, sys.argv[1])
from pathlib import Path
from screener import pb, sectors
P = Path(sys.argv[2]); txt = (P/"holdings.txt").read_text(encoding="utf-8")
rt = (P/"rules.txt").read_text(encoding="utf-8") if (P/"rules.txt").exists() else ""
for flag in (True, False):
    sectors.OFFICIAL_LIMITS = flag
    ev = pb.evaluate(txt, rt)
    print(f"OFFICIAL_LIMITS={flag}: 반도체(ex) {ev['semi_ex']*100:.1f}% · 스트레스 D2 {ev['stress']['2026-07']*100:+.2f}%")
```
   → 결과를 보고 `screener/pb.py` 의 `evaluate` 행 생성부(`semi`·`semi_new` 칸)와 `stress_loss`(어느 칸으로 −50% 를 거나)를 읽어 원인을 한 줄로. 그리고 이것이 결함인지 의도인지는 **내가 정하지 않고** FRM(시나리오 소관)·개발에 묻는 요청 문장을 쓴다(실제 ask 는 첫 업무에서, 교육이 이미 넘겼으면 그 id 를 인용).
(b) **고아 헤지 시나리오.** 10/22 하이닉스 롱(비중 0.5%, β1.46)에 붙였던 K200F 헤지(명목 1.46 × 0.50% = 0.73%, `reports/hf_discretion.json` closed 2026-10-22-9)를 예로: 부모가 손절됐는데 헤지가 남았다면 ① 열린 리스크 계산에서 그 다리는 어떻게 바뀌나 ② 지수 ±10% 때 장부 손익 ③ 사용률 표의 어느 줄로 가나.

정답 기준(교육 실측 10/24):
- (a) `True: 반도체(ex) 15.4% · 스트레스 D2 −14.87%` / `False: 21.9% · −14.87%` — 비중은 −6.4%p 바뀌는데 **스트레스는 그대로**. 원인: `stress_loss` 가 행의 `semi`(옛 체인 분류 `semi_class == 'semi'`)로 −50% 를 걸고, 밴드 판정은 `OFFICIAL_LIMITS` 에 따라 `semi_new` 를 쓴다 → 한 테마의 두 한도가 서로 다른 분류. 방향: 지금은 옛 분류가 반도체를 더 넓게 잡아 스트레스가 **보수적**(새 분류로 바꾸면 −6.4%p 가 −50% 에서 빠져 덜 나쁘게 나옴 — 단 한도선 위라 판정이 바뀔 수 있음). 요청 문장 = FRM·개발에 '스트레스 입력 분류를 밴드와 맞출지, 옛 분류 유지가 의도인지' (교육이 10/24 FRM 에 넘김 — req-frm-585cd67f).
- (b) ① 헤지 다리는 부모가 있을 때 열린 리스크 0(hf_book 머리말 '헤지 다리는 0으로 계산') → 부모가 사라지면 **손절 없는 지수 숏 0.73%** = 최대손실 미정 줄(kb:posrisk#10) ② 지수 +10% → −0.073%, −10% → +0.073% ③ 사용률 표 '최대손실 미정' 칸 + 단일·건수에 새 숏 1건. 현행 규칙은 부모 청산 때 동시 청산(`close_orphan_pairs`)이라 이 상태는 **규칙이 지켜지면 0건** — 0건인지 매일 세는 게 포지션리스크 일.
- 금지 답: 내 표에서 스트레스를 새 분류로 '고쳐' 다른 숫자를 공식 값처럼 쓰기(모형은 FRM 소관 — 두 숫자를 나란히).
채점 방법: 평가가 (a) 스크립트를 재현해 15.4/21.9·−14.87 두 번을 보고, 원인 문장(semi vs semi_new, stress_loss)·방향(보수적)·요청 대상(FRM·개발)을 키와 대조. (b)는 0.73%·0.073%·최대손실 미정·close_orphan_pairs.

## 첫 업무와의 연결 (보드 posrisk-first-output, 마감 10/31)
- 실습 1 표 = 매일 장후 점검 ①·②·⑥(kb:posrisk 첫 산출물 계획)의 원형. 유동성 버킷(③)·만기 버킷(④)은 ADV·옵션 잔존일 입력이 필요 — 입력 파일 자리부터 확정.
- 실습 2 (a) = 첫 '모형 이견' 장부 건. (b) = 매일 '고아 헤지 0건' 확인 줄.
