"""scripts/ui_align_check.py — 정렬·대칭 검사(UXUI 10/31) 판정 함수와 브라우저 측정."""
from __future__ import annotations

import asyncio
import glob
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ui_align_check as ua  # noqa: E402

OK = {"panels": 3, "gutterL": 16, "gutterR": 16, "gutterDiff": 0, "edgeErr": 0, "rowTopErr": 0, "rowBotErr": 0, "overflow": [], "clip": []}


def test_judge_pass_and_each_failure():
    assert ua.judge(OK) == []
    assert ua.judge({**OK, "gutterDiff": 0.9}) == []             # 1px 이내 허용
    assert "좌우 여백" in ua.judge({**OK, "gutterDiff": 2, "gutterR": 18})[0]
    assert "행 윗변" in ua.judge({**OK, "rowTopErr": 12})[0]
    assert "행 아랫변" in ua.judge({**OK, "rowBotErr": 5})[0]
    assert "공통 세로선" in ua.judge({**OK, "edgeErr": 3})[0]
    assert "넘침" in ua.judge({**OK, "overflow": ["div 0~420"]})[0]
    assert "잘림" in ua.judge({**OK, "clip": ["span.t"]})[0]
    assert ua.judge({"panels": 0})[0].startswith("패널 0개")


GOOD = """<!doctype html><meta name=viewport content="width=device-width"><style>body{margin:0}
.g{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:0 16px}.p{border:1px solid #000}</style>
<div class=g><div class=p data-panel>a<br>a<br>a</div><div class=p data-panel>b</div></div>"""
BAD = """<!doctype html><meta name=viewport content="width=device-width"><style>body{margin:0}
.g{display:flex;align-items:flex-start;gap:16px;padding:0 40px 0 16px}.p{flex:1;border:1px solid #000}
.t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;width:40px}</style>
<div class=g><div class=p data-panel>a<br>a<br>a</div><div class=p data-panel><div class=t>아주 긴 글자가 잘린다</div></div></div>"""


@pytest.mark.skipif(not glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"), reason="크로미움 없음")
def test_browser_measure_good_vs_bad(tmp_path):
    pytest.importorskip("playwright")
    g, b = tmp_path / "good.html", tmp_path / "bad.html"
    g.write_text(GOOD, encoding="utf-8"); b.write_text(BAD, encoding="utf-8")
    rg = asyncio.run(ua.measure(str(g), [(360, 600)], [""], "[data-panel]", "[data-edge]", wait_ms=50))
    rb = asyncio.run(ua.measure(str(b), [(360, 600)], [""], "[data-panel]", "[data-edge]", wait_ms=50))
    assert rg[0]["bad"] == []
    msg = " ".join(rb[0]["bad"])
    assert "좌우 여백" in msg and "행 아랫변" in msg and "잘림" in msg
