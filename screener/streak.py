"""운용회의 매수 후보 '연속 N일째' 표시 (req-dev-42019d08, 10/23 PB — 겸이 "이게 맨날 dell이네?").

표시만 바꾼다 — 후보 산식(드라이버·20일 수익률 조건)은 그대로. 같은 목록이 반복되면 '새 정보 없음'을 바로 알게
각 후보에 streak(오늘 포함 연속 회의일 수)·new(직전 회의엔 없던 종목)를 붙인다.

기록 원천: 국장 reports/committee_hist.json · 미장 reports/committee_us_hist.json 의 rows[{date, long[...]}].
회의일 기준(거래일 아님) — 하루 여러 판이면 hist 는 날짜당 마지막 판 하나라서 그대로 1일로 센다.
"""
from __future__ import annotations


def streaks(rows: list[dict], today: str, today_long: list[str], key: str = "long") -> dict[str, int]:
    """오늘 후보 각각의 연속 회의일 수(오늘 포함). rows 에 오늘 행이 있어도 무시하고 today_long 을 쓴다."""
    past = sorted((r for r in rows or [] if str(r.get("date", "")) < today), key=lambda r: r["date"], reverse=True)
    out = {}
    for t in today_long:
        n = 1
        for r in past:
            if t in (r.get(key) or []):
                n += 1
            else:
                break
        out[t] = n
    return out


def mark(items: list[dict], rows: list[dict], today: str, key: str = "long", sym: str = "s") -> dict:
    """items(후보 dict 목록)에 streak·new 를 제자리에서 붙이고 요약을 돌려준다.

    new = 직전 회의 기록이 있고 그 회의엔 없던 종목(기록이 아예 없으면 첫 회의라 new 를 붙이지 않는다).
    """
    has_prev = any(str(r.get("date", "")) < today for r in rows or [])
    st = streaks(rows, today, [x[sym] for x in items], key)
    for x in items:
        x["streak"] = st[x[sym]]
        x["new"] = bool(has_prev and st[x[sym]] == 1)
    n = len(items)
    new = [x[sym] for x in items if x["new"]]
    rep = n - len(new)
    line = ""
    if n and has_prev:
        mx = max(items, key=lambda x: x["streak"])
        line = (f"매수 후보 {n}개 중 신규 {len(new)} · 반복 {rep}"
                + (f" · 최장 {mx[sym]} {mx['streak']}일째" if mx["streak"] > 1 else "")
                + (" — 직전 회의와 같은 목록(새 정보 없음)" if not new else ""))
    return {"n": n, "new": new, "repeat": rep, "line": line, "basis": "연속 회의일 수(오늘 포함) — 산식 변경 없음, 표시만"}


def tag(x: dict) -> str:
    """텔레그램용 짧은 꼬리: 신규 → '🆕', 2일 이상 → '·N일째'."""
    if x.get("new"):
        return "🆕"
    n = x.get("streak") or 0
    return f"·{n}일째" if n >= 2 else ""
