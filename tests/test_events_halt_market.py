from screener.events import halt_hits, format_msg


def test_kosdaq_sidecar_not_kospi():
    # 11/11 실제 오탐 제목
    assert halt_hits("[속보]코스피, 1%대 강세…코스닥은 매수 사이드카 발동하며 4%대 급등") == [("KOSDAQ", "매수 사이드카")]


def test_plain_cases():
    assert halt_hits("[속보] 4%대 급등 코스닥, 매수 사이드카 발동") == [("KOSDAQ", "매수 사이드카")]
    assert halt_hits("코스피 매도 사이드카 발동") == [("KOSPI", "매도 사이드카")]
    assert halt_hits("유가증권시장 서킷브레이커 1단계 발동") == [("KOSPI", "서킷브레이커")]
    assert halt_hits("매도 사이드카 발동…코스피 5% 급락") == [("KOSPI", "매도 사이드카")]


def test_both_markets():
    assert sorted(halt_hits("코스피 매도 사이드카 이어 코스닥도 매도 사이드카 발동")) == [("KOSDAQ", "매도 사이드카"), ("KOSPI", "매도 사이드카")]


def test_no_market_word_skipped():
    assert halt_hits("매수 사이드카 발동") == []


def test_format_msg():
    new = [{"time": "11:32", "market": "KOSDAQ", "type": "매수 사이드카", "title": "t"},
           {"time": "11:38", "market": "KOSDAQ", "type": "경보:급등 +5% (매수 사이드카 근처)", "title": "KOSDAQ +5.08%"}]
    m = format_msg(new)
    assert "코스닥 매수 사이드카 발동" in m and "근접 경보" in m and "발동 아님" in m and "다음 날 통계" in m
    assert "다음 날 통계" not in format_msg([new[1]])
