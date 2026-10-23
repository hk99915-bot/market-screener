"""정답 ↔ 해설·계산 모순 검사 (scripts/study_answer_lint.py) — 10/24 %p 정답 오류(deb1d643) 계기, G2 와 묶음. 네트워크 없음."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import study_answer_lint as L  # noqa: E402
import study_content_check as scc  # noqa: E402


@pytest.fixture(scope="module")
def S():
    return scc.load_sources()


def test_real_content_has_no_contradiction(S):
    errs, warns = L.lint(S)
    assert errs == [] and warns == [], "\n".join(errs + warns)


def test_value_parses_korean_math_notation():
    assert L.value("1/0.7 − 1") == pytest.approx(0.428571, rel=1e-4)
    assert L.value("√1.44 − 1") == pytest.approx(0.2)
    assert L.value("(0.5×40)²") == pytest.approx(400)
    assert L.value("½ × 12 × (20 − 8)") == pytest.approx(72)
    assert L.value("3,200 × 1,000 ÷ 8") == pytest.approx(400000)
    assert L.value("(144 ÷ 100)^(1/2) − 1") == pytest.approx(0.2)
    assert L.value("__import__('os')") is None and L.value("9**99999") is None


def test_arith_ok_and_wrong():
    assert L.arith_errors("회복 수익률 = 1/(1−손실) − 1 = 1/0.7 − 1 ≈ 42.9%") == []
    assert L.arith_errors("0.4 ÷ 1.02 = 0.392") == []
    assert L.arith_errors("(3 − 2) ÷ 2 = 50%") == []
    assert L.arith_errors("WACC = 0.6×10 + 0.4×5×0.75 = 6 + 1.5 = 7.5%") == []
    assert L.arith_errors("(0.5×40)² : (0.5×10)² = 400 : 25") == []          # 비율 표기는 건너뜀
    assert L.arith_errors("C(3,2)/C(5,2) = 3/10") == []                       # 함수 표기는 건너뜀
    assert L.arith_errors("1/0.7 − 1 ≈ 38.2%")                                 # 틀린 검산
    assert L.arith_errors("0.6×4 − 0.4×8 = 2.4 − 3.2 = +0.8%")                 # 부호 오류


def test_percent_point_case_from_1024_is_caught():
    """deb1d643 이전 0트랙 문항 그대로 — 정답이 '둘 다 표현만 다름'."""
    old = {"t": "응용", "q": "금리가 2%에서 3%로 올랐다. 기사 A '1% 상승', 기사 B '50% 상승'. 누가 맞나?",
           "a": "둘 다 표현만 다름 — 정확히는 '1%p 상승(50% 증가)'", "why": "%p와 %를 구분해야 오해가 없다."}
    assert any("얼버무림" in e for e in L.item_errors(old))
    new = dict(old, a="B가 맞다 — 2%→3%는 1%p 상승이고 비율로는 50% 상승. A의 '1% 상승'은 %p를 %로 잘못 쓴 것",
               why="%p = 3% − 2% = 1%p. % 변화 = (3 − 2) ÷ 2 = 50%.")
    assert L.item_errors(new) == []


def test_key_moved_to_distractor_is_caught(S):
    it = next(q for q in S["quiz_bank"]["items"] if q["id"] == "R1-b1")       # −30% 회복 = 42.9%
    assert L.item_errors(it) == []
    bad = copy.deepcopy(it)
    bad["answer"] = (it["answer"] + 1) % 4
    assert any("정답 키" in e for e in L.item_errors(bad))


def test_key_mutation_detection_rate(S):
    """숫자 선택지 문항의 정답 키를 오답 자리로 옮긴 변이 중 절반 이상을 잡는다(10/24 실측 66/117)."""
    items = list(S["quiz_bank"]["items"]) + [q for t in S["tracks"] for m in t["modules"] for q in m.get("quiz", []) if "choices" in q]
    tot = det = 0
    for q in items:
        if sum(L.first_num(c) is not None for c in q["choices"]) < 3 or not L.results(q.get("why", "")):
            continue
        for j in range(4):
            if j != q["answer"]:
                tot += 1
                det += bool(L.key_error(dict(q, answer=j)))
    assert tot >= 60 and det / tot >= 0.5, (det, tot)


def test_ox_polarity_and_legacy_calc_warning():
    assert L.item_errors({"t": "O/X", "q": "q", "a": "O", "why": "아니다 — 반대로 움직인다."})
    assert L.item_errors({"t": "O/X", "q": "q", "a": "X", "why": "반대 — 이익은 빨리, 손실은 오래."}) == []
    assert L.item_warnings({"t": "계산", "q": "유럽형 콜=6, 풋은?", "a": "6", "why": "C − P = S − K = 0."})
    assert L.item_warnings({"t": "계산", "q": "q", "a": "6", "why": "C − P = S − K = 0 → P = C = 6."}) == []
    assert L.item_warnings({"t": "계산", "q": "q", "a": "13만 5천 원", "why": "100 × 1,350 = 135,000원."}) == []


def test_checker_blocks_contradiction(S):
    qb = copy.deepcopy(S["quiz_bank"])
    it = next(q for q in qb["items"] if q["id"] == "R1-b1")
    it["answer"] = (it["answer"] + 1) % 4
    assert any("정답↔해설" in e for e in scc.check_all({**S, "quiz_bank": qb}).errors)


def test_cli_ok():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "study_answer_lint.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
