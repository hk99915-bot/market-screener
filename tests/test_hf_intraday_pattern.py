import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hf_intraday_pattern as P


def test_classify_types():
    assert P.classify(100, 101, 102, 99, 100)["type"] == "전강후약"
    assert P.classify(100, 99, 101, 98, 100)["type"] == "전약후강"
    assert P.classify(100, 101, 103, 100.5, 102)["type"] == "강세 지속"
    assert P.classify(100, 99, 99.5, 97, 98)["type"] == "약세 지속"
    assert P.classify(100, 100.2, 101, 99, 100.1)["type"] == "혼조"


def test_build_from_csv(tmp_path):
    f = tmp_path / "d.csv"
    rows = ["date,kospi_open,kospi_high,kospi_low,kospi_close"]
    px = 100.0
    for i in range(30):
        d = f"2021-01-{i + 1:02d}"
        o = px * (1.01 if i % 2 else 0.99)
        c = px * (0.995 if i % 2 else 1.005)
        rows.append(f"{d},{o},{max(o, c) * 1.002},{min(o, c) * 0.998},{c}")
        px = c
    f.write_text("\n".join(rows))
    o = P.build((100, 101, 98, 99), path=f)
    assert o["today"]["type"] in ("전강후약", "혼조", "전약후강", "강세 지속", "약세 지속")
    assert "전강후약" in o["stats"] and o["stats"]["전강후약"]["OOS(2020~)"]["n"] > 0
