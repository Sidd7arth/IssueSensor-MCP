"""Unit tests for tools defined on server.py."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

pytest.importorskip("mcp", reason="mcp package required for FastMCP server tests")

import server



def test_server_inspect_repository_no_workspace(monkeypatch):
    monkeypatch.delenv("REPROMCP_WORKSPACE", raising=False)
    res_str = server.inspect_repository()
    res = json.loads(res_str)
    assert res["status"] == "error"
    assert "REPROMCP_WORKSPACE is not set" in res["error"]


def test_server_inspect_repository_success(monkeypatch, tmp_path):
    root = (tmp_path / "valid_repo").resolve()
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(root))

    res_str = server.inspect_repository()
    res = json.loads(res_str)
    assert res["status"] == "ok"
    assert res["workspace"] == root.name
    assert "pyproject.toml" in res["project_manifests_and_docs"]


def test_server_search_code_validation(monkeypatch, tmp_path):
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(root))

    # Test short query
    res = json.loads(server.search_code("a"))
    assert res["status"] == "error"
    assert "two characters" in res["error"]

    # Test overly long query
    res = json.loads(server.search_code("x" * 201))
    assert res["status"] == "error"
    assert "too long" in res["error"]


def test_server_search_code_success(monkeypatch, tmp_path):
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    (root / "hello.py").write_text("def say_hello(): print('hello world')\n", encoding="utf-8")
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(root))

    res = json.loads(server.search_code("say_hello"))
    assert res["status"] == "ok"
    assert res["match_count"] == 1
    assert res["matches"][0]["file"] == "hello.py"
    assert res["matches"][0]["line"] == 1


def test_server_run_safe_tests_authorization(monkeypatch, tmp_path):
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(root))
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "false")

    res = json.loads(server.run_safe_tests(confirm_execution=False))
    assert res["status"] == "blocked"

    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")
    res = json.loads(server.run_safe_tests(confirm_execution=False))
    assert res["status"] == "confirmation_required"
