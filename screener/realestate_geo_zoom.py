"""부동산 지도 줌 자산 빌더 — 서울 → 구 → 법정동 (10/26 겸이 "동·단지 세부가 지도에도, 점점 확대 같은 느낌, 한강도 넣고").

출력(저장소 정적, 화면이 필요할 때만 읽음):
  assets/realestate_geo/seoul.json   = {proj, rivers:[{name,d,w}], src}  — 서울 지도 위 한강·주요 하천(선, 폭 = 실제 강폭 근사)
  assets/realestate_geo/<구코드>.json = {gu, code, dongs:[{name, code, d, cx, cy}], src}  — 그 구의 법정동 경계(구 누를 때 lazy)
좌표계 = assets/realestate_map.json 과 같은 등거리 원통 투영(realestate_geo.projection) → 구 경계와 그대로 겹친다.

원본(저장소엔 넣지 않음 — 받아서 단순화한 결과만):
  법정동: southkorea/seoul-maps juso/2015/json/seoul_neighborhoods_geo_simple.json (467개, EMD_CD 8자리 = 법정동코드 앞 8자리)
    https://github.com/southkorea/seoul-maps — 저장소 라이선스 Apache-2.0(README 'License'), 원자료 도로명주소(juso.go.kr) 2015 서울 읍면동.
    · 2015 기준 — 이후 법정동 신설·폐지는 반영 안 됨(화면에 '경계 없음'으로 남음).
  하천: OpenStreetMap waterway(한강 rel 5488151 · 안양천 rel 19282613 · 중랑천·홍제천·불광천 way) Nominatim polygon_geojson, © OpenStreetMap contributors, ODbL 1.0.
RTMS 매칭: RTMS 법정동 이름 umdNm(+ 구 = LAWD_CD 5자리) ↔ EMD_KOR_NM(+ EMD_CD 앞 5자리). 행정동(역삼1동 등)이 아니라 법정동(역삼동) 단위라 이름이 그대로 맞는다.
재생성:
  curl -L -o /tmp/seoul_dong.json https://raw.githubusercontent.com/southkorea/seoul-maps/master/juso/2015/json/seoul_neighborhoods_geo_simple.json
  (하천) Nominatim search?q=<이름>&layer=natural&format=geojson&polygon_geojson=1&polygon_threshold=0.0002 → riv_<이름>.json
  python -m screener.realestate_geo_zoom /tmp/kor_adm2.geojson /tmp/seoul_dong.json riv_한강.json riv_안양천.json ...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .realestate_geo import ROOT, _area, _rings, dp, projection

OUT_DIR = ROOT / "assets" / "realestate_geo"
DONG_TOL = 0.06        # viewBox 단위 — 구 하나가 화면 폭을 채울 때(약 8~10배) 0.5px 안팎
RIVER_TOL = 0.08
RIVER_W = {"한강": 4.2}  # 선 폭(viewBox 단위). 1 단위 ≈ 0.23km → 한강 ≈ 1km. 지류는 기본 0.5(≈ 110m)
SRC = {
    "dong": {"name": "southkorea/seoul-maps juso 2015 서울 법정동(seoul_neighborhoods_geo_simple)", "license": "Apache-2.0 (저장소 README)",
             "origin": "도로명주소 juso.go.kr 2015 서울 읍면동", "url": "https://github.com/southkorea/seoul-maps", "checked": "2026-10-26",
             "match": "RTMS umdNm(법정동 이름) + 구코드(LAWD_CD) ↔ EMD_KOR_NM + EMD_CD 앞 5자리"},
    "river": {"name": "OpenStreetMap waterway (Nominatim)", "license": "ODbL 1.0", "attribution": "하천 © OpenStreetMap contributors (ODbL)",
              "url": "https://www.openstreetmap.org/relation/5488151", "checked": "2026-10-26"},
    "attribution": "법정동 경계: southkorea/seoul-maps(Apache-2.0, 원자료 juso 2015) · 하천 © OpenStreetMap contributors (ODbL)",
}


def _path(pts) -> str:
    return "M" + "L".join(f"{x:.2f},{y:.2f}" for x, y in pts)


def build_dongs(dong_src: dict, proj) -> dict[str, list[dict]]:
    """법정동 GeoJSON → {구코드: [{name, code, d, cx, cy}]}. 같은 구 안 같은 이름이 둘이면 실패(매칭 키가 깨지므로)."""
    out: dict[str, list[dict]] = {}
    for f in dong_src["features"]:
        p = f["properties"]
        cd, nm = str(p["EMD_CD"]), p["EMD_KOR_NM"].strip()
        parts, ax, ay, aa = [], 0.0, 0.0, 0.0
        for r in _rings(f["geometry"]):
            pr = [proj(x, y) for x, y in r]
            q = dp(pr, DONG_TOL)
            if len(q) < 4:
                continue
            parts.append(_path(q[:-1]) + "Z")
            a = _area(pr)
            ax += a * sum(x for x, _ in pr) / len(pr)
            ay += a * sum(y for _, y in pr) / len(pr)
            aa += a
        if not parts:
            continue
        out.setdefault(cd[:5], []).append({"name": nm, "code": cd, "d": "".join(parts), "cx": round(ax / aa, 2), "cy": round(ay / aa, 2)})
    for cd, L in out.items():
        names = [x["name"] for x in L]
        if len(set(names)) != len(names):
            raise ValueError(f"{cd} 법정동 이름 중복: {[n for n in names if names.count(n) > 1]}")
        L.sort(key=lambda x: x["name"])
    return out


def build_rivers(feats: list[dict], proj, box) -> list[dict]:
    """하천 LineString → 화면 상자(box = x0,y0,x1,y1, viewBox 단위) 밖 점에서 끊은 선 path."""
    x0, y0, x1, y1 = box
    out: dict[str, list[str]] = {}
    for f in feats:
        nm = (f.get("properties") or {}).get("name") or "?"
        g = f["geometry"]
        lines = [g["coordinates"]] if g["type"] == "LineString" else (g["coordinates"] if g["type"] == "MultiLineString" else [])
        for ln in lines:
            seg: list = []
            for c in list(ln) + [None]:   # None = 마지막 조각 비우기
                pt = proj(c[0], c[1]) if c is not None else None
                if pt and x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1:
                    seg.append(pt)
                    continue
                if len(seg) >= 2:
                    out.setdefault(nm, []).append(_path(dp(seg, RIVER_TOL)))
                seg = []
    return [{"name": k, "d": "".join(v), "w": RIVER_W.get(k, 0.5)} for k, v in out.items()]


def seoul_box(asset: dict, pad: float = 3.0) -> tuple[float, float, float, float]:
    import re
    n = [float(v) for a in asset["areas"] if a["sido"] == "서울" for v in re.findall(r"-?\d+(?:\.\d+)?", a["d"])]
    xs, ys = n[0::2], n[1::2]
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def main(adm2: str, dong: str, rivers: list[str]) -> None:
    from .realestate import GU_CODES
    from .realestate_geo import load_asset
    GU_NAME_BY_CODE = {v: k for k, v in GU_CODES.items()}
    src = json.loads(Path(adm2).read_text(encoding="utf-8"))
    (x0, y0, s, _h), proj = projection(src)
    import math
    from .realestate_geo import LAT0
    pp = {"k": math.cos(math.radians(LAT0)), "x0": x0, "y0": y0, "s": s}   # 화면이 단지 경위도 → viewBox 로 바꿀 때 씀
    asset = load_asset()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    feats = [f for r in rivers for f in json.loads(Path(r).read_text(encoding="utf-8"))["features"]]
    base = {"v": 1, "proj": asset.get("projection"), "rivers": build_rivers(feats, proj, seoul_box(asset)), "gu": GU_CODES, "pp": pp, "src": SRC}
    (OUT_DIR / "seoul.json").write_text(json.dumps(base, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tot = 0
    for cd, L in sorted(build_dongs(json.loads(Path(dong).read_text(encoding="utf-8")), proj).items()):
        doc = {"v": 1, "gu": GU_NAME_BY_CODE.get(cd, cd), "code": cd, "dongs": L, "attribution": SRC["attribution"]}
        p = OUT_DIR / f"{cd}.json"
        p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tot += p.stat().st_size
        print(cd, doc["gu"], len(L), "동", p.stat().st_size, "B")
    print("seoul.json", (OUT_DIR / "seoul.json").stat().st_size, "B · 구 파일 합", tot, "B")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
