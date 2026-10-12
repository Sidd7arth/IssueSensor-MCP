"""ReproMCP: evidence-first bug triage MCP server for an explicitly configured repository.

Security note: repository test suites are executable code. Test execution is disabled
unless REPROMCP_ALLOW_TEST_EXECUTION=true and the caller explicitly confirms it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server using the project's MCP SDK
mcp = FastMCP("ReproMCP")

from repromcp.gemma import (
    call_gemma_analysis,
    get_configured_gemma_model,
)
from repromcp.report import build_triage_report
from repromcp.runner import run_safe_pytest
from repromcp.workspace import (
    inspect_workspace,
    resolve_screenshot,
    resolve_workspace,
    search_workspace,
)


def _json(data: Any) -> str:
    """Serialize dictionary data to formatted JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False)


def _workspace() -> Path:
    """Resolve the authorized repository workspace."""
    return resolve_workspace()


# ============================================================================
# Registered MCP Tools
# ============================================================================

@mcp.tool()
def inspect_repository() -> str:
    """Inspect the configured repository's structure, files, detected languages, manifests, and test directories. Read-only; does not execute code."""
    try:
        root = _workspace()
        data = inspect_workspace(root)
        data["status"] = "ok"
        data["ai_provider"] = os.environ.get("AI_PROVIDER", "gemma").lower()
        data["model"] = get_configured_gemma_model()
        return _json(data)
    except ValueError as exc:
        return _json({"status": "error", "error": str(exc)})
    except Exception as exc:
        return _json({"status": "error", "error": f"Failed to inspect repository: {exc}"})


@mcp.tool()
def search_code(query: str, max_results: int = 12) -> str:
    """Search readable repository files and return exact file paths, line numbers, and bounded code snippets. Never searches secret or build directories."""
    if not isinstance(query, str) or len(query.strip()) < 2:
        return _json({"status": "error", "error": "Query must contain at least two characters."})
    if len(query.strip()) > 200:
        return _json({"status": "error", "error": "Query is too long; maximum length is 200 characters."})

    try:
        root = _workspace()
        matches = search_workspace(root, query, max_results=max_results)
        return _json({
            "status": "ok",
            "query": query,
            "match_count": len(matches),
            "matches": matches,
        })
    except ValueError as exc:
        return _json({"status": "error", "error": str(exc)})
    except Exception as exc:
        return _json({"status": "error", "error": f"Search failed: {exc}"})


@mcp.tool()
def run_safe_tests(target_path: str = "", confirm_execution: bool = False) -> str:
    """Run pytest on an authorized target in the repository only after explicit environment opt-in and confirmation.

    Security note: Subprocess execution is not a security sandbox. Tests run with the current user's
    operating-system permissions. Only execute tests on trusted code.
    """
    try:
        root = _workspace()
        result = run_safe_pytest(root, target_path=target_path, confirm_execution=confirm_execution)
        return _json(result)
    except ValueError as exc:
        return _json({"status": "error", "error": str(exc)})
    except Exception as exc:
        return _json({"status": "error", "error": f"Test runner invocation failed: {exc}"})


@mcp.tool()
def analyze_issue(
    issue_text: str,
    screenshot_path: str = "",
    observed_test_output: str = "",
    test_target: str = "",
    confirm_test_execution: bool = False,
) -> str:
    """Diagnose an issue using verified repository evidence, optional test execution, and Gemma 4 multimodal AI.

    Returns a structured report strictly distinguishing verified deterministic evidence from AI hypotheses.
    """
    clean_issue = (issue_text or "").strip()
    if not clean_issue or len(clean_issue) < 2:
        return _json({"status": "invalid_input", "error": "issue_text must contain at least two characters."})

    try:
        root = _workspace()
    except ValueError as exc:
        return _json({"status": "error", "error": str(exc)})

    # Pre-validate screenshot if specified
    clean_screenshot = (screenshot_path or "").strip()
    if clean_screenshot:
        try:
            resolve_screenshot(root, clean_screenshot)
        except ValueError as exc:
            return _json({"status": "invalid_image", "error": str(exc)})

    # 1. Deterministic repository search evidence
    repo_matches = search_workspace(root, clean_issue, max_results=12)

    # 2. Test evidence handling
    test_result: dict[str, Any] | None = None
    if observed_test_output.strip():
        test_result = {
            "status": "user_supplied",
            "stdout": observed_test_output.strip()[:7000],
            "command": "user_supplied_output",
        }
    elif confirm_test_execution:
        test_result = run_safe_pytest(root, target_path=test_target, confirm_execution=True)
    else:
        test_result = {"status": "not_requested"}

    # 3. Call Gemma 4 multimodal analysis
    test_payload = test_result.get("stdout") or test_result.get("stderr") or ""
    gemma_response = call_gemma_analysis(
        root=root,
        issue_text=clean_issue,
        screenshot_path=clean_screenshot,
        repository_evidence=repo_matches,
        test_evidence=test_payload,
    )

    gemma_status = gemma_response.get("status", "error")
    model_id = gemma_response.get("model", get_configured_gemma_model())

    if gemma_status == "success":
        ai_analysis = gemma_response.get("analysis")
        err_msg = ""
    else:
        ai_analysis = None
        err_msg = gemma_response.get("error", f"AI analysis status: {gemma_status}")

    # 4. Build unified report strictly separating facts from AI hypotheses
    report = build_triage_report(
        issue_summary=clean_issue,
        status=gemma_status,
        model_id=model_id,
        repo_matches=repo_matches,
        test_result=test_result,
        screenshot_path=clean_screenshot,
        ai_analysis=ai_analysis,
        error_message=err_msg,
    )
    return _json(report)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    # stdio transport is the default and is suitable for MCP hosts that launch local servers.
    mcp.run()
