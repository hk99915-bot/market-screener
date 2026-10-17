"""screener.valuation.us_all — 합성 SEC long parquet 으로 US 가치평가 검사 (네트워크 없음).
(a) 키 매핑·TTM EPS (b) 금융업 DCF 제외 (c) 분기 부족·누적 의심·자본 음수 → 검증전 (d) currency USD·가정 분리 (e) 사이클 블록."""
from datetime import date, timedelta

import polars as pl
import pytest

from screener import config, sec
from screener import valuation as V

RF = (0.05, "test")


def _long(ticker: str, n: int, ni=100.0, rev=1000.0, eq=2000.0, cfo=130.0, capex=20.0, div=-30.0, shares=100.0, ni_seq=None):
    rows, d0 = [], date(2020, 3, 31)
    for i in range(n):
        end = (d0 + timedelta(days=91 * i)).isoformat()
        vals = {"revenue": rev, "op": ni * 1.2, "ni": ni_seq[i] if ni_seq else ni, "cfo": cfo, "capex": capex, "div_paid": div,
                "da": 10.0, "assets": 5000.0, "liab": 5000.0 - eq, "equity": eq, "cash": 300.0, "shares": shares}
        rows += [{"ticker": ticker, "end": end, "item": k, "value": float(v), "derived": False} for k, v in vals.items() if v is not None]
    return rows


@pytest.fixture
def env(tmp_path, monkeypatch):
    def make(rows, sectors: dict[str, str]):
        p = tmp_path / "us_quarterly.parquet"
        pl.DataFrame(rows, schema=sec.SCHEMA).write_parquet(p)
        u = tmp_path / "universe"
        u.mkdir(exist_ok=True)
        (u / "us_sector.csv").write_text("yf,sector\n" + "".join(f"{k},{v}\n" for k, v in sectors.items()), encoding="utf-8")
        (u / "us.csv").write_text("symbol,yf,name,market,mcap\n", encoding="utf-8")
        monkeypatch.setattr(sec, "OUT", p)
        monkeypatch.setattr(config, "UNIVERSE_DIR", u)
    return make


def test_key_mapping_and_ttm_eps(env):
    env(_long("AAA", 8), {"AAA": "산업재"})
    v = V.us_all({"AAA": 80.0}, verified={}, rf=RF)["AAA"]
    assert v["per"] == pytest.approx(20.0)            # TTM ni 400 / 100주 = EPS 4 → 80/4
    assert v["pbr"] == pytest.approx(4.0)             # BPS 2000/100 = 20
    assert v["roe"] == pytest.approx(0.2)
    assert "DCF(FCFE)" in v["models"]                 # (130−20)×4/100 = FCFE 4.4
    assert "$4.40" in v["models"]["DCF(FCFE)"]["note"]
    assert v["quality"]["verified"] and v["quality"]["n_quarters"] == 8


def test_currency_and_us_assumptions(env):
    env(_long("AAA", 8), {"AAA": "산업재"})
    v = V.us_all({"AAA": 80.0}, verified={}, rf=RF)["AAA"]
    a = v["assumptions"]
    assert v["currency"] == "USD"
    assert a["coe"] == pytest.approx(0.05 + V.US_ERP) and a["g"] == V.US_G and a["rf"] == 0.05
    assert all("원" not in m["note"] for m in v["models"].values())
    assert set(v["rim_sens"]) == {"9%", "10%", "11%"}       # COE ±1%p
    assert any("같은 전제" in f for f in v["flags"])         # 6모델 공통 가정 한 줄


def test_financial_sector_excludes_cash_flow_models(env):
    env(_long("BNK", 8), {"BNK": "금융"})
    v = V.us_all({"BNK": 80.0}, verified={}, rf=RF)["BNK"]
    assert "DCF(FCFE)" not in v["models"] and "implied_g" not in v
    assert v["assumptions"]["financial_sector"]
    assert any("금융업" in f for f in v["flags"])
    assert "RIM" in v["models"]


def test_short_history_unverified(env):
    env(_long("NEW", 3), {"NEW": "IT"})
    v = V.us_all({"NEW": 50.0}, verified={}, rf=RF)["NEW"]
    assert v["models"] == {} and v["currency"] == "USD" and not v["quality"]["verified"]
    assert any(f.startswith("검증전") for f in v["flags"])


def test_cumulative_smell_unverified_unless_verified(env):
    seq = [100.0] * 4 + [100.0, 200.0, 400.0, 800.0]
    env(_long("CUM", 8, ni_seq=seq), {"CUM": "IT"})
    v = V.us_all({"CUM": 80.0}, verified={}, rf=RF)["CUM"]
    assert not v["quality"]["verified"] and any("누적치 의심" in f for f in v["flags"])
    assert v["verdict"] is None or v["verdict"].startswith("(검증전)")
    end = (date(2020, 3, 31) + timedelta(days=91 * 7)).isoformat()
    v = V.us_all({"CUM": 80.0}, verified={"CUM": {end: {"ni": 800.0, "src": "8-K test"}}}, rf=RF)["CUM"]
    assert v["quality"]["verified"] and any("해제" in f for f in v["flags"])


def test_negative_equity_unverified(env):
    env(_long("NEG", 8, eq=-500.0), {"NEG": "필수소비재"})
    v = V.us_all({"NEG": 80.0}, verified={}, rf=RF)["NEG"]
    assert not v["quality"]["verified"] and any("자본 음수" in f for f in v["flags"])
    assert not any(k in v["models"] for k in ("PBR-ROE", "RIM", "상대 PBR"))


def test_outlier_models_excluded():
    m = V.base_metrics([{"period": "p", "revenue": 1000.0, "op": 120.0, "ni": 100.0, "cfo": 130.0, "capex": 20.0,
                         "equity": 2.0, "assets": 5000.0, "liab": 4998.0}] * 8, 100.0)
    v = V.value(m, 80.0, "IT", {"IT": {"per": 20.0, "pbr": 3.0, "n": 9}}, coe=0.1, g=0.025, currency="USD", outlier=20)
    assert "상대 PBR" not in v["models"] and "상대 PBR" in v.get("excluded", {})   # PBR 4000배 → BPS 모델 제외
    assert any("PBR" in f and ">100" in f for f in v["flags"])


def test_cycle_view_for_semis(env):
    seq = [10.0] * 20 + [100.0, 300.0, 500.0, 700.0]   # 평균 이익률 낮다가 최근 급증 (매출 1000 고정)
    env(_long("MU", 24, ni_seq=seq), {"MU": "IT"})
    v = V.us_all({"MU": 400.0}, verified={"MU": {(date(2020, 3, 31) + timedelta(days=91 * 23)).isoformat(): {"ni": 700.0}}}, rf=RF)["MU"]
    cv = v["cycle_view"]
    assert cv["current"]["per_ttm"] == pytest.approx(400 * 100 / 1600, rel=1e-3)      # 시총 40000 / TTM 1600
    assert cv["current"]["per_runrate"] == pytest.approx(40000 / 2800, rel=1e-2)
    assert cv["normal"]["method"] == "margin" and cv["normal"]["margin"] == pytest.approx(1800 / 24000)
    assert cv["normal"]["per_high"] == pytest.approx(40000 / (0.075 * 4000), rel=1e-2)
    assert len(cv["lines"]) == 2 and "정규화" in cv["lines"][1]


def test_kr_default_unchanged():
    m = V.base_metrics([{"period": "p", "revenue": 1000.0, "op": 120.0, "ni": 100.0, "cfo": 130.0, "capex": 20.0,
                         "equity": 2000.0, "assets": 5000.0, "liab": 3000.0}] * 8, 100.0)
    v = V.value(m, 80.0, "반도체", {"반도체": {"per": 12.0, "pbr": 1.3, "n": 9}})
    assert v["assumptions"]["coe"] == 0.09 and "원" in v["models"]["DCF(FCFE)"]["note"]
    assert set(v["rim_sens"]) == {"8%", "9%", "10%"} and "currency" not in v
