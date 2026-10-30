"""KR 테마 분류: 네이버 '테마별 시세' 구성종목 → 대표 테마 1개 + 소속 테마 목록.

KRX 업종은 '전기·전자'처럼 너무 넓어서 반도체·2차전지·디스플레이가 한 덩어리가 된다.
네이버 테마는 반대로 너무 잘게 쪼개져 있어(수백 개, 한 종목이 수십 개 소속) 대표 버킷으로 묶는다:
종목이 속한 테마 이름을 버킷 키워드에 맞춰 세고, 가장 많이 걸린 버킷(동률이면 위쪽 우선)을 대표 테마로 쓴다.
주 1회 universe/kr_theme.csv 캐시. 실패하면 이전 캐시를 쓴다.
"""
from __future__ import annotations

import logging
import re
import time

import polars as pl
import requests

from .config import REPORT_DIR, UNIVERSE_DIR

log = logging.getLogger(__name__)
P = UNIVERSE_DIR / "kr_theme.csv"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
      "Referer": "https://finance.naver.com/sise/theme.naver"}

# (대표 테마, 네이버 테마명 키워드) — 위쪽이 우선
BUCKETS: list[tuple[str, tuple[str, ...]]] = [
    ("반도체 장비·소재", ("반도체 장비", "반도체장비", "반도체 소재", "반도체 재료", "반도체 부품", "CXL", "유리기판", "프로브카드", "웨이퍼")),
    ("반도체", ("반도체", "HBM", "파운드리", "메모리", "시스템반도체", "온디바이스", "NPU")),
    ("2차전지", ("2차전지", "이차전지", "배터리", "리튬", "양극재", "음극재", "전해질", "분리막", "전고체", "폐배터리", "LFP")),
    ("디스플레이", ("디스플레이", "OLED", "LCD", "마이크로LED")),
    ("전력기기·전선", ("전력설비", "변압기", "전선", "송배전", "스마트그리드", "전력 인프라", "초고압")),
    ("원전", ("원자력", "원전", "SMR")),
    ("조선", ("조선", "LNG선", "해양플랜트", "선박")),
    ("방산·우주", ("방위산업", "방산", "우주항공", "위성", "드론")),
    ("로봇", ("로봇",)),
    ("AI·소프트웨어", ("인공지능", "AI", "챗봇", "데이터센터", "클라우드", "보안", "소프트웨어", "SI")),
    ("바이오·헬스케어", ("바이오", "제약", "신약", "치료제", "백신", "비만", "의료기기", "진단", "헬스케어", "줄기세포", "CMO")),
    ("자동차", ("자동차", "전기차", "자율주행", "타이어", "수소차")),
    ("인터넷·게임", ("게임", "메타버스", "플랫폼", "인터넷", "웹툰", "핀테크")),
    ("엔터·미디어", ("엔터", "음원", "드라마", "미디어", "콘텐츠", "K-POP", "아이돌", "영화")),
    ("화장품·소비재", ("화장품", "면세점", "음식료", "의류", "여행", "카지노", "K-푸드", "라면", "주류", "편의점")),
    ("금융", ("은행", "증권", "보험", "카드", "인터넷은행")),
    ("건설·부동산", ("건설", "시멘트", "리츠", "재건", "인테리어", "건자재")),
    ("에너지·소재", ("철강", "정유", "석유화학", "화학", "태양광", "풍력", "수소", "비철금속", "구리", "가스")),
    ("통신", ("5G", "통신", "6G")),
    ("운송·물류", ("해운", "항공", "물류", "택배")),
]


IGNORE = ("밸류업", "지주사", "기업가치 제고", "고배당", "자사주", "외국인", "코스피200", "MSCI")


def bucket_of(names: list[str]) -> str | None:
    cnt: dict[str, int] = {}
    for n in names:
        if any(k in n for k in IGNORE):   # 업종이 아닌 이벤트성 테마는 대표 테마 판정에서 제외
            continue
        for b, kws in BUCKETS:
            if any(k.lower() in n.lower() for k in kws):
                cnt[b] = cnt.get(b, 0) + 1
                break   # 테마 하나는 버킷 하나에만
    if not cnt:
        return None
    order = {b: i for i, (b, _) in enumerate(BUCKETS)}
    return sorted(cnt.items(), key=lambda x: (-x[1], order[x[0]]))[0][0]


# ── WICS 정합 게이트 (req-data-630b1bfe, 10/30) ──
# 네이버 테마 버킷은 키워드 부분 일치라 업종 밖으로 샌다: SK스퀘어 '모바일콘텐츠'→엔터·미디어(WICS IT/반도체),
# 롯데쇼핑 '영화'(롯데시네마)→엔터·미디어(WICS 소매). 대표 테마가 공식 섹터(WICS)와 양립 안 하면 WICS 중분류 버킷으로 바꾼다.
# 양립 = 버킷별 허용 WICS 대분류(L1) — 테마는 업종을 가로지르므로 넓게(2차전지 = IT·소재·산업재·자동차부품 …).
THEME_WICS_L1: dict[str, frozenset[str]] = {
    "반도체 장비·소재": frozenset({"IT", "소재", "산업재"}),
    "반도체": frozenset({"IT"}),
    "2차전지": frozenset({"IT", "소재", "산업재", "경기관련소비재", "에너지"}),
    "디스플레이": frozenset({"IT", "소재"}),
    "전력기기·전선": frozenset({"산업재", "IT", "유틸리티"}),
    "원전": frozenset({"산업재", "에너지", "유틸리티"}),
    "조선": frozenset({"산업재", "소재"}),
    "방산·우주": frozenset({"산업재", "IT", "소재"}),
    "로봇": frozenset({"산업재", "IT", "경기관련소비재", "건강관리"}),
    "AI·소프트웨어": frozenset({"IT", "커뮤니케이션서비스"}),
    "바이오·헬스케어": frozenset({"건강관리"}),
    "자동차": frozenset({"경기관련소비재", "소재", "IT", "산업재"}),
    "인터넷·게임": frozenset({"커뮤니케이션서비스", "IT"}),
    "화장품·소비재": frozenset({"경기관련소비재", "필수소비재", "소재"}),
    "금융": frozenset({"금융"}),
    "건설·부동산": frozenset({"산업재", "금융", "소재"}),
    "에너지·소재": frozenset({"소재", "에너지", "유틸리티", "산업재"}),
    "통신": frozenset({"커뮤니케이션서비스", "IT"}),
    "운송·물류": frozenset({"산업재"}),
}
# 엔터·미디어는 대분류가 아니라 중분류로 — 같은 경기관련소비재라도 소매(롯데쇼핑)는 아님.
THEME_WICS_L2: dict[str, frozenset[str]] = {
    "엔터·미디어": frozenset({"미디어와엔터테인먼트", "호텔,레스토랑,레저등"}),
}
# 게이트에 걸렸을 때 쓸 WICS 중분류 → 버킷(기존 버킷 이름 재사용, 없는 건 WICS 이름 짧게)
WICS_L2_BUCKET: dict[str, str] = {
    "반도체와반도체장비": "반도체", "디스플레이": "디스플레이", "기술하드웨어와장비": "IT 하드웨어",
    "소프트웨어와서비스": "AI·소프트웨어", "건강관리장비와서비스": "바이오·헬스케어", "제약과생물공학": "바이오·헬스케어",
    "교육서비스": "교육", "내구소비재와의류": "내구소비재·의류", "소매(유통)": "유통", "자동차와부품": "자동차",
    "호텔,레스토랑,레저등": "호텔·레저", "다각화된금융": "금융", "보험": "금융", "은행": "금융", "증권": "금융",
    "부동산": "건설·부동산", "상업서비스와공급품": "상업서비스", "운송": "운송·물류", "자본재": "자본재",
    "소재": "에너지·소재", "에너지": "에너지·소재", "유틸리티": "유틸리티", "미디어와엔터테인먼트": "엔터·미디어",
    "전기통신서비스": "통신", "가정용품과개인용품": "화장품·소비재", "식품,음료,담배": "화장품·소비재",
    "식품과기본식료품소매": "화장품·소비재",
}


def wics_compatible(theme: str | None, l1: str | None, l2: str | None) -> bool:
    """대표 테마가 WICS 와 양립하는가. WICS 모름·게이트 없는 버킷은 True(판정 불가 → 테마 유지)."""
    if not theme or not l1:
        return True
    if theme in THEME_WICS_L2:
        return (l2 or "") in THEME_WICS_L2[theme]
    allowed = THEME_WICS_L1.get(theme)
    return True if allowed is None else l1 in allowed


def gated_theme(theme: str | None, l1: str | None, l2: str | None) -> str | None:
    """양립하면 테마 그대로, 아니면 WICS 중분류 버킷(없으면 None → 호출자가 다음 출처로)."""
    if wics_compatible(theme, l1, l2):
        return theme
    return WICS_L2_BUCKET.get(l2 or "")


def _get(url: str) -> str:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    r.encoding = "euc-kr"
    return r.text


def _json(url: str):
    r = requests.get(url, headers={"User-Agent": UA["User-Agent"]}, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch() -> dict[str, list[str]]:
    """{종목코드: [소속 테마명...]} — 네이버 모바일 API (PC 테마 페이지는 Next.js 로 바뀌어 파싱 불가)."""
    themes: dict[int, str] = {}
    for page in range(1, 6):
        try:
            j = _json(f"https://m.stock.naver.com/api/stocks/theme?page={page}&pageSize=100")
        except Exception:  # noqa: BLE001
            if themes:
                break
            raise
        gs = j.get("groups") or []
        for g in gs:
            themes[g["no"]] = g["name"]
        if len(themes) >= (j.get("totalCount") or 0) or not gs:
            break
        time.sleep(0.2)
    log.info("네이버 테마 %d개", len(themes))
    out: dict[str, list[str]] = {}
    bad = 0
    for no, name in themes.items():
        codes = set()
        for url in (f"https://m.stock.naver.com/api/stocks/theme/{no}?page=1&pageSize=100",
                    f"https://m.stock.naver.com/api/stocks/theme/{no}/stocks?page=1&pageSize=100"):
            try:
                j = _json(url)
            except Exception:  # noqa: BLE001
                continue
            for it in (j.get("stocks") or j.get("items") or []):
                c = str(it.get("itemCode") or it.get("code") or "")
                if re.fullmatch(r"\d{6}", c):
                    codes.add(c)
            if codes:
                break
            if bad == 0:
                (REPORT_DIR / "logs").mkdir(parents=True, exist_ok=True)
                (REPORT_DIR / "logs" / "naver_theme.json").write_text(str(j)[:20000], encoding="utf-8")
        if not codes:
            bad += 1
            if bad >= 5 and not out:
                raise RuntimeError("테마 구성종목 API 응답 형식 불일치 (logs/naver_theme.json)")
            continue
        for c in codes:
            out.setdefault(c, []).append(name)
        time.sleep(0.1)
    return out


def kr_themes(refresh_days: int = 7, force: bool = False) -> dict[str, dict]:
    """{코드: {"theme": 대표 테마, "themes": "테마1|테마2|..."}}"""
    import time as _t
    if not force and P.exists() and (_t.time() - P.stat().st_mtime) < refresh_days * 86400:
        return _load()
    try:
        m = fetch()
        if len(m) < 300:
            raise RuntimeError(f"테마 소속 종목 {len(m)}개뿐")
        rows = [{"code": c, "theme": bucket_of(v) or "", "themes": "|".join(sorted(set(v)))} for c, v in m.items()]
        pl.DataFrame(rows).write_csv(P)
        log.info("KR 테마 분류 %d종목", len(rows))
    except Exception as e:  # noqa: BLE001
        log.warning("테마 수집 실패, 이전 캐시 사용: %s", e)
    return _load() if P.exists() else {}


def _load() -> dict[str, dict]:
    df = pl.read_csv(P, schema_overrides={"code": pl.Utf8, "theme": pl.Utf8, "themes": pl.Utf8})
    return {r["code"]: {"theme": r["theme"] or None, "themes": r["themes"] or ""} for r in df.to_dicts()}
