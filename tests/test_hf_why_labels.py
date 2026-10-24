"""운용회의 HF 카드 진입 근거 이름표(UXUI 10/24 req-uxui-ce6484a5): entry_why.build().long 줄 형식이
apps-script/tab_committee.html cmtHFWhyParse 의 정규식과 맞는지 고정 — 형식이 바뀌면 화면 이름표가 '·'로 떨어진다."""
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATS = [(r"^근거 기술 — ", "왜"), (r"^근거 기대값·리스크 — ", "값"),
        (r"^근거 (펀더|내러|센티) (\+|−|-|중립|미확인)(?:\s+.*)?$", "축"), (r"^근거 약함 — ", "약함")]


def _label(x: str) -> str | None:
    for p, k in PATS:
        if re.search(p, x, re.S):
            return k
    return None


def test_ui_regex_present_in_tab():
    src = (ROOT / "apps-script" / "tab_committee.html").read_text(encoding="utf-8")
    for frag in ("^근거 기술 — ", "^근거 기대값·리스크 — ", "^근거 (펀더|내러|센티) ", "^근거 약함 — ", "HF_VB"):
        assert frag in src


def test_entry_why_long_lines_all_labelled(tmp_path):
    from screener import entry_why as EW
    from tests.test_alphabook import _ew_order, _ew_root
    det = {"close": 100.0, "theme": "AI·소프트웨어", "valuation": {"group_upside": {"current": -0.25}},
           "financials": {"quarters": [{"year": 2025, "q": 2, "op": 100.0, "period": "2025Q2"}, {"year": 2026, "q": 2, "op": 70.0, "period": "2026Q2"}]},
           "flows": [{"외국인": -1.0, "기관": -2.0} for _ in range(5)]}
    for root in (_ew_root(tmp_path / "a"), _ew_root(tmp_path / "b", det=det, accum={"status": "ok", "top": {"accum": []}})):
        w = EW.build(_ew_order(), "KR", grade="B", today=date(2026, 10, 24), root=root)
        labs = [_label(x) for x in w["long"]]
        assert None not in labs, w["long"]
        assert labs[:2] == ["왜", "값"] and labs.count("축") == 3
