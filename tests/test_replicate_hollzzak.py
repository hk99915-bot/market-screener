"""합성 데이터로 replicate_hollzzak 의 사건 분류·에피소드·정확검정 확인 (네트워크·data/hist 불필요)."""
import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import replicate_hollzzak as rh  # noqa: E402


def _series(rets):
    c, out = 100.0, [100.0]
    for r in rets:
        c *= 1 + r
        out.append(c)
    d0 = date(2015, 1, 1)
    return [d0 + timedelta(days=i) for i in range(len(out))], out


def test_classify_first_re_consec_bigup_episode():
    # 0:평 1:폭락(first) 2:반등 3:폭락(re — 1의 익일 반등) 4:폭락(re 유지: 1 이 창 안) 5:+4% 양봉(big_up)
    # 6~20: 평평 21:폭락(first, 새 에피소드 — 간격 > 10) 22:폭락(consec — 21 익일 반등 없음)
    rets = [0.0, -0.04, 0.01, -0.035, -0.031, 0.04] + [0.001] * 15 + [-0.05, -0.04, 0.002]
    dates, close = _series(rets)
    rows = rh.build_events(dates, close, {dates[6]: 0.05})
    kind = {i: x["kind"] for i, x in enumerate(rows) if x["kind"]}
    assert kind == {2: "first", 4: "re", 5: "re", 22: "first", 23: "consec"}
    assert rows[6]["big_up"] and rows[6]["side_px"] and rows[6]["ep"] == rows[5]["ep"] == 0
    assert rows[22]["ep"] == 1


def test_exact_tests():
    assert math.isclose(rh.binom_upper(3, 3, 0.5), 0.125)
    # 재 0/4 vs 첫 4/4 → 단측 Fisher = 1/C(8,4)
    assert math.isclose(rh.fisher_lower(0, 4, 4, 4), 1 / 70)


def test_grade_rules():
    mk = lambda n, ep, e, p: {"first": {"n": n, "episodes": ep}, "H1": {"effect": e, "p": p}}
    by = {"design": mk(13, 10, 0.02, 0.5), "valid": mk(16, 14, 0.2, 0.08), "pooled": mk(29, 24, 0.12, 0.12)}
    assert rh.grade(by, "H1") == ("F", "기각")
    by["pooled"]["H1"]["p"] = 0.05
    assert rh.grade(by, "H1") == ("C", "보류")
    by["valid"]["H1"]["effect"] = -0.01
    assert rh.grade(by, "H1")[0] == "F"
