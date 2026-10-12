# IssueSensor-MCP (ReproMCP Visual) — Quality Verification & Test Report

**Date:** 2026-10-12<br>
**Target System:** IssueSensor-MCP: ReproMCP Visual (Evidence-First Multimodal Debugging MCP Server)<br>
**SDK Stack:** Python 3.13 / FastMCP v1 (`mcp>=1.12,<2`), `google-genai` (Gemma 4), `Pillow`, `pytest`


---

## 1. Executive Summary

All quality gates, end-to-end scenario validations, and test suites completed successfully.
- **Python Compilation (`compileall`):** 0 syntax/bytecode errors across `server.py` and `repromcp/`.
- **Core Unit & Integration Test Suite (`tests/`):** 64 passed out of 64 tests (100% green, 100% offline hermetic).
- **Graceful Dependency Isolation:** All test modules use `pytest.importorskip` for optional framework packages (`mcp`, `google.genai`), ensuring clean execution without crashing collection in minimal environments.
- **Synthetic Demo Test Suite (`demo_repo/tests/`):** 1 failed, 1 passed. The single failure is the intentional synthetic discount assertion (`assert 120.0 == 80.0`). Zero setup, import, or collection failures.
- **Live Gemma 4 Multimodal Smoke Test:** Verified against `gemma-4-26b-a4b-it` with live screenshot analysis and evidence correlation.

---

## 2. Command Execution & Observed Results

### A. Python Bytecode Compilation
```bash
python -m compileall -q server.py repromcp
```
- **Exit Code:** `0`
- **Output:** Clean (no errors, warnings, or syntax anomalies).

### B. Core Test Suite
```bash
python -m pytest -q tests
```
- **Exit Code:** `0`
- **Duration:** ~28s
- **Result:**
  ```text
  ................................................................         [100%]
  64 passed in 28.85s
  ```
- **Coverage Breakdown:**
  - `tests/test_workspace.py`: 14 passed (safe directory traversal, symlink confinement, secret file filtering, lexical token scoring, absolute path omission).
  - `tests/test_runner.py`: 17 passed (dual opt-in enforcement, target path traversal rejection, timeout clamping, output bounding, subprocess environment secret scrubbing).
  - `tests/test_gemma.py`: 9 passed (image payload validation, model ID allowlist enforcement, strict 7-key JSON schema validation, error sanitization).
  - `tests/test_mcp_workflow.py`: 5 passed (FastMCP initialization, invalid screenshot handling, API key preservation, report segregation).
  - `tests/test_server_helpers.py` & `test_server_tools.py`: 10 passed (tool schemas, JSON serialization, argument parsing).
  - `tests/test_scenario_e2e.py`: 9 passed (end-to-end 8-point scenario checks, absolute path leak prevention).


### C. Demo Fixture Execution
```bash
python -m pytest -q demo_repo/tests
```
- **Exit Code:** `1` (Expected failure)
- **Duration:** 0.42s
- **Result:**
  ```text
  F.                                                                       [100%]
  ================================== FAILURES ===================================
  _________________ test_twenty_percent_discount_reduces_price __________________

      def test_twenty_percent_discount_reduces_price():
          # Expected 80.00, but the intentionally buggy function returns 120.00.
  >       assert calculate_discount(100, 20) == 80.00
  E       assert 120.0 == 80.0
  E        +  where 120.0 = calculate_discount(100, 20)

  demo_repo\tests\test_discounts.py:6: AssertionError
  =========================== short test summary info ===========================
  FAILED demo_repo\tests\test_discounts.py::test_twenty_percent_discount_reduces_price
  1 failed, 1 passed in 0.42s
  ```
- **Note:** `test_zero_discount_leaves_price_unchanged` passes; `test_twenty_percent_discount_reduces_price` fails strictly on the calculation assertion `120.0 == 80.0`.

---

## 3. End-to-End Scenario Verification (Prompt 5 Checks)

| Check # | Requirement | Implementation / Test Verification | Status |
|:---:|:---|:---|:---:|
| **1** | Repository inspection finds demo files | Discovers `discounts.py`, `tests/test_discounts.py`, `evidence/discount-bug.png`, and `pytest.ini`. | **PASS** |
| **2** | Code search returns exact relevant function & 1-based line | Locates `def calculate_discount` in `discounts.py:3` with 3-line snippet. | **PASS** |
| **3** | Runner refuses execution when disabled | When `REPROMCP_ALLOW_TEST_EXECUTION=false`, returns `status: blocked` with policy rationale. | **PASS** |
| **4** | Dual opt-in executes test & returns real failing assertion | With `REPROMCP_ALLOW_TEST_EXECUTION=true` + `confirm_execution=true`, runs pytest and captures exit code 1 with `assert 120.0 == 80.0`. | **PASS** |
| **5** | Gemma receives multimodal payload | Screenshot (`discount-bug.png`), issue text, search evidence, and test output passed to `gemma-4-26b-a4b-it`. | **PASS** |
| **6** | Structured report segregates evidence from hypotheses | `verified_evidence` (deterministic facts) strictly quarantined from `ai_analysis` (hypotheses) in JSON and Markdown. | **PASS** |
| **7** | Missing API key reports honestly & preserves evidence | Returns `status: not_configured` with AI section flagged, while code matches and test execution logs remain fully visible. | **PASS** |
| **8** | No secrets or developer paths leak | Environment sanitization scrubs `KEY`, `SECRET`, `TOKEN`, `AUTH` variables; all file paths formatted as safe relative POSIX paths. | **PASS** |

---

## 4. Live Gemma Smoke Test Verification

Command:
```bash
python scripts/smoke_test_gemma.py
```
- **Model Selected:** `gemma-4-26b-a4b-it` (via `GEMMA_MODEL`)
- **Latency:** 24.82s
- **Status:** `success`
- **Confidence:** `high`
- **Visual Observations:** Identified product card displaying original price of ₹100, a 20% discount badge, and an incorrectly inflated final total of ₹120.
- **Root Cause Identified:** Function `calculate_discount` in `discounts.py:3` adds the percentage rather than subtracting: `price * (1 + percent / 100)`.

---

## 5. Security Architecture & Operational Limitations

1. **Subprocess Execution is Not a Sandbox:**
   - Tests executed through `run_safe_tests` run with the operating system permissions of the user hosting the MCP server.
   - Dual authorization is mandatory: `REPROMCP_ALLOW_TEST_EXECUTION=true` environment variable AND `confirm_execution=true` tool parameter.
   - Commands are fixed (`python -m pytest -q --disable-warnings --maxfail=3`); arbitrary shell commands or custom argument arrays are rejected.
2. **Workspace Boundaries:**
   - Repository access is strictly confined to `REPROMCP_WORKSPACE`.
   - Symlinks resolving outside the root directory and path traversal sequences (`..`) are rejected with errors.
3. **Execution Quotas & Resource Clamping:**
   - Test timeouts are clamped to a maximum of 60 seconds (default: 25s).
   - Standard output is bounded to the last 7,000 characters; standard error is bounded to 3,000 characters.
   - Files exceeding 1 MiB or identified as binary/secret patterns are excluded from search.
4. **Offline Capability:**
   - Repository inspection, code search, test execution, and triage report generation operate 100% offline.
   - Live AI diagnosis requires Google Gemini API access (`GEMINI_API_KEY`) and outbound HTTPS connectivity.

---

## 6. Audit Findings & Release Remediation

| Priority | Finding | Remediation Applied | Verification Status |
|:---:|:---|:---|:---:|
| **P1** | `inspect_repository` exposes absolute developer path | Removed `"absolute_path"` from both `inspect_workspace` and `search_workspace` in `repromcp/workspace.py`. Only relative POSIX paths and the workspace folder name are returned. Added tests in `test_scenario_e2e.py` asserting no absolute paths leak in MCP tool serialization. | **RESOLVED & VERIFIED** |
| **P1** | Gemma model ID not strictly allowlisted | Updated `get_configured_gemma_model()` in `repromcp/gemma.py` to strictly enforce permitted Gemma 4 models (`SUPPORTED_GEMMA_MODELS` allowlist or valid `gemma-4-*` family). Added explicit tests rejecting arbitrary third-party models (e.g. `other-provider-model`, `gpt-4o`) and Gemini-branded models. | **RESOLVED & VERIFIED** |
| **P2** | Generated cache artifacts present in archive | Purged all `__pycache__` and `.pytest_cache` directories in `demo_repo/`. Updated `.gitignore` with recursive `**/__pycache__/` and `**/.pytest_cache/` patterns to permanently prevent recommittal. | **RESOLVED & VERIFIED** |
| **P2** | Project naming inconsistency between archive and tool | Unified project branding across `README.md`, `TEST_REPORT.md`, and code as **IssueSensor-MCP: ReproMCP Visual** (`IssueSensor-MCP` repository delivering `ReproMCP Visual` engine). | **RESOLVED & VERIFIED** |
| **P2** | Dependency-limited environments fail test collection | Added `pytest.importorskip` guards for `mcp` and `google.genai` in integration test modules, allowing test suites to be cleanly evaluated on machines without all optional dependencies preinstalled. | **RESOLVED & VERIFIED** |
