"""단지 좌표 캐시 — 브이월드 2D 데이터 API 연속지적도(LP_PA_CBND_BUBUN) 필지 중심점 (10/26 겸이 링크 확정:
https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do?svcIde=cadastral).

경로: RTMS 매매 원자료 sggCd(5)+umdCd(5)=법정동코드 10자리 + 산 구분(landCd 2=산→2, 그 외 1) + 본번 4 + 부번 4 = PNU 19자리
      → GetFeature attrFilter=pnu:=:<PNU> → 필지 폴리곤 → 꼭짓점 면적가중 중심(경위도 5자리 ≈ 1m) → 캐시.
저장: reports/realestate_coords.json {pnu: {lon, lat, d}} / 못 찾음 {miss: 날짜}(30일 뒤 재시도). **폴리곤 원본은 저장·재배포 안 함(중심점만).**
      구별 드릴다운 파일(reports/realestate_trades/<구>.json) 단지 행에 lon·lat 을 붙여 화면은 캐시만 읽는다(브라우저에서 브이월드 호출 없음).
키: 환경변수 VWORLD_KEY(GitHub Secrets — 저장소·로그에 키 금지, 오류 문구는 _scrub). 브이월드 키는 발급 때 '서비스 URL' 을 등록하고
    호출에 domain 파라미터로 같은 값을 보낸다 → VWORLD_DOMAIN(기본 https://hk99915-bot.github.io). 키 없으면 아무것도 안 함(화면은 동 단위까지).
출처 표기: "단지 위치: 브이월드(국토교통부) 연속지적도 필지 중심점".
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "reports" / "realestate_coords.json"
VW_URL = "https://api.vworld.kr/req/data"
VW_LAYER = "LP_PA_CBND_BUBUN"
DEFAULT_DOMAIN = "https://hk99915-bot.github.io"
MAX_CALLS = 1500        # 한 번 실행 상한(첫 실행은 여러 날에 나눠 채움 — 브이월드 일 호출 한도 안쪽)
MISS_RETRY_DAYS = 30
SRC = "단지 위치: 브이월드(국토교통부) 연속지적도 필지 중심점 — RTMS 지번 → PNU 매칭"


def _d(v, n: int) -> str | None:
    s = re.sub(r"\D", "", str(v or ""))
    return s.zfill(n)[-n:] if s else None


def make_pnu(x: dict) -> str | None:
    """RTMS 매매 행 → PNU 19자리. 본번이 없으면 jibun('12-3'·'산12')에서 읽는다. 못 만들면 None."""
    sgg, umd = _d(x.get("sggCd"), 5), _d(x.get("umdCd"), 5)
    if not sgg or not umd or len(re.sub(r"\D", "", str(x.get("umdCd") or ""))) != 5:
        return None
    bon, bu = _d(x.get("bonbun"), 4), _d(x.get("bubun"), 4)
    jb = str(x.get("jibun") or "").strip()
    san = str(x.get("landCd") or "").strip() == "2" or jb.startswith("산")
    if bon is None or int(bon) == 0:
        m = re.match(r"^산?\s*(\d+)(?:-(\d+))?$", jb)
        if not m:
            return None
        bon, bu = m.group(1).zfill(4)[-4:], (m.group(2) or "0").zfill(4)[-4:]
    return f"{sgg}{umd}{'2' if san else '1'}{bon}{bu or '0000'}"


def centroid(geom: dict) -> tuple[float, float] | None:
    """Polygon/MultiPolygon 바깥 고리 면적가중 중심(작은 필지라 평면 근사)."""
    polys = [geom["coordinates"]] if geom.get("type") == "Polygon" else (geom.get("coordinates") or [])
    ax = ay = aa = 0.0
    first = next((poly[0][0] for poly in polys if poly and poly[0]), None)
    if first is None:
        return None
    ox, oy = first[0], first[1]   # 원점 이동(경위도 큰 값끼리 빼서 생기는 자리 손실 방지)
    for poly in polys:
        r = poly[0] if poly else []
        for i in range(len(r) - 1):
            x0, y0, x1, y1 = r[i][0] - ox, r[i][1] - oy, r[i + 1][0] - ox, r[i + 1][1] - oy
            c = x0 * y1 - x1 * y0
            aa += c
            ax += (x0 + x1) * c
            ay += (y0 + y1) * c
    if abs(aa) < 1e-14:
        pts = [p for poly in polys for p in (poly[0] if poly else [])]
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else None
    return ox + ax / (3 * aa), oy + ay / (3 * aa)


def fetch_parcel(get_json, pnu: str, key: str, domain: str) -> tuple[float, float] | None:
    """get_json(url, params) → dict. 응답 status NOT_FOUND → None, ERROR → 예외."""
    j = get_json(VW_URL, {"service": "data", "version": "2.0", "request": "GetFeature", "format": "json", "data": VW_LAYER,
                          "key": key, "domain": domain, "attrFilter": f"pnu:=:{pnu}", "geometry": "true", "crs": "EPSG:4326",
                          "size": "1", "columns": "pnu"})
    res = (j or {}).get("response") or {}
    st = res.get("status")
    if st == "NOT_FOUND":
        return None
    if st != "OK":
        raise RuntimeError(f"vworld status {st} {((res.get('error') or {}).get('code'))}")
    feats = (((res.get("result") or {}).get("featureCollection") or {}).get("features")) or []
    return centroid(feats[0]["geometry"]) if feats else None


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def attach_coords(detail_dir: Path, key: str | None, get_json, today: date, domain: str | None = None,
                  cache_path: Path | None = None, max_calls: int = MAX_CALLS, sleep=None) -> dict:
    """구별 드릴다운 파일의 단지(pnu 있는 것)에 lon·lat 을 붙인다. 키 없으면 캐시에 있는 것만 붙임(호출 0). 결과 요약 dict."""
    from .realestate import _scrub
    cache_path = cache_path or CACHE
    doc = _load(cache_path)
    pts: dict = doc.get("pts") or {}
    calls = hit = miss = 0
    err = None
    files = sorted(detail_dir.glob("*.json")) if detail_dir.exists() else []
    for f in files:
        d = _load(f)
        changed = False
        for c in d.get("complexes") or []:
            pnu = c.get("pnu")
            if not pnu:
                continue
            e = pts.get(pnu)
            stale_miss = e and "miss" in e and e["miss"] < (today - timedelta(days=MISS_RETRY_DAYS)).isoformat()
            if (e is None or stale_miss) and key and calls < max_calls and err is None:
                calls += 1
                try:
                    xy = fetch_parcel(get_json, pnu, key, domain or DEFAULT_DOMAIN)
                    e = pts[pnu] = {"lon": round(xy[0], 5), "lat": round(xy[1], 5), "d": today.isoformat()} if xy else {"miss": today.isoformat()}
                except Exception as ex:  # noqa: BLE001 — 키·도메인 오류면 이번 실행 중단(남은 호출 낭비 방지)
                    err = _scrub(f"{type(ex).__name__}: {ex}", key)
                if sleep:
                    sleep(0.05)
            if e and "lon" in e:
                if c.get("lon") != e["lon"] or c.get("lat") != e["lat"]:
                    c["lon"], c["lat"] = e["lon"], e["lat"]
                    changed = True
                hit += 1
            else:
                miss += 1
        if changed:
            d["coords_src"] = SRC
            f.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    out = {"calls": calls, "with_pt": hit, "without_pt": miss, "error": err, "key": bool(key)}
    if calls:
        cache_path.write_text(json.dumps({"src": SRC, "asof": today.isoformat(), "pts": pts}, ensure_ascii=False, separators=(",", ":")),
                              encoding="utf-8")
    log.info("부동산 단지 좌표: 호출 %d · 점 있음 %d · 없음 %d%s", calls, hit, miss, f" · 오류 {err}" if err else "")
    return out


def _get_json(url: str, params: dict) -> dict:
    import requests
    r = requests.get(url, params=params, timeout=(10, 30))
    r.raise_for_status()
    return r.json()
