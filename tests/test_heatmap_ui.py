import shutil
import subprocess
from pathlib import Path
import pytest

@pytest.mark.skipif(not shutil.which("node"), reason="node unavailable")
def test_heatmap_live_overlay():
    r=subprocess.run(["node",str(Path(__file__).with_suffix(".cjs"))],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
