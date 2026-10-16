"""journal_skeleton — 합성 공개 데이터로 뼈대 생성, 금액·보유 미포함, 기존 파일 보호."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import journal_skeleton as js  # noqa: E402

D = "2026-10-16"


@pytest.fixture
def rep(tmp_path):
    r = tmp_path / "reports"
    (r / "archive" / "committee").mkdir(parents=True)
    (r / "events.json").write_text(json.dumps({"events": [
        {"date": D, "time": "12:57", "market": "KOSDAQ", "type": "매수 사이드카", "title": "코스닥 급등"},
        {"date": "2026-10-15", "time": "12:49", "market": "KOSPI", "type": "서킷브레이커", "title": "전날 것"}]}), encoding="utf-8")
    (r / "decisions.json").write_text(json.dumps({"items": [
        {"id": f"{D}-entry", "date": D, "kind": "entry", "title": "진입 타점 대결",
         "picks": {"나": {"ticker": "475310", "name": "SOL 반도체후공정", "notional": 1000000.0, "entry": "close", "exit": "trail", "submitted": "11:46"},
                   "PB": {"ticker": "015760", "name": "한국전력", "notional": 1000000.0, "entry": "close", "exit": "d5_close", "at": "14:46"},
                   "규칙": {"cash": True}}},
        {"id": f"{D}-ticket-000001", "date": D, "kind": "ticket", "name": "테스트전자", "code": "000001", "verdict": "✅ 통과", "rr": 3.0,
         "horizon_days": 5, "submitted": "14:00", "entry": 10000, "stop": 9500, "target": 11500, "amount": 1500000, "picks": {}},
        {"id": "2026-10-15-x", "date": "2026-10-15", "title": "전날 대결", "picks": {"나": {"cash": True}}}]}, ensure_ascii=False), encoding="utf-8")
    (r / "archive" / "committee" / "_index.json").write_text(json.dumps({"days": [
        {"id": f"{D}_장후", "date": D, "session": "장후", "asof": f"{D} 15:50", "headline": "관망"},
        {"id": f"{D}_장전", "date": D, "session": "장전", "asof": f"{D} 09:03", "headline": "관망"}]}), encoding="utf-8")
    (r / "archive" / "committee" / f"{D}_장후.json").write_text(json.dumps({
        "verdict": "강세 44%", "bottom_line": {"label": "🟡 지켜보기", "stance": "관망",
                                            "lines": ["직전 회의(10-16 장중 13:35) 대비: 코스피 5,752→5,665 (-1.5%) · 판정 유지(관망)", "기타"]}}, ensure_ascii=False), encoding="utf-8")
    (r / "archive" / "committee" / f"{D}_장전.json").write_text(json.dumps({"verdict": "강세 47%", "bottom_line": {"label": "", "lines": []}}, ensure_ascii=False), encoding="utf-8")
    (r / "rebound.json").write_text(json.dumps({"days": [{"date": D, "time": "14:25", "last": 5700.0, "prev": 5554.0, "thr": 5581.77, "chg": 0.0263, "ok": True}]}), encoding="utf-8")
    (r / "live.json").write_text(json.dumps({"updated_at": "10-16 18:42 KST", "items": [
        {"key": "KOSPI", "last": 5668.05, "chg": 0.0205, "status": "CLOSE"}, {"key": "KOSDAQ", "last": 794.78, "chg": 0.0446, "status": "CLOSE"},
        {"key": "SPX", "last": 7744.0, "chg": 0.003}]}), encoding="utf-8")
    return r


def test_build_prefills_facts_and_leaves_feelings_blank(rep, monkeypatch):
    monkeypatch.setattr(js, "study_grade_changes", lambda root, d: ["semis_cap: 변경 1건 (A×1)"])
    md = js.build(D, rep, rep.parent)
    assert md.startswith(f"# 매매 일기 — {D}(금) · 반등일")
    assert "코스피 5,668.05 (+2.05%) · 코스닥 794.78 (+4.46%)" in md
    assert "14:25 반등일 판정: ✅" in md
    assert "12:57 매수 사이드카" in md and "전날 것" not in md
    assert "회의 장전(09:03)" in md and "회의 장후(15:50): 🟡 지켜보기 · 강세 44%" in md
    assert "Δ 직전 회의(10-16 장중 13:35) 대비" in md
    assert "나: SOL 반도체후공정 (종가 진입 → 추세 끌고가기) · 제출 11:46" in md
    assert "PB: 한국전력 (종가 진입 → 5거래일 종가)" in md and "규칙: 현금" in md and "전날 대결" not in md
    assert "주문표 테스트전자: ✅ 통과 · 손익비 1:3.0 · 보유 5일" in md
    assert "| 시각 | 마음 | 대응 | 결과 |" in md and "누나" not in md and "겸이" not in md
    assert "| 11:46 | … | … | 나 픽 제출 — SOL 반도체후공정 |" in md
    assert "- semis_cap: 변경 1건 (A×1)" in md
    assert "## 14:30 이후" in md and "- [ ] 오늘 한 줄 회고" in md
    # 금액·보유 흔적 없음 (모의 notional, 주문표 amount·가격, 종합 손익)
    for bad in ("notional", "1,000,000", "1000000", "amount", "1500000", "pnl"):
        assert bad not in md


def test_amount_guard_raises():
    with pytest.raises(SystemExit):
        js.assert_no_amounts("- 보유 평가액 1,234,567원")


def test_missing_inputs_still_build(tmp_path, monkeypatch):
    rep = tmp_path / "reports"
    rep.mkdir()
    monkeypatch.setattr(js, "study_grade_changes", lambda root, d: [])
    md = js.build("2026-10-13", rep, rep.parent)
    assert "이벤트: 없음" in md and "회의: 기록 없음" in md and "## 오늘의 대결\n- 없음" in md and "- 없음" in md


def test_out_does_not_overwrite(rep, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(js, "study_grade_changes", lambda root, d: [])
    out = tmp_path / "j" / f"{D}.md"
    assert js.main(["--date", D, "--reports", str(rep), "--out", str(out)]) == 0
    first = out.read_text(encoding="utf-8")
    assert "## 마음의 타임라인" in first
    out.write_text(first.replace("- 수급: …", "- 수급: 외국인 순매수"), encoding="utf-8")
    assert js.main(["--date", D, "--reports", str(rep), "--out", str(out)]) == 0
    assert "이미 있음 — 덮어쓰지 않음" in capsys.readouterr().out
    assert "외국인 순매수" in out.read_text(encoding="utf-8")
