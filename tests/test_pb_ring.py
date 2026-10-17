"""감사 M1 (2026-10-17 refactor_audit): PB 아침 점검의 ⛔ 줄도 결재 #9 등급표(alerts.RING_KINDS)를 거친다.
PB 회신: '손절 2일' = 보유 종목 기준가 2일 연속 종가 이탈(+코스피 5,451 선) → stop2(소리). 손실 한도 도달은 표 밖(무음).
네트워크 없음 — 가짜 detail JSON, send_telegram 은 가로챔. 금액은 테스트 전용 가상 숫자."""
import json

from screener import alerts, pb, report
from tests.test_pb_stress import _fake_reports


def _set_c1y(tmp_path, code: str, closes: list[float]) -> None:
    f = tmp_path / "detail" / "KR" / f"{code}.json"
    d = json.loads(f.read_text())
    d["c1y"] = [[f"2026-10-{13 + i:02d}", c] for i, c in enumerate(closes)]
    d["close"] = closes[-1]
    f.write_text(json.dumps(d))


def _env(monkeypatch, rules: str):
    monkeypatch.setenv("MY_HOLDINGS", "005930 10\n009150 5\n현금 500\n")
    monkeypatch.setenv("MY_RULES", rules)
    monkeypatch.setattr(pb, "semi_regime", lambda closes=None: {"regime": "하락장", "tag": "하락", "above20": 0, "n": 260, "src": "t"})


def _sent(monkeypatch):
    out: list[tuple[str, bool]] = []
    monkeypatch.setattr(report, "send_telegram", lambda text, *, disable_notification=True: out.append((text, disable_notification)))
    return out


def test_price_rule_two_day_breach_is_stop2_and_rings(tmp_path, monkeypatch):
    _fake_reports(tmp_path, monkeypatch)
    _set_c1y(tmp_path, "005930", [100.0, 95.0, 94.0])   # 기준 96 아래 2일 연속
    _env(monkeypatch, "005930 96\n")
    text, keys = pb.brief_keys()
    assert "⛔ 2일 연속 이탈 — 실행" in text and keys == ["stop2:005930"]
    assert alerts.kind("stop2:005930") == "stop2" and alerts.ring(keys)
    sent = _sent(monkeypatch)
    assert pb.send() and sent[-1][1] is False        # 호출부는 소리 요청 (send_telegram 이 전체 무음으로 덮음)


def test_one_day_breach_and_ok_are_silent(tmp_path, monkeypatch):
    _fake_reports(tmp_path, monkeypatch)
    _set_c1y(tmp_path, "005930", [100.0, 97.0, 95.0])   # 1일 이탈
    _env(monkeypatch, "005930 96\n")
    _, keys = pb.brief_keys()
    assert keys == ["stop1:005930"] and alerts.silent(keys)
    _set_c1y(tmp_path, "005930", [100.0, 99.0, 98.0])   # 이탈 없음
    _, keys = pb.brief_keys()
    assert keys == []
    sent = _sent(monkeypatch)
    assert pb.send() and sent[-1][1] is True


def test_loss_limit_hit_is_silent(tmp_path, monkeypatch):
    _fake_reports(tmp_path, monkeypatch)
    monkeypatch.setenv("MY_HOLDINGS", "005930 10 130\n현금 10\n")   # 가상: 평단 130 → 종가 100, 손실 300 / 순자산 1010
    monkeypatch.setenv("MY_RULES", "LOSS_LIMIT 0.05\n")
    monkeypatch.setattr(pb, "semi_regime", lambda closes=None: {"regime": "하락장", "tag": "하락", "above20": 0, "n": 260, "src": "t"})
    text, keys = pb.brief_keys()
    assert "⛔ 한도 도달" in text and keys == ["loss_limit"]
    assert "loss_limit" not in alerts.RING_KINDS and alerts.silent(keys)
    sent = _sent(monkeypatch)
    assert pb.send() and sent[-1][1] is True


def test_all_silent_switch_still_wins(tmp_path, monkeypatch):
    """오너 10/17 '전체 무음' — stop2 라도 실제 payload 는 무음."""
    from screener import defs
    assert defs.TELEGRAM_ALL_SILENT is True
    _fake_reports(tmp_path, monkeypatch)
    _set_c1y(tmp_path, "005930", [100.0, 95.0, 94.0])
    _env(monkeypatch, "005930 96\n")
    posted: list[dict] = []

    class _R:
        status_code, text = 200, "ok"
    monkeypatch.setattr(report.CFG, "telegram_token", "123456789:" + "A" * 35)
    monkeypatch.setattr(report.CFG, "telegram_chat", "-100123")
    monkeypatch.setattr(report.requests, "post", lambda url, data, timeout: posted.append(data) or _R())
    assert pb.send()
    assert posted and {p["disable_notification"] for p in posted} == {"true"}
