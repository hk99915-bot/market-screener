"""RTMS 백필·반복매매 하락폭 비교 — 네트워크 없음(가짜 get)."""
import json

from screener import realestate_hist as h
from screener.realestate import GU_CODES


def _xml(items):
    body = "".join("<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in it.items()) + "</item>" for it in items)
    return f"<response><header><resultCode>000</resultCode></header><body><items>{body}</items><totalCount>{len(items)}</totalCount></body></response>".encode()


def test_months_range():
    assert h.months("202111", "202202") == ["202111", "202112", "202201", "202202"]
    assert len(h.months()) == 30


def test_compact_drops_cancel_and_keeps_fields():
    rows = h.compact([{"dealAmount": "120,000", "excluUseAr": "59.97", "umdNm": "망원동", "aptNm": "A", "aptSeq": "11440-1",
                       "floor": "5", "dealDay": "3", "buildYear": "1999"},
                      {"dealAmount": "100,000", "excluUseAr": "59.97", "cdealType": "O"}], "202201")
    assert len(rows) == 1 and rows[0]["p"] == 120000 and rows[0]["seq"] == "11440-1" and rows[0]["by"] == 1999


def test_backfill_resume_and_no_key_in_output(tmp_path):
    calls = []

    def get(url, params):
        calls.append(params["DEAL_YMD"])
        return _xml([{"dealAmount": "50,000", "excluUseAr": "59.9", "umdNm": "d", "aptNm": "a", "aptSeq": "s", "floor": "3", "dealDay": "1"}])

    s = h.backfill(get, "SECRETKEY", ["202110", "202111"], out_dir=tmp_path, max_calls=10)
    assert s["calls"] == 10 and s["done"] == 10
    s2 = h.backfill(get, "SECRETKEY", ["202110", "202111"], out_dir=tmp_path, max_calls=1000)
    assert s2["done"] == 2 * len(GU_CODES)
    assert len(calls) == 2 * len(GU_CODES)     # 이어받기: 완료 월 재호출 없음
    blob = "".join(p.read_text() for p in tmp_path.iterdir())
    assert "SECRETKEY" not in blob


def test_backfill_failure_scrubs_key(tmp_path):
    def get(url, params):
        raise RuntimeError(f"boom serviceKey={params['serviceKey']}")
    s = h.backfill(get, "SECRETKEY", ["202110"], out_dir=tmp_path, max_calls=3)
    assert s["failed"] and all("SECRETKEY" not in f["why"] for f in s["failed"])


def _rows(peak, trough, rec, seq="s", fl="5"):
    out = []
    for ym, p in (("202201", peak), ("202301", trough), ("202311", rec)):
        if p is not None:
            out.append({"ym": ym, "d": "1", "dong": "d", "apt": "a", "seq": seq, "a": "59.9", "fl": fl, "p": str(p), "by": ""})
    return out


def test_pairs_drop_and_recovery():
    ps = h.pairs({"강남구": _rows(100, 80, 90)})
    assert len(ps) == 1 and abs(ps[0]["drop"] + 0.2) < 1e-9 and abs(ps[0]["recov"] - 0.5) < 1e-9 and ps[0]["inside"]
    assert h.pairs({"강남구": _rows(100, 80, 90, fl="1")}, min_floor=3) == []


def test_judge_support_reject_hold():
    ins = {"n_pairs": 40, "drop_med": -0.10, "recov_med": 0.5}
    assert h.judge(ins, {"n_pairs": 40, "drop_med": -0.20, "recov_med": 0.3})["verdict"] == "지지"
    assert h.judge(ins, {"n_pairs": 40, "drop_med": -0.12, "recov_med": 0.3})["verdict"] == "기각"
    assert h.judge(ins, {"n_pairs": 40, "drop_med": -0.20, "recov_med": 0.6})["verdict"] == "기각"
    assert h.judge(ins, {"n_pairs": 10, "drop_med": -0.20, "recov_med": 0.3})["verdict"] == "보류"


def test_analyze_end_to_end_excludes_junggu():
    rows = {"강남구": [r for i in range(35) for r in _rows(100, 90, 98, seq=f"i{i}")],
            "노원구": [r for i in range(35) for r in _rows(100, 75, 80, seq=f"o{i}")],
            "중구": _rows(100, 10, 10)}
    res = h.analyze(rows)
    j = res["all_floors"]["judge"]
    assert j["verdict"] == "지지" and j["ratio_out_in"] == 2.5
    assert "중구" not in res["by_gu"]
    json.dumps(res, ensure_ascii=False)
