"""전역 알림 무음 스위치 ALERTS_OFF (리팩토링 v1 병행 11/7~, docs/refactor_v1_inventory.md §5 '알림 이중 발송').
저장소 변수 ALERTS_OFF=1 이면 send_telegram 은 보내지 않고 로그만(예외 없음). 텔레그램 시크릿을 쓰는 워크플로는 전부 변수를 넘긴다."""
import glob
import re

import pytest
import yaml

from screener import report


class _Resp:
    status_code = 200
    text = "ok"


@pytest.fixture
def posted(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(report.CFG, "telegram_token", "123456789:" + "A" * 35)
    monkeypatch.setattr(report.CFG, "telegram_chat", "-100123")
    monkeypatch.setattr(report.requests, "post", lambda url, data, timeout: calls.append(data) or _Resp())
    return calls


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_alerts_off_blocks_send(posted, monkeypatch, val):
    monkeypatch.setenv("ALERTS_OFF", val)
    report.send_telegram("⛔ 손절선", disable_notification=False)
    assert posted == []


@pytest.mark.parametrize("val", [None, "", "0", "false", "off", "no"])
def test_alerts_on_sends(posted, monkeypatch, val):
    if val is None:
        monkeypatch.delenv("ALERTS_OFF", raising=False)
    else:
        monkeypatch.setenv("ALERTS_OFF", val)
    report.send_telegram("📐 점도표")
    assert len(posted) == 1


def test_alerts_off_does_not_need_secrets(monkeypatch):
    """옛 저장소 무음 중엔 시크릿이 비어도 실패하지 않는다(산출물 대조만 하면 됨)."""
    monkeypatch.setenv("ALERTS_OFF", "1")
    monkeypatch.setattr(report.CFG, "telegram_token", "")
    monkeypatch.setattr(report.CFG, "telegram_chat", "")
    report.send_telegram("x")   # 예외 없음


def test_single_send_point():
    """api.telegram.org 를 직접 부르는 파이썬은 report.py 하나 — 다른 곳이 생기면 무음 스위치를 우회한다."""
    hits = [p for p in glob.glob("screener/**/*.py", recursive=True) + glob.glob("scripts/**/*.py", recursive=True)
            + glob.glob("tools/**/*.py", recursive=True)
            if "api.telegram.org" in open(p, encoding="utf-8").read()]
    assert hits == ["screener/report.py"]


def _uses_telegram(text: str) -> bool:
    return bool(re.search(r"secrets\.(TELEGRAM_TOKEN|TELE)\b", text)) or "api.telegram.org" in text


def test_every_telegram_workflow_passes_alerts_off():
    wfs = sorted(glob.glob(".github/workflows/*.yml"))
    tele = [p for p in wfs if _uses_telegram(open(p, encoding="utf-8").read())]
    assert len(tele) >= 11
    missing = [p for p in tele
               if (yaml.safe_load(open(p, encoding="utf-8")).get("env") or {}).get("ALERTS_OFF") != "${{ vars.ALERTS_OFF }}"]
    assert missing == []


def test_telegram_test_curl_respects_switch():
    s = open(".github/workflows/telegram_test.yml", encoding="utf-8").read()
    assert s.index("ALERTS_OFF}") < s.index("curl ")
