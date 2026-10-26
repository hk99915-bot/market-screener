"""단지 좌표(브이월드 연속지적도 PNU → 필지 중심점) — 네트워크 없음, get_json 가짜."""
import json
from datetime import date

from screener.realestate import summarize_detail
from screener.realestate_coords import attach_coords, centroid, make_pnu


def test_make_pnu_from_rtms_fields_and_jibun():
    assert make_pnu({"sggCd": "11680", "umdCd": "10100", "landCd": "1", "bonbun": "0123", "bubun": "0004"}) == "1168010100101230004"
    assert make_pnu({"sggCd": "11680", "umdCd": "10100", "jibun": "산12-3"}) == "1168010100200120003"
    assert make_pnu({"sggCd": "11680", "umdCd": "10100", "jibun": "45"}) == "1168010100100450000"
    assert make_pnu({"sggCd": "11680", "jibun": "45"}) is None and make_pnu({"sggCd": "11680", "umdCd": "10100", "jibun": "블록"}) is None


def test_centroid_square():
    c = centroid({"type": "MultiPolygon", "coordinates": [[[[127, 37], [127.002, 37], [127.002, 37.002], [127, 37.002], [127, 37]]]]})
    assert abs(c[0] - 127.001) < 1e-9 and abs(c[1] - 37.001) < 1e-9


def test_summarize_detail_carries_pnu():
    tr = [{"umdNm": "역삼동", "aptNm": "가", "dealAmount": "150,000", "excluUseAr": "84.9", "dealYear": "2026", "dealMonth": "9", "dealDay": "1",
           "sggCd": "11680", "umdCd": "10100", "bonbun": "0007", "bubun": "0000", "landCd": "1"}]
    assert summarize_detail(tr, [])["complexes"][0]["pnu"] == "1168010100100070000"


def test_attach_coords_caches_centroid_and_skips_without_key(tmp_path):
    dd = tmp_path / "tr"
    dd.mkdir()
    (dd / "11680.json").write_text(json.dumps({"complexes": [{"name": "가", "pnu": "1168010100100070000"}, {"name": "나", "pnu": None}]}), encoding="utf-8")
    cache = tmp_path / "coords.json"
    seen = []

    def gj(url, params):
        seen.append(params)
        return {"response": {"status": "OK", "result": {"featureCollection": {"features": [{"geometry": {
            "type": "Polygon", "coordinates": [[[127, 37.5], [127.002, 37.5], [127.002, 37.502], [127, 37.502], [127, 37.5]]]}}]}}}}
    assert attach_coords(dd, None, gj, date(2026, 10, 26), cache_path=cache)["calls"] == 0 and not seen
    out = attach_coords(dd, "SECRET", gj, date(2026, 10, 26), "https://x.github.io", cache_path=cache)
    assert out["calls"] == 1 and seen[0]["attrFilter"] == "pnu:=:1168010100100070000" and seen[0]["domain"] == "https://x.github.io"
    c = json.loads((dd / "11680.json").read_text(encoding="utf-8"))["complexes"][0]
    assert (c["lon"], c["lat"]) == (127.001, 37.501) and "SECRET" not in cache.read_text(encoding="utf-8")
    assert attach_coords(dd, "SECRET", gj, date(2026, 10, 27), cache_path=cache)["calls"] == 0   # 캐시 재사용


def test_attach_coords_scrubs_key_on_error(tmp_path):
    dd = tmp_path / "tr"
    dd.mkdir()
    (dd / "11680.json").write_text(json.dumps({"complexes": [{"name": "가", "pnu": "1168010100100070000"}, {"name": "다", "pnu": "1168010100100080000"}]}), encoding="utf-8")

    def gj(url, params):
        raise RuntimeError(f"401 for {url}?key={params['key']}")
    out = attach_coords(dd, "SECRET", gj, date(2026, 10, 26), cache_path=tmp_path / "c.json")
    assert out["calls"] == 1 and out["error"] and "SECRET" not in out["error"]
