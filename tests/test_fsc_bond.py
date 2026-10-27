from datetime import date

from screener import fsc_bond as f


def _js(items):
    return {"response": {"body": {"items": {"item": items}, "totalCount": len(items)}}}


ROWS = [
    {"itmsNm": "국고03250-2903(25-1)", "clprBnfRt": "3.79"},    # 잔존 ≈ 2.37년(2026-10-27 기준) → 제외
    {"itmsNm": "국고02750-2909(26-5)", "clprBnfRt": "3.80"},    # ≈ 2.87년 → 3.0년에 가장 가까움
    {"itmsNm": "국고03000-3003(26-1)", "clprBnfRt": "3.70"},    # ≈ 3.37년
    {"itmsNm": "통안0300-2702-01", "clprBnfRt": "3.0"},          # 국고 아님
    {"itmsNm": "국고03000-3006(26-3)", "clprBnfRt": "-"},        # 수익률 없음
]


def test_maturity_parse():
    assert f.maturity("국고02750-2909(26-5)") == date(2029, 9, 10)
    assert f.maturity("회사채") is None


def test_ktb_3y_pick_and_compare():
    r = f.ktb_3y(ROWS, date(2026, 10, 27))
    assert r["name"].startswith("국고02750-2909") and r["yield"] == 3.80 and r["n_band"] == 2
    c = f.compare(r, 3.758)
    assert c["gap_bp"] == 4.2 and c["match"] is False
    assert f.compare(r, None)["status"].startswith("비교 대상 없음")


def test_run_no_key(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "OUT", tmp_path / "o.json")
    assert f.run(env={})["status"] == "키 대기"


def test_run_fake_get_hides_key(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "OUT", tmp_path / "o.json")

    def get(p):
        return _js(ROWS) if p["basDt"] == "20261026" else _js([])

    st = f.run(get=get, env={"DATA_GO_KR_KEY": "SECRETX9"}, days=2, today=date(2026, 10, 27), krx=lambda d: 3.79)
    assert st["status"] == "ok" and st["match_rate"] == 1.0
    assert "SECRETX9" not in (tmp_path / "o.json").read_text()
