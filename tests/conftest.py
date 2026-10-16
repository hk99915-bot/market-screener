"""pytest 공통 설정 — 저장소 루트를 import 경로에 올려 `screener` 패키지를 바로 쓴다 (네트워크 없이 도는 순수 로직만 검사)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
