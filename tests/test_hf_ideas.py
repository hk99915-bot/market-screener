"""HF 아이디에이션(scripts/hf_ideas.py)·S4 페이드 전진 추적(scripts/hf_forward.py) — 임시 저장소로 검증."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hf_forward as F  # noqa: E402
import hf_ideas as I  # noqa: E402


def _chart(n=300, start=date(2025, 8, 1), c0=10_000.0, v=200_000, last=None):
    ch, d = [], start
    for i in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        ch.append({"t": d.isoformat(), "o": c0, "h": c0 * 1.01, "l": c0 * 0.99, "c": c0, "v": v})
        d += timedelta(days=1)
    if last:
        ch[-1].update(last)
    return ch


def _write(root: Path, mk: str, code: str, chart, name=None, drivers=None):
    p = root / "reports" / "detail" / mk
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{code}.json").write_text(json.dumps({"name": name or code, "chart": chart, "drivers": drivers or {}}, ensure_ascii=False))


def test_ideas_types_and_status(tmp_path):
    (tmp_path / "reports").mkdir()
    base = _chart()
    today = date.fromisoformat(base[-1]["t"])
    _write(tmp_path, "KR", "S4CHASE", _chart(last={"c": 12_000.0, "o": 10_100.0, "v": 2_000_000}))           # 거래량 10배 + 신고가
    _write(tmp_path, "KR", "HIGH", _chart(last={"c": 10_600.0, "v": 200_000}))                             # 52주 고점(거래량 보통)
    drop = _chart()
    for b in drop[-5:]:
        b["c"] = 9_000.0
    _write(tmp_path, "KR", "EARN", drop)
    _write(tmp_path, "US", "ILLQ", _chart(c0=10.0, v=1000))                                                # 유동성 미달
    (tmp_path / "reports" / "calendar.json").write_text(json.dumps({"events": [
        {"date": (today + timedelta(days=3)).isoformat(), "type": "실적", "ticker": "EARN", "market": "KR", "name": "EARN 실적"}]}))
    (tmp_path / "reports" / "macro_series.json").write_text(json.dumps({"series": {}}))
    o = I.build(today=today, root=tmp_path)
    types = {(x["code"], x["type"]) for x in o["ideas"]}
    assert ("S4CHASE", "거래량 돌파(추격 금지)") in types and ("HIGH", "52주 고점 돌파") in types and ("EARN", "실적 임박") in types
    s4 = next(x for x in o["ideas"] if x["code"] == "S4CHASE")
    assert s4["direction"].startswith("회피") and "F" in s4["status"]
    assert not any(x["code"] == "ILLQ" for x in o["ideas"])
    assert ("S4CHASE", "52주 고점 돌파") not in types                       # 추격 금지 우선
    assert all(x.get("src") and x.get("status") for x in o["ideas"])
    assert I.lines(o)[0].startswith("아이디어")


def test_macro_tilts_threshold():
    ser = lambda a, b: [["d", 0, 0, 0, a]] * 20 + [["d", 0, 0, 0, b]]  # noqa: E731
    t = I.macro_tilts({"US10Y": ser(4.80, 5.10), "WTI": ser(70, 72), "USDKRW": ser(1350, 1320)})
    drivers = " ".join(x["driver"] for x in t)
    assert "미 10년" in drivers and "원달러" in drivers and "WTI" not in drivers


def test_forward_records_and_scores(tmp_path):
    ch = _chart(n=60, start=date(2026, 9, 1))
    k = next(i for i, b in enumerate(ch) if b["t"] >= "2026-10-22")
    ch[k].update({"c": 12_000.0, "v": 3_000_000})                       # 신호
    for b in ch[k + 1:]:
        b.update({"o": 12_000.0, "c": 11_000.0})                         # 이후 하락 → 페이드 이익
    _write(tmp_path, "KR", "SIG", ch)
    for i in range(35):                                                  # 유니버스(평탄)
        _write(tmp_path, "KR", f"U{i:02d}", _chart(n=60, start=date(2026, 9, 1)))
    st = F.update({"v": 1, "start": F.START, "events": []}, root=tmp_path)
    ev = [e for e in st["events"] if e["code"] == "SIG"]
    assert ev and ev[0]["d"] == ch[k]["t"]
    if ev[0]["status"] == "완료":
        assert ev[0]["fade"] > 0
    assert st["summary"]["verdict"].startswith("추적 중")
    assert F.is_s4(ch, k) and not F.is_s4(ch, k - 1)


def test_watch_status_strong_vs_context(tmp_path):
    ch = _chart()
    for b in ch:
        b["s200"] = 9_000.0
    _write(tmp_path, "KR", "W1", ch)
    w = {"code": "W1", "market": "KR", "reason": "t"}
    st = I.watch_status(w, root=tmp_path)
    assert st["action"] == "대기" and any("200일선" in x for x in st["on"])     # 배경 조건만 → 대기
    p = tmp_path / "reports" / "detail" / "KR" / "W1.json"
    d = json.loads(p.read_text())
    d["flow_note"] = "5일 외국인 +12억 · 기관 +3억 — 동반 매수"
    p.write_text(json.dumps(d, ensure_ascii=False))
    assert I.watch_status(w, root=tmp_path)["action"] == "체크리스트 재실행"


def test_late_flags_need_two():
    ft = {"s4": True, "ext50": 0.30, "ext50_p90": 0.15, "ret20": 0.10, "hi250": 1.0}
    assert len(I.late_flags("KR", ft)) == 2                                   # S4 + 이격 상위 10%
    assert I.late_flags("KR", {**ft, "s4": False, "ext50": 0.05}) == []
    assert any("B2" in x for x in I.late_flags("US", {**ft, "s4": False}))   # 미장 52주 고점 근처


def test_us_kr_gap_regression(tmp_path):
    import csv
    nd, rows, px, k = [], [], 100.0, 2500.0
    d = date(2024, 1, 1)
    for i in range(120):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        r = 0.01 * ((i * 7) % 5 - 2)                                       # 결정적 나스닥 수익률
        px *= 1 + r
        nd.append([d.isoformat(), px, px, px, px, 0])
        nxt = d + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        o = k * (1 + 0.5 * r)
        rows.append({"date": nxt.isoformat(), "kospi_open": o, "kospi_close": o})
        k = o
        d = nxt
    (tmp_path / "data" / "deriv").mkdir(parents=True)
    with open(tmp_path / "data" / "deriv" / "daily.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "kospi_open", "kospi_close"])
        w.writeheader()
        w.writerows(rows)
    g = I.us_kr_gap({"NASDAQ": nd}, tmp_path)
    assert g and abs(g["beta"] - 0.5) < 0.05 and g["status"].startswith("검증전")
