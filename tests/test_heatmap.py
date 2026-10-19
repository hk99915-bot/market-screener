from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from screener.heatmap import session_plan, quote_rows

def test_calendar_dst_winter_holiday_and_early_close():
    et=ZoneInfo("America/New_York")
    assert session_plan(datetime(2026,10,20,10,0,tzinfo=et)) == ("2026-10-20","LIVE")
    assert session_plan(datetime(2026,12,1,10,0,tzinfo=et)) == ("2026-12-01","LIVE")
    assert session_plan(datetime(2026,11,26,10,0,tzinfo=et)) is None
    assert session_plan(datetime(2026,11,27,13,12,tzinfo=et)) == ("2026-11-27","CLOSE")
    assert session_plan(datetime(2026,11,27,14,0,tzinfo=et)) is None
    assert session_plan(datetime(2026,10,20,8,0,tzinfo=et),True) == ("2026-10-19","CLOSE")

def test_missing_and_stale_rows_are_not_mixed_with_current():
    def frame(dates,prices):
        return pd.DataFrame({"Close":prices},index=pd.to_datetime(dates))
    frames={"A":frame(["2026-10-16","2026-10-19"],[100,110]),"B":frame(["2026-10-15","2026-10-16"],[90,100])}
    out=quote_rows([{"s":"A"},{"s":"B"},{"s":"C"}],frames,"2026-10-19")
    assert len(out)==1 and out[0]["s"]=="A"
    assert abs(out[0]["r1"]-.1)<1e-9
