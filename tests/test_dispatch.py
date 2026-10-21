"""노트북 정시 dispatcher (tools/dispatch) — 네트워크 없음, 가짜 opener. 10/21 A1 이중화."""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from tools.dispatch import dispatch as d

KST = timezone(timedelta(hours=9))
TOK = "github_pat_SECRET-MARK-9c1e"


class FakeOpener:
    def __init__(self, runs=None, code=204):
        self.calls, self.runs, self.code = [], runs or [], code

    def __call__(self, req, timeout=0):
        self.calls.append((req.get_method(), req.full_url))
        if req.get_method() == "GET":
            body = json.dumps({"workflow_runs": self.runs}).encode()
            status = 200
        else:
            body, status = b"", self.code
        r = io.BytesIO(body)
        r.status = status
        r.__enter__ = lambda: r  # noqa
        return _Ctx(r)


class _Ctx:
    def __init__(self, r):
        self.r = r

    def __enter__(self):
        return self.r

    def __exit__(self, *a):
        return False


def test_dispatch_once_per_slot_and_no_token_in_output(tmp_path):
    lines = []
    op = FakeOpener()
    now = datetime(2026, 10, 21, 8, 52, tzinfo=KST)   # 08:50 premarket_kr 창
    st = d.run(now, token=TOK, opener=op, data=tmp_path, out=lines.append)
    posts = [u for m, u in op.calls if m == "POST"]
    assert posts == ["https://api.github.com/repos/hk99915-bot/market-screener/actions/workflows/briefing.yml/dispatches"]
    assert st["last_run"].startswith("2026-10-21T08:52") and st["last_error"] is None
    d.run(now + timedelta(minutes=2), token=TOK, opener=op, data=tmp_path, out=lines.append)
    assert len([1 for m, _ in op.calls if m == "POST"]) == 1          # 같은 슬롯 두 번 안 보냄
    blob = "\n".join(lines) + (tmp_path / "dispatcher.json").read_text()
    assert TOK not in blob


def test_skip_when_gas_already_dispatched(tmp_path):
    run = {"id": 1, "event": "workflow_dispatch", "display_title": "briefing [premarket_kr] commit=true",
           "conclusion": None, "created_at": "2026-10-20T23:51:00Z"}
    op = FakeOpener(runs=[run])
    d.run(datetime(2026, 10, 21, 8, 53, tzinfo=KST), token=TOK, opener=op, data=tmp_path, out=lambda s: None)
    assert [m for m, _ in op.calls] == ["GET"]


def test_only_dispatch_and_runs_paths():
    with pytest.raises(ValueError):
        d._req("GET", "/repos/hk99915-bot/market-screener/contents/README.md", TOK, opener=FakeOpener())
    with pytest.raises(ValueError):
        d._req("POST", "/user/repos", TOK, opener=FakeOpener())


def test_due_respects_lead_and_window():
    gas = d.g.parse_gas()
    at = lambda h, m: d.due(gas, datetime(2026, 10, 21, h, m, tzinfo=KST), set())  # noqa: E731  (수요일)
    assert at(8, 50) == [] and [s["time"] for s in at(8, 52)] == ["08:50"] and at(9, 0) == []
