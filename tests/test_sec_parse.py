"""screener.sec.parse — companyfacts 기간 값을 분기 값으로 바꾸는 규칙 (네트워크 없음, 합성 facts).

회계연도가 12월이 아닌 회사(MU: 8월 말 시작)에서도 6·9개월·연간 누적치가 분기 값으로 새지 않고,
같은 시작일 사슬의 차분으로만 분기가 만들어지는지 검사한다.
"""
import pytest

from screener import sec


def _r(start, end, val, fy, fp, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "fy": fy, "fp": fp, "form": form, "filed": filed}


def _facts(**tags):
    return {"facts": {"us-gaap": {t: {"units": {"USD": recs}} for t, recs in tags.items()}}}


def _by(rows, item):
    return {r["end"]: r for r in rows if r["item"] == item}


# MU 형 FY26: 시작 2025-08-29, Q1 말 11-27(90일), 6M 02-26(181일), 9M 05-28(272일), FY 09-03(370일, 53주)
MU_NI = [
    _r("2025-08-29", "2025-11-27", 5.24, 2026, "Q1", "2025-12-18"),
    _r("2025-08-29", "2026-02-26", 13.785, 2026, "Q2", "2026-03-20"),     # 6M 누적
    _r("2025-11-28", "2026-02-26", 8.545, 2026, "Q2", "2026-03-20"),      # Q2 3M (SEC 가 보통 같이 준다)
    _r("2025-08-29", "2026-05-28", 28.243, 2026, "Q3", "2026-06-26"),     # 9M 누적
    _r("2026-02-27", "2026-05-28", 14.458, 2026, "Q3", "2026-06-26"),     # Q3 3M
    _r("2025-08-29", "2026-09-03", 37.701, 2026, "FY", "2026-10-10", "10-K"),   # 연간
]


def test_mu_like_fiscal_year_q4_is_fy_minus_9m():
    ni = _by(sec.parse(_facts(NetIncomeLoss=MU_NI)), "ni")
    assert ni["2025-11-27"]["value"] == 5.24 and ni["2025-11-27"]["derived"] is False
    assert ni["2026-02-26"]["value"] == 8.545 and ni["2026-02-26"]["derived"] is False     # 3M 기록 우선
    assert ni["2026-05-28"]["value"] == 14.458 and ni["2026-05-28"]["derived"] is False
    assert ni["2026-09-03"]["value"] == pytest.approx(37.701 - 28.243) and ni["2026-09-03"]["derived"] is True
    # 누적치(13.785·28.243·37.701)가 분기 값으로 새지 않는다
    assert not {13.785, 28.243, 37.701} & {round(r["value"], 3) for r in ni.values()}
    assert sum(r["value"] for r in ni.values()) == pytest.approx(37.701)


def test_mu_like_ytd_only_item_is_differenced_each_quarter():
    """현금흐름표처럼 누적만 있는 항목: Q2 = 6M − Q1, Q3 = 9M − 6M, Q4 = FY − 9M (예전엔 Q2 가 비었다)."""
    ytd = [r for r in MU_NI if r["start"] == "2025-08-29"]
    cfo = _by(sec.parse(_facts(NetCashProvidedByUsedInOperatingActivities=ytd)), "cfo")
    assert [round(cfo[e]["value"], 3) for e in sorted(cfo)] == [5.24, 8.545, 14.458, 9.458]
    assert [cfo[e]["derived"] for e in sorted(cfo)] == [False, True, True, True]


def test_calendar_year_filer():
    recs = [
        _r("2025-01-01", "2025-03-31", 10, 2025, "Q1", "2025-04-30"),
        _r("2025-01-01", "2025-06-30", 25, 2025, "Q2", "2025-07-30"),
        _r("2025-04-01", "2025-06-30", 15, 2025, "Q2", "2025-07-30"),
        _r("2025-01-01", "2025-09-30", 45, 2025, "Q3", "2025-10-30"),
        _r("2025-07-01", "2025-09-30", 20, 2025, "Q3", "2025-10-30"),
        _r("2025-01-01", "2025-12-31", 70, 2025, "FY", "2026-02-20", "10-K"),
        # 10-K 의 전년 비교치(fy=2025 로 붙어 온다) — 시작일이 달라 2025 사슬에 섞이지 않아야 한다
        _r("2024-01-01", "2024-12-31", 50, 2025, "FY", "2026-02-20", "10-K"),
        _r("2024-01-01", "2024-09-30", 38, 2024, "Q3", "2024-10-30"),
    ]
    rev = _by(sec.parse(_facts(Revenues=recs)), "revenue")
    assert {e: r["value"] for e, r in rev.items()} == {"2025-03-31": 10, "2025-06-30": 15, "2025-09-30": 20, "2025-12-31": 25, "2024-12-31": 12}
    assert rev["2025-12-31"]["derived"] and not rev["2025-06-30"]["derived"]


def test_missing_6m_fact_skips_q2_without_fabricating():
    recs = [r for r in MU_NI if not (r["end"] == "2026-02-26")]   # Q2 3M·6M 둘 다 없음
    ni = _by(sec.parse(_facts(NetIncomeLoss=recs)), "ni")
    assert "2026-02-26" not in ni
    assert ni["2026-05-28"]["value"] == 14.458                       # Q3 3M 기록은 그대로
    assert ni["2026-09-03"]["value"] == pytest.approx(37.701 - 28.243)
    # 9M 만 있고 6M·3M 이 없으면 9M − Q1 (181일 간격) 은 분기가 아니므로 만들지 않는다
    only = [MU_NI[0], MU_NI[3], MU_NI[5]]
    ni2 = _by(sec.parse(_facts(NetIncomeLoss=only)), "ni")
    assert set(ni2) == {"2025-11-27", "2026-09-03"} and ni2["2026-09-03"]["derived"]


def test_never_emits_long_duration_raw():
    """100일 넘는 기록만 있으면(앞 기록 없음) 아무것도 내지 않는다."""
    recs = [_r("2025-08-29", "2026-02-26", 13.785, 2026, "Q2", "2026-03-20"), _r("2025-08-29", "2026-09-03", 37.7, 2026, "FY", "2026-10-10", "10-K")]
    assert _by(sec.parse(_facts(NetIncomeLoss=recs)), "ni") == {}


def test_latest_filing_wins_and_fy_report_preferred():
    recs = [
        _r("2025-01-01", "2025-03-31", 10, 2025, "Q1", "2025-04-30"),
        _r("2025-01-01", "2025-03-31", 11, 2025, "Q1", "2025-07-30"),   # 재작성(최신 제출)
    ]
    assert _by(sec.parse(_facts(NetIncomeLoss=recs)), "ni")["2025-03-31"]["value"] == 11


def test_revenue_tag_switch_merges_old_and_new_tags():
    """태그 전환 회사(MU 형): 옛 태그(SalesRevenueNet)는 2018 이전 분기만, 새 태그는 2025~ 분기만 갖는다.
    예전엔 첫 태그에서 break → 옛 분기만 나오고 update() 의 2019 필터가 전부 버려 '매출 0행'이 됐다."""
    old = [_r("2017-09-01", "2017-11-30", 6.8, 2018, "Q1", "2017-12-20")]
    new = [
        _r("2025-08-29", "2025-11-27", 13.64, 2026, "Q1", "2025-12-18"),
        _r("2025-08-29", "2026-09-03", 150.0, 2026, "FY", "2026-10-10", "10-K"),
        _r("2025-08-29", "2026-05-28", 95.77, 2026, "Q3", "2026-06-26"),
    ]
    rev = _by(sec.parse(_facts(SalesRevenueNet=old, RevenueFromContractWithCustomerExcludingAssessedTax=new)), "revenue")
    assert set(rev) == {"2017-11-30", "2025-11-27", "2026-09-03"}
    assert rev["2026-09-03"]["value"] == pytest.approx(150.0 - 95.77) and rev["2026-09-03"]["derived"] is True
    assert [r for r in rev.values() if r["end"] >= "2019-01-01"]   # update() 필터 뒤에도 살아남는다


def test_revenue_same_quarter_end_earlier_tag_wins():
    """두 태그가 같은 분기말을 가지면 FLOW 순서상 앞선 태그 값 하나만 (중복 행 없음)."""
    a = [_r("2025-01-01", "2025-03-31", 10, 2025, "Q1", "2025-04-30")]
    b = [_r("2025-01-01", "2025-03-31", 99, 2025, "Q1", "2025-04-30"), _r("2025-04-01", "2025-06-30", 12, 2025, "Q2", "2025-07-30")]
    rows = [r for r in sec.parse(_facts(Revenues=a, RevenueFromContractWithCustomerExcludingAssessedTax=b)) if r["item"] == "revenue"]
    assert len(rows) == 2
    assert _by(rows, "revenue")["2025-03-31"]["value"] == 10 and _by(rows, "revenue")["2025-06-30"]["value"] == 12
