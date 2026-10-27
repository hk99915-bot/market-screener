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


RETRY = 3               # 일시 오류(502·끊김·시간초과) 필지당 시도 횟수 (10/26 Actions 502 → RemoteDisconnected, req-dev-dcd43e3b ②)
ABORT_SKIPS = 5         # 일시 오류로 연속 건너뛴 필지가 이만큼이면 이번 실행 중단(차단 상태에서 한도 낭비 방지)
ACTIONS_SKIP_AFTER = 2  # Actions 에서 '성공 0 + 일시 오류 중단' 이 연속 이 횟수면 다음 실행부터 호출 생략(캐시만 붙임, ③)
ACTIONS_SKIP_DAYS = 7   # 생략 기간 — 지나면 1회 다시 시도. 노트북 실행이 성공하면 즉시 초기화
FATAL_RE = re.compile(r"vworld status|\b40[13]\b|INVALID_KEY|INCORRECT_KEY|UNAVAILABLE_KEY|OVER_REQUEST_LIMIT", re.I)


def _fatal(msg: str) -> bool:
    """키·도메인·한도 오류 = 재시도해도 같음 → 실행 중단. 나머지(502·끊김·시간초과) = 일시 오류 → 재시도·건너뛰기."""
    return bool(FATAL_RE.search(msg))


def actions_skip(doc: dict, today: date) -> bool:
    f = doc.get("actions_fail") or {}
    return f.get("n", 0) >= ACTIONS_SKIP_AFTER and f.get("last", "") >= (today - timedelta(days=ACTIONS_SKIP_DAYS)).isoformat()


def attach_coords(detail_dir: Path, key: str | None, get_json, today: date, domain: str | None = None,
                  cache_path: Path | None = None, max_calls: int = MAX_CALLS, sleep=None, where: str = "actions",
                  write_files: bool = True) -> dict:
    """구별 드릴다운 파일의 단지(pnu 있는 것)에 lon·lat 을 붙인다. 키 없으면 캐시에 있는 것만 붙임(호출 0). 결과 요약 dict.

    where='actions'|'laptop' — Actions(미국 IP)는 브이월드가 끊는 경우가 있어(10/26 2회 연속 실패) 연속 실패 기록 시 호출 생략.
    write_files=False = 캐시(reports/realestate_coords.json)만 갱신(노트북 CLI — 드릴다운 파일은 다음 Actions 실행이 캐시로 붙임).
    """
    from .realestate import _scrub
    cache_path = cache_path or CACHE
    doc = _load(cache_path)
    pts: dict = doc.get("pts") or {}
    calls = hit = miss = ok_calls = skipped = streak = 0
    err = None
    aborted = False
    skip_net = where == "actions" and actions_skip(doc, today)
    if skip_net and key:
        log.warning("부동산 단지 좌표: Actions 연속 실패 기록(%s) — 이번 실행 호출 생략, 캐시만 붙임 (노트북 CLI 로 채우기)", doc.get("actions_fail"))
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
            if (e is None or stale_miss) and key and not skip_net and calls < max_calls and err is None and not aborted:
                calls += 1
                last = None
                for k in range(RETRY):
                    try:
                        xy = fetch_parcel(get_json, pnu, key, domain or DEFAULT_DOMAIN)
                        e = pts[pnu] = {"lon": round(xy[0], 5), "lat": round(xy[1], 5), "d": today.isoformat()} if xy else {"miss": today.isoformat()}
                        ok_calls += 1
                        streak = 0
                        last = None
                        break
                    except Exception as ex:  # noqa: BLE001
                        last = _scrub(f"{type(ex).__name__}: {ex}", key)
                        if _fatal(last):
                            err = last          # 키·도메인 오류 = 이번 실행 중단(남은 호출 낭비 방지)
                            break
                        if sleep and k < RETRY - 1:
                            sleep(1.0 * (k + 1))
                if last and err is None:        # 일시 오류 3회 → 이 필지만 건너뜀(캐시에 miss 안 남김 — 다음 실행에 다시)
                    skipped += 1
                    streak += 1
                    if streak >= ABORT_SKIPS:
                        aborted = True
                        err = f"일시 오류로 {streak}필지 연속 실패 — 중단 (마지막: {last})"
                if sleep:
                    sleep(0.05)
            if e and "lon" in e:
                if c.get("lon") != e["lon"] or c.get("lat") != e["lat"]:
                    c["lon"], c["lat"] = e["lon"], e["lat"]
                    changed = True
                hit += 1
            else:
                miss += 1
        if changed and write_files:
            d["coords_src"] = SRC
            f.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    fail0 = doc.get("actions_fail")
    if calls and ok_calls:
        fail = None                                    # 어디서든 성공하면 초기화
    elif calls and where == "actions":
        n = (fail0 or {}).get("n", 0) + 1
        fail = {"n": n, "last": today.isoformat(), "why": (err or "")[:200]}
    else:
        fail = fail0
    out = {"calls": calls, "ok_calls": ok_calls, "skipped": skipped, "with_pt": hit, "without_pt": miss, "error": err, "key": bool(key),
           "skipped_net": bool(skip_net and key), "where": where}
    if calls or fail != fail0:
        body = {"src": SRC, "asof": today.isoformat(), "pts": pts}
        if fail:
            body["actions_fail"] = fail
        cache_path.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("부동산 단지 좌표(%s): 호출 %d(성공 %d·건너뜀 %d) · 점 있음 %d · 없음 %d%s", where, calls, ok_calls, skipped, hit, miss,
             f" · 오류 {err}" if err else "")
    return out


def _get_json(url: str, params: dict) -> dict:
    import requests
    r = requests.get(url, params=params, timeout=(10, 30))
    r.raise_for_status()
    return r.json()


def main(argv=None) -> int:
    """노트북(국내 IP) 1회 실행 CLI (req-dev-dcd43e3b ①) — 실행법 docs/realestate/vworld_laptop.md.
    키 = 환경변수 VWORLD_KEY(인자·파일로 받지 않음). 결과 = reports/realestate_coords.json 만 갱신(이어받기: 캐시에 있는 필지는 건너뜀)."""
    import argparse
    import os
    import time
    ap = argparse.ArgumentParser(description="브이월드 단지 좌표 캐시 채우기 (노트북 1회 실행)")
    ap.add_argument("--max", type=int, default=MAX_CALLS, help=f"이번 실행 호출 상한(기본 {MAX_CALLS}, 브이월드 일 한도 안쪽)")
    ap.add_argument("--dry", action="store_true", help="호출 없이 남은 필지 수만")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    key = os.environ.get("VWORLD_KEY")
    detail = ROOT / "reports" / "realestate_trades"
    doc = _load(CACHE)
    pts = doc.get("pts") or {}
    todo = {c["pnu"] for f in sorted(detail.glob("*.json")) for c in (_load(f).get("complexes") or []) if c.get("pnu") and c["pnu"] not in pts}
    print(f"캐시 {len(pts)}필지 · 남은 필지 {len(todo)} · Actions 연속 실패 기록 {doc.get('actions_fail') or '없음'}")
    if a.dry:
        return 0
    if not key:
        print("VWORLD_KEY 환경변수가 없음 — 종료 (키를 파일·인자로 넘기지 말 것)")
        return 2
    out = attach_coords(detail, key, _get_json, date.today(), os.environ.get("VWORLD_DOMAIN"), max_calls=a.max, sleep=time.sleep,
                        where="laptop", write_files=False)
    print(json.dumps(out, ensure_ascii=False))
    return 1 if out["error"] and not out["ok_calls"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
