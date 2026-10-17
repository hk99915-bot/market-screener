"""시도 일지 집계(scripts/trial_log.py) — m 필드 추출·주제별 N·md 동기화 (네트워크 없음)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import trial_log as tl  # noqa: E402


def test_extract_m_all_schemas():
    assert tl.extract_m({"m": 10, "alpha_bonf": 0.005}) == (10, "m")                      # derivs/gamma/fib
    assert tl.extract_m({"prereg": {"m": 7}}) == (7, "prereg.m")                            # semis_cap
    assert tl.extract_m({"params": {"m": 6}}) == (6, "params.m")                            # entry/rule_audit
    assert tl.extract_m({"params": {"m1": 15, "m3": 2, "m4": 2, "min_n": 8}}) == (19, "params.m1+m3+m4")  # exec_signal
    assert tl.extract_m({"base": {}}) == (None, "미등록")                                   # crash_rebound(서술)
    assert tl.extract_m({"m": "10"}) == (None, "미등록")                                    # 문자열은 안 받음


def test_build_counts_topics(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"asof": "2026-10-15", "m": 4, "grades": {"H1": "F", "H2": {"grade": "C"}}}), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"generated": "2026-10-16 04:00", "params": {"m": 6}}), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"base": {}}), encoding="utf-8")
    log = {"studies": {"a": {"topic": "x", "unregistered_trials": 32}, "b": {"topic": "x"}, "ghost": {"topic": "y"}},
           "trials": [{"date": "2026-10-16", "topic": "x", "hypothesis": "h", "params": "p", "result": "r", "discarded_why": "w", "study": "b"}]}
    lj = tmp_path / "trial_log.json"
    lj.write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")
    b = tl.build(tmp_path, lj)
    assert [r["study"] for r in b["rows"]] == ["a", "b", "c"]            # 일지 자신은 제외
    a = b["rows"][0]
    assert a["m"] == 4 and a["alpha_bonf"] == 0.0125 and a["unregistered"] == 32 and a["trials"] == 36
    assert a["grades"] == {"C": 1, "F": 1} and a["date"] == "2026-10-15"
    assert b["topics"]["x"]["N"] == 42 and b["topics"]["x"]["alpha_N"] == round(0.05 / 42, 5)
    assert b["topics"]["(미분류)"]["N"] == 0 and b["topics"]["(미분류)"]["alpha_N"] is None
    assert b["N_total"] == 42 and b["manual_without_file"] == ["ghost"]
    md = tl.render_md(b)
    assert "| a | 2026-10-15 | x | 4 | m | 0.0125 | 32 | C1 F1 |" in md
    assert "ghost" in md and "| 2026-10-16 | x | h | p | r | w | b |" in md


def test_repo_log_in_sync():
    b = tl.build()
    names = {r["study"] for r in b["rows"]}
    assert {"playbook_signals", "entry_signals", "exec_signal"} <= names
    crash = b["topics"]["crash_entry"]
    assert crash["N"] >= 32 + 6 + 19                                     # 급락 뒤 진입 질문의 반복 검정 (kb:quant#13)
    # md 동기화는 CLI --check 가 본다 (여러 데스크가 reports/studies 에 동시에 파일을 넣으므로 테스트에선 구조만 확인)
    md = tl.render_md(b)
    assert "## 2. 주제별 N" in md and "| crash_entry |" in md
