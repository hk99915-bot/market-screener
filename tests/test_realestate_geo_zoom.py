"""부동산 지도 줌 자산(assets/realestate_geo, screener/realestate_geo_zoom.py) — 네트워크 없음."""
import json

from screener.realestate import GU_CODES
from screener.realestate_geo_zoom import OUT_DIR, build_dongs, build_rivers


def test_assets_cover_all_seoul_gu_and_small():
    base = json.loads((OUT_DIR / "seoul.json").read_text(encoding="utf-8"))
    assert base["gu"] == GU_CODES and any(r["name"] == "한강" for r in base["rivers"])
    assert "ODbL" in base["src"]["attribution"] and "Apache-2.0" in base["src"]["attribution"]
    total = 0
    for gu, cd in GU_CODES.items():
        f = OUT_DIR / f"{cd}.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        names = [x["name"] for x in d["dongs"]]
        assert d["gu"] == gu and names and len(set(names)) == len(names)
        assert all(n.endswith(("동", "가")) or "로" in n for n in names), names   # 법정동(…동·…가) — 행정동 번호(역삼1동)는 없음
        total += f.stat().st_size
    assert total < 400_000


def test_build_dongs_groups_by_gu_code_and_rejects_duplicates():
    sq = lambda x: {"type": "Polygon", "coordinates": [[[x, 37.5], [x + .01, 37.5], [x + .01, 37.51], [x, 37.51], [x, 37.5]]]}  # noqa: E731
    proj = lambda lon, lat: (lon * 100, -lat * 100)  # noqa: E731
    src = {"features": [{"properties": {"EMD_CD": "11680101", "EMD_KOR_NM": "역삼동"}, "geometry": sq(127.0)},
                        {"properties": {"EMD_CD": "11710101", "EMD_KOR_NM": "잠실동"}, "geometry": sq(127.1)}]}
    out = build_dongs(src, proj)
    assert set(out) == {"11680", "11710"} and out["11680"][0]["name"] == "역삼동" and out["11680"][0]["d"].startswith("M")
    src["features"].append({"properties": {"EMD_CD": "11680102", "EMD_KOR_NM": "역삼동"}, "geometry": sq(127.05)})
    try:
        build_dongs(src, proj)
        assert False, "중복 이름은 실패해야 함"
    except ValueError:
        pass


def test_build_rivers_splits_outside_box():
    proj = lambda lon, lat: (lon, lat)  # noqa: E731
    f = {"properties": {"name": "한강"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1], [50, 50], [2, 2], [3, 3]]}}
    r = build_rivers([f], proj, (-1, -1, 10, 10))
    assert r[0]["name"] == "한강" and r[0]["d"].count("M") == 2 and r[0]["w"] > 1
