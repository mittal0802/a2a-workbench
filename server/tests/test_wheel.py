import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (ROOT / "a2a_workbench/static/index.html").exists(), reason="SPA not built")
def test_wheel_contents(tmp_path):
    subprocess.run(
        ["uv", "build", "--wheel", "-o", str(tmp_path)], cwd=ROOT, check=True, capture_output=True
    )
    (wheel,) = tmp_path.glob("a2a_workbench-*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    assert "a2a_workbench/static/index.html" in names
    assert "a2a_workbench/core/store/migrations/env.py" in names
    assert "a2a_workbench/core/store/migrations/script.py.mako" in names
    assert any(n.startswith("a2a_workbench/core/store/migrations/versions/0001") for n in names)
