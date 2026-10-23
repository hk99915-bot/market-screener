"""데이터 — scripts/retention.py 보존 규칙(드라이런 기본·추적 파일만·이름 날짜 기준) + 반등일 전일 종가 복원."""
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import retention  # noqa: E402

T = date(2026, 12, 31)


def test_plan_rules_by_name_date():
    files = ["reports/archive/committee/2026-10-01_장후.json",   # 91일 → 후보
             "reports/archive/committee/2026-10-02_장후.json",   # 90일 → 보존
             "reports/signals/2026-12-20_KR.csv",                # 11일 → 후보
             "reports/signals/2026-12-21_KR.csv",                # 10일 → 보존
             "reports/anomalies/2026-12-01_US.csv",
             "reports/daily/2026-12-01_KR.md",
             "reports/archive/README.md",                        # 날짜 없음 → 건너뜀
             "reports/committee.json"]                           # 규칙 밖
    r = retention.plan(files, T)
    got = [c["path"] for c in r["candidates"]]
    assert got == ["reports/anomalies/2026-12-01_US.csv", "reports/archive/committee/2026-10-01_장후.json",
                   "reports/daily/2026-12-01_KR.md", "reports/signals/2026-12-20_KR.csv"]
    assert [s["path"] for s in r["skipped"]] == ["reports/archive/README.md"]


def _repo(tmp_path):
    g = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    g("init", "-q")
    for f in ("reports/signals/2026-01-01_KR.csv", "reports/signals/2026-12-30_KR.csv"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x")
    g("add", "reports")
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    (tmp_path / "reports/signals/2026-01-02_KR.csv").write_text("미추적")   # 미추적 — 손대면 안 됨
    return tmp_path


def test_dry_run_deletes_nothing_and_ignores_untracked(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(retention, "ROOT", root)
    r = retention.plan(retention.tracked(root), T)
    assert [c["path"] for c in r["candidates"]] == ["reports/signals/2026-01-01_KR.csv"]   # 미추적 01-02 없음
    retention.main(["--today", "2026-12-31"])                                              # 기본 = 드라이런
    assert (root / "reports/signals/2026-01-01_KR.csv").exists()
    assert (root / "reports/logs/retention_2026-12-31.json").exists()


def test_apply_removes_only_candidates(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(retention, "ROOT", root)
    retention.main(["--today", "2026-12-31", "--apply", "--no-log"])
    assert not (root / "reports/signals/2026-01-01_KR.csv").exists()
    assert (root / "reports/signals/2026-12-30_KR.csv").exists()
    assert (root / "reports/signals/2026-01-02_KR.csv").exists()   # 미추적 보존


def test_rebound_uses_exact_prev_when_given():
    from screener import rebound
    j = rebound.judge({"last": 5561.44, "chg": 0.005, "prev": 5533.77, "src": "naver"})
    assert j["prev"] == 5533.77 and j["prev_src"] == "diff"
    assert abs(j["chg"] - (5561.44 / 5533.77 - 1)) < 1e-4
    j2 = rebound.judge({"last": 5561.44, "chg": 0.005, "src": "naver"})
    assert j2["prev_src"] == "ratio" and abs(j2["prev"] - 5561.44 / 1.005) < 0.01
