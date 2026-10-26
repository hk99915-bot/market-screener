"""서울·경기 지도 자산 빌더 — 부동산 데스크 (10/24 겸이 "서울·경기권 지도 붙이고").

원본 경계: geoBoundaries gbOpen KOR ADM2 (2020 기준, 빌드 2023-12-12) simplified GeoJSON
  https://www.geoboundaries.org/api/current/gbOpen/KOR/ADM2/  (boundaryID KOR-ADM2-91817680)
  라이선스 = Creative Commons Attribution 3.0 (출처 geoBoundaries · citypopulation.de) — 출처 표기 의무 → 자산·화면에 고정 표기.
  (southkorea-maps 는 저장소에 라이선스 파일이 없고 원자료 SGIS 이용조건 미확인이라 쓰지 않음, 2026-10-24 확인)
단위: 서울 25개 자치구 + 경기 시 단위(경기 시의 일반구 — 분당·영통 등 — 는 원본에 없어 시 전체 경계).
출력: assets/realestate_map.json — 등거리 원통 투영(위도 37.5° cos 보정)·Douglas-Peucker 단순화·소수 1자리 SVG path.
외부 CDN·라이브러리 없음. 화면은 이 path 를 인라인 SVG 로 그린다.

재생성(원본 GeoJSON 은 저장소에 넣지 않음 — 890KB):
  curl -L -o /tmp/kor_adm2.geojson "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/9469f09/releaseData/gbOpen/KOR/ADM2/geoBoundaries-KOR-ADM2_simplified.geojson"
  python -m screener.realestate_geo /tmp/kor_adm2.geojson
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "assets" / "realestate_map.json"

SOURCE = {
    "name": "geoBoundaries gbOpen KOR ADM2 (simplified)",
    "boundary_id": "KOR-ADM2-91817680",
    "year": "2020",
    "build": "2023-12-12",
    "url": "https://www.geoboundaries.org/api/current/gbOpen/KOR/ADM2/",
    "license": "CC BY 3.0",
    "attribution": "경계: geoBoundaries (Runfola et al. 2020) · citypopulation.de — CC BY 3.0, 단순화·투영 변경",
    "checked": "2026-10-24",
}

# 영문 이름 → (id, 한글, 시도). 서울의 Jung-gu·Gangseo-gu 는 다른 시에도 있어 경위도 상자로 거른다.
SEOUL = {
    "Jongno-gu": "종로구", "Jung-gu": "중구", "Yongsan-gu": "용산구", "Seongdong-gu": "성동구", "Gwangjin-gu": "광진구",
    "Dongdaemun-gu": "동대문구", "Jungnang-gu": "중랑구", "Seongbuk-gu": "성북구", "Gangbuk-gu": "강북구", "Dobong-gu": "도봉구",
    "Nowon-gu": "노원구", "Eunpyeong-gu": "은평구", "Seodaemun-gu": "서대문구", "Mapo-gu": "마포구", "Yangcheon-gu": "양천구",
    "Gangseo-gu": "강서구", "Guro-gu": "구로구", "Geumcheon-gu": "금천구", "Yeongdeungpo-gu": "영등포구", "Dongjak-gu": "동작구",
    "Gwanak-gu": "관악구", "Seocho-gu": "서초구", "Gangnam-gu": "강남구", "Songpa-gu": "송파구", "Gangdong-gu": "강동구",
}
# 경기: 서울 접경 + 남부·서부(과제 최소 범위 성남·용인·수원·화성·안양·광명·부천·고양·하남 포함). 북동부 외곽(연천·가평 등)은 뺌.
GYEONGGI = {
    "Seongnam-si": "성남시", "Yongin-si": "용인시", "Suwon-si": "수원시", "Hwaseong-si": "화성시", "Anyang-si": "안양시",
    "Gwangmyeong-si": "광명시", "Bucheon-si": "부천시", "Goyang-si": "고양시", "Hanam-si": "하남시", "Gwacheon-si": "과천시",
    "Gunpo-si": "군포시", "Uiwang-si": "의왕시", "Siheung-si": "시흥시", "Ansan-si": "안산시", "Osan-si": "오산시",
    "Gimpo-si": "김포시", "Guri-si": "구리시", "Namyangju-si": "남양주시", "Uijeongbu-si": "의정부시", "Pyeongtaek-si": "평택시",
    "Gwangju-si": "광주시",
}
# 인천(값 없음, 바다·경계 맥락용 회색 — 클릭 안 됨). 중구(영종·공항 섬)·강화·옹진은 지도 폭을 키워 뺌.
INCHEON = {"Yeonsu-gu": "인천 연수구", "Namdong-gu": "인천 남동구", "Michuhol-gu": "인천 미추홀구", "Dong-gu": "인천 동구",
           "Seo-gu": "인천 서구", "Gyeyang-gu": "인천 계양구", "Bupyeong-gu": "인천 부평구"}
SEOUL_BOX = (126.76, 37.41, 127.19, 37.72)   # lon0, lat0, lon1, lat1
INCHEON_BOX = (126.55, 37.35, 126.79, 37.62)
LAT0 = 37.5
W = 400.0          # viewBox 폭
TOL = 0.55         # 단순화 허용 오차(viewBox 단위) — 390px 에서 약 0.5px
MIN_RING_AREA = 6.0  # 이보다 작은 섬 고리는 버림(viewBox 단위²)


def _rings(geom: dict) -> list[list[list[float]]]:
    if geom["type"] == "Polygon":
        return [r for r in geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return [r for poly in geom["coordinates"] for r in poly]
    return []


def _centroid_lonlat(geom: dict) -> tuple[float, float]:
    pts = [p for r in _rings(geom) for p in r]
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def dp(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker (반복형). 닫힌 고리는 호출 쪽에서 첫·끝점 유지."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1e-12
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / n if n > 1e-12 else math.hypot(x - x1, y - y1)
            if d > best:
                best, idx = d, i
        if best > tol and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def _area(r: list[tuple[float, float]]) -> float:
    return abs(sum(r[i][0] * r[i - 1][1] - r[i - 1][0] * r[i][1] for i in range(len(r)))) / 2


def _pick(src: dict) -> list[tuple[str, str, dict]]:
    picked = []
    for f in src["features"]:
        en = re.sub(r"\s*\[.*\]$", "", f["properties"].get("shapeName", ""))   # 'Jung-gu [Central District]' → 'Jung-gu'
        lon, lat = _centroid_lonlat(f["geometry"])
        in_seoul = SEOUL_BOX[0] <= lon <= SEOUL_BOX[2] and SEOUL_BOX[1] <= lat <= SEOUL_BOX[3]
        if en in SEOUL and in_seoul:
            picked.append((SEOUL[en], "서울", f["geometry"]))
        elif en in GYEONGGI:   # 경기 시 이름은 전국 유일(부천·광명·과천·구리는 중심점이 서울 상자 안이라 상자 검사 안 함)
            picked.append((GYEONGGI[en], "경기", f["geometry"]))
        elif en in INCHEON and INCHEON_BOX[0] <= lon <= INCHEON_BOX[2] and INCHEON_BOX[1] <= lat <= INCHEON_BOX[3]:
            picked.append((INCHEON[en], "인천", f["geometry"]))
    names = [p[0] for p in picked]
    if len(set(names)) != len(names) or len(picked) != len(SEOUL) + len(GYEONGGI) + len(INCHEON):
        raise ValueError(f"영역 수 불일치: {len(picked)} (중복 {[n for n in names if names.count(n) > 1]})")
    return picked


def projection(src: dict, picked: list | None = None):
    """(x0, y0, s, H), proj(lon, lat) → (x, y) viewBox 단위. 줌 자산(realestate_geo_zoom)이 같은 좌표계를 쓰려고 분리(10/26)."""
    picked = picked if picked is not None else _pick(src)
    k = math.cos(math.radians(LAT0))
    allp = [(p[0] * k, -p[1]) for _, _, g in picked for r in _rings(g) for p in r]
    x0, x1 = min(p[0] for p in allp), max(p[0] for p in allp)
    y0, y1 = min(p[1] for p in allp), max(p[1] for p in allp)
    s = W / (x1 - x0)
    return (x0, y0, s, round((y1 - y0) * s, 1)), (lambda lon, lat: ((lon * k - x0) * s, (-lat - y0) * s))


def build_asset(src: dict) -> dict:
    picked = _pick(src)
    (x0, y0, s, H), _ = projection(src, picked)
    k = math.cos(math.radians(LAT0))
    areas = []
    for ko, sido, g in picked:
        parts, cx, cy, n = [], 0.0, 0.0, 0
        for r in _rings(g):
            pr = [((p[0] * k - x0) * s, (-p[1] - y0) * s) for p in r]
            if _area(pr) < MIN_RING_AREA and len(_rings(g)) > 1:
                continue
            q = dp(pr, TOL)
            if len(q) < 4:
                continue
            parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in q[:-1]) + "Z")
            if _area(pr) >= MIN_RING_AREA:
                cx += sum(x for x, _ in pr)
                cy += sum(y for _, y in pr)
                n += len(pr)
        areas.append({"id": ko, "name": ko, "sido": sido, "d": "".join(parts),
                      "cx": round(cx / n, 1), "cy": round(cy / n, 1)})
    areas.sort(key=lambda a: (["서울", "경기", "인천"].index(a["sido"]), a["name"]))
    return {"v": 1, "source": SOURCE, "projection": f"equirectangular, lon×cos({LAT0}°), DP tol {TOL}",
            "unit_note": "서울 = 자치구 · 경기 = 시 단위(일반구 경계 없음 — 분당·영통 등 구 값은 소속 시 칸에 '대표 구'로 표시)",
            "viewBox": f"0 0 {int(W)} {H}", "areas": areas}


def load_asset() -> dict | None:
    try:
        return json.loads(ASSET.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


if __name__ == "__main__":
    out = build_asset(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    ASSET.parent.mkdir(exist_ok=True)
    ASSET.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(ASSET, ASSET.stat().st_size, "bytes", len(out["areas"]), "areas", out["viewBox"])
