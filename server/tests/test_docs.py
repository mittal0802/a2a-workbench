import subprocess
import sys
from pathlib import Path

from a2a_workbench.core.health.registry import builtin_checks

ROOT = Path(__file__).resolve().parents[2]


def _gen(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/gen_docs.py"), *args], capture_output=True, text=True
    )


def test_generated_reference_is_up_to_date():
    out = _gen("--check")
    assert out.returncode == 0, out.stdout + out.stderr


def test_every_check_is_documented():
    text = (ROOT / "docs/reference/checks.md").read_text()
    missing = [c.id for c in builtin_checks() if f"`{c.id}`" not in text]
    assert missing == []


def test_every_cli_command_is_documented():
    text = (ROOT / "docs/reference/cli.md").read_text()
    for command in ("check", "db upgrade", "push deliveries", "auth login", "fixtures"):
        assert f"a2a-workbench {command}" in text


def test_every_documented_setting_has_a_description():
    text = (ROOT / "docs/reference/configuration.md").read_text()
    for env in ("A2AW_HOME", "A2AW_DATABASE_URL", "A2AW_SECRET_KEY", "A2AW_PUBLIC_BASE_URL"):
        assert f"`{env}`" in text
    assert "A2AW_MODE" not in text


def test_check_reports_a_stale_file(tmp_path):
    out = _gen("--check", "--out", str(tmp_path))
    assert out.returncode == 1
