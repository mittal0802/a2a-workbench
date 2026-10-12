import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _notes(version, changelog, tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(changelog)
    return subprocess.run(
        [str(ROOT / "scripts/release-notes.sh"), version, str(path)],
        capture_output=True,
        text=True,
    )


def test_prints_only_that_section(tmp_path):
    out = _notes(
        "1.0.0",
        "# Changelog\n\n## 1.0.0 — 2026-10-20\n\n- First release.\n\n## 0.1.0\n\n- Old.\n",
        tmp_path,
    )
    assert out.returncode == 0
    assert out.stdout.strip() == "- First release."


def test_missing_section_fails(tmp_path):
    assert _notes("1.0.1", "# Changelog\n\n## 1.0.0\n\n- x\n", tmp_path).returncode == 1


def test_empty_section_fails(tmp_path):
    assert _notes("1.0.0", "# Changelog\n\n## 1.0.0\n\n## 0.9.0\n\n- x\n", tmp_path).returncode == 1


def test_does_not_match_a_longer_version(tmp_path):
    out = _notes("1.0.1", "# Changelog\n\n## 1.0.10\n\n- ten\n", tmp_path)
    assert out.returncode == 1


def test_repo_changelog_has_the_current_version():
    from a2a_workbench import __version__

    assert _notes_repo(__version__).returncode == 0


def _notes_repo(version):
    return subprocess.run(
        [str(ROOT / "scripts/release-notes.sh"), version, str(ROOT / "CHANGELOG.md")],
        capture_output=True,
        text=True,
    )
