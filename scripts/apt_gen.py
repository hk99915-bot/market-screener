"""오늘의 인적성 문항 생성기(계산형 6종) — LLM 없이 숫자·보기·함정·해설을 만든다 (교육 데스크, 2026-11-10).

영어 큐(content/english_queue/<날짜>.json 의 aptitude 3문항)를 보충할 때 쓴다. 정답은 식으로 계산하고,
보기는 scripts/apt_daily_check.py 규칙 v1(R1 오름차순 · R2 정답 자리 = plan · R3 함정 값 ≠ 정답 · R4 서로 다른 값)에 맞춰 놓는다.
평가 데스크 발견(분모 혼동·역산 약점)에 맞춘 유형만 둔다. 수치는 모두 가상 예시(실제 시세·개인 수치 아님).

유형(kind)과 인자:
  inv      전 값 역산        subj('~이'), unit, now, r(부호 있는 %), dec, verb(선택: '늘어'·'줄어')
  base     기준(분모) 비교   q, a, b            — 'a 는 b 보다 몇 % 큰가' (a > b)
  share    구성비            q, parts{이름: 값}, target, den[이름…]
  recover  회복에 필요한 %   x(부호: −20 = 20% 떨어진 뒤 회복 상승률, +25 = 25% 오른 뒤 되돌림 하락률)
  compound 누적 증감률       q, a, b(부호 있는 %)
  pp       %와 %p            q, a, b(비율 %, a → b)

  from apt_gen import make
  item = make("inv", pos=2, seed="2026-11-11-0", subj="한 카페의 원두 값이", unit="원", now=18400, r=-8, dec=0)
"""
from __future__ import annotations

import hashlib
import random

N = 5


def _f(v: float, dec: int, unit: str) -> str:
    s = f"{abs(v):,.{dec}f}"
    return ("−" if round(v, dec) < 0 else "") + s + unit


def _place(c: float, traps: list[tuple[str, float]], pos: int, dec: int, unit: str, seed: str, step: float | None):
    """정답 c 를 pos 자리에 두고 오름차순 5지. 함정은 방향이 맞는 것만 남기고(최소 1개 필요) 나머지는 간격을 둔 오답으로 채운다."""
    q = 10 ** -dec
    r = lambda v: round(v, dec)  # noqa: E731
    c = r(c)
    rng = random.Random(int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16))
    gap = max(2 * q, r(step if step else abs(c) * 0.035))
    seen, lo, hi = {c}, [], []
    for name, v in traps:
        v = r(v)
        if v in seen or abs(v - c) < 2 * q:
            continue
        seen.add(v)
        (lo if v < c else hi).append((name, v))
    lo = sorted(lo, key=lambda t: c - t[1])[:pos]            # 정답에 가까운 함정부터
    hi = sorted(hi, key=lambda t: t[1] - c)[:N - 1 - pos]
    if not lo and not hi:
        raise ValueError(f"자리 {pos + 1}에 놓을 함정이 없다 — 유형·입력을 바꾼다 (c={c}, traps={traps})")
    vals = {c} | {v for _, v in lo + hi}

    def fill(side: list, need: int, sign: int):
        k, out, guard = 1, [], 0
        while len(side) + len(out) < need and guard < 200:
            guard += 1
            v = r(c + sign * gap * (k + rng.uniform(-0.25, 0.25)))
            k += 1
            if all(abs(v - x) >= 2 * q for x in vals) and (unit != "%" or sign > 0 or v > 0 or c <= 0):
                vals.add(v)
                out.append(v)
        if len(side) + len(out) < need:
            raise ValueError("오답 채우기 실패")
        return out

    below = [v for _, v in lo] + fill(lo, pos, -1)
    above = [v for _, v in hi] + fill(hi, N - 1 - pos, +1)
    order = sorted(below) + [c] + sorted(above)
    assert order == sorted(order) and len(set(order)) == N and order.index(c) == pos
    ch = [_f(v, dec, unit) for v in order]
    assert len(set(ch)) == N
    return ch, [{"name": n, "value": _f(v, dec, unit)} for n, v in lo + hi]


def make(kind: str, pos: int, seed: str, **kw) -> dict:
    dec, step = kw.get("dec", 1), kw.get("step")
    if kind == "inv":
        now, rr, unit = kw["now"], kw["r"], kw["unit"]
        dec = kw.get("dec", 2)
        m = 1 + rr / 100
        c = now / m
        word = kw.get("verb") or ("올라" if rr > 0 else "내려")
        q = f"{kw['subj']} 전날보다 {abs(rr):g}% {word} {_f(now, dec, unit)}이 되었다. 전날 값에 가장 가까운 것은?"
        traps = [("나눗셈 대신 곱셈 — 오늘 값에 같은 %를 반대로 적용", now * (2 - m)),
                 ("방향 반대 — 오늘 값에 같은 변화를 한 번 더", now * m)]
        typ = "자료해석(역산 · 전날 = 오늘 ÷ (1+r))"
        exp = (f"① 분모 동그라미: 변화율의 기준은 '전날'(모르는 값). 오늘 = 전날 × {m:g} → 전날 = {_f(now, dec, unit)} ÷ {m:g} ≈ {_f(c, dec, unit)}. "
               f"② 거꾸로 검산: {_f(c, dec, unit)} × {m:g} ≈ {_f(round(c, dec) * m, dec, unit)} ✓.")
        t = 50
    elif kind == "base":
        a, b, unit = kw["a"], kw["b"], "%"
        c = (a - b) / b * 100
        q = kw["q"]
        traps = [("분모 바꿔치기 — 큰 쪽(앞의 값)으로 나눔", (a - b) / a * 100),
                 ("비율을 그대로 — 작은 쪽 ÷ 큰 쪽을 답으로", b / a * 100)]
        typ = "자료해석(증감률 · 기준 = '~보다' 앞의 말)"
        exp = (f"① 분모 동그라미: '~보다' 앞에 오는 값이 기준 = {b:g}. 차이 = {a:g} − {b:g} = {a - b:g}. "
               f"② {a - b:g} ÷ {b:g} ≈ {c:.{dec}f}%. ③ 거꾸로 검산: {b:g} × (1 + {c / 100:.3f}) ≈ {b * (1 + round(c, dec) / 100):.1f} ≈ {a:g} ✓.")
        t = 45
    elif kind == "share":
        parts, tg, den, unit = kw["parts"], kw["target"], kw["den"], "%"
        tot = sum(parts[k] for k in den)
        c = parts[tg] / tot * 100
        q = kw["q"]
        traps = [(f"방향 반대 — {k}의 비중", parts[k] / tot * 100) for k in den if k != tg]
        allsum = sum(parts.values())
        if allsum != tot:
            traps.append(("분모에 전부 넣음 — 묻지 않은 항목까지 합계에 포함", parts[tg] / allsum * 100))
        others = tot - parts[tg]
        if others:
            traps.append(("분모 바꿔치기 — 나머지 대비 비율", parts[tg] / others * 100))
        typ = "자료해석(구성비 · 분모 = 묻는 범위의 합계)"
        exp = (f"① 분모 동그라미: 묻는 범위의 합계 = {' + '.join(f'{parts[k]:g}' for k in den)} = {tot:g}. "
               f"② {parts[tg]:g} ÷ {tot:g} ≈ {c:.{dec}f}%. ③ 거꾸로 검산: {tot:g} × {c / 100:.3f} ≈ {tot * round(c, dec) / 100:.1f} ≈ {parts[tg]:g} ✓.")
        t = 40
    elif kind == "recover":
        x, unit = kw["x"], "%"
        if x < 0:
            d = -x
            c = d / (100 - d) * 100
            q = kw.get("q") or f"어떤 값이 {d:g}% 떨어졌다. 떨어지기 전 값으로 돌아가려면 지금 값에서 몇 % 올라야 하는가? (가장 가까운 값)"
            exp = (f"① 분모 동그라미: 올라야 할 %의 기준은 '지금 값'(= 처음의 {100 - d:g}%). ② 필요한 폭 {d:g} ÷ 기준 {100 - d:g} ≈ {c:.{dec}f}%. "
                   f"③ 거꾸로 검산: {100 - d:g} × (1 + {c / 100:.3f}) ≈ {(100 - d) * (1 + round(c, dec) / 100):.1f} ≈ 100 ✓.")
            traps = [("같은 %면 된다는 착각 — 기준이 바뀐 걸 놓침", d), ("처음 값 기준 계산을 한 번 더 — (1 + 하락률)을 곱함", d * (1 + d / 100))]
        else:
            c = x / (100 + x) * 100
            q = kw.get("q") or f"어떤 값이 {x:g}% 올랐다. 오르기 전 값으로 돌아가려면 지금 값에서 몇 % 내려야 하는가? (가장 가까운 값)"
            exp = (f"① 분모 동그라미: 내려야 할 %의 기준은 '지금 값'(= 처음의 {100 + x:g}%). ② 되돌릴 폭 {x:g} ÷ 기준 {100 + x:g} ≈ {c:.{dec}f}%. "
                   f"③ 거꾸로 검산: {100 + x:g} × (1 − {c / 100:.3f}) ≈ {(100 + x) * (1 - round(c, dec) / 100):.1f} ≈ 100 ✓.")
            traps = [("같은 %면 된다는 착각 — 기준이 바뀐 걸 놓침", x), ("처음 값 기준 계산을 한 번 더 — (1 − 상승률)을 곱함", x * (1 - x / 100))]
        typ = "자료해석(필요 변화율 · 기준 = 지금 값)"
        t = 40
    elif kind == "compound":
        a, b, unit = kw["a"], kw["b"], "%"
        c = ((1 + a / 100) * (1 + b / 100) - 1) * 100
        q = kw["q"]
        traps = [("단순 합산 — 두 %를 그냥 더함", a + b), ("두 번째 변화만 봄", b), ("첫 번째 변화만 봄", a)]
        typ = "자료해석(누적 증감률 · 곱으로 잇기)"
        exp = (f"① 분모 동그라미: 두 번째 %의 기준은 '첫 변화 뒤의 값'. ② {1 + a / 100:g} × {1 + b / 100:g} = {(1 + a / 100) * (1 + b / 100):.4f} → {c:+.{dec}f}%. "
               f"③ 단순 합산({a + b:+g}%)과 {abs(c - (a + b)):.{dec}f}%p 차이가 난다.").replace("-", "−")
        t = 45
    elif kind == "pp":
        a, b, unit = kw["a"], kw["b"], "%"
        c = (b - a) / a * 100
        q = kw["q"]
        traps = [("%p를 %로 — 두 비율의 차이를 그대로 답함", b - a), ("분모 바꿔치기 — 나중 비율로 나눔", (b - a) / b * 100),
                 ("배율을 증가율로 — 나중 ÷ 처음을 그대로", b / a * 100)]
        typ = "자료해석(%와 %p · 비율의 증가율)"
        exp = (f"① 분모 동그라미: '몇 % 늘었나'의 기준은 처음 비율 {a:g}%. 차이 = {b - a:g}%p(퍼센트포인트). "
               f"② {b - a:g} ÷ {a:g} ≈ {c:.{dec}f}%. ③ 거꾸로 검산: {a:g} × (1 + {c / 100:.3f}) ≈ {a * (1 + round(c, dec) / 100):.2f} ≈ {b:g} ✓.").replace("-", "−")
        t = 45
    else:
        raise ValueError(kind)
    ch, used = _place(c, traps, pos, dec, unit, seed, step)
    exp += " 함정: " + " / ".join(f"{u['value']} = {u['name']}" for u in used) + "."
    return {"type": typ, "q": q, "choices": ch, "a": pos, "traps": used, "exp_ko": exp, "time_sec": t}
