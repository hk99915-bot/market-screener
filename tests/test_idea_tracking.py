import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from screener.idea_tracking import capture, evaluate, summarize

def row(status="실행 후보"):
    return {"date":"2026-10-19","original":{"status":status,"side":"롱","entry":100,"entry_max":102,"stop":90,"target":120}}
def bar(d="2026-10-20",o=100,h=110,l=95,c=105):
    return dict(date=d,open=o,high=h,low=l,close=c)
class TrackingTests(unittest.TestCase):
    def test_no_lookahead(self):
        self.assertEqual(evaluate(row(),[bar("2026-10-19")])["status"],"waiting")
    def test_waiting_never_enters(self):
        s=evaluate(row("대기 — 촉매 없음"),[bar()]); self.assertEqual(s["status"],"not_entered"); self.assertNotIn("ret",s)
    def test_gap_not_filled(self):
        self.assertEqual(evaluate(row(),[bar(o=108)])["status"],"expired")
    def test_close_stop_not_low(self):
        self.assertEqual(evaluate(row(),[bar(l=85)])["status"],"open")
        self.assertEqual(evaluate(row(),[bar(l=85,c=89)])["mark_price"],89)
    def test_ambiguous(self):
        s=evaluate(row(),[bar(h=125,l=85,c=89)]); self.assertEqual(s["status"],"ambiguous"); self.assertNotIn("ret",s)
    def test_target_and_fee(self):
        s=evaluate(row(),[bar(h=125)]); self.assertEqual(s["status"],"target"); self.assertAlmostEqual(s["ret"],.1995)
    def test_missing(self):
        self.assertEqual(evaluate(row(),[bar(h=None)])["status"],"review")
    def test_snapshot_immutable_max3(self):
        now=datetime(2026,10,19,18,tzinfo=ZoneInfo("Asia/Seoul")); book={}
        m={"date":"2026-10-19","asof":"2026-10-19 14:00","ideas_top":{"items":[{"s":str(i),"entry":100} for i in range(5)]}}
        capture(book,m,now); m["ideas_top"]["items"][0]["entry"]=999; capture(book,m,now)
        self.assertEqual(len(book["rows"]),3); self.assertEqual(book["rows"][0]["original"]["entry"],100)
    def test_metrics_exclude_open_and_ambiguous(self):
        s=summarize([{"state":{"status":"open","ret":1,"entry_date":"d"}},{"state":{"status":"ambiguous","entry_date":"d"}},{"state":{"status":"not_entered"}},{"state":{"status":"target","entry_date":"d","ret":.1}}])
        self.assertEqual(s["closed"],1); self.assertEqual(s["hit_rate"],1); self.assertEqual(s["no_entry_rate"],.25)

    def test_timeout_twenty_sessions(self):
        from datetime import date, timedelta
        days=[]; d=date(2026,10,20)
        while len(days)<20:
            if d.weekday()<5: days.append(bar(str(d),h=105,c=101))
            d+=timedelta(days=1)
        self.assertEqual(evaluate(row(),days)["status"],"timeout")
    def test_history_not_invented(self):
        r=row(); del r["original"]["status"]
        self.assertEqual(evaluate(r,[bar()])["status"],"review")


    def test_run_persists_day_history_and_filters_future_bars(self):
        import tempfile, types, sys
        from pathlib import Path
        from unittest.mock import patch
        from screener import idea_tracking as tracking
        class Frame:
            def iter_rows(self, named=True):
                return iter([dict(yf="000001.KS",date="2026-10-20",open=100,high=121,low=99,close=119)])
        meeting={"date":"2026-10-19","asof":"2026-10-19 14:00","ideas_top":{"items":[dict(s="000001",n="fixture",side="롱",status="실행 후보",entry=100,entry_max=102,stop=90,target=120)]}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(tracking,"REPORT_DIR",Path(tmp)), patch.dict(sys.modules,{"screener.prices":types.SimpleNamespace(load_kr=lambda **kw:Frame())}):
                first=tracking.run(meeting,datetime(2026,10,19,18,tzinfo=ZoneInfo("Asia/Seoul")))
                self.assertEqual(first["rows"][0]["state"]["status"],"waiting")
                second=tracking.run({},datetime(2026,10,20,16,tzinfo=ZoneInfo("Asia/Seoul")))
                self.assertEqual(second["rows"][0]["state"]["status"],"target")
                self.assertEqual(second["summary"]["closed"],1)
                self.assertTrue((Path(tmp)/"idea_tracking/2026-10-19.json").exists())
                self.assertTrue((Path(tmp)/"idea_tracking/2026-10-20.json").exists())

if __name__=="__main__": unittest.main()
