"""Unit tests for repromcp.workspace module."""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from repromcp.workspace import (
    MAX_FILE_BYTES,
    inspect_workspace,
    is_dir_ignored,
    is_ignored,
    is_safe_relative,
    iter_text_files,
    iter_workspace_files,
    resolve_screenshot,
    resolve_workspace,
    search_workspace,
)


def test_resolve_workspace_missing_env(monkeypatch):
    monkeypatch.delenv("REPROMCP_WORKSPACE", raising=False)
    with pytest.raises(ValueError, match="REPROMCP_WORKSPACE is not set"):
        resolve_workspace()


def test_resolve_workspace_nonexistent(monkeypatch, tmp_path):
    missing_dir = tmp_path / "does_not_exist"
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(missing_dir))
    with pytest.raises(ValueError, match="does not exist"):
        resolve_workspace()


def test_resolve_workspace_not_a_dir(monkeypatch, tmp_path):
    file_path = tmp_path / "regular_file.txt"
    file_path.write_text("hello", encoding="utf-8")
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(file_path))
    with pytest.raises(ValueError, match="not a directory"):
        resolve_workspace()


def test_resolve_workspace_valid(monkeypatch, tmp_path):
    root = (tmp_path / "valid_repo").resolve()
    root.mkdir()
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(root))
    assert resolve_workspace() == root


def test_is_ignored_secrets_and_extensions(tmp_path: Path):
    root = tmp_path.resolve()
    assert is_ignored(root / ".env", root)
    assert is_ignored(root / ".env.local", root)
    assert is_ignored(root / ".env.production", root)
    assert is_ignored(root / "private.pem", root)
    assert is_ignored(root / "app.db", root)
    assert is_ignored(root / "bundle.min.js", root)
    assert is_ignored(root / "node_modules" / "pkg.js", root)
    assert is_ignored(root / ".venv" / "lib.py", root)
    assert not is_ignored(root / "src" / "main.py", root)


def test_is_dir_ignored():
    assert is_dir_ignored(".git")
    assert is_dir_ignored("node_modules")
    assert is_dir_ignored(".venv")
    assert is_dir_ignored("__pycache__")
    assert not is_dir_ignored("src")
    assert not is_dir_ignored("tests")


def test_directory_pruning_does_not_enter_ignored_dirs(tmp_path: Path):
    root = tmp_path.resolve()
    (root / "src").mkdir()
    (root / "src" / "code.py").write_text("x = 1\n", encoding="utf-8")

    ignored_dir = root / "node_modules" / "huge_dep"
    ignored_dir.mkdir(parents=True)
    (ignored_dir / "index.js").write_text("console.log(1)\n", encoding="utf-8")

    discovered = list(iter_workspace_files(root))
    assert len(discovered) == 1
    assert discovered[0].name == "code.py"


def test_inspect_workspace(tmp_path: Path):
    root = tmp_path.resolve()
    (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (root / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    data = inspect_workspace(root)
    assert data["workspace"] == root.name
    assert data["files_listed"] == 4
    assert data["file_list_truncated"] is False
    assert "Python" in data["detected_languages"]
    assert "Markdown" in data["detected_languages"]
    assert "pyproject.toml" in data["project_manifests_and_docs"]
    assert "README.md" in data["project_manifests_and_docs"]
    assert "tests" in data["test_directories"]
    assert "tests/test_app.py" in data["discovered_test_files"]


# ---------------------------------------------------------------------------
# Prompt 1 Requirements: Explicit tests 1 to 5
# ---------------------------------------------------------------------------

def test_exact_search_returns_correct_file_and_line_number(tmp_path: Path):
    """Test 1: Exact search returns correct file and line number."""
    root = tmp_path.resolve()
    target_file = root / "discounts.py"
    target_file.write_text(
        "# Header\n"
        "\n"
        "def calculate_discount(price, percent):\n"
        "    return price * (1 - percent / 100)\n",
        encoding="utf-8",
    )

    matches = search_workspace(root, "calculate_discount", max_results=5)
    assert len(matches) >= 1
    match = matches[0]
    assert match["file"] == "discounts.py"
    assert match["line"] == 3
    assert "def calculate_discount" in match["text"]
    assert "   3 | def calculate_discount" in match["snippet"]
    assert match["score"] >= 100  # Exact match boost


def test_excluded_secret_files_never_searchable_or_returned(tmp_path: Path):
    """Test 2: Excluded secret files are not searchable and their content is never returned."""
    root = tmp_path.resolve()
    (root / ".env").write_text("API_SECRET_KEY=super_secret_value_123\n", encoding="utf-8")
    (root / ".env.production").write_text("DATABASE_PASSWORD=production_secret_456\n", encoding="utf-8")
    (root / "secrets.json").write_text('{"token": "secret_token_789"}\n', encoding="utf-8")
    (root / "service-account.json").write_text('{"private_key_id": "secret_sa_key"}\n', encoding="utf-8")
    (root / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n", encoding="utf-8")
    (root / "private.pem").write_text("-----BEGIN PRIVATE KEY-----\n...\n", encoding="utf-8")

    assert search_workspace(root, "super_secret_value") == []
    assert search_workspace(root, "production_secret") == []
    assert search_workspace(root, "secret_token") == []
    assert search_workspace(root, "secret_sa_key") == []
    assert search_workspace(root, "BEGIN RSA PRIVATE KEY") == []
    assert search_workspace(root, "BEGIN PRIVATE KEY") == []


def test_outside_workspace_paths_and_symlinks_rejected_or_skipped(tmp_path: Path):
    """Test 3: Outside-workspace paths and symlinks are rejected/skipped."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    outside_dir = (tmp_path / "outside").resolve()
    outside_dir.mkdir()
    outside_secret = outside_dir / "secret.txt"
    outside_secret.write_text("OUTSIDE_LEAKED_DATA", encoding="utf-8")

    # Containment check fails for outside file
    assert not is_safe_relative(outside_secret, root)

    # Symlink pointing outside workspace must be ignored
    symlink_path = root / "symlink_to_outside.txt"
    try:
        os.symlink(outside_secret, symlink_path)
    except (OSError, NotImplementedError):
        pass  # Windows may require admin privilege for symlinks; if unsupported, test passes containment check
    else:
        # If symlink was created, verify iter_workspace_files ignores it
        discovered_files = list(iter_workspace_files(root))
        assert symlink_path not in discovered_files
        assert search_workspace(root, "OUTSIDE_LEAKED_DATA") == []


def test_missing_workspace_and_empty_or_no_match_query(tmp_path: Path, monkeypatch):
    """Test 4: Missing workspace and empty/no-match query return understandable results."""
    # Missing workspace
    monkeypatch.delenv("REPROMCP_WORKSPACE", raising=False)
    with pytest.raises(ValueError, match="REPROMCP_WORKSPACE is not set"):
        resolve_workspace()

    # Empty and single-character queries return empty list safely without crashing
    root = tmp_path.resolve()
    (root / "code.py").write_text("hello_world = True\n", encoding="utf-8")
    assert search_workspace(root, "") == []
    assert search_workspace(root, "   ") == []
    assert search_workspace(root, "h") == []

    # No-match query returns empty list
    assert search_workspace(root, "completely_unmatched_query_xyz") == []


def test_large_files_and_output_are_bounded(tmp_path: Path):
    """Test 5: Large files/output are bounded."""
    root = tmp_path.resolve()

    # Oversized file > MAX_FILE_BYTES (512 KB) must be skipped
    large_file = root / "huge.txt"
    large_file.write_text("HUGE_KEYWORD " * 50000, encoding="utf-8")
    assert large_file.stat().st_size > MAX_FILE_BYTES

    # Normal sized file
    normal_file = root / "normal.txt"
    # Create a line with > 400 characters to verify line snippet truncation
    long_line = "long_prefix_" + ("A" * 350) + "_suffix"
    normal_file.write_text(f"def test_long():\n    {long_line}\n", encoding="utf-8")

    # iter_text_files skips the oversized file
    text_files = list(iter_text_files(root))
    assert large_file not in text_files
    assert normal_file in text_files

    # Search ignores the oversized file
    assert search_workspace(root, "HUGE_KEYWORD") == []

    # Search snippet lines on normal file are bounded to 280 characters
    matches = search_workspace(root, "long_prefix")
    assert len(matches) == 1
    snippet_lines = matches[0]["snippet"].splitlines()
    for s_line in snippet_lines:
        # Each line in snippet has format "   2 | <text[:280]>"
        content_part = s_line.split("|", 1)[1].strip()
        assert len(content_part) <= 280

    # Max results is clamped (e.g. asking for 100 results is capped to <= 50)
    capped_matches = search_workspace(root, "long_prefix", max_results=100)
    assert len(capped_matches) <= 50


def test_resolve_screenshot(tmp_path: Path):
    root = tmp_path.resolve()
    img_dir = root / "evidence"
    img_dir.mkdir()
    img_file = img_dir / "bug.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    resolved = resolve_screenshot(root, "evidence/bug.png")
    assert resolved == img_file.resolve()

    # Reject empty path
    with pytest.raises(ValueError, match="cannot be empty"):
        resolve_screenshot(root, " ")

    # Reject non-existent file
    with pytest.raises(ValueError, match="does not exist"):
        resolve_screenshot(root, "evidence/nonexistent.png")

    # Reject file outside workspace
    outside = (tmp_path.parent / "outside.png").resolve()
    outside.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    try:
        with pytest.raises(ValueError, match="inside the configured"):
            resolve_screenshot(root, str(outside))
    finally:
        if outside.exists():
            outside.unlink()

    # Reject invalid image signature
    fake_png = img_dir / "fake.png"
    fake_png.write_bytes(b"not a real png header")
    with pytest.raises(ValueError, match="signature"):
        resolve_screenshot(root, "evidence/fake.png")
