"""생성기별 `top` 어댑터 — 각 생성기의 완성된 out dict 를 읽어 topline.make() 로 상단 3칸을 만든다.

원칙(지시서 4절 1단계): 칸 문장은 기존 문장 재배치 우선, 새 문장은 So What 1줄만. 기존 키는 읽기만 한다(삭제·변경 없음).
모든 함수는 실패해도 생성기를 막지 않도록 호출부에서 try 로 감싼다. 시장·모델 숫자 등급: 시나리오 확률·모델 북 = 검증전.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .topline import fit, make

KST = ZoneInfo("Asia/Seoul")


def _now() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")


def _asof(x) -> str:
    s = str(x or "").replace(" KST", "").strip()
    return s[:16] if len(s) >= 10 else _now()


def _pct(x, d=1) -> str:
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def committee(o: dict, market: str = "KR") -> dict:
    """T1·T3 운용회의 — ①=직전 대비 ②=판정·시나리오 확률 함의(신설) ③=할 일 · 시계는 근거로."""
    bl = o.get("bottom_line") or {}
    ls = bl.get("lines") or []
    head = (o.get("head") or [""])[0]
    what = fit(head, max_lines=1) + fit(ls[0] if ls else "직전 회의 기록 없음", max_lines=2)
    sc = sorted(o.get("scenarios") or [], key=lambda s: -(s.get("prob") or 0))
    st = bl.get("stance") or (o.get("stance") or {}).get("stance") or "판정 없음"
    so = []
    if sc:
        so.append(f"판정 {st} · 최다 시나리오 {sc[0]['name']} {(sc[0].get('prob') or 0) * 100:.0f}%(검증전)")
    else:
        so.append(f"판정 {st} · 시나리오 확률 데이터 없음(생성 실패)")
    pm = o.get("premortem") or {}
    if pm.get("wrong"):
        so += fit("반대 근거: " + pm["wrong"], max_lines=1)
    now = fit((ls[2] if len(ls) > 2 else "조치 없음(bottom_line 없음)").replace("할 일: ", ""), max_lines=2)
    if pm.get("tell"):
        now += fit("뒤집힐 조건: " + pm["tell"], max_lines=1)
    src = "reports/committee.json" if market == "KR" else "reports/committee_us.json"
    return make(what, so, now[:3], evidence=[ls[1]] if len(ls) > 1 else None, src=[src], asof=_asof(o.get("asof")), grade="검증전")


def macro(o: dict) -> dict:
    """T5 매크로 뷰 — summary 를 ' → ' 앞(관측)·뒤(함의)로 나눔."""
    s = o.get("summary") or ""
    a, _, b = s.partition(" → ")
    what = fit(a, max_lines=2)
    so = fit(b, max_lines=1) if b else []
    so.append("바람 점수 가중치는 검증전 — 단독 방향 근거 불가")
    now = ["조치 없음(바람 점수 단독 매매 규칙 없음 — 운용회의 판정 입력으로만 사용)"]
    return make(what, so, now, src=["reports/macro_view.json"], asof=_now(), grade="검증전")


def bonds(o: dict) -> dict:
    """T6 채권 — 금리 변화 → 듀레이션 함의 → 조치(reco 재배치)."""
    us, kr = (o.get("us") or {}).get("chg") or {}, (o.get("kr") or {}).get("chg") or {}
    sp = (o.get("spreads") or {}).get("us_10_2") or {}
    bits = []
    for lab, d in (("미 10년", us.get("10Y")), ("미 2년", us.get("2Y")), ("국고 3년", kr.get("3Y"))):
        if d and d.get("v") is not None:
            bits.append(f"{lab} {d['v']:.2f}%(1M {d.get('m1', 0):+.0f}bp)")
    if sp.get("v") is not None:
        bits.append(f"미 10Y−2Y {sp['v'] * 100:+.0f}bp")
    what = fit(" · ".join(bits) or "금리 데이터 없음(수집 실패)", max_lines=2)
    notes = o.get("notes") or []
    imp = next((n for n in notes if "부담" in n or "할인율" in n), notes[0] if notes else "함의 문장 없음(interpret 실패)")
    so = fit(imp, max_lines=2)
    c = ((o.get("corr") or {}).get("IEF_SPX") or {}).get("c250")
    if c is not None:
        so.append(f"주식-채권 1년 상관 {c:+.2f} — 양(+)이면 채권 헤지 효과 제한")
    reco = o.get("reco") or []
    now = fit(reco[0], max_lines=2) if reco else ["조치 없음(권고 문장 없음)"]
    return make(what, so[:3], now, src=["reports/bonds.json"], asof=_asof(o.get("generated_at") or o.get("asof")))


def derivs(o: dict) -> dict:
    """T7 파생 — 포지셔닝 → 변동성 함의 → 헤지 조치(insight 재배치)."""
    f = lambda x, d=2: "—" if x is None else f"{x:,.{d}f}"  # noqa: E731
    what = [f"PCR(미결제) {f(o.get('pcr_oi'))} · 맥스페인 {f(o.get('max_pain'), 1)} · 현물 {f(o.get('spot'))} (만기 {o.get('expiry', '—')}, D-{o.get('dte', '—')})",
            f"감마 노출 {f(o.get('gex_bn'), 1)}억 · 전환점 {f(o.get('flip'), 1)} · ATM IV {_pct(o.get('atm_iv')).lstrip('+')} · 20일 RV {_pct(o.get('rv20')).lstrip('+')}"]
    ins = o.get("insight") or {}
    so = fit(ins.get("one_line") or "인사이트 없음(생성 실패)", max_lines=1) + ["방향 신호로서 PCR·맥스페인 효과는 검증전"]
    now = fit(ins.get("so_what") or "조치 없음(인사이트 생성 실패)", max_lines=2)
    return make(what, so, now, src=["reports/derivs.json"], asof=_asof(o.get("asof") or o.get("date")), grade="검증전")


def alphabook_block(blk: dict, market: str) -> dict:
    """T9 HF 알파북(시장 1개 블록) — lines[0]=현재 · lines[1]=제안 · lines[3]=틀린 것."""
    ls = blk.get("lines") or []
    st = blk.get("stats") or {}
    what = fit(ls[0] if ls else f"알파북({market}) 데이터 없음", max_lines=2)
    so = [f"모의(가상 1단위) · {st.get('ir_note') or '표본 부족'} — 성과 판단 불가(검증전)"]
    if len(ls) > 3:
        so += fit(ls[3], max_lines=1)
    now = fit(ls[1] if len(ls) > 1 else "조치 없음(제안 없음)", max_lines=2)
    return make(what, so, now, src=["reports/alphabook.json"], asof=_asof(blk.get("asof")), grade="검증전")


def alphabook(S: dict) -> dict:
    """alphabook.json 전체 — KR·US 요약 합침."""
    sm = S.get("summary") or {}
    what, now = [], []
    for m in ("KR", "US"):
        x = sm.get(m)
        if not x:
            continue
        ls = x.get("lines") or []
        what += fit(ls[0] if ls else f"{m} 데이터 없음", max_lines=1)
        now += fit(ls[1] if len(ls) > 1 else f"{m} 제안 없음", max_lines=1)
    so = ["모의(가상 1단위 NAV) · 표본 20일 미만이면 IR 미산출 — 성과 판단 불가(검증전)"]
    return make(what or ["알파북 데이터 없음"], so, now or ["조치 없음(제안 없음)"], src=["reports/alphabook.json"],
                asof=_asof(S.get("updated")), grade="검증전")


def hf_ideas(o: dict) -> dict:
    """T10 HF 아이디어 — 후보 수·유형 → '후보일 뿐' → 체크리스트."""
    c = dict(o.get("counts") or {})
    tot = c.pop("total", 0)
    ideas = o.get("ideas") or []
    what = [f"후보 {tot:,}건 중 상위 {len(ideas)}개 — " + (", ".join(f"{k} {v}" for k, v in list(c.items())[:4]) or "유형 없음")]
    if ideas:
        what += fit("상위: " + ", ".join(f"{x.get('name')}({x.get('type')})" for x in ideas[:3]), max_lines=1)
    so = ["후보일 뿐 진입 아님 · 검증 상태 F 신호는 반대 근거로만"]
    g = o.get("gap") or {}
    if g.get("status"):
        so += fit(f"미·한 갭 추정 {_pct(g.get('pred_gap'), 2)} — {g['status']}", max_lines=1)
    now = ["진입은 scripts/hf_book.py 체크리스트 통과 건만(HF 데스크)"]
    return make(what, so, now, src=["reports/hf_ideas.json"], asof=_asof(o.get("generated_at") or o.get("asof")), grade="검증전")


def hf_book(b: dict) -> dict:
    """T11 HF 재량 북 자동 상단(CLI --what 등 미지정 시)."""
    op, cl = b.get("open") or [], b.get("closed") or []
    lim = b.get("limits") or {}
    what = [f"보유 {len(op)}건 · 청산 {len(cl)}건 · 누적 손익 {_pct(lim.get('pnl'), 2)}(가상 1단위) · 최대 낙폭 {_pct(lim.get('dd'), 2)}"]
    if cl:
        what.append(f"청산 평균 {sum(c.get('r', 0) for c in cl) / len(cl):+.2f}R (n {len(cl)})")
    so = ["모의 북 — 실계좌 주문 아님 · 표본 적어 성적 판단 불가(검증전)"]
    if lim.get("ban_new"):
        so.append(f"신규 금지 상태 — {lim.get('why') or '사유 미기재'}")
    now = ["조치 없음(장부 갱신만) — 진입·청산은 hf_book.py add/close-now 기록 기준"]
    return make(what, so, now, src=["reports/hf_discretion.json"], asof=_asof(b.get("asof")), grade="검증전")


def daily(o: dict) -> dict:
    """T12 증권가 일일 브리프 — headline → 이탈·하향 함의 → 확인 조치."""
    what = fit(o.get("headline") or "헤드라인 없음", max_lines=2)
    so = [f"목표가 하향 {len(o.get('tp_cuts') or [])}건 · 톤 이탈 {len(o.get('dissent') or [])}건 — 증권가 집계, 우리 판단·매매 신호 아님"]
    flag = [d for d in (o.get("disclosures") or []) if d.get("flag")]
    now = [f"주의 공시 {len(flag)}건 확인 필요(애널 데스크)"] if flag else ["조치 없음(집계 보고 — 매매 신호 아님)"]
    return make(what, so, now, src=["reports/daily_brief.json", "reports/daily_brief.md"], asof=_asof(o.get("asof")))


def research(o: dict) -> dict:
    """T13 리서치 종합 — headline.text → 라벨·괴리 → 괴리 재검토."""
    h = (o.get("headline") or {}).get("text") or "헤드라인 없음"
    what = fit(h, max_lines=2)
    dv = o.get("divergence") or []
    so = [o.get("label") or "증권가 집계 — 우리 판단·매매 신호 아님", f"우리 후보와 증권가 괴리 {len(dv)}건 — 톤 지표는 검증전"]
    now = ([f"괴리 상위 {', '.join(x.get('name', '') for x in dv[:2])} 근거 재확인(애널)"] if dv
           else ["조치 없음(괴리 없음)"])
    return make(what, so, now, src=["reports/research_synthesis.json"], asof=_asof(o.get("generated_at") or o.get("asof")))


def study(title: str, what, so_what, now_what=None, src=None, asof=None, grade=None) -> dict:
    """T20 퀀트 연구 스크립트 공용 — 자동 요약(문서형). 조치 판단은 퀀트 본문 몫이라 기본 '조치 없음(사유)'."""
    now = now_what or [f"조치 없음(자동 생성 요약 — {title} 적용 판단은 퀀트 본문 결론 기준)"]
    return make(what, so_what, now, src=src, asof=asof or _now(), grade=grade)
