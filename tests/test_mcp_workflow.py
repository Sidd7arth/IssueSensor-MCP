"""Integration tests for MCP workflow and report generation (Prompt 4)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("mcp", reason="mcp package required for FastMCP server tests")

import server

from repromcp.report import build_triage_report, render_markdown_report


def test_mcp_imports_and_initializes_without_api_call():
    """Verify MCP server imports and initializes FastMCP without making live API calls."""
    assert server.mcp is not None
    assert server.mcp.name == "ReproMCP"


def test_analyze_issue_invalid_screenshot(tmp_path: Path, monkeypatch):
    """Verify analyze_issue returns correct error when screenshot is invalid."""
    root = tmp_path.resolve()
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(root))

    res_str = server.analyze_issue(
        issue_text="Discount bug report",
        screenshot_path="nonexistent_screenshot.png",
    )
    res = json.loads(res_str)
    assert res["status"] == "invalid_image"
    assert "does not exist" in res["error"]


def test_analyze_issue_returns_evidence_when_ai_not_configured(tmp_path: Path, monkeypatch):
    """Verify analyze_issue preserves repository and test evidence even when GEMINI_API_KEY is not set."""
    root = tmp_path.resolve()
    (root / "calculator.py").write_text("def calc(a, b): return a + b\n", encoding="utf-8")
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(root))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    res_str = server.analyze_issue(
        issue_text="calc function",
        observed_test_output="User test assertion passed",
    )
    res = json.loads(res_str)

    # Status must reflect unconfigured AI
    assert res["status"] == "not_configured"
    assert res["ai_analysis"] is None

    # Verified evidence must be preserved and populated
    verified = res["verified_evidence"]
    assert len(verified["repository_search"]) >= 1
    assert verified["repository_search"][0]["file"] == "calculator.py"
    assert verified["test_execution"]["status"] == "user_supplied"
    assert "User test assertion passed" in verified["test_execution"]["stdout"]

    # Rendered Markdown must contain verified facts and note AI was unavailable
    md = res["rendered_markdown"]
    assert "calculator.py:1" in md
    assert "User test assertion passed" in md
    assert "AI Analysis Unavailable" in md


def test_report_rendering_states():
    """Verify Markdown report rendering across success, error, and no-analysis states."""
    repo_matches = [{"file": "app.py", "line": 42, "text": "foo = bar", "snippet": "42 | foo = bar", "matched_terms": ["foo"]}]
    test_res = {"status": "completed", "passed": True, "exit_code": 0, "stdout": "1 passed in 0.05s"}

    # 1. Success state
    ai_success = {
        "visual_observations": ["Red error banner on screen."],
        "likely_root_cause": "Misconfiguration in foo setting.",
        "confidence": "high",
        "reproduction_steps": ["Step 1", "Step 2"],
        "suggested_regression_test": "assert foo == bar",
        "unknowns_and_limitations": ["Limited log visibility."],
    }
    report_success = build_triage_report(
        issue_summary="Problem with foo",
        status="success",
        model_id="gemma-4-26b-a4b-it",
        repo_matches=repo_matches,
        test_result=test_res,
        ai_analysis=ai_success,
    )
    md_success = report_success["rendered_markdown"]
    assert "ReproMCP Visual — Bug Triage Report" in md_success
    assert "Confidence: `HIGH`" in md_success
    assert "Misconfiguration in foo setting." in md_success
    assert "app.py:42" in md_success

    # 2. Not configured (no analysis) state
    report_no_ai = build_triage_report(
        issue_summary="Problem with foo",
        status="not_configured",
        model_id="gemma-4-26b-a4b-it",
        repo_matches=repo_matches,
        test_result=test_res,
        error_message="GEMINI_API_KEY is not set.",
    )
    md_no_ai = report_no_ai["rendered_markdown"]
    assert "AI Analysis Unavailable" in md_no_ai
    assert "GEMINI_API_KEY is not set." in md_no_ai
    assert "app.py:42" in md_no_ai  # Evidence still rendered!

    # 3. Error state
    report_err = build_triage_report(
        issue_summary="Problem with foo",
        status="api_error",
        model_id="gemma-4-26b-a4b-it",
        repo_matches=repo_matches,
        error_message="Network timeout.",
    )
    md_err = report_err["rendered_markdown"]
    assert "Network timeout." in md_err


def test_model_paths_not_treated_as_verified_evidence():
    """Verify model-generated hallucinations are quarantined in ai_analysis and not in verified_evidence."""
    repo_matches = [{"file": "real_file.py", "line": 10, "text": "real_code()", "snippet": "10 | real_code()", "matched_terms": ["real_code"]}]
    fake_ai_analysis = {
        "visual_observations": [],
        "likely_root_cause": "Bug in imaginary module.",
        "confidence": "low",
        "supporting_evidence": [
            {"file": "nonexistent_fake_file.py", "line": 999, "observation": "hallucinated file"}
        ],
        "reproduction_steps": [],
        "suggested_regression_test": "",
        "unknowns_and_limitations": [],
    }

    report = build_triage_report(
        issue_summary="Testing evidence segregation",
        status="success",
        model_id="gemma-4-26b-a4b-it",
        repo_matches=repo_matches,
        ai_analysis=fake_ai_analysis,
    )

    # verified_evidence contains ONLY genuine search matches
    verified_files = [m["file"] for m in report["verified_evidence"]["repository_search"]]
    assert "real_file.py" in verified_files
    assert "nonexistent_fake_file.py" not in verified_files

    # Model's citation is strictly inside ai_analysis
    assert report["ai_analysis"]["supporting_evidence"][0]["file"] == "nonexistent_fake_file.py"
