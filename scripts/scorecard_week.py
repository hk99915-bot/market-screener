#!/usr/bin/env python3
"""주간 성적표 (공개 층) — 일요일 08:30 KST 에 돈다 (.github/workflows/scorecard.yml).

공개 저장소에 있는 것만 읽어 **비율·건수**로만 요약한다. 보유·수량·금액(실계좌)은 여기 없다 —
그쪽은 pb-private/scorecard/build_week.py 가 같은 주에 대해 따로 만든다 (week_YYYY-WW.md).

읽는 것
  reports/decisions.json           모의 대결 (나 · 나🔥(감/판단) · PB · PB🔥 · 규칙) — 이번 주 채점분 + 누적 tally
  views/registry.json              관점(렌즈) 등급·상태
  reports/studies/*.json           사전등록 연구 등급
  reports/archive/committee/*.json 운용회의 레짐 (일별) — 없으면 reports/committee_hist.json 확률만
  reports/events.json              서킷·사이드카 건수
  reports/health.json              워크플로 실패 건수 (fails7d)
  reports/macro_series.json        코스피 주간 등락 (비율)

쓰는 것: reports/scorecard_week.json · reports/scorecard_week.md
텔레그램: TELEGRAM_TOKEN·TELEGRAM_CHAT_ID 가 있으면 한 줄 (비율만). --no-send 로 끔.

  python scripts/scorecard_week.py [--date YYYY-MM-DD] [--no-send]
주 = --date(기본 오늘 KST)가 속한 ISO 주 (월~일). 일요일 아침에 돌면 '그 일요일로 끝나는 주'.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
KST = timezone(timedelta(hours=9))
PARTICIPANTS = ["나", "나🔥", "PB", "PB🔥", "규칙"]
GRADE_ORDER = ["A", "B", "C", "F", "검증전"]


# ---------------------------------------------------------------- 공통
def _j(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def week_bounds(d: date) -> tuple[date, date]:
    """d 가 속한 ISO 주의 (월요일, 일요일)."""
    mon = d - timedelta(days=d.weekday())
    return mon, mon + timedelta(days=6)


def pct(x, d: int = 1, sign: bool = True) -> str:
    if x is None:
        return "n/a"
    s = f"{abs(x) * 100:.{d}f}%"
    return (("+" if x >= 0 else "−") if sign else ("−" if x < 0 else "")) + s


def _in_week(ds: str | None, mon: date, sun: date) -> bool:
    try:
        return mon <= date.fromisoformat((ds or "")[:10]) <= sun
    except ValueError:
        return False


# ---------------------------------------------------------------- 모의 대결
def _blank() -> dict:
    return {"n": 0, "win": 0, "pnl": 0.0, "rets": []}


def _finish(t: dict) -> dict:
    rs = t.pop("rets", [])
    t["pnl"] = round(t["pnl"])
    t["trades"] = len(rs)
    t["hit"] = round(sum(1 for r in rs if r > 0) / len(rs), 3) if rs else None
    t["avg_ret"] = round(sum(rs) / len(rs), 4) if rs else None
    t["win_rate"] = round(t["win"] / t["n"], 3) if t["n"] else None
    return t


def duel_record(items: list[dict], mon: date, sun: date) -> dict:
    """이번 주(판단일 기준) 채점이 끝난 대결의 참가자별 전적. 나🔥 는 근거(감/판단)로 쪼갠다.

    n = 참가한 판 수, win = 그 판의 승자, hit = 진입한 판 중 수익 낸 비율, avg_ret = 진입한 판 평균 수익률,
    pnl = 모의 손익(공개 모의 금액 기준, 실계좌 아님)."""
    rec = {w: _blank() for w in PARTICIPANTS}
    bold = {"감": _blank(), "판단": _blank()}
    scored = void = pending = 0
    for it in items:
        if not _in_week(it.get("date"), mon, sun):
            continue
        r = it.get("result")
        if not r:
            pending += 1
            continue
        if r.get("void"):
            void += 1
            continue
        scored += 1
        for who, p in (it.get("picks") or {}).items():
            if who not in r:
                continue
            rw = r[who] or {}
            t = rec.setdefault(who, _blank())
            t["n"] += 1
            t["pnl"] += float(rw.get("pnl") or 0)
            if r.get("winner") == who:
                t["win"] += 1
            if not p.get("cash") and rw.get("ret") is not None:
                t["rets"].append(float(rw["ret"]))
            if who == "나🔥":
                k = p.get("basis") or ("감" if not p.get("why") or p.get("why") == "감" else "판단")
                b = bold.setdefault(k, _blank())
                b["n"] += 1
                b["pnl"] += float(rw.get("pnl") or 0)
                if "나" in r and float(rw.get("pnl") or 0) > float((r["나"] or {}).get("pnl") or 0):
                    b["win"] += 1   # 나🔥 의 win = '나'를 이긴 횟수
                if not p.get("cash") and rw.get("ret") is not None:
                    b["rets"].append(float(rw["ret"]))
    out = {w: _finish(t) for w, t in rec.items()}
    out["나🔥"]["by_basis"] = {k: _finish(t) for k, t in bold.items()}
    return {"scored": scored, "void": void, "pending": pending, "by": out}


def crash_day_pb(items: list[dict], mon: date, sun: date) -> dict:
    """급락일 PB 행동률 — 이번 주 급락일(항목 crash_day=True, KR entry) 수와 그중 PB 가 행동한 수.
    행동 = 현금이 아닌 PB 픽, 또는 현금이지만 게이트 불통 사유를 명시(pb_view.gate_fail 또는 why 에 '게이트')."""
    n = acted = 0
    days = []
    for it in items:
        if it.get("kind") not in (None, "entry") or str(it.get("market", "KR")).upper() == "US" or not it.get("crash_day"):
            continue
        if not _in_week(it.get("date"), mon, sun):
            continue
        pb = (it.get("picks") or {}).get("PB")
        if not pb:
            continue
        pv = it.get("pb_view") or {}
        ok = (not pb.get("cash")) or bool(pv.get("gate_fail")) or ("게이트" in str(pv.get("why") or ""))
        n += 1
        acted += int(ok)
        days.append({"date": it.get("date"), "acted": ok, "cash": bool(pb.get("cash"))})
    return {"n": n, "acted": acted, "rate": (acted / n) if n else None, "days": days}


# ---------------------------------------------------------------- 렌즈·연구
def lens_table(reg: dict) -> dict:
    rows, counts = [], {g: 0 for g in GRADE_ORDER}
    for l in reg.get("lenses") or []:
        g = ((l.get("evidence") or {}).get("grade")) or "검증전"
        counts[g] = counts.get(g, 0) + 1
        rows.append({"id": l.get("id"), "name": l.get("name_ko"), "family": l.get("family"), "grade": g,
                     "status": l.get("status"), "roles": l.get("roles") or {}})
    return {"n": len(rows), "by_grade": counts, "rows": rows, "updated": reg.get("updated")}


def _grade_of(v) -> str | None:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get("grade") or v.get("lens_grade")
    return None


def study_grades(studies_dir: Path) -> list[dict]:
    """reports/studies/*.json 에서 (연구, 가설, 등급) 을 긁는다 — 파일마다 형식이 달라 알려진 키만 본다."""
    out = []
    for fp in sorted(studies_dir.glob("*.json")):
        j = _j(fp, {})
        if not isinstance(j, dict):
            continue
        name = fp.stem
        if isinstance(j.get("grades"), dict):
            for h, v in j["grades"].items():
                g = _grade_of(v)
                if g:
                    out.append({"study": name, "id": h, "grade": g, "why": (v.get("why") if isinstance(v, dict) else None)})
        if isinstance(j.get("signals"), list):
            for s in j["signals"]:
                if isinstance(s, dict) and s.get("grade"):
                    out.append({"study": name, "id": s.get("id") or s.get("lens_id"), "grade": s["grade"], "why": s.get("name")})
        if isinstance(j.get("lens_grade"), str):
            out.append({"study": name, "id": "lens", "grade": j["lens_grade"], "why": None})
        if isinstance(j.get("grade"), str) and not isinstance(j.get("grades"), dict):
            out.append({"study": name, "id": j.get("id") or "-", "grade": j["grade"], "why": j.get("question")})
    return out


# ---------------------------------------------------------------- 레짐·이벤트·건강
def regime_history(archive_dir: Path, hist_rows: list[dict], mon: date, sun: date) -> list[dict]:
    by_day: dict[str, dict] = {}
    for fp in sorted(archive_dir.glob("*.json")):
        d = fp.stem[:10]
        if not _in_week(d, mon, sun):
            continue
        j = _j(fp, {}) or {}
        if d in by_day and (j.get("asof") or "") <= (by_day[d].get("asof") or ""):
            continue   # 같은 날 여러 세션 — 가장 늦은 회의(보통 장후)만
        lab = (((j.get("macro") or {}).get("regime")) or {}).get("label")
        probs = {str(s.get("name")).split(" ")[0]: s.get("prob") for s in (j.get("scenarios") or []) if isinstance(s, dict)} or None
        by_day[d] = {"date": d, "session": j.get("session") or fp.stem[11:] or None, "asof": j.get("asof"), "regime": lab, "probs": probs,
                     "stance": (j.get("stance") or {}).get("stance")}
    for r in hist_rows or []:
        d = r.get("date")
        if _in_week(d, mon, sun) and d not in by_day:
            by_day[d] = {"date": d, "session": None, "asof": None, "regime": None, "probs": r.get("probs"), "stance": None}
    return [by_day[k] for k in sorted(by_day)]


def event_counts(events: list[dict], mon: date, sun: date) -> dict:
    c = {"서킷": 0, "사이드카": 0, "경보": 0, "total": 0}
    for e in events or []:
        if not _in_week(e.get("date"), mon, sun):
            continue
        t = str(e.get("type") or "")
        if "서킷" not in t and "사이드카" not in t:
            continue
        c["total"] += 1
        if t.startswith("경보"):
            c["경보"] += 1
        elif "서킷" in t:
            c["서킷"] += 1
        elif "사이드카" in t:
            c["사이드카"] += 1
    return c


def health_summary(h: dict | None) -> dict:
    h = h or {}
    f7 = h.get("fails7d") or {}
    return {"asof": h.get("asof"), "failed_runs_7d": int(sum(int(v or 0) for v in f7.values())), "by_workflow": f7,
            "issues": len(h.get("issues") or [])}


def kospi_week(ms: dict | None, mon: date, sun: date) -> dict | None:
    s = ((ms or {}).get("series") or {}).get("KOSPI") or []
    pts = [(r[0][:10], float(r[4] if len(r) >= 6 else r[1])) for r in s if r and r[0]]
    if not pts:
        return None
    before = [p for p in pts if p[0] < mon.isoformat()]
    inw = [p for p in pts if mon.isoformat() <= p[0] <= sun.isoformat()]
    if not before or not inw:
        return None
    return {"base": before[-1][0], "last": inw[-1][0], "ret": round(inw[-1][1] / before[-1][1] - 1, 4), "days": len(inw)}


# ---------------------------------------------------------------- 정합성 표 (공개 입력만 — 값은 비공개 성적표가 채움)
def consistency_skeleton(reg: dict, regime: str | None) -> list[dict]:
    """규칙 간 정합성 표의 뼈대. 공개 저장소엔 한도·설정만 있고 현재값은 없다 (pb-private week_YYYY-WW.md 가 채움)."""
    def env(k, dflt):
        try:
            return float(os.environ.get(k, "") or dflt)
        except ValueError:
            return dflt
    params = {}
    for l in reg.get("lenses") or []:
        if l.get("id") == "personal.theme_concentration":
            params = ((l.get("read") or {}).get("params")) or {}
    cap = env("SCORECARD_THEME_CAP", params.get("cap", 0.40))
    band = env("SCORECARD_THEME_BAND", params.get("band", 0.45))
    bear = regime == "하락장"
    rows = [
        {"rule": "[3] 테마 집중도", "limit": f"목표 {pct(cap, 0, False)} · 발동선 {pct(band, 0, False)} (주 1회 점검)", "input": "env SCORECARD_THEME_CAP/BAND · registry personal.theme_concentration"},
        {"rule": "[11] 1일 VaR99 (60일 실현, 계기판)", "limit": "하락장 1.5% / 기본 2% — 판정 아님(계기판)" if bear else "기본 2% / 하락장 1.5% — 판정 아님(계기판)", "input": f"레짐 {regime or 'n/a'} (views kr_regime)"},
        {"rule": "[11] 스트레스", "limit": "어느 시나리오도 −15% 초과 금지", "input": "시나리오: 2020-03 · 2024-08-05 · 2026-07 반도체 · 원/달러 +10%"},
        {"rule": "[0] 위성 북 크기", "limit": "상한 (비공개 금액) — 초과분 연말까지 코어 이전", "input": "pb-private holdings"},
        {"rule": "[5] 보유 백스톱", "limit": "종목별 −20% 도달 시 2주 내 정리", "input": "pb-private holdings"},
    ]
    for r in rows:
        r.update({"value": "비공개 (pb-private 성적표)", "status": "—"})
    return rows


# ---------------------------------------------------------------- 출력
def telegram_line(res: dict) -> str:
    by = res["duel"]["by"]
    bb = by["나🔥"].get("by_basis", {})

    def wr(t):
        return pct(t.get("win_rate"), 0, False) if t.get("n") else "—"
    parts = [f"대결 {res['duel']['scored']}건",
             f"나 승률 {wr(by['나'])}", f"나🔥(감) {wr(bb.get('감', {}))}", f"나🔥(판단) {wr(bb.get('판단', {}))}",
             f"PB {wr(by['PB'])}", f"PB🔥 {wr(by['PB🔥'])}"]
    k = res.get("kospi")
    if k:
        parts.append(f"코스피 주간 {pct(k['ret'])}")
    rg = [r["regime"] for r in res["regime"] if r.get("regime")]
    if rg:
        parts.append(f"레짐 {rg[-1]}")
    g = res["lenses"]["by_grade"]
    parts.append("렌즈 " + "/".join(f"{x}{g.get(x, 0)}" for x in ("A", "B", "C", "F")))
    ev = res["events"]
    if ev["total"]:
        parts.append(f"서킷·사이드카 {ev['total']}건")
    h = res["health"]
    if h["failed_runs_7d"]:
        parts.append(f"워크플로 실패 {h['failed_runs_7d']}건")
    return f"📊 주간 성적표 준비됨 ({res['week']['label']}) — " + " · ".join(parts)


def render_md(res: dict) -> str:
    w = res["week"]
    L = [f"# 주간 성적표 (공개) {w['label']}", "",
         f"- 기준: {res['asof']} KST · ISO 주 {w['iso']} ({w['mon']} ~ {w['sun']}) · 비율·건수만 (금액·보유는 비공개 성적표)",
         f"- 코스피 주간: {pct(res['kospi']['ret']) if res.get('kospi') else 'n/a'}" + (f" ({res['kospi']['base']} → {res['kospi']['last']})" if res.get("kospi") else ""),
         "", "## 모의 대결 (이번 주 판단일 기준)", "",
         f"채점 {res['duel']['scored']}건 · 제외 {res['duel']['void']}건 · 채점 대기 {res['duel']['pending']}건 — 모의 금액 기준, 실계좌 아님", "",
         "| 참가자 | 판 | 승 | 승률 | 진입 | 적중 | 평균 수익률 | 모의 손익 |", "|---|---|---|---|---|---|---|---|"]
    by = res["duel"]["by"]
    for who in PARTICIPANTS:
        t = by.get(who) or _finish(_blank())
        L.append(f"| {who} | {t['n']} | {t['win']} | {pct(t['win_rate'], 0, False)} | {t['trades']} | {pct(t['hit'], 0, False)} | {pct(t['avg_ret'], 2)} | {t['pnl']:+,} |")
        if who == "나🔥":
            for k, b in (t.get("by_basis") or {}).items():
                L.append(f"| └ 나🔥({k}) | {b['n']} | {b['win']}* | {pct(b['win_rate'], 0, False)} | {b['trades']} | {pct(b['hit'], 0, False)} | {pct(b['avg_ret'], 2)} | {b['pnl']:+,} |")
    L += ["", "\\* 나🔥 의 '승' = 같은 판에서 '나'보다 손익이 큰 횟수 — **레버리지 해금 근거에서 제외**(결재 #14, 10/17~ 기록·비교용)", ""]
    cd = res.get("crash_pb") or {}
    L += [f"급락일 PB 행동률: {cd.get('acted', 0)}/{cd.get('n', 0)}" + (f" ({pct(cd['rate'], 0, False)})" if cd.get("rate") is not None else " (급락일 없음)")
          + " — 급락일(코스피 −5%)에 현금이 아닌 PB 픽 또는 게이트 불통 사유 명시 건수", ""]
    cum = res.get("cumulative") or {}
    if cum:
        L += ["누적 (전체 기간): " + " · ".join(
            f"{who} {t.get('win', 0)}/{t.get('n', 0)}" + (f" (적중 {pct(t.get('hit'), 0, False)})" if t.get("hit") is not None else "")
            for who, t in cum.items() if isinstance(t, dict)), ""]
    L += ["## 레짐 (운용회의)", ""]
    if res["regime"]:
        L += ["| 날짜 | 세션 | 레짐 | 강세/기본/약세 | 스탠스 |", "|---|---|---|---|---|"]
        for r in res["regime"]:
            p = r.get("probs") or {}
            L.append(f"| {r['date']} | {r.get('session') or ''} | {r.get('regime') or ''} | {'/'.join(pct(p.get(k), 0, False) for k in ('강세', '기본', '약세')) if p else ''} | {r.get('stance') or ''} |")
    else:
        L.append("기록 없음.")
    ev = res["events"]
    L += ["", "## 이벤트 · 운영", "",
          f"- 서킷·사이드카: 실제 {ev['서킷'] + ev['사이드카']}건 (서킷 {ev['서킷']} · 사이드카 {ev['사이드카']}) · 경보(기준 근접) {ev['경보']}건",
          f"- 워크플로 실패 (7일): {res['health']['failed_runs_7d']}건" + (f" — {', '.join(f'{k} {v}' for k, v in res['health']['by_workflow'].items())}" if res["health"]["by_workflow"] else "") + f" · 데이터 이슈 {res['health']['issues']}건 (health {res['health']['asof']})",
          "", "## 관점(렌즈) 등급", "",
          "등급별: " + " · ".join(f"{g} {res['lenses']['by_grade'].get(g, 0)}" for g in GRADE_ORDER) + f" (총 {res['lenses']['n']}, registry {res['lenses']['updated']})", "",
          "| 렌즈 | 등급 | 상태 | 진입/청산/배분 |", "|---|---|---|---|"]
    for r in res["lenses"]["rows"]:
        ro = r["roles"]
        L.append(f"| {r['name']} (`{r['id']}`) | {r['grade']} | {r['status'] or ''} | {ro.get('entry', '-')}/{ro.get('exit', '-')}/{ro.get('allocation', '-')} |")
    L += ["", "## 연구 등급 (reports/studies)", "", "| 연구 | 가설 | 등급 | 메모 |", "|---|---|---|---|"]
    for s in res["studies"]:
        L.append(f"| {s['study']} | {s['id']} | {s['grade']} | {(s.get('why') or '')[:60]} |")
    L += ["", "## 규칙 간 정합성 (뼈대 — 값은 비공개 성적표 week_YYYY-WW.md)", "",
          "| 규칙 | 한도·설정 (공개 입력) | 현재값 | 상태 |", "|---|---|---|---|"]
    for r in res["consistency"]:
        L.append(f"| {r['rule']} | {r['limit']} | {r['value']} | {r['status']} |")
    L += ["", "---", "", "공개 층은 비율·건수만 다룬다. 위성 북 vs 코스피 알파·위반·벌금·반도체 비중·순자산 목표 진행률은 비공개 성적표에."]
    return "\n".join(L) + "\n"


def build(today: date | None = None) -> dict:
    now = datetime.now(KST)
    today = today or now.date()
    mon, sun = week_bounds(today)
    iso = f"{sun.isocalendar()[0]}-W{sun.isocalendar()[1]:02d}"
    dec = _j(REPORTS / "decisions.json", {}) or {}
    reg = _j(ROOT / "views" / "registry.json", {}) or {}
    regime = regime_history(REPORTS / "archive" / "committee", (_j(REPORTS / "committee_hist.json", {}) or {}).get("rows") or [], mon, sun)
    cur_regime = next((r["regime"] for r in reversed(regime) if r.get("regime")), None)
    if cur_regime is None:
        for l in (_j(REPORTS / "views.json", {}) or {}).get("lenses") or []:
            if isinstance(l, dict) and l.get("id") == "kr_regime":
                cur_regime = l.get("state")
    res = {
        "asof": now.strftime("%Y-%m-%d %H:%M"),
        "week": {"iso": iso, "mon": mon.isoformat(), "sun": sun.isoformat(), "label": f"{mon:%m/%d}~{sun:%m/%d}", "partial": today < sun},
        "kospi": kospi_week(_j(REPORTS / "macro_series.json", {}), mon, sun),
        "duel": duel_record(dec.get("items") or [], mon, sun),
        "cumulative": dec.get("tally") or {},
        "crash_pb": crash_day_pb(dec.get("items") or [], mon, sun),
        "regime": regime,
        "regime_now": cur_regime,
        "events": event_counts((_j(REPORTS / "events.json", {}) or {}).get("events") or [], mon, sun),
        "health": health_summary(_j(REPORTS / "health.json", {})),
        "lenses": lens_table(reg),
        "studies": study_grades(REPORTS / "studies"),
        "consistency": consistency_skeleton(reg, cur_regime),
    }
    res["telegram"] = telegram_line(res)
    try:   # STANDARD 8절 상단 3칸(묶음 B, 추가만)
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from screener import topline_from
        res["top"] = topline_from.scorecard(res)
    except Exception:  # noqa: BLE001
        pass
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="이 날짜가 속한 주 (기본 오늘 KST)")
    ap.add_argument("--no-send", action="store_true", help="텔레그램 보내지 않음")
    a = ap.parse_args()
    res = build(date.fromisoformat(a.date) if a.date else None)
    (REPORTS / "scorecard_week.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (REPORTS / "scorecard_week.md").write_text(render_md(res), encoding="utf-8")
    print(res["telegram"])
    if not a.no_send and os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        try:
            sys.path.insert(0, str(ROOT))
            from screener.report import send_telegram
            send_telegram(res["telegram"])
        except Exception as e:  # noqa: BLE001 — 알림 실패가 성적표 저장을 막지 않게
            print(f"::warning::텔레그램 전송 실패: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
