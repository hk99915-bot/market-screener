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


def _tr(tmp_path, n):
    dd = tmp_path / "tr"
    dd.mkdir()
    cs = [{"name": f"c{i}", "pnu": f"11680101001{i:04d}0000"} for i in range(n)]
    (dd / "11680.json").write_text(json.dumps({"complexes": cs}), encoding="utf-8")
    return dd


OKJ = {"response": {"status": "OK", "result": {"featureCollection": {"features": [{"geometry": {
    "type": "Polygon", "coordinates": [[[127, 37.5], [127.002, 37.5], [127.002, 37.502], [127, 37.502], [127, 37.5]]]}}]}}}}


def test_transient_error_retries_then_skips(tmp_path):
    """req-dev-dcd43e3b ②: 502·끊김 = 필지당 3회 재시도 → 건너뜀(캐시에 miss 안 남김), 다음 필지 계속."""
    dd = _tr(tmp_path, 3)
    tries = {}

    def gj(url, params):
        p = params["attrFilter"]
        tries[p] = tries.get(p, 0) + 1
        if p.endswith("1168010100100000000"):
            raise ConnectionError("RemoteDisconnected('Remote end closed connection without response')")
        if p.endswith("1168010100100010000") and tries[p] < 3:
            raise RuntimeError("502 Server Error: Bad Gateway")
        return OKJ
    cache = tmp_path / "c.json"
    out = attach_coords(dd, "K", gj, date(2026, 10, 27), cache_path=cache, sleep=lambda s: None)
    assert out["calls"] == 3 and out["ok_calls"] == 2 and out["skipped"] == 1 and out["error"] is None
    assert tries["pnu:=:1168010100100000000"] == 3 and tries["pnu:=:1168010100100010000"] == 3
    pts = json.loads(cache.read_text(encoding="utf-8"))["pts"]
    assert "1168010100100000000" not in pts and len(pts) == 2


def test_actions_consecutive_failures_then_skip_network(tmp_path):
    """③: Actions 에서 '성공 0' 실행이 2회 연속이면 다음부터 호출 생략(7일), 노트북 성공 시 초기화."""
    dd = _tr(tmp_path, 6)
    cache = tmp_path / "c.json"
    n = {"calls": 0}

    def bad(url, params):
        n["calls"] += 1
        raise RuntimeError("502 Server Error: Bad Gateway")
    for day in (26, 27):
        out = attach_coords(dd, "K", bad, date(2026, 10, day), cache_path=cache, sleep=lambda s: None)
        assert out["ok_calls"] == 0 and out["skipped"] == 5 and "중단" in out["error"]   # 5필지 연속 → 중단(6번째 안 부름)
    assert json.loads(cache.read_text(encoding="utf-8"))["actions_fail"]["n"] == 2
    before = n["calls"]
    out = attach_coords(dd, "K", bad, date(2026, 10, 28), cache_path=cache, sleep=lambda s: None)
    assert out["skipped_net"] and out["calls"] == 0 and n["calls"] == before
    out = attach_coords(dd, "K", lambda u, p: OKJ, date(2026, 10, 28), cache_path=cache, where="laptop", write_files=False)
    doc = json.loads(cache.read_text(encoding="utf-8"))
    assert out["ok_calls"] == 6 and "actions_fail" not in doc
    assert "lon" not in json.loads((dd / "11680.json").read_text(encoding="utf-8"))["complexes"][0]   # 노트북은 캐시만
    assert attach_coords(dd, None, None, date(2026, 10, 29), cache_path=cache)["with_pt"] == 6        # Actions 키 없이도 캐시로 붙임
