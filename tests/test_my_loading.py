"""Exercise asynchronous MY loading without a browser or private holdings."""
import shutil
import subprocess
from pathlib import Path
import pytest

@pytest.mark.skipif(not shutil.which("node"), reason="node unavailable")
def test_my_loading_failures_and_retries():
    p = Path(__file__).with_suffix(".cjs")
    r = subprocess.run(["node", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
