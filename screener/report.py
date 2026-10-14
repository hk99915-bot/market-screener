"""Markdown 리포트 + 텔레그램 요약 + (선택) 구글시트."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl
import requests

from .config import CFG, REPORT_DIR

log = logging.getLogger(__name__)

CLASS_KO = {
    "TREND_LONG": "추세 상승", "TREND_OVEREXTENDED": "추세 과열", "PULLBACK_IN_UPTREND": "상승추세 눌림",
    "COUNTERTREND_BOUNCE": "역추세 반등", "TREND_SHORT": "추세 하락", "NEUTRAL": "중립",
}
COLS = ["symbol", "name", "market", "close", "ret1", "ret20", "trend_score", "momentum_score",
        "reversal_risk", "class", "adx14", "rsi14", "from_high52", "vol_ratio", "dollar_vol20"]


def _pct(x) -> str:
    return "" if x is None else f"{x * 100:+.1f}%"


def _num(x, d=0) -> str:
    return "" if x is None else f"{x:,.{d}f}"


def _md_table(df: pl.DataFrame, cols: list[str], n: int) -> str:
    head = ["종목", "이름", "시장", "종가", "1D", "20D", "Trend", "Mom", "RevRisk", "분류", "ADX", "RSI", "52H대비", "거래량배"]
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in df.head(n).select(cols).to_dicts():
        rows.append("| " + " | ".join([
            r["symbol"], str(r["name"])[:18], r["market"], _num(r["close"], 2 if r["market"] not in ("KOSPI", "KOSDAQ") else 0),
            _pct(r["ret1"]), _pct(r["ret20"]), _num(r["trend_score"]), _num(r["momentum_score"]), _num(r["reversal_risk"]),
            CLASS_KO.get(r["class"], r["class"]), _num(r["adx14"]), _num(r["rsi14"]), _pct(r["from_high52"]), _num(r["vol_ratio"], 1),
        ]) + " |")
    return "\n".join(rows)


def sections(last: pl.DataFrame, top_n: int) -> dict[str, pl.DataFrame]:
    s = {}
    s["trend_long"] = (last.filter(pl.col("class") == "TREND_LONG")
                           .sort(["trend_score", "momentum_score"], descending=True).head(top_n))
    s["pullback"] = (last.filter(pl.col("class") == "PULLBACK_IN_UPTREND")
                         .sort(["trend_score"], descending=True).head(top_n))
    s["bounce"] = (last.filter(pl.col("class") == "COUNTERTREND_BOUNCE")
                       .sort(["momentum_score"], descending=True).head(top_n))
    s["overextended"] = (last.filter(pl.col("reversal_risk") >= 60)
                             .sort(["reversal_risk"], descending=True).head(top_n))
    s["new_high"] = last.filter(pl.col("high") >= pl.col("high52")).sort("trend_score", descending=True).head(top_n)
    s["new_low"] = last.filter(pl.col("low") <= pl.col("low52")).sort("trend_score").head(top_n)
    return s


def write_markdown(market: str, status: str, last: pl.DataFrame, br: dict, anom: pl.DataFrame,
                   mr: list[dict], top_n: int, news: dict | None = None) -> str:
    asof = br.get("date", "")
    s = sections(last, top_n)
    L = [f"# {market} 스크리너 — {asof} [{status}]", "",
         f"생성 {datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M')} KST · 유니버스 {br.get('n', 0)}종목 (필터 후)", ""]
    if br:
        L += ["## 시장 폭 (Breadth)", "",
              f"- 20일선 위 {br['pct_above20']*100:.0f}% · 50일선 위 {br['pct_above50']*100:.0f}% · 200일선 위 {br['pct_above200']*100:.0f}%"
              + (f" (20일 전 {br['pct_above200_20d_ago']*100:.0f}%)" if 'pct_above200_20d_ago' in br else ""),
              f"- 상승 {br['adv']} / 하락 {br['dec']} · 52주 신고가 {br['new_high52']} / 신저가 {br['new_low52']}",
              f"- 추세상승 {br['n_trend_long']} / 추세하락 {br['n_trend_short']} · 중앙값 수익률 {_pct(br['median_ret1'])}", ""]
    if mr:
        L += ["## 매크로 컨텍스트 (점수 미반영)", "", "| 지표 | 값 | 1D | 20D | 50일선대비 | 레짐 |", "|---|---|---|---|---|---|"]
        L += [f"| {d['key']} | {_num(d['last'], 2)} | {_pct(d['chg1'])} | {_pct(d['chg20'])} | {_pct(d['vs_sma50'])} | {d['regime']} |" for d in mr]
        L.append("")
    titles = [("trend_long", "추세 상승 (Trend ≥65 & Mom ≥55)"), ("pullback", "상승추세 눌림 (Trend ≥60 & Mom ≤40)"),
              ("bounce", "역추세 반등 (Trend ≤40 & Mom ≥60)"), ("overextended", "과열 (Reversal Risk ≥60)"),
              ("new_high", "52주 신고가"), ("new_low", "52주 신저가")]
    for k, t in titles:
        L += [f"## {t} — {len(s[k])}종목", ""]
        L += [_md_table(s[k], COLS, top_n) if len(s[k]) else "_없음_", ""]
    if len(anom):
        L += [f"## 이상 신호 (거래량 ≥3× 또는 갭 ≥5%) — {len(anom)}종목", "",
              "| 종목 | 이름 | 1D | 갭 | 거래량배 | 분류 |", "|---|---|---|---|---|---|"]
        L += [f"| {r['symbol']} | {str(r['name'])[:18]} | {_pct(r['ret1'])} | {_pct(r['gap'])} | {_num(r['vol_ratio'],1)} | {CLASS_KO.get(r['class'], r['class'])} |"
              for r in anom.head(30).to_dicts()]
        L.append("")
    if news:
        name_of = dict(zip(last["yf"].to_list(), last["name"].to_list()))
        if news.get("yf"):
            L += ["## 뉴스 (신호 종목, 최근 3일 · 컨텍스트 전용)", ""]
            for s, items in news["yf"].items():
                L.append(f"- **{name_of.get(s, s)}**")
                L += [f"  - [{it['time']}] [{it['title']}]({it['url']}) — {it['source']}" for it in items]
            L.append("")
        tg = news.get("tg")
        if tg is not None and len(tg):
            L += [f"## 텔레그램 채널 언급 (24h) — {len(tg)}건", ""]
            L += [f"- [{r['time']}] {name_of.get(r['yf'], r['yf'])} · {r['channel']}: {r['text']}" for r in tg.head(40).to_dicts()]
            L.append("")
    md = "\n".join(L)

    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "daily").mkdir(exist_ok=True)
    (REPORT_DIR / "signals").mkdir(exist_ok=True)
    (REPORT_DIR / "anomalies").mkdir(exist_ok=True)
    (REPORT_DIR / "daily" / f"{asof}_{market}.md").write_text(md, encoding="utf-8")
    (REPORT_DIR / f"latest_{market}.md").write_text(md, encoding="utf-8")
    last.select(COLS).sort("trend_score", descending=True).write_csv(REPORT_DIR / "signals" / f"{asof}_{market}.csv")
    if len(anom):
        anom.write_csv(REPORT_DIR / "anomalies" / f"{asof}_{market}.csv")
    (REPORT_DIR / "breadth_history.jsonl").open("a", encoding="utf-8").write(
        json.dumps({"market": market, **br}, ensure_ascii=False) + "\n")
    return md


def telegram_summary(market: str, status: str, last: pl.DataFrame, br: dict, anom: pl.DataFrame,
                     mr: list[dict], regime_line: str, top_n: int, news: dict | None = None) -> str:
    s = sections(last, min(top_n, 8))
    esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    L = [f"<b>🧭 {market} 스크리너</b> · {br.get('date', '')} [{status}]"]
    if br:
        L.append(f"폭: 20D↑ {br['pct_above20']*100:.0f}% · 200D↑ {br['pct_above200']*100:.0f}% · "
                 f"신고가 {br['new_high52']} / 신저가 {br['new_low52']} · 상승 {br['adv']}/하락 {br['dec']}")
    if regime_line:
        L.append(f"매크로: {esc(regime_line)}")

    def block(title, df, fmt):
        if not len(df):
            return
        L.append(""); L.append(f"<b>{title}</b> ({len(df)})")
        for r in df.to_dicts():
            L.append("• " + fmt(r))

    f_trend = lambda r: f"{esc(r['name'])} ({r['symbol']}) T{r['trend_score']:.0f}/M{r['momentum_score']:.0f} {_pct(r['ret1'])} ADX{r['adx14']:.0f}"  # noqa: E731
    f_pull = lambda r: f"{esc(r['name'])} ({r['symbol']}) T{r['trend_score']:.0f} RSI{r['rsi14']:.0f} 20D{_pct(r['ret20'])}"  # noqa: E731
    f_over = lambda r: f"{esc(r['name'])} ({r['symbol']}) Risk{r['reversal_risk']:.0f} 5D{_pct(r['ret5'])} 이격{r['dist_sma20_atr']:.1f}ATR"  # noqa: E731
    block("추세 상승", s["trend_long"], f_trend)
    block("상승추세 눌림", s["pullback"], f_pull)
    block("역추세 반등", s["bounce"], f_trend)
    block("과열 주의", s["overextended"], f_over)
    if len(anom):
        block("이상 신호", anom.head(6), lambda r: f"{esc(r['name'])} ({r['symbol']}) {_pct(r['ret1'])} 거래량 {r['vol_ratio']:.1f}×")
    if news:
        name_of = dict(zip(last["yf"].to_list(), last["name"].to_list()))
        heads = [(name_of.get(s, s), items[0]) for s, items in news.get("yf", {}).items()][:6]
        if heads:
            L.append(""); L.append("<b>뉴스 (신호 종목)</b>")
            L += [f"• {esc(n)}: <a href=\"{esc(it['url'])}\">{esc(it['title'])[:70]}</a>" for n, it in heads]
        tg = news.get("tg")
        if tg is not None and len(tg):
            cnt = tg.group_by("yf").len().sort("len", descending=True).head(5)
            L.append(""); L.append("<b>텔레그램 언급 상위</b> " + ", ".join(
                f"{esc(name_of.get(r['yf'], r['yf']))}({r['len']})" for r in cnt.to_dicts()))
    L.append(""); L.append(f"전체 리포트: reports/latest_{market}.md")
    return "\n".join(L)


def send_telegram(text: str) -> None:
    if not CFG.telegram_token or not CFG.telegram_chat:
        raise RuntimeError("텔레그램 미설정: TELEGRAM_TOKEN / TELEGRAM_CHAT_ID 시크릿이 비어 있음 (이름 철자 확인)")
    url = f"https://api.telegram.org/bot{CFG.telegram_token}/sendMessage"
    chunks, buf = [], ""
    for line in text.split("\n"):
        if len(buf) + len(line) > 3800:
            chunks.append(buf); buf = ""
        buf += line + "\n"
    chunks.append(buf)
    for c in chunks:
        r = requests.post(url, data={"chat_id": CFG.telegram_chat, "text": c, "parse_mode": "HTML",
                                     "disable_web_page_preview": "true"}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"텔레그램 전송 실패 {r.status_code}: {r.text[:300]}")
    log.info("텔레그램 전송 완료 (%d개 메시지)", len(chunks))


def push_gsheet(market: str, last: pl.DataFrame) -> None:
    """GSHEET_ID + GCP_SA_JSON 이 있을 때만. 시트명 'SCREENER_KR' / 'SCREENER_US' 를 덮어씀."""
    if not CFG.gsheet_id or not CFG.gcp_sa_json:
        return
    try:
        import gspread  # type: ignore
        gc = gspread.service_account_from_dict(json.loads(CFG.gcp_sa_json))
        sh = gc.open_by_key(CFG.gsheet_id)
        title = f"SCREENER_{market}"
        try:
            ws = sh.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title, rows=2000, cols=20)
        df = last.select(COLS).sort("trend_score", descending=True)
        values = [COLS] + [[("" if v is None else v) for v in row] for row in df.rows()]
        ws.clear()
        ws.update(values, "A1")
        log.info("구글시트 %s 갱신 %d행", title, len(values) - 1)
    except Exception as e:  # noqa: BLE001
        log.error("구글시트 실패: %s", e)
