"""추적 parquet 전수 표(scripts/parquet_inventory.py) — 표에 없는 parquet 이 git 에 늘면 실패 (보드 data-parquet-out)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import parquet_inventory as I  # noqa: E402


def test_every_tracked_parquet_is_in_inventory():
    by, unknown = I.classify()
    assert not unknown, f"표에 없는 추적 parquet: {unknown} — INVENTORY 에 쓰기/읽기 주체를 적고, 새 큰 파일은 data_store GROUPS 로"


def test_classify_and_big_store_files_not_tracked():
    by, unknown = I.classify(["data/hist/kr_2020.parquet", "data/research.parquet", "data/zzz.parquet"])
    assert by["data/hist/kr_20[0-9][0-9].parquet"] == ["data/hist/kr_2020.parquet"] and unknown == ["data/zzz.parquet"]
    # 이미 릴리스 전용인 것(data_store GROUPS)은 추적 목록에 있으면 안 된다
    assert not [f for f in I.tracked() if f in ("data/kr_prices.parquet", "data/signals.parquet") or f.endswith("_daily.parquet")]
