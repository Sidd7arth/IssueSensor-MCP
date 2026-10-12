from pathlib import Path

from repromcp_core import is_ignored, ranked_matches, resolve_screenshot


def test_ignored_secrets_and_generated_directories(tmp_path: Path):
    root = tmp_path.resolve()
    assert is_ignored(root / ".env", root)
    assert is_ignored(root / "node_modules" / "pkg.js", root)
    assert is_ignored(root / "private.pem", root)
    assert not is_ignored(root / "src" / "main.py", root)


def test_search_finds_real_file_and_line(tmp_path: Path, monkeypatch):
    root = tmp_path.resolve()
    (root / "discounts.py").write_text(
        "def calculate_discount(price, percent):\n    return price * (1 + percent / 100)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(root))
    matches = ranked_matches(root, "calculate_discount percent", 10)
    assert matches
    assert matches[0]["file"] == "discounts.py"
    assert matches[0]["line"] == 1


def test_search_skips_env_file(tmp_path: Path):
    root = tmp_path.resolve()
    (root / ".env").write_text("API_TOKEN=secret-value", encoding="utf-8")
    assert ranked_matches(root, "API_TOKEN secret-value", 10) == []


def test_resolve_screenshot_accepts_workspace_image(tmp_path: Path):
    root = tmp_path.resolve()
    evidence = root / "evidence"
    evidence.mkdir()
    screenshot = evidence / "bug.png"
    screenshot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
    assert resolve_screenshot(root, "evidence/bug.png") == screenshot.resolve()


def test_resolve_screenshot_rejects_path_outside_workspace(tmp_path: Path):
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
    try:
        resolve_screenshot(root, str(outside))
    except ValueError as exc:
        assert "inside the configured" in str(exc)
    else:
        raise AssertionError("Screenshot outside configured workspace was accepted")
