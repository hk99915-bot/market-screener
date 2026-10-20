"""CIO TOP3 점검(reports/studies/cio_top3_review_2026-10-21.md) — D1 확정판 캡처 · D3 미장 실패 기록 · 스위치 CIO_TOP3_V2 OFF/ON(P1~P3)."""
import re
import sys
import types
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from screener import committee, config, us_committee
from screener import idea_tracking as T

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent.parent


def board(asof, codes, day="2026-10-16"):
    return {"date": day, "asof": f"{day} {asof}", "ideas_top": {"items": [{"s": c, "n": c, "status": "실행 후보"} for c in codes]}}


class FinalBoardCapture(unittest.TestCase):   # D1
    def test_last_post_close_board_wins(self):
        book, now = {}, datetime(2026, 10, 16, 20, tzinfo=KST)
        T.capture(book, board("13:35", ["015760", "004800", "138930"]), now)
        self.assertEqual(book.get("rows", []), [])            # 장중 판은 기록 안 함
        T.capture(book, board("15:50", ["111111", "222222", "333333"]), now)
        T.capture(book, board("19:44", ["402340", "012450", "010120"]), now)
        self.assertEqual([r["ticker"] for r in book["rows"]], ["402340", "012450", "010120"])
        self.assertEqual({r["proposed_at"] for r in book["rows"]}, {"2026-10-16 19:44"})
        self.assertIn("확정판으로 교체", book["rows"][0]["replaced"])

    def test_frozen_after_day_change_and_after_pricing(self):
        book = {}
        T.capture(book, board("19:44", ["A", "B", "C"]), datetime(2026, 10, 16, 20, tzinfo=KST))
        T.capture(book, board("21:00", ["X", "Y", "Z"]), datetime(2026, 10, 17, 0, 5, tzinfo=KST))
        self.assertEqual([r["ticker"] for r in book["rows"]], ["A", "B", "C"])
        book["rows"][0]["state"] = {"status": "open", "entry_date": "2026-10-17"}
        T.capture(book, board("22:00", ["X", "Y", "Z"]), datetime(2026, 10, 16, 22, 5, tzinfo=KST))
        self.assertEqual([r["ticker"] for r in book["rows"]], ["A", "B", "C"])

    def test_us_last_board_before_open(self):
        book, now = {}, datetime(2026, 10, 21, 23, tzinfo=KST)
        T.capture(book, board("20:52", ["AAPL"], "2026-10-21"), now, "US")
        T.capture(book, board("21:52", ["NVDA"], "2026-10-21"), now, "US")
        T.capture(book, board("22:52", ["MSFT"], "2026-10-21"), now, "US")
        self.assertEqual([r["ticker"] for r in book["rows"]], ["NVDA"])
        self.assertEqual(book["rows"][0]["id"], "US:2026-10-21:NVDA")


class USFailureSurfaced(unittest.TestCase):   # D3
    def test_price_error_recorded(self):
        import tempfile
        def boom(*a, **k):
            raise RuntimeError("no chart")
        m = board("21:52", ["NVDA"], "2026-10-21")
        m["ideas_top"]["items"][0].update(side="롱", entry=100, entry_max=102, stop=90, target=120)
        with tempfile.TemporaryDirectory() as tmp, patch.object(T, "REPORT_DIR", Path(tmp)), \
                patch.dict(sys.modules, {"screener.fwd_perf": types.SimpleNamespace(us_bars=boom)}):
            b = T.run(m, datetime(2026, 10, 21, 22, tzinfo=KST), market="US")
        self.assertIn("RuntimeError", b["errors"]["US"]["error"])
        self.assertEqual(b["rows"][0]["state"]["status"], "review")
        self.assertIn("ticker(종목코드", b["schema"])

    def test_committee_logs_warning_not_info(self):
        src = (ROOT / "screener/committee.py").read_text(encoding="utf-8")
        self.assertIn('out["idea_tracking_top"] = {"error"', src)
        self.assertNotIn('log.info("미장 아이디어 추적 실패', src)


# ── 스위치 OFF/ON ──
BOX = {"close": 100.0, "stop": 90.0, "stop_pct": 0.1, "target": 120.0, "atr_pct": 0.04, "skip": False}


def kr_fixture():
    def src(k, g):
        return {"k": k, "label": k, "side": "agree", "grade": g}
    S = {c: [src("exec_plan", "C"), src("committee_ideas", "검증전")] for c in ("000001", "000002", "000003")}
    S["000004"] = [src("research:tp_up", "검증전"), src("disclosure:plus", "검증전")]
    S["000005"] = [src("exec_plan", "C"), src("research:tp_up", "검증전")]
    return S, {c: {"n": c} for c in S}


def run_kr(on):
    with patch.object(config, "CIO_TOP3_V2", on), patch.object(committee, "_v2_sources", lambda *a: kr_fixture()), \
            patch.object(committee, "_j", lambda n, d=None: d), patch.object(committee, "_risk_box", lambda c, *a: dict(BOX)):
        return committee._v2_ideas_top({"stance": {}}, [], {}, date(2026, 10, 20), peers=[])


def run_us(on):
    peers = [{"s": s, "n": s, "drv": d} for s, d in (("AAA", 0.5), ("BBB", 0.45), ("CCC", 0.41), ("DDD", 0.4))]
    cal = [{"type": "실적", "ticker": "DDD", "date": "2026-10-25"}]
    with patch.object(config, "CIO_TOP3_V2", on):
        return us_committee.ideas_top_us({}, peers, {}, cal, date(2026, 10, 20), lambda c: dict(BOX),
                                         lambda c: [{"c": 110, "s50": 100, "t": "2026-10-19"}], "pass", "ok")


class SwitchOff(unittest.TestCase):
    def test_kr_unchanged(self):   # 10/21 이전 동작: 합산 0.9 자기 참조 3종목이 TOP3, 진입 하한 = 종가
        r = run_kr(False)
        self.assertEqual([x["s"] for x in r["items"]], ["000001", "000002", "000003"])
        self.assertEqual([x["status"] for x in r["items"]], ["대기 — 촉매 없음"] * 3)
        self.assertEqual(r["items"][0]["score"], 0.9)
        self.assertTrue(all(x["entry"] == 100.0 for x in r["items"] + r["candidates"]))
        self.assertNotIn("rule", r); self.assertNotIn("valid", r["items"][0])

    def test_us_unchanged(self):
        r = run_us(False)
        self.assertEqual([x["s"] for x in r["items"]], ["AAA", "BBB", "CCC"])
        self.assertEqual(r["items"][0]["entry"], 100.0); self.assertNotIn("rule", r)


class SwitchOn(unittest.TestCase):
    def test_p2_exec_first_one_wait_and_self_ref_max(self):
        r = run_kr(True)
        self.assertEqual([x["s"] for x in r["items"]], ["000005", "000004", "000001"])   # 실행 2 + 대기 1
        self.assertEqual(sum(not x["status"].startswith("실행") for x in r["items"]), 1)
        self.assertEqual(r["candidates"][0]["score"], 0.6)   # exec_plan .6 + committee_ideas .3 → max .6
        self.assertIsNone(r["exec_zero"])

    def test_p2_exec_zero_note(self):
        items, cands, note = T.pick_top3([{**dict(entry=98, entry_max=102, stop=90, target=120, valid=T.VALID,
                                                  catalyst=[], catalyst_note="없음"), "status": "대기 — 촉매 없음"}] * 1 + [], "KR")
        self.assertEqual(len(items), 1); self.assertIn("오늘 KR 실행 0", note)

    def test_p1_missing_field_disqualified(self):
        ok = dict(entry=98, entry_max=102, stop=90, target=120, valid=dict(T.VALID), catalyst=[{"what": "x"}], status="실행 후보")
        rows = [dict(ok, s="A", valid=None), dict(ok, s="B", catalyst=[]), dict(ok, s="C", target=None), dict(ok, s="D")]
        items, cands, _ = T.pick_top3(rows)
        self.assertEqual([x["s"] for x in items], ["D"])
        r = run_kr(True)
        self.assertTrue(all(T.top3_ready(x) for x in r["items"]))
        self.assertEqual(r["items"][-1]["catalyst_note"], "없음")

    def test_p3_entry_floor(self):
        self.assertAlmostEqual(T.entry_floor(100, 90, 0.04), 98.0)    # 종가−0.5ATR 가 더 높음
        self.assertAlmostEqual(T.entry_floor(100, 98, 0.04), 99.0)    # 손절+0.5R 가 더 높음
        r = run_kr(True)
        self.assertTrue(all(x["entry"] == 98.0 and abs(x["entry_max"] - 102.0) < 1e-9 for x in r["items"]))
        u = run_us(True)
        self.assertEqual(u["items"][0]["entry"], 98.0)
        self.assertEqual([x["s"] for x in u["items"]], ["AAA", "DDD"])   # 실행(DDD 실적 촉매) 1 + 대기 1, 순위 순서 유지

    def test_tracking_enters_on_gap_down_only_when_on(self):   # P3 효과: 갭다운 99 시가
        bars = [dict(date="2026-10-21", open=99, high=101, low=98, close=100)]
        for on, want in ((False, "expired"), (True, "open")):
            x = (run_kr(on)["items"] + run_kr(on)["candidates"])
            x = next(i for i in x if i["s"] == "000005")
            self.assertEqual(T.evaluate({"date": "2026-10-20", "original": x}, bars)["status"], want)


class Scope(unittest.TestCase):   # 적용 범위 = 운용회의 TOP3 표시·모의 추적. 포트폴리오 한도·주문 경로(pb 등)는 이 스위치·ideas_top 을 안 읽음
    def test_switch_only_in_committee_paths(self):
        allowed = {"screener/config.py", "screener/committee.py", "screener/us_committee.py", "screener/idea_tracking.py"}
        hits = {str(p.relative_to(ROOT)) for d in ("screener", "scripts") for p in (ROOT / d).rglob("*.py")
                if re.search(r"CIO_TOP3_V2|v2_on\(|pick_top3|entry_floor", p.read_text(encoding="utf-8"))}
        self.assertLessEqual(hits, allowed)
        readers = {str(p.relative_to(ROOT)) for d in ("screener", "scripts") for p in (ROOT / d).rglob("*.py")
                   if "ideas_top" in p.read_text(encoding="utf-8")}
        self.assertLessEqual(readers, allowed | {"screener/signal_tracking.py", "scripts/light_calibration.py"})


if __name__ == "__main__":
    unittest.main()
