"""웹 대시보드용 데이터 묶음 → reports/dashboard.json (커밋됨).
Apps Script 웹앱(apps-script/)이 GitHub API로 이 파일을 읽어 터미널 스타일로 렌더링한다.
각 실행(스크리너·브리핑) 끝에 호출되며, 항상 현재 저장소 상태로 전체를 다시 만든다.
"""
from __future__ import annotations

import glob
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from .config import DATA_DIR, REPORT_DIR

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
OUT = REPORT_DIR / "dashboard.json"
STATE = REPORT_DIR / "dashboard_state.json"   # 브리핑들이 남기는 조각(마감 코멘트·매크로·US tone 등)

SIG_COLS = ["symbol", "name", "market", "close", "ret1", "ret20", "trend_score", "momentum_score", "reversal_risk",
            "class", "adx14", "rsi14", "from_high52", "vol_ratio"]


def put_state(key: str, value, asof=None) -> bool:
    """브리핑 모듈이 조각을 저장 (예: close_comment 텍스트, macro 표). 쓴 경우 True.
    asof(데이터 기준일·시각)를 주면 조각 단위 역행 가드(guard-rest 10/17): 기존 조각의 asof 보다 과거면 그 조각만 쓰지 않고
    reports/freshness.json regress_blocked 에 'dashboard_state.json#<key>' 로 기록. 둘 다 시각이 있으면 분 단위(같은 날 늦은 시각 허용).
    asof 없는 조각(장중 브리핑 등)은 항상 쓴다 — 기록 시각 'at' 은 실행 시각이라 비교 근거가 아님."""
    import os
    from . import contracts, guard
    try:
        st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except Exception:  # noqa: BLE001
        st = {}
    old = (st.get(key) or {}).get("asof") if isinstance(st.get(key), dict) else None
    if asof is not None and old is not None and not guard.not_older(old, asof) and os.environ.get("SCREENER_ALLOW_REGRESS") != "1":
        log.warning("⛔ asof 역행 차단: dashboard_state.json#%s 기존 %s → 새 %s (조각 쓰지 않음)", key, old, asof)
        try:
            guard.record_block(STATE.parent / f"{STATE.name}#{key}", guard._label(old), guard._label(asof))
        except Exception as e:  # noqa: BLE001
            log.warning("역행 기록 실패: %s", e)
        return False
    piece = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "value": value}
    if asof is not None:
        piece["asof"] = str(asof)
    errs = contracts.check(STATE, {key: piece})   # 새 조각만 검사 — 기존 조각이 깨져 있어도 다른 조각 갱신을 막지 않음
    st[key] = piece
    if errs:
        log.warning("⛔ 데이터 계약 위반 — dashboard_state.json 쓰지 않음: %s", "; ".join(errs[:3]))
        try:
            guard.record_contract(STATE, errs)
        except Exception as e:  # noqa: BLE001
            log.warning("계약 위반 기록 실패: %s", e)
        return False
    REPORT_DIR.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return True


def _signals(market: str, per_class: int = 12) -> dict:
    files = sorted(glob.glob(str(REPORT_DIR / "signals" / f"*_{market}.csv")))
    if not files:
        return {}
    df = pl.read_csv(files[-1], schema_overrides={"symbol": pl.Utf8})
    cols = [c for c in SIG_COLS if c in df.columns]
    out = {"asof": files[-1].split("/")[-1][:10], "n": len(df), "sections": {}}
    sec = {
        "TREND_LONG": df.filter(pl.col("class") == "TREND_LONG").sort(["trend_score", "momentum_score"], descending=True),
        "PULLBACK_IN_UPTREND": df.filter(pl.col("class") == "PULLBACK_IN_UPTREND").sort("trend_score", descending=True),
        "COUNTERTREND_BOUNCE": df.filter(pl.col("class") == "COUNTERTREND_BOUNCE").sort("momentum_score", descending=True),
        "OVEREXTENDED": df.filter(pl.col("reversal_risk") >= 60).sort("reversal_risk", descending=True),
        "TREND_SHORT": df.filter(pl.col("class") == "TREND_SHORT").sort("trend_score"),
    }
    for k, d in sec.items():
        out["sections"][k] = {"total": len(d), "rows": d.select(cols).head(per_class).to_dicts()}
    out["class_counts"] = {r["class"]: r["len"] for r in df.group_by("class").len().to_dicts()}
    return out


def _breadth(n: int = 60) -> list[dict]:
    p = REPORT_DIR / "breadth_history.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    # 같은 market·date 는 마지막 것만
    seen = {}
    for r in rows:
        seen[(r.get("market"), r.get("date"))] = r
    rows = sorted(seen.values(), key=lambda r: (r.get("date", ""), r.get("market", "")))
    keep = ["market", "date", "pct_above20", "pct_above50", "pct_above200", "adv", "dec", "new_high52", "new_low52", "n"]
    return [{k: r.get(k) for k in keep} for r in rows[-n * 2:]]


def _anomalies(market: str) -> list[dict]:
    files = sorted(glob.glob(str(REPORT_DIR / "anomalies" / f"*_{market}.csv")))
    if not files:
        return []
    return pl.read_csv(files[-1], schema_overrides={"symbol": pl.Utf8}).head(20).to_dicts()


def _reports(days: int = 3, n: int = 60) -> list[dict]:
    p = DATA_DIR / "research.parquet"
    if not p.exists():
        return []
    df = pl.read_parquet(p)
    cutoff = datetime.now(KST).date() - timedelta(days=days)
    return (df.filter(pl.col("date") >= cutoff).sort("date", descending=True).head(n)
              .with_columns(pl.col("date").cast(pl.Utf8))
              .select("date", "code", "name", "broker", "opinion", "target", "title", "link").to_dicts())


def write_research(days: int = 180) -> int:
    """리서치 화면용 전체 묶음 → reports/research.json (섹터·종가 포함, 집계는 브라우저에서)."""
    from . import research
    store = research.load_store()
    if store.is_empty():
        return 0
    try:
        rv = research.revisions(store).select("key", "tp_chg", "op_chg")
        store = store.join(rv, on="key", how="left")
    except Exception as e:  # noqa: BLE001
        log.warning("리비전 계산 실패: %s", e)
        store = store.with_columns(pl.lit(None, pl.Float64).alias("tp_chg"), pl.lit(None, pl.Int8).alias("op_chg"))
    cutoff = datetime.now(KST).date() - timedelta(days=days)
    df = store.filter(pl.col("date") >= cutoff).sort("date", descending=True)
    try:
        from .universe import kr_sectors
        sec = kr_sectors()
    except Exception as e:  # noqa: BLE001
        log.warning("업종 분류 실패: %s", e)
        sec = {}
    try:
        from .themes import kr_themes
        th = kr_themes()
    except Exception as e:  # noqa: BLE001
        log.warning("테마 분류 실패: %s", e)
        th = {}
    df = df.with_columns(
        pl.col("code").replace_strict({k: v["theme"] for k, v in th.items() if v.get("theme")}, default=None,
                                      return_dtype=pl.Utf8).alias("theme"))
    items = (df.with_columns(pl.col("date").cast(pl.Utf8),
                             pl.col("code").replace_strict(sec, default="기타", return_dtype=pl.Utf8).alias("sector"))
               .with_columns(pl.col("tp_chg").round(4))
               .with_columns(pl.coalesce("theme", "sector").alias("theme"))
               .select("date", "code", "name", "sector", "theme", "broker", "analyst", "opinion", "target", "title", "link",
                       "summary", "tp_chg", "op_chg").to_dicts())
    close = {}
    pp = DATA_DIR / "kr_prices.parquet"
    if pp.exists():
        codes = set(df["code"].to_list())
        last = (pl.read_parquet(pp, columns=["yf", "date", "close"]).sort("date").group_by("yf").last()
                  .with_columns(pl.col("yf").str.slice(0, 6).alias("code")).filter(pl.col("code").is_in(sorted(codes))))
        close = dict(zip(last["code"].to_list(), [round(float(x), 2) for x in last["close"].to_list()]))
    manual = {}
    try:   # 사람이(또는 대화 중 Claude 가) 원문을 읽고 정리한 요약이 있으면 규칙 기반 결과보다 우선
        from pathlib import Path
        mp = Path(__file__).resolve().parents[1] / "notes" / "research_manual.json"
        manual = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    except Exception as e:  # noqa: BLE001
        log.warning("수동 요약 로드 실패: %s", e)
    keys = df["key"].to_list()
    for k, it in zip(keys, items):
        try:
            it.update(research.structure(it, close.get(it["code"])))
        except Exception as e:  # noqa: BLE001
            log.debug("구조화 실패 %s: %s", it.get("code"), e)
        if k in manual:
            it.update({f: v for f, v in manual[k].items() if f in ("thesis", "evidence", "risk", "method", "tone", "tone_why", "view")})
            it["curated"] = True
    try:   # 발간일 국면 태그 — 코스피·해당 종목 (regime_tag 정의)
        from . import regime_tag
        kp, st = regime_tag.load_series(DATA_DIR, set(df["code"].to_list()))
        log.info("리서치 국면 태그 %d건", regime_tag.tag_items(items, kp, st))
    except Exception as e:  # noqa: BLE001
        log.warning("국면 태그 실패: %s", e)
    from .calendar_ev import surprise_guard   # '서프라이즈' 는 컨센서스 병기 때만 (감사 경-7 10/17). 제목은 원문 인용이라 화면에서 표시
    for it in items:
        for f in ("view", "thesis"):
            if isinstance(it.get(f), str):
                it[f] = surprise_guard(it[f])
    out = {"asof": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "days": days, "items": items, "close": close}
    (REPORT_DIR / "research.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return len(items)


def _watchlist() -> list[dict]:
    p = REPORT_DIR / "watchlist_KR.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    except Exception:  # noqa: BLE001
        return []


def _last_error() -> str:
    p = REPORT_DIR / "last_error.txt"
    return p.read_text(encoding="utf-8")[:600] if p.exists() else ""


def build() -> None:
    try:
        st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except Exception:  # noqa: BLE001
        st = {}
    data = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "kr": _signals("KR"), "us": _signals("US"),
        "breadth": _breadth(),
        "anomalies": {"KR": _anomalies("KR"), "US": _anomalies("US")},
        "reports": _reports(),
        "watchlist": _watchlist(),
        "state": st,
        # last_error 는 공개 페이지에 싣지 않음 (reports/last_error.txt 로만 확인)
    }
    REPORT_DIR.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    log.info("dashboard.json 갱신 (%d bytes)", OUT.stat().st_size)
    try:
        log.info("research.json %d건", write_research())
    except Exception as e:  # noqa: BLE001
        log.warning("research.json 실패: %s", e)
    try:
        from . import dart
        log.info("disclosures.json %d건", dart.write_json())
    except Exception as e:  # noqa: BLE001
        log.warning("disclosures.json 실패: %s", e)
    try:
        from . import daily
        daily.build()
    except Exception as e:  # noqa: BLE001
        log.warning("데일리 브리프 실패: %s", e)
