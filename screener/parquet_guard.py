"""연도별 시세 parquet(data/hist/kr_YYYY·us_YYYY) 부재 가드 — data-parquet-out(11/5) 이후 이 파일들은 git 이 아니라 릴리스 자산이다.
없으면 '빈 결과로 조용히 진행'하지 말고 받는 명령을 안내하며 멈춘다. 공통 로더 screener.prices._load_cached(hist_from) 가 호출."""
from __future__ import annotations

import glob
from pathlib import Path

GROUP = "hist_year"          # scripts/data_store.py GROUPS 키와 같아야 한다(tests/test_parquet_guard.py 가 검사)
PULL_CMD = f"python scripts/data_store.py pull --groups {GROUP}"


class HistYearMissing(FileNotFoundError):
    """연도별 hist parquet 부재."""


def hist_year_files(hist_dir: Path | str, market: str = "kr") -> list[str]:
    return sorted(glob.glob(str(Path(hist_dir) / f"{market}_[0-9][0-9][0-9][0-9].parquet")))


def require_hist_year(hist_dir: Path | str, market: str = "kr") -> list[str]:
    """연도별 파일이 하나도 없으면 HistYearMissing. 있으면 정렬된 경로 목록."""
    fs = hist_year_files(hist_dir, market)
    if not fs:
        raise HistYearMissing(
            f"{Path(hist_dir)}/{market}_YYYY.parquet 이 없습니다 — 연도별 시세는 릴리스 자산입니다. "
            f"{PULL_CMD} 를 먼저 실행하세요.")
    return fs
