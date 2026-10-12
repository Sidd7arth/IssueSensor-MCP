"""Prompt 5: End-to-end scenario and quality verification test suite.

Verifies:
1. Repository inspection finds demo files.
2. Code search returns exact relevant function and 1-based line.
3. Test execution disabled by default blocks execution.
4. Dual opt-in executes demo test and captures 120 vs 80 assertion failure.
5. Gemma multimodal call receives screenshot, issue, code evidence, and test output.
6. Structured report segregates verified evidence from AI hypotheses.
7. Unconfigured API key returns not_configured while preserving evidence.
8. No secrets or absolute developer paths leak in reports.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("mcp", reason="mcp package required for FastMCP server tests")

import server

from repromcp.report import build_triage_report, render_markdown_report


@pytest.fixture
def demo_workspace(monkeypatch):
    """Point REPROMCP_WORKSPACE to the repository's demo_repo fixture."""
    demo_dir = Path(__file__).resolve().parent.parent / "demo_repo"
    monkeypatch.setenv("REPROMCP_WORKSPACE", str(demo_dir))
    return demo_dir


def test_e2e_1_repository_inspection_finds_demo_files(demo_workspace: Path):
    """Check 1: Repository inspection discovers all demo files and structure."""
    res_str = server.inspect_repository()
    data = json.loads(res_str)

    assert data["status"] == "ok"
    assert data["workspace"] == "demo_repo"
    assert "discounts.py" in data["files"]
    assert "tests/test_discounts.py" in data["discovered_test_files"]
    assert "Python" in data["detected_languages"]


def test_e2e_2_code_search_returns_exact_function_and_line(demo_workspace: Path):
    """Check 2: Code search locates calculate_discount with exact 1-based line number."""
    res_str = server.search_code("calculate_discount")
    data = json.loads(res_str)

    assert data["status"] == "ok"
    assert len(data["matches"]) >= 1

    # Exact definition in discounts.py at line 3
    def_match = next((m for m in data["matches"] if m["file"] == "discounts.py"), None)
    assert def_match is not None
    assert def_match["line"] == 3
    assert "def calculate_discount(price: float, percent: float)" in def_match["text"]
    assert "3 | def calculate_discount" in def_match["snippet"]


def test_e2e_3_execution_disabled_blocks_runner(demo_workspace: Path, monkeypatch):
    """Check 3: Without REPROMCP_ALLOW_TEST_EXECUTION=true, execution is refused."""
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "false")
    res_str = server.run_safe_tests("tests/test_discounts.py", confirm_execution=True)
    data = json.loads(res_str)

    assert data["status"] == "blocked"
    assert data["exit_code"] is None
    assert data["passed"] is False
    assert "Test execution is disabled by default" in data["reason"]


def test_e2e_4_dual_optin_executes_demo_test_with_failing_assertion(demo_workspace: Path, monkeypatch):
    """Check 4: Opt-in + explicit confirmation executes test and returns real 120 vs 80 assertion."""
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")
    res_str = server.run_safe_tests("tests/test_discounts.py", confirm_execution=True)
    data = json.loads(res_str)

    assert data["status"] == "completed"
    assert data["exit_code"] == 1
    assert data["passed"] is False
    assert "120.0 == 80.0" in data["stdout"]
    assert "1 failed" in data["stdout"]
    assert "Subprocess execution is not a security sandbox" in data["note"]


def test_e2e_5_gemma_receives_multimodal_payload(demo_workspace: Path, monkeypatch):
    """Check 5: Multimodal call receives screenshot, issue text, search evidence, and test output."""
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-mock-key-12345")

    mock_client = MagicMock()
    mock_file_upload = MagicMock(name="uploaded_ref")
    mock_client.files.upload.return_value = mock_file_upload

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "visual_observations": ["Product card shows 100 with 20% discount but total is 120."],
        "likely_root_cause": "The formula in discounts.py adds percent instead of subtracting.",
        "confidence": "high",
        "supporting_evidence": [
            {"file": "discounts.py", "line": 3, "observation": "Calculates 1 + percent / 100 instead of 1 - percent / 100"}
        ],
        "reproduction_steps": ["Call calculate_discount(100, 20)"],
        "suggested_regression_test": "assert calculate_discount(100, 20) == 80.00",
        "unknowns_and_limitations": ["UI rendering depends on backend API"],
    })
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        res_str = server.analyze_issue(
            issue_text="Discount formula displays 120 instead of 80 for 100 price with 20% off",
            screenshot_path="evidence/discount-bug.png",
            test_target="tests/test_discounts.py",
            confirm_test_execution=True,
        )

    res = json.loads(res_str)
    assert res["status"] == "success"
    assert res["ai_analysis"]["confidence"] == "high"
    assert "The formula in discounts.py adds percent" in res["ai_analysis"]["likely_root_cause"]

    # Verify generate_content received prompt with evidence
    called_contents = mock_client.models.generate_content.call_args[1]["contents"]
    assert len(called_contents) == 2  # image upload ref + text prompt
    prompt_text = called_contents[1]
    assert "calculate_discount" in prompt_text
    assert "120.0 == 80.0" in prompt_text  # verified test execution result included


def test_e2e_6_report_distinguishes_evidence_from_hypotheses(demo_workspace: Path):
    """Check 6: Report distinctly segregates verified tool facts from AI hypotheses."""
    repo_matches = [{"file": "discounts.py", "line": 3, "text": "return round(price * (1 + percent / 100), 2)", "snippet": "3 | ...", "matched_terms": ["percent"]}]
    test_result = {"status": "completed", "passed": False, "exit_code": 1, "stdout": "assert 120.0 == 80.0"}
    ai_analysis = {
        "visual_observations": ["Price shows 120"],
        "likely_root_cause": "Addition instead of subtraction",
        "confidence": "high",
        "supporting_evidence": [{"file": "discounts.py", "line": 3, "observation": "faulty formula"}],
        "reproduction_steps": ["step 1"],
        "suggested_regression_test": "assert calc(100, 20) == 80",
        "unknowns_and_limitations": [],
    }

    report = build_triage_report(
        issue_summary="20% discount displays 120",
        status="success",
        model_id="gemma-4-26b-a4b-it",
        repo_matches=repo_matches,
        test_result=test_result,
        ai_analysis=ai_analysis,
    )

    # 1. Structured JSON level separation
    assert "verified_evidence" in report
    assert "ai_analysis" in report
    assert report["verified_evidence"]["repository_search"] == repo_matches
    assert report["verified_evidence"]["test_execution"] == test_result
    assert report["ai_analysis"] == ai_analysis

    # 2. Rendered Markdown level distinction
    md = report["rendered_markdown"]
    assert "## 1. Verified Repository Evidence" in md
    assert "## 2. AI Diagnosis & Hypothesis (Gemma 4)" in md
    assert "discounts.py:3" in md
    assert "assert 120.0 == 80.0" in md
    assert "Addition instead of subtraction" in md



def test_e2e_7_missing_api_key_reports_honestly_and_preserves_evidence(demo_workspace: Path, monkeypatch):
    """Check 7: When GEMINI_API_KEY is missing, reports not_configured while preserving evidence."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    res_str = server.analyze_issue(
        issue_text="Discount formula displays 120 instead of 80 calculate_discount",
        screenshot_path="evidence/discount-bug.png",
        test_target="tests/test_discounts.py",
        confirm_test_execution=True,
    )
    res = json.loads(res_str)

    assert res["status"] == "not_configured"
    assert res["ai_analysis"] is None
    assert len(res["verified_evidence"]["repository_search"]) >= 1
    assert res["verified_evidence"]["test_execution"]["status"] == "completed"
    assert "120.0 == 80.0" in res["verified_evidence"]["test_execution"]["stdout"]
    assert "AI Analysis Unavailable" in res["rendered_markdown"]


def test_e2e_8_no_secrets_or_absolute_paths_leak(demo_workspace: Path, monkeypatch):
    """Check 8: Neither secrets nor raw developer absolute paths leak in generated reports."""
    secret_key = "AIzaSySuperSecretKeyDoNotLeakMe99"
    monkeypatch.setenv("GEMINI_API_KEY", secret_key)
    monkeypatch.setenv("SUPER_SECRET_TOKEN", "TopSecretToken987654")
    monkeypatch.setenv("REPROMCP_ALLOW_TEST_EXECUTION", "true")

    res_str = server.analyze_issue(
        issue_text="Discount formula displays 120 instead of 80 calculate_discount",
        screenshot_path="evidence/discount-bug.png",
        test_target="tests/test_discounts.py",
        confirm_test_execution=True,
    )

    # 1. Secret keys must NEVER appear anywhere in the output
    assert secret_key not in res_str
    assert "TopSecretToken987654" not in res_str

    # 2. Absolute root path must not be exposed in relative search/test items
    assert str(demo_workspace) not in res_str
    data = json.loads(res_str)
    for match in data["verified_evidence"]["repository_search"]:
        assert not Path(match["file"]).is_absolute(), f"File path must be relative: {match['file']}"
        assert "absolute_path" not in match


def test_e2e_inspect_and_search_never_leak_absolute_path(demo_workspace: Path):
    """Verify inspect_repository and search_code never return developer absolute paths."""
    insp_str = server.inspect_repository()
    assert str(demo_workspace) not in insp_str
    insp_data = json.loads(insp_str)
    assert "absolute_path" not in insp_data
    for f in insp_data["files"]:
        assert not Path(f).is_absolute()

    search_str = server.search_code("calculate_discount")
    assert str(demo_workspace) not in search_str
    search_data = json.loads(search_str)
    for match in search_data["matches"]:
        assert "absolute_path" not in match
        assert not Path(match["file"]).is_absolute()
