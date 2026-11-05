"""parquet 전수 표(scripts/parquet_inventory.py) — git(main)에 parquet 이 하나라도 있으면 실패, 표의 모든 패턴은 릴리스 그룹에 속하고 읽는 워크플로가 받는다 (보드 data-parquet-out)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import data_store  # noqa: E402,F401
import parquet_inventory as I  # noqa: E402


def test_every_tracked_parquet_is_in_inventory():
    by, unknown = I.classify()
    assert not unknown, f"표에 없는 추적 parquet: {unknown} — INVENTORY 에 쓰기/읽기 주체를 적고, 새 큰 파일은 data_store GROUPS 로"


def test_classify_and_big_store_files_not_tracked():
    by, unknown = I.classify(["data/hist/kr_2020.parquet", "data/research.parquet", "data/zzz.parquet"])
    assert by["data/hist/kr_20[0-9][0-9].parquet"] == ["data/hist/kr_2020.parquet"] and unknown == ["data/zzz.parquet"]
    # 이미 릴리스 전용인 것(data_store GROUPS)은 추적 목록에 있으면 안 된다
    assert not [f for f in I.tracked() if f in ("data/kr_prices.parquet", "data/signals.parquet") or f.endswith("_daily.parquet")]


def test_no_parquet_tracked_in_main():
    """11/5 data-parquet-out: parquet 은 전부 릴리스 data-latest. git 추적 0개(새 parquet 은 data_store GROUPS 로)."""
    assert I.tracked() == []


def test_every_inventory_pattern_is_a_release_group():
    import data_store as ds
    for r in I.INVENTORY:
        assert r["group"] in ds.GROUPS, r
        ex = r["pattern"].replace("[0-9][0-9]", "25")
        assert ds.matches(ex, ds.GROUPS[r["group"]]), (r["pattern"], r["group"])


def test_readers_pull_their_groups():
    """parquet 을 읽는 워크플로가 받는 그룹 — 표의 hist_year 읽는 곳(fin·lab·hist)은 hist_year, 누적 small 을 쓰는 곳(fin·screener·briefing)은 push 까지."""
    wf = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    rd = lambda n: (wf / n).read_text(encoding="utf-8")  # noqa: E731
    for n in ("fin.yml", "lab.yml", "hist.yml"):
        assert "data_store.py pull --groups all,hist_year" in rd(n), n
    for n, g in (("fin.yml", "fin,small"), ("screener.yml", "prices,signals,small"), ("briefing.yml", "signals,small")):
        assert f"data_store.py push --groups {g}" in rd(n), n


def test_no_workflow_git_adds_release_parquet():
    """릴리스 전용이 된 parquet 경로를 커밋 대상(git add 목록)에 다시 넣으면 저장소가 또 분다."""
    wf = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    bad = re.compile(r"git add[^\n]*\.parquet|for p in [^;\n]*(research|dart|short_hist)[^;\n]*\.parquet")
    for f in wf.glob("*.yml"):
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.lstrip().startswith("#"):
                continue
            assert not bad.search(ln), f"{f.name}: {ln.strip()[:120]}"
