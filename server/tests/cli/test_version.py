import subprocess
from pathlib import Path

from typer.testing import CliRunner

from a2a_workbench import __version__
from a2a_workbench.cli.main import app

ROOT = Path(__file__).resolve().parents[3]


def test_version_flag():
    out = CliRunner().invoke(app, ["--version"])
    assert out.exit_code == 0
    assert out.stdout.strip() == f"a2a-workbench {__version__}"


def test_version_is_1_0_0():
    assert __version__ == "1.0.0"


def test_check_version_script():
    script = str(ROOT / "scripts/check-version.sh")
    assert subprocess.run([script, f"v{__version__}"], capture_output=True).returncode == 0
    assert subprocess.run([script, "v0.0.1"], capture_output=True).returncode == 1
