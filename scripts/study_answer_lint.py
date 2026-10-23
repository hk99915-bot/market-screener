#!/usr/bin/env python3
"""STUDY 문항 '정답 ↔ 해설·계산' 모순 자동 검사 (교육 데스크, 10/24 겸이 결재 G2 와 묶음).

계기: 10/24 아침 겸이 제보 — 0트랙 %p 문항의 정답이 '둘 다 표현만 다름'이었는데 해설은 '%p 와 % 를 구분해야'(deb1d643 정정).
문항 220개(quiz_bank 125 + 모듈 4지 95) + 구형 175개를 사람이 매번 다 읽을 수 없으니, 기계가 볼 수 있는 모순만 잡는다.

검사(실패 = study_content_check 가 막음, 경고 = 사람이 볼 것):
  ① 계산 검산(실패)   — 문항·해설·공식 예시의 `식 = 값`, `식 ≈ 값` 을 실제로 계산해 틀리면 실패. √·²·½·^·÷·× 지원,
                        % 는 단위로 보고 값·×100·÷100 중 하나가 맞으면 통과(0.392 = 39.2%). 유효숫자: 덜 정밀한 쪽 반올림 + 상대 0.6%(≈ 는 2%).
  ② 정답 키 ↔ 해설 결과(실패) — 숫자 선택지 문항에서 해설의 마지막 결과값(=·≈·→ 뒤 숫자)이 **오답지** 숫자와 맞고 정답 숫자와는
                        어느 결과에도 안 맞으면 '정답 키가 다른 자리'로 본다. 10/24 변이 시험: 숫자 문항 39개 × 오답 자리 3 = 117건 중 66건 검출(56%), 현 콘텐츠 오탐 0.
  ③ 얼버무린 정답(실패) — '누가 맞나/어느 쪽이 맞나' 문항의 정답이 '둘 다 …/표현만 다름/같은 말' (10/24 %p 사례 그대로).
  ④ O/X 극성(실패)     — 정답 O 인데 해설이 '아니다/틀리다/반대' 로 시작(또는 X 인데 '맞다/그렇다' 로 시작).
  ⑤ 구형 계산 문항(경고) — 정답 `a` 의 숫자가 해설 결과값 어디에도 없음(해설이 정답까지 안 가는 경우 포함).
한계: 말로 된 판단 문항(응용·상황)의 논리 모순은 못 본다 — 그건 출제자≠검수자 교차 검수(LOOP 피어 항목, G2)로 막는다.

  python scripts/study_answer_lint.py        # 콘텐츠 전체 검사, 실패 시 종료코드 1
"""
from __future__ import annotations

import ast
import operator as _op
import re
import sys
from pathlib import Path

ALLOWED = set("0123456789.,+-*/()% √²³½^")
_OPS = {ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul, ast.Div: _op.truediv, ast.Pow: _op.pow,
        ast.USub: _op.neg, ast.UAdd: _op.pos}
HAS_OP = re.compile(r"[\d)²³]\s*[-+*/^]\s*[\d(√½]|√|²|³|½")
_KO_UNITS = (("억", 1e8), ("만", 1e4), ("천", 1e3))


def norm(t: str) -> str:
    return str(t).replace("−", "-").replace("–", "-").replace("×", "*").replace("÷", "/").replace("＝", "=")


def _ev(n):
    if isinstance(n, ast.Expression):
        return _ev(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return float(n.value)
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        a, b = _ev(n.left), _ev(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > 12:
            raise ValueError("지수 과대")
        return _OPS[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
        return _OPS[type(n.op)](_ev(n.operand))
    if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "sqrt" and len(n.args) == 1:
        return _ev(n.args[0]) ** 0.5
    raise ValueError("허용 안 된 식")


def value(expr: str) -> float | None:
    """'1/0.7 − 1', '√1.44 − 1', '(0.5×40)²', '3,200 × 1,000 ÷ 8' → 값. 식이 아니면 None (eval 미사용, ast 화이트리스트)."""
    e = norm(expr).strip()
    if not e or not re.search(r"\d", e) or len(e) > 120:
        return None
    x = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", e)
    if "," in x:
        return None
    x = x.replace("%", "").replace("^", "**").replace("½", "(1/2)").replace("²", "**2").replace("³", "**3")
    x = re.sub(r"√\s*(\d+(?:\.\d+)?|\([^()]*\))", r"sqrt(\1)", x)
    if "√" in x:
        return None
    try:
        return _ev(ast.parse(x, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None


def _tail(seg: str) -> str | None:
    """'=' 왼쪽 조각의 끝에 붙은 산술식. 식별자·함수 호출(C(5,2))·비율(a : b)에 붙은 것은 버린다."""
    i = len(seg)
    while i > 0 and seg[i - 1] in ALLOWED:
        i -= 1
    e = seg[i:].strip()
    if not e or seg[:i].rstrip().endswith(":"):
        return None
    if e[0] in "+*/)%,^":
        return None
    prev = seg[i - 1] if i > 0 else ""
    if prev and (prev.isalnum() or prev in "_'’") and (e[0] in "(-" or e[0].isdigit()):
        return None
    return e


def _head(seg: str) -> tuple[str, float] | None:
    """'=' 오른쪽 조각의 앞머리 식(또는 숫자)과 값. 문장 끝 '. ' 에서 멈춘다."""
    j = 0
    while j < len(seg) and seg[j] in ALLOWED:
        j += 1
    e = seg[:j]
    m = re.search(r"\.\s", e)
    if m:
        e = e[:m.start()]
    if seg[len(e):].lstrip().startswith(":"):
        return None
    while e:
        es = e.rstrip(" .,")
        if es and es.count("(") == es.count(")"):
            v = value(es)
            if v is not None:
                return es, v
        e = e[:-1]
    return None


def _decimals(e: str) -> int:
    nums = re.findall(r"\d+(?:\.(\d+))?", e)
    return len(nums[-1]) if nums and nums[-1] else 0


def _close(a: float, b: float, rel: float = 0.006, ab: float = 0.0) -> bool:
    """a ≈ b (또는 b 를 % 단위로 본 b/100, b×100). 절대 허용오차 ab 도 같은 배율로 줄인다."""
    return any(abs(a - b * k) <= max(rel * max(abs(a), abs(b * k)), ab * k) + 1e-12 for k in (1, 0.01, 100))


def arith_errors(text: str) -> list[str]:
    """① `식 = 값` 검산. 틀린 줄 설명 목록."""
    out = []
    parts = re.split(r"(=|≈)", norm(text))
    for k in range(1, len(parts) - 1, 2):
        left = _tail(parts[k - 1])
        right = _head(parts[k + 1])
        if left is None or right is None:
            continue
        rexpr, rv = right
        if not (HAS_OP.search(left) or HAS_OP.search(rexpr)):
            continue
        lv = value(left)
        if lv is None:
            continue
        ab = max(0.5 * 10 ** -_decimals(rexpr), 0 if HAS_OP.search(left) else 0.5 * 10 ** -_decimals(left))
        if not _close(lv, rv, 0.02 if parts[k] == "≈" else 0.006, ab):
            out.append(f"'{left.strip()} {parts[k]} {rexpr.strip()}' 계산하면 {lv:.6g}")
    return out


_NUM = re.compile(r"([+-]?)\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(억|만|천)?")


def first_num(text: str, units: bool = True) -> float | None:
    """첫 숫자. units=True 면 '13만 5천' → 135000, False 면 단위 무시(13)."""
    m = _NUM.search(norm(text))
    if not m:
        return None
    v = float(m.group(2).replace(",", ""))
    for u, mul in (_KO_UNITS if units else ()):
        if m.group(3) == u:
            v *= mul
            rest = norm(text)[m.end():]
            n2 = re.match(r"\s*(\d+)\s*천", rest)   # '13만 5천'
            if u == "만" and n2:
                v += float(n2.group(1)) * 1e3
    return -v if m.group(1) == "-" else v


def results(why: str) -> list[float]:
    """해설의 결과값들: '=', '≈', '→' 뒤(짧은 단어 하나 건너뛰기 허용 — '→ 비율 3.0')의 식·숫자 값."""
    n = norm(why)
    out = []
    for m in re.finditer(r"(=|≈|→)\s*(?:[^\d\s=≈→.()+-]{1,8}\s+)?", n):
        h = _head(n[m.end():])
        if h:
            out.append(h[1])
    return out


def _hit(v: float, rs: list[float]) -> bool:
    return any(_close(v, r, ab=0.051) or _close(abs(v), abs(r), ab=0.051) for r in rs)


def key_error(q: dict) -> str | None:
    """② 숫자 선택지 문항: 해설 마지막 결과가 오답지와 맞고 정답과는 어느 결과에도 안 맞으면 메시지."""
    ch, a = q.get("choices"), q.get("answer")
    if not isinstance(ch, list) or not isinstance(a, int) or not 0 <= a < len(ch):
        return None
    rs = results(q.get("why", ""))
    nums = [first_num(c) for c in ch]
    have = [x for x in nums if x is not None]
    if not rs or nums[a] is None or len(have) < 3 or len(set(have)) < len(have):
        return None
    if _hit(nums[a], rs):
        return None
    wrong = [j for j, x in enumerate(nums) if j != a and x is not None and _hit(x, rs[-1:])]
    if wrong:
        return f"해설 결과 {rs[-1]:.6g} 가 오답지 [{wrong[0]}] '{ch[wrong[0]]}' 와 맞고 정답 [{a}] '{ch[a]}' 와는 안 맞음 — 정답 키 확인"
    return None


_WHO = re.compile(r"누가 (맞|옳)|어느 (쪽|것)이 (맞|옳)|어느 쪽 말이")
_HEDGE = re.compile(r"둘 다|모두 맞|표현만 다|같은 말")
_NEG = re.compile(r"^\s*(아니다|아님|아니오|틀리다|틀림|틀렸|반대|거짓|그렇지 않)")
_POS = re.compile(r"^\s*(맞다|맞음|그렇다|옳다|참이다)")


def answer_text(q: dict) -> str:
    if isinstance(q.get("choices"), list) and isinstance(q.get("answer"), int) and 0 <= q["answer"] < len(q["choices"]):
        return str(q["choices"][q["answer"]])
    return str(q.get("a", ""))


def item_errors(q: dict) -> list[str]:
    """문항 하나의 ①~④ 실패 사유."""
    errs = []
    for k in ("q", "why", "a"):
        for e in arith_errors(q.get(k, "") or ""):
            errs.append(f"{k} 계산 불일치 {e}")
    for j, c in enumerate(q.get("choices") or []):
        for e in arith_errors(str(c)):
            errs.append(f"choices[{j}] 계산 불일치 {e}")
    ke = key_error(q)
    if ke:
        errs.append(ke)
    if _WHO.search(q.get("q", "")) and _HEDGE.search(answer_text(q)):
        errs.append(f"'누가 맞나' 문항인데 정답이 얼버무림 '{answer_text(q)[:30]}' — 맞는 쪽을 정답으로 (10/24 %p 사례)")
    if q.get("t") == "O/X":
        a, why = str(q.get("a", "")).strip()[:1], q.get("why", "")
        if (a == "O" and _NEG.search(why)) or (a == "X" and _POS.search(why)):
            errs.append(f"O/X 극성 모순 — 정답 {a} 인데 해설이 '{why[:12]}…' 로 시작")
    return errs


def item_warnings(q: dict) -> list[str]:
    """⑤ 구형 계산 문항: 정답 숫자가 해설 결과에 없음."""
    if q.get("t") != "계산" or "choices" in q:
        return []
    a = str(q.get("a", ""))
    if re.search(r"\d{1,2}:\d{2}", a):   # 시각(22:30)은 산술 결과가 아님
        return []
    v, rs = first_num(a), results(q.get("why", ""))
    if v is None or not rs or _hit(v, rs) or _hit(first_num(a, units=False), rs):
        return []
    return [f"정답 '{a[:20]}' 의 숫자가 해설 결과({', '.join(f'{r:.4g}' for r in rs[-3:])})에 없음 — 해설이 정답까지 가는지 확인"]


def text_fields(m: dict):
    """모듈의 문항 밖 계산 텍스트(공식·예시·개념) — ① 만 적용."""
    for i, f in enumerate(m.get("formulas", []) or []):
        if isinstance(f, dict):
            for k in ("f", "example", "note"):
                if f.get(k):
                    yield f"formulas[{i}].{k}", f[k]
    for k in ("concepts", "pitfalls", "example"):
        v = m.get(k)
        if isinstance(v, list):
            for i, x in enumerate(v):
                if isinstance(x, str):
                    yield f"{k}[{i}]", x
        elif isinstance(v, str):
            yield k, v


def lint(S: dict) -> tuple[list[str], list[str]]:
    """study_content_check.load_sources() 결과 → (실패, 경고)."""
    errs: list[str] = []
    warns: list[str] = []
    for t in S.get("tracks", []):
        for m in t.get("modules", []):
            mid = m.get("id", "?")
            for i, q in enumerate(m.get("quiz", []) or []):
                errs += [f"{mid}.quiz[{i}]: {e}" for e in item_errors(q)]
                warns += [f"{mid}.quiz[{i}]: {w}" for w in item_warnings(q)]
            for where, txt in text_fields(m):
                errs += [f"{mid}.{where}: 계산 불일치 {e}" for e in arith_errors(txt)]
    for it in (S.get("quiz_bank") or {}).get("items", []):
        errs += [f"quiz_bank.{it.get('id')}: {e}" for e in item_errors(it)]
    for it in (S.get("aptitude") or {}).get("items", []):
        for k in ("q", "exp", "why"):
            errs += [f"aptitude.{it.get('id')}.{k}: 계산 불일치 {e}" for e in arith_errors(it.get(k, "") or "")]
    return errs, warns


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import study_content_check as scc
    errs, warns = lint(scc.load_sources())
    for w in warns:
        print("WARN", w)
    for e in errs:
        print("FAIL", e)
    print(f"{'ok' if not errs else str(len(errs)) + ' errors'}: 정답↔해설 검사, 경고 {len(warns)}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
