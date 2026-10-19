import json
from screener.json_safe import dumps


def test_nonfinite_nested_prices_are_null_without_changing_text():
    raw = dumps({"chart": [{"p": float("nan"), "c": 146.03}], "x": [float("inf"), -float("inf")], "label": "NaN Infinity", "missing": None})
    obj = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    assert obj == {"chart": [{"p": None, "c": 146.03}], "x": [None, None], "label": "NaN Infinity", "missing": None}


def test_sol_always_in_required_etfs():
    from screener.etf import KR_MUST
    assert "475310" in KR_MUST
