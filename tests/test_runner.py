"""Unit tests for repromcp.runner module."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repromcp.runner import (
    FIXED_COMMAND_STR,
    MAX_STDOUT_CHARS,
    MAX_STDERR_CHARS,
    MAX_TIMEOUT_SECONDS,
    run_safe_pytest,
    sanitize_child_env,
    truncate_output,
)


def test_sanitize_child_env():
    dirty_env = {
        "PATH": "C:\\Windows\\System32",
        "GEMINI_API_KEY": "secret-gemini-key",
        "GOOGLE_API_KEY": "secret-google-key",
        "MY_SECRET_TOKEN": "token123",
        "AUTH_PASSWORD": "password123",
        "SAFE_VAR": "visible_value",
    }
    clean = sanitize_child_env(dirty_env)
    assert "PATH" in clean
    assert "SAFE_VAR" in clean
    assert clean["SAFE_VAR"] == "visible_value"
    assert "GEMINI_API_KEY" not in clean
    assert "GOOGLE_API_KEY" not in clean
    assert "MY_SECRET_TOKEN" not in clean
    assert "AUTH_PASSWORD" not in clean


def test_truncate_output():
    assert truncate_output(None, 100) == ""
    assert truncate_output("short", 100) == "short"
    assert truncate_output(b"binary short", 100) == "binary short"
    long_str = "abcdefghij" * 20  # 200 chars
    truncated = truncate_output(long_str, 50)
    assert len(truncated) == 50
    assert truncated == long_str[-50:]


def test_run_safe_pytest_denied_when_env_missing(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("REPROMCP_ALLOW_TEST_EXECUTION", raising=False)
    res = run_safe_pytest(tmp_path, confirm_execution=True)
    assert res["status"] == "blocked"
    assert res["passed"] is False
    assert res["exit_code"] is None
    assert res["timed_out"] is False
    assert res["command"] == FIXED_COMMAND_STR
    assert "disabled by default" in res["reason"]


def test_run_safe_pytest_denied_when_env_false(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "false")
    res = run_safe_pytest(tmp_path, confirm_execution=True)
    assert res["status"] == "blocked"
    assert res["passed"] is False
    assert res["exit_code"] is None
    assert res["timed_out"] is False
    assert "disabled by default" in res["reason"]


def test_run_safe_pytest_denied_when_per_call_confirmation_absent_or_false(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    # Absent (default False)
    res_default = run_safe_pytest(tmp_path)
    assert res_default["status"] == "confirmation_required"
    assert res_default["passed"] is False
    assert res_default["exit_code"] is None
    assert "confirm_execution=true" in res_default["reason"]

    # Explicit False
    res_explicit_false = run_safe_pytest(tmp_path, confirm_execution=False)
    assert res_explicit_false["status"] == "confirmation_required"
    assert res_explicit_false["passed"] is False
    assert res_explicit_false["exit_code"] is None
    assert "confirm_execution=true" in res_explicit_false["reason"]


def test_run_safe_pytest_invalid_workspace_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    # Non-existent directory
    missing_dir = tmp_path / "missing_subdir"
    res_missing = run_safe_pytest(missing_dir, confirm_execution=True)
    assert res_missing["status"] == "error"
    assert res_missing["passed"] is False
    assert res_missing["exit_code"] is None
    assert "does not exist" in res_missing["error"]

    # File instead of directory
    a_file = tmp_path / "file.txt"
    a_file.write_text("not a dir", encoding="utf-8")
    res_file = run_safe_pytest(a_file, confirm_execution=True)
    assert res_file["status"] == "error"
    assert res_file["passed"] is False
    assert "not a directory" in res_file["error"]


def test_run_safe_pytest_traversal_and_outside_path_rejected(tmp_path: Path, monkeypatch):
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    outside = (tmp_path / "outside.py").resolve()
    outside.write_text("def test_outside(): pass\n", encoding="utf-8")

    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    # Obvious parent traversal
    res_parent = run_safe_pytest(root, target_path="../outside.py", confirm_execution=True)
    assert res_parent["status"] == "error"
    assert "parent" in res_parent["error"] or "inside" in res_parent["error"]

    # Traversal inside nested path
    res_nested = run_safe_pytest(root, target_path="tests/../../outside.py", confirm_execution=True)
    assert res_nested["status"] == "error"

    # Absolute path targeting outside
    res_abs = run_safe_pytest(root, target_path=str(outside), confirm_execution=True)
    assert res_abs["status"] == "error"


def test_run_safe_pytest_wrong_file_type_and_nonexistent(tmp_path: Path, monkeypatch):
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    (root / "README.md").write_text("# Not a python test\n", encoding="utf-8")

    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    # Non-Python file
    res_type = run_safe_pytest(root, target_path="README.md", confirm_execution=True)
    assert res_type["status"] == "error"
    assert "Python (.py) file" in res_type["error"]

    # Non-existent file
    res_missing = run_safe_pytest(root, target_path="nonexistent.py", confirm_execution=True)
    assert res_missing["status"] == "error"
    assert "does not exist" in res_missing["error"]


def test_run_safe_pytest_passing_suite(tmp_path: Path, monkeypatch):
    root = (tmp_path / "test_repo").resolve()
    root.mkdir()
    (root / "test_sample.py").write_text("def test_ok(): assert 1 + 1 == 2\n", encoding="utf-8")

    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")
    res = run_safe_pytest(root, confirm_execution=True)

    assert res["status"] == "completed"
    assert res["exit_code"] == 0
    assert res["passed"] is True
    assert res["timed_out"] is False
    assert res["command"] == FIXED_COMMAND_STR
    assert "1 passed" in res["stdout"]
    assert "not a security sandbox" in res["note"]


def test_run_safe_pytest_passing_specific_target(tmp_path: Path, monkeypatch):
    root = (tmp_path / "test_repo_target").resolve()
    root.mkdir()
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_one.py").write_text("def test_first(): assert True\n", encoding="utf-8")
    (tests_dir / "test_two.py").write_text("def test_second(): assert True\n", encoding="utf-8")

    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")
    res = run_safe_pytest(root, target_path="tests/test_one.py", confirm_execution=True)

    assert res["status"] == "completed"
    assert res["exit_code"] == 0
    assert res["passed"] is True
    assert "tests/test_one.py" in res["command"]
    assert "1 passed" in res["stdout"]


def test_run_safe_pytest_failing_suite(tmp_path: Path, monkeypatch):
    root = (tmp_path / "test_repo_fail").resolve()
    root.mkdir()
    (root / "test_fail.py").write_text("def test_bad(): assert 1 == 2\n", encoding="utf-8")

    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")
    res = run_safe_pytest(root, confirm_execution=True)

    assert res["status"] == "completed"
    assert res["exit_code"] != 0
    assert res["passed"] is False
    assert res["timed_out"] is False
    assert "1 failed" in res["stdout"]
    assert "not a security sandbox" in res["note"]


def test_run_safe_pytest_timeout(tmp_path: Path, monkeypatch):
    root = (tmp_path / "test_repo_timeout").resolve()
    root.mkdir()
    (root / "test_sleep.py").write_text("import time\ndef test_slow(): time.sleep(2)\n", encoding="utf-8")

    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")
    res = run_safe_pytest(root, confirm_execution=True, timeout_seconds=1)

    assert res["status"] == "timeout"
    assert res["timed_out"] is True
    assert res["exit_code"] is None
    assert res["passed"] is False
    assert "timed out" in res["reason"]
    assert "not a security sandbox" in res["note"]


def test_run_safe_pytest_timeout_clamped_to_sixty(tmp_path: Path, monkeypatch):
    root = (tmp_path / "test_repo_clamp").resolve()
    root.mkdir()
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    recorded_kwargs = {}

    def fake_subprocess_run(*args, **kwargs):
        recorded_kwargs.update(kwargs)
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "1 passed\n"
        mock_res.stderr = ""
        return mock_res

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    res = run_safe_pytest(root, confirm_execution=True, timeout_seconds=120)
    assert res["status"] == "completed"
    assert recorded_kwargs["timeout"] == MAX_TIMEOUT_SECONDS  # 60
    assert recorded_kwargs["shell"] is False


def test_run_safe_pytest_no_arbitrary_shell_interpretation(tmp_path: Path, monkeypatch):
    root = (tmp_path / "test_repo_shell").resolve()
    root.mkdir()
    (root / "test_sample.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    recorded_kwargs = {}

    def fake_subprocess_run(*args, **kwargs):
        recorded_kwargs.update(kwargs)
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "1 passed\n"
        mock_res.stderr = ""
        return mock_res

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    # Calling with valid target
    res = run_safe_pytest(root, target_path="test_sample.py", confirm_execution=True)
    assert res["status"] == "completed"
    assert recorded_kwargs["shell"] is False
    assert isinstance(recorded_kwargs.get("args") or recorded_kwargs.get("cmd") or recorded_kwargs.get("fixed_cmd", []), list)

    # Reject target containing shell injection syntax because file doesn't exist
    res_injected = run_safe_pytest(root, target_path="test_sample.py; echo INJECTED", confirm_execution=True)
    assert res_injected["status"] == "error"


def test_run_safe_pytest_output_limits(tmp_path: Path, monkeypatch):
    root = (tmp_path / "test_repo_limits").resolve()
    root.mkdir()
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    fake_completed = MagicMock()
    fake_completed.returncode = 0
    fake_completed.stdout = "X" * 20000
    fake_completed.stderr = "Y" * 10000

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: fake_completed)

    res = run_safe_pytest(root, confirm_execution=True)
    assert res["status"] == "completed"
    assert len(res["stdout"]) == MAX_STDOUT_CHARS
    assert len(res["stderr"]) == MAX_STDERR_CHARS


def test_run_safe_pytest_missing_pytest(tmp_path: Path, monkeypatch):
    root = (tmp_path / "test_repo_missing").resolve()
    root.mkdir()
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    fake_completed = MagicMock()
    fake_completed.returncode = 1
    fake_completed.stdout = ""
    fake_completed.stderr = "C:\\Python\\python.exe: No module named pytest\n"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: fake_completed)

    res = run_safe_pytest(root, confirm_execution=True)
    assert res["status"] == "missing_pytest"
    assert res["passed"] is False
    assert res["exit_code"] == 1
    assert "pytest is not installed" in res["error"]


def test_run_safe_pytest_startup_error(tmp_path: Path, monkeypatch):
    root = (tmp_path / "test_repo_startup").resolve()
    root.mkdir()
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    def raise_oserror(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(subprocess, "run", raise_oserror)

    res = run_safe_pytest(root, confirm_execution=True)
    assert res["status"] == "startup_error"
    assert res["passed"] is False
    assert res["exit_code"] is None
    assert "Could not start pytest" in res["error"]
