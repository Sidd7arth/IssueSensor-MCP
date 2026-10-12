"""Optional live smoke test for Gemma 4 via Gemini API.

Runs only when GEMINI_API_KEY is present in the environment.
Usage:
    python scripts/smoke_test_gemma.py
    python scripts/smoke_test_gemma.py --compare-31b
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Reconfigure stdout for utf-8 on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from repromcp.gemma import call_gemma_analysis, get_api_key
from repromcp.runner import run_safe_pytest
from repromcp.workspace import resolve_workspace, search_workspace


def run_smoke_test(model_id: str, root: Path) -> dict[str, Any]:
    print(f"\n=======================================================")
    print(f"Testing Gemma Model: {model_id}")
    print(f"=======================================================")

    # 1. Collect real repository search evidence
    print("[1/3] Gathering repository search evidence...")
    evidence = search_workspace(root, "calculate_discount", max_results=5)
    print(f"      Found {len(evidence)} matches.")

    # 2. Collect real test evidence
    print("[2/3] Executing safe test runner on demo fixture...")
    os.environ["REPROMCP_ALLOW_TEST_EXECUTION"] = "true"
    test_result = run_safe_pytest(root, target_path="tests/test_discounts.py", confirm_execution=True)
    test_output = test_result.get("stdout", "")
    print(f"      Captured test run status: {test_result.get('status')}")

    # 3. Call Gemma 4
    print(f"[3/3] Sending multimodal prompt + screenshot to {model_id}...")
    issue_text = (
        "Checkout UI bug: A 20% discount on a 100 order shows a total of 120.00 instead of 80.00. "
        "Locate the defect in the discounts logic and propose a regression test."
    )
    screenshot_rel = "evidence/discount-bug.png"

    os.environ["GEMMA_MODEL"] = model_id
    start_time = time.monotonic()
    response = call_gemma_analysis(
        root=root,
        issue_text=issue_text,
        screenshot_path=screenshot_rel,
        repository_evidence=evidence,
        test_evidence=test_output,
    )
    elapsed = round(time.monotonic() - start_time, 2)

    status = response.get("status")
    print(f"\nResult for {model_id}:")
    print(f"- Latency: {elapsed} seconds")
    print(f"- Status:  {status}")

    if status == "success":
        analysis = response.get("analysis", {})
        print(f"- Confidence:             {analysis.get('confidence')}")
        print(f"- Likely Root Cause:      {analysis.get('likely_root_cause')}")
        print(f"- Visual Observations:    {analysis.get('visual_observations')}")
        print(f"- Supporting Evidence:    {len(analysis.get('supporting_evidence', []))} citations")
        print(f"- Proposed Regression:    {analysis.get('suggested_regression_test')}")
    else:
        print(f"- Error: {response.get('error')}")

    return {
        "model": model_id,
        "latency_seconds": elapsed,
        "status": status,
        "response": response,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Live smoke test for Gemma 4")
    parser.add_argument("--compare-31b", action="store_true", help="Also test gemma-4-31b-it")
    parser.add_argument("--model", type=str, default="", help="Specific model ID to test")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("[SKIP] GEMINI_API_KEY is not set in environment.")
        print("To run live smoke tests, set GEMINI_API_KEY in your terminal session:")
        print("    $env:GEMINI_API_KEY = 'your_api_key_here'")
        return 0

    demo_root = (PROJECT_ROOT / "demo_repo").resolve()
    if not demo_root.exists():
        print(f"[ERROR] demo_repo directory not found at {demo_root}")
        return 1

    models_to_test = []
    if args.model:
        models_to_test.append(args.model)
    else:
        models_to_test.append("gemma-4-26b-a4b-it")
        if args.compare_31b:
            models_to_test.append("gemma-4-31b-it")

    for model_id in models_to_test:
        run_smoke_test(model_id, demo_root)

    return 0


if __name__ == "__main__":
    sys.exit(main())
