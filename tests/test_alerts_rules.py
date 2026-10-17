"""규정 알림 순수 로직 — 손절선 2일 연속 이탈 판정 · 기한 D-n · ISA 북 파서 (네트워크·보유 데이터 없음)."""
from datetime import date

from screener import alerts, pb


def test_stop_streak_two_days():
    assert alerts.stop_streak([5600, 5440, 5430], 5451) == 2
    assert alerts.stop_streak([5600, 5500, 5430], 5451) == 1
    assert alerts.stop_streak([5600, 5500, 5460], 5451) == 0
    assert alerts.stop_streak([5400, 5500, 5430], 5451) == 1   # 중간에 회복하면 연속 끊김
    assert alerts.stop_streak([], 5451) == 0


def test_stop_line_keys():
    k, line = alerts.stop_line([5440, 5430], 5451)
    assert k == "stop2" and "2일 연속" in line and "즉시 집행" in line
    k, line = alerts.stop_line([5500, 5430], 5451)
    assert k == "stop1" and "1일 이탈" in line and "내일 종가" in line
    k, _ = alerts.stop_line([5500, 5460], 5451)
    assert k is None


def test_deadline_line():
    assert alerts.deadline_line(date(2026, 10, 20), "2026-10-22")[0] == "dl2"
    assert alerts.deadline_line(date(2026, 10, 21), "2026-10-22")[0] == "dl1"
    assert alerts.deadline_line(date(2026, 10, 22), "2026-10-22")[0] == "dl0"
    assert alerts.deadline_line(date(2026, 10, 19), "2026-10-22")[0] is None
    assert alerts.deadline_line(date(2026, 10, 23), "2026-10-22")[0] is None


def test_stop_level_from_lows(monkeypatch):
    monkeypatch.delenv("RULE_STOP_LEVEL", raising=False)
    rows = [[f"2026-09-{i:02d}", 100, 110, 90 + i, 100, 1] for i in range(1, 26)]
    monkeypatch.setenv("RULE_DEADLINE", "2026-10-22")   # 특칙 기간 안 → 규정 [12] 고정선
    assert alerts.stop_level(rows) == (5451.0, "규정 [12] 고정선") or alerts.stop_level(rows)[1] == "20일 저점"
    monkeypatch.setenv("RULE_DEADLINE", "2000-01-01")   # 기한 지남 → 롤링 20일 저점
    level, src = alerts.stop_level(rows)
    assert src == "20일 저점" and level == min(90 + i for i in range(5, 25))   # 오늘(마지막 봉) 제외 20일
    monkeypatch.setenv("RULE_STOP_LEVEL", "5,451")
    assert alerts.stop_level(rows) == (5451.0, "설정")


def test_parse_books_isa():
    txt = "005930 10 70000\nTIGER 200 IT 5 30000\n현금 100\nUSD 2\n## ISA\n360750 3 100\n# 주석\n069500 1\n현금 50\n"
    b = pb.parse_books(txt)
    sat, isa = b["sat"], b["isa"]
    assert [h["key"] for h in sat[0]] == ["005930", "TIGER 200 IT"] and sat[1] == 100 and sat[2] == 2
    assert [h["key"] for h in isa[0]] == ["360750", "069500"] and isa[1] == 50 and isa[0][1]["avg"] is None
    assert pb.parse(txt) == sat          # 하위 호환: parse 는 위성 북만
    assert pb.parse_books("005930 1")["isa"] == ([], 0.0, 0.0)


def test_isa_bucket_and_semi_class():
    assert pb.isa_bucket("360750", "TIGER 미국S&P500") == "S&P500"
    assert pb.isa_bucket("133690", "TIGER 미국나스닥100") == "NDX"
    assert pb.isa_bucket("069500", "KODEX 200") == "K200"
    assert pb.isa_bucket("139260", "TIGER 200 IT") is None
    assert pb.isa_bucket("148070", "KIWOOM 국고채10년") == "KTB"
    assert pb.isa_bucket("132030", "KODEX 골드선물(H)") == "Gold"
    # 지수 ETF: 한도 제외, 룩스루는 참고치
    assert pb.semi_class("KR", "069500", "KODEX 200", "ETF", True, {"메모리 반도체": 0.6, "금융": 0.1}) == (None, 0.6)
    assert pb.semi_class("KR", "139260", "TIGER 200 IT", "ETF", True, {"메모리 반도체": 0.56}) == ("semi", 0.0)
    assert pb.semi_class("US", "SOXX", "iShares Semiconductor", "ETF", True, {}) == ("semi", 0.0)
    assert pb.semi_class("KR", "009150", "삼성전기", "IT 하드웨어 — 전자부품(MLCC·기판)", False, {}) == ("elec", 0.0)
    assert pb.semi_class("KR", "005930", "삼성전자", "메모리 반도체", False, {}) == ("semi", 0.0)
    assert pb.semi_class("US", "MU", "Micron", "미국 주식", False, {}) == ("semi", 0.0)


def test_rules_defaults():
    r = pb.rules("SEMI_CAP 0.40\n005930 60000\n")
    assert r["semi_cap"] == 0.40 and r["semi_band"] == 0.45 and r["loss_limit"] == 0.12 and r["price"] == {"005930": 60000.0}


def test_touch_rule_parses_and_fires(monkeypatch):
    r = pb.rules("000660 1170000 touch\n005930 80000\nSEMI_CAP 0.40")
    assert r["touch"] == {"000660": 1170000.0} and r["price"] == {"005930": 80000.0}
    monkeypatch.setenv("MY_RULES", "000660 1170000 touch")
    fake = {"000660": {"last": 1200000.0, "low": 1169000.0, "name": "SK하이닉스"}}
    out = alerts.touch_lines(fetch=lambda c: fake.get(c))
    assert len(out) == 1 and out[0][0] == "touch:000660" and "예외 조건 충족" in out[0][1] and "장중 저가" in out[0][1]
    fake["000660"]["low"] = 1171000.0            # 저가가 선 위 → 조용
    assert alerts.touch_lines(fetch=lambda c: fake.get(c)) == []
    fake["000660"] = {"last": 1160000.0, "low": None, "name": "SK하이닉스"}   # 저가 키 없으면 현재가로
    assert "현재가" in alerts.touch_lines(fetch=lambda c: fake.get(c))[0][1]
