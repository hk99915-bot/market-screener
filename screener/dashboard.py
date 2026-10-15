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


def put_state(key: str, value) -> None:
    """브리핑 모듈이 조각을 저장 (예: close_comment 텍스트, macro 표)."""
    try:
        st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except Exception:  # noqa: BLE001
        st = {}
    st[key] = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "value": value}
    REPORT_DIR.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


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
