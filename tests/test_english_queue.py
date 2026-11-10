"""영어 사전 생성 큐 — 게시(screener/english_queue.py)·검사(scripts/english_queue_check.py)·인적성 생성기(scripts/apt_gen.py)."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import apt_daily_check as apt  # noqa: E402
import apt_gen  # noqa: E402
import english_queue_check as chk  # noqa: E402
from screener import english_queue as eq  # noqa: E402

DOC = {"level": "L", "title": "T", "body": "b", "ko": "k", "vocab": [1], "grammar": [1], "tense": [1], "review": [1], "quiz": [1],
       "talk": [1], "opic": {"combo": [1]}, "aptitude": [1]}


def _root(tmp_path, queued, published=("2026-11-10",)):
    (tmp_path / "content" / "english_queue").mkdir(parents=True)
    eng = tmp_path / "reports" / "english"
    eng.mkdir(parents=True)
    for d in queued:
        (tmp_path / "content" / "english_queue" / f"{d}.json").write_text(json.dumps({**DOC, "date": d}), encoding="utf-8")
    for d in published:
        (eng / f"{d}.json").write_text(json.dumps({**DOC, "date": d, "title": "old"}), encoding="utf-8")
        (eng / "latest.json").write_text(json.dumps({**DOC, "date": d, "title": "old"}), encoding="utf-8")
    (eng / "index.json").write_text(json.dumps({"dates": list(published)}), encoding="utf-8")
    return tmp_path


def test_publish_writes_dated_latest_index(tmp_path):
    r = _root(tmp_path, ["2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17"])
    o = eq.run(date(2026, 11, 11), send=False, root=r)
    assert o["status"] == "published" and o["left"] == 4 and o["warn"] is None
    eng = r / "reports" / "english"
    assert json.loads((eng / "latest.json").read_text())["date"] == "2026-11-11"
    assert (eng / "2026-11-11.json").read_text() == (eng / "latest.json").read_text()
    assert json.loads((eng / "index.json").read_text())["dates"] == ["2026-11-11", "2026-11-10"]


def test_publish_never_overwrites_existing_day(tmp_path):
    r = _root(tmp_path, ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16"])
    o = eq.run(date(2026, 11, 10), send=False, root=r)
    assert o["status"] == "already"
    assert json.loads((r / "reports" / "english" / "2026-11-10.json").read_text())["title"] == "old"


def test_low_queue_warns_with_last_date(tmp_path, capsys):
    r = _root(tmp_path, ["2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16"])
    o = eq.run(date(2026, 11, 11), send=False, root=r)
    assert o["status"] == "published" and o["left"] == 3
    assert "잔량 3일" in o["warn"] and "2026-11-16" in o["warn"]
    assert "::warning::" in capsys.readouterr().out
    o = eq.run(date(2026, 11, 16), send=False, root=r)
    assert o["left"] == 0 and "오늘이 마지막" in o["warn"]


def test_missing_day_is_loud_and_keeps_latest(tmp_path):
    r = _root(tmp_path, ["2026-11-11"])
    o = eq.run(date(2026, 11, 12), send=False, root=r)
    assert o["status"] == "missing" and "게시 못 함" in o["warn"]
    assert json.loads((r / "reports" / "english" / "latest.json").read_text())["date"] == "2026-11-10"
    assert not (r / "reports" / "english" / "2026-11-12.json").exists()


def test_invalid_queue_file_not_published(tmp_path):
    r = _root(tmp_path, ["2026-11-11"])
    p = r / "content" / "english_queue" / "2026-11-11.json"
    p.write_text(json.dumps({**DOC, "date": "2026-11-12"}), encoding="utf-8")
    o = eq.run(date(2026, 11, 11), send=False, root=r)
    assert o["status"] == "invalid" and not (r / "reports" / "english" / "2026-11-11.json").exists()


def test_warning_goes_to_telegram(tmp_path, monkeypatch):
    sent = []
    import screener.report as rep
    monkeypatch.setattr(rep, "send_telegram", lambda t, **k: sent.append(t))
    r = _root(tmp_path, ["2026-11-11", "2026-11-12"])
    eq.run(date(2026, 11, 11), send=True, root=r)
    assert len(sent) == 1 and "잔량 1일" in sent[0]


def test_real_queue_passes_check():
    errs, _ = chk.check_all()
    assert errs == [], errs[:10]


def test_no_sample_or_personal_markers_in_queue():
    for p in chk.QUEUE.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        assert not d["title"].startswith("SAMPLE") and d["date"] == p.stem


def test_workflow_publishes_before_study_daily_and_commits_english():
    y = (ROOT / ".github" / "workflows" / "study_daily.yml").read_text(encoding="utf-8")
    assert y.index("python -m screener.english_queue") < y.index("python -m screener.study_daily")
    assert "git add reports/english" in y and "scripts/english_queue_check.py" in y


@pytest.mark.parametrize("pos", range(5))
def test_apt_gen_items_follow_rule_v1(pos):
    cases = [("inv", dict(subj="가상 지수 K가", unit="", now=2541.3, r=3.2, dec=1)),
             ("base", dict(q="q", a=460, b=368)),
             ("share", dict(q="q", parts={"가": 320, "나": 180, "다": 240}, target="가", den=["가", "나"])),
             ("recover", dict(x=25)), ("compound", dict(q="q", a=20, b=-15)), ("pp", dict(q="q", a=12.5, b=15))]
    for kind, kw in cases:
        it = apt_gen.make(kind, pos, f"s{pos}", **kw)
        assert apt.check_item(it, kind, pos) == [] and it["exp_ko"] and it["traps"]


def test_apt_gen_answers_are_computed():
    it = apt_gen.make("recover", 3, "s", x=-20)
    assert it["choices"][3] == "25.0%" and {"name", "value"} <= set(it["traps"][0])
    it = apt_gen.make("inv", 2, "s", subj="값이", unit="원", now=18400, r=-8, dec=0)
    assert it["choices"][2] == "20,000원"
    with pytest.raises(ValueError):
        apt_gen.make("recover", 0, "s", x=-20)   # 정답보다 큰 함정이 없는 조합은 조용히 만들지 않는다
