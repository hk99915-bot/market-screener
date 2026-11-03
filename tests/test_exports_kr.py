import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import exports_kr as ek  # noqa: E402

F = Path(__file__).parent / "fixtures"


def _t(n):
    return (F / n).read_text(encoding="utf-8")


def test_customs_monthly_and_series():
    t = _t("exports_customs.txt")
    s = ek.parse_customs_summary(t)
    assert s["export_100m_usd"] == 1153 and s["export_yoy_pct"] == 93.7 and s["import_yoy_pct"] == 36.0
    ser = ek.parse_monthly_series(t)
    assert ser["export"]["2026"][9] == 115276 and ser["export"]["2025"][0] == 49177


def test_tenday_and_motie():
    s = ek.parse_customs_summary(_t("exports_tenday.txt"))
    assert s["export_100m_usd"] == 261 and s["export_yoy_pct"] == 102.0 and s["semiconductor_100m_usd"] == 122
    it = ek.parse_motie_items(_t("exports_motie.txt"))
    assert it["반도체"] == {"usd_100m": 564.4, "yoy_pct": 259.4} and it["선박"]["yoy_pct"] < 0


def test_list_titles():
    html = '<a href="/briefing/pressReleaseView.do?newsId=1&amp;x=1">2026년 10월 1일 ~ 10월 10일 수출입 현황 [잠정치] 요약</a>'
    r = ek.parse_list(html)
    assert r[0]["kind"] == "customs_period" and r[0]["groups"] == [2026, 10, 1, 10, 10]
