# derivs 라운드1 — 2026-10-17

1. **읽기** — derivs.md 전체(복기 2건) · 피어 macro.md · _scoreboard.md(파생 채점 행 아직 없음) · 보드 파생 태스크 8건(검수 6·완료 1·대기 gamma-verdict 10/30).
2. **배움** — SEC·FINRA 2009 Investor Alert(레버리지·인버스 ETF 일일 리셋, 장기 보유 시 L배와 괴리·변동성에서 확대) + Cheng & Madhavan 2009 근사식 끌림 ≈ (L−L²)/2·σ²T 를 KB '공식'에 추가(출처 등급 규정·교과서, 근사식 쪽수 `[확인 필요]`).
3. **고침** — `screener/duel.py` `lev_factor`·`lev_drag`·`lev_drag_note`·`lev_note_for_pick`: pick/pick-us/pick🔥 에 레버리지 ETF 가 들어오면 `picks[slot].lev_drag` 한 줄(예: 2일 ±3% 왕복 → 3배 −0.81%, 끌림 −0.54%p) + 이슈 답글 ⚠; `screener/ticket.py` 주문표 reasons 에도 표기(금지 여부와 별개). 테스트 `tests/test_lev_drag.py` 7건(손계산 일치·보유일/진폭 단조·추세 시 부호·인버스·배수표·기록 연동). 결재 #14 ① 코드 근거.
4. **피어(매크로)** — macro.md #3 바람 점수는 VIX 계단만 있고 '한국 변동성' 이 없다. 코스피200 ATM IV(`reports/derivs.json` `atm_iv`, `daily.csv` `rep_iv`)를 KOSPI 처럼 '표시 전용' 칩으로라도 올려 주길 요청 — 10/15 같은 한국 고유 급락(IV 54%)은 VIX 로 안 잡힌다. 점수 가중은 검증전이니 넣지 말고 표시만.
5. **복기** — 브리프 예시 숫자(5일 −0.81%)를 검산 없이 옮길 뻔함: −0.81% 는 2일 값. 숫자 예시는 함수로 재계산해 적는다(KB 복기 참조).

요청→매크로: `macro_view.json` 칩에 코스피200 ATM IV(÷√252 = 하루 1σ)를 표시 전용으로 추가 검토 (점수 제외, 출처 reports/derivs.json atm_iv).
