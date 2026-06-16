import os
import tempfile

from scanners.repo_scanner import RepoScanner


def test_repo_scanner_detects_directory() -> None:
    scanner = RepoScanner()
    with tempfile.TemporaryDirectory() as tmpdir:
        open(os.path.join(tmpdir, "main.py"), "w").close()
        open(os.path.join(tmpdir, "README.md"), "w").close()
        result = scanner.run(tmpdir)

    assert result["total_files"] == 2
    assert ".py" in result["languages"]
    assert ".md" in result["languages"]
    assert result["has_git"] is False


def test_repo_scanner_handles_missing_target() -> None:
    scanner = RepoScanner()
    result = scanner.run("/nonexistent/path")
    assert "error" in result
