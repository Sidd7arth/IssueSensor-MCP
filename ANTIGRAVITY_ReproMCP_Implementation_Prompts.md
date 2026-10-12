# ReproMCP Visual — Antigravity implementation prompt pack

**Use these prompts sequentially in the existing ReproMCP project workspace. Do not paste all prompts at once.**

Deadline-aware plan for October 12: at 13:02 IST, approximately 1 hour 58 minutes remain until 15:00. Keep the project focused on one working screenshot-to-evidence-to-diagnosis MCP workflow.

## Target product

ReproMCP Visual is an evidence-first MCP server for debugging reported software bugs. The user provides an issue description and a screenshot; the server inspects a configured repository, finds real code references, optionally runs an explicitly approved trusted test target, and asks Gemma 4 to generate a structured diagnosis. Tool-generated evidence must remain separate from AI hypotheses.

## Chosen stack (do not needlessly change it)

- Python 3.11+
- Official MCP Python SDK 1.x API: `mcp[cli]>=1.12,<2` and `FastMCP` from `mcp.server.fastmcp`. Preserve `<2` because the current code uses the v1 API; do not upgrade to SDK v2 during this deadline.
- Google Gen AI Python SDK: `google-genai`
- Pillow for image handling/validation
- pytest for deterministic automated tests
- Gemini API-hosted Gemma 4 model. Default `GEMMA_MODEL=gemma-4-26b-a4b-it`. Also permit `gemma-4-31b-it` via environment configuration for a controlled comparison.
- No web dashboard, database, vector database, Docker requirement, user authentication or autonomous code editing in this sprint. MCP Inspector is enough for the demo.

Official model documentation: https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api
Official MCP Python SDK v1 docs: https://py.sdk.modelcontextprotocol.io/v1/

## Team split (if three people are working concurrently)

- Person A — MCP/repository: `server.py`, `repromcp/workspace.py`, `repromcp/runner.py`
- Person B — AI: `repromcp/gemma.py`, `repromcp/prompts.py` if needed, model smoke tests
- Person C — integration/release: `repromcp/report.py`, `tests/`, `demo_repo/`, `README.md`, `LICENSE`, `.gitignore`, GitHub submission

Avoid editing the same file concurrently. Agree on the report schema before merging work.

---

# PROMPT 0 — Audit the existing demo before changing anything (10 minutes)

You are operating inside my EXISTING ReproMCP Visual project in Antigravity. Do not assume the repo structure matches a template and do not replace the project wholesale.

First inspect the actual workspace, file tree, git status/diff, README, dependency files, MCP server, Gemma integration, demo assets and tests. Identify which features already work, which are stubs, and which are broken. Run the current test suite and Python compilation. If dependencies are missing, report that and install only from the existing requirements/lock file when allowed; do not silently change dependency major versions.

Stack constraints: keep Python 3.11+, the existing `mcp[cli]` v1 API with `mcp>=1.12,<2`, `google-genai`, Pillow and pytest. Do not upgrade `mcp` to v2 because the existing FastMCP imports are v1-style. Gemma 4 model IDs must be configurable through `GEMMA_MODEL`; default to `gemma-4-26b-a4b-it`, with `gemma-4-31b-it` available for comparison.

Do not make code changes during this audit. Report:
1. Current architecture and entry command.
2. Exact baseline test command and output.
3. Any test that is intentionally expected to fail as part of the demo, distinguished from a broken project test.
4. Top five blockers ordered by whether they threaten a working demo.
5. The exact files you propose to change per implementation chunk.

Do not say a test passed unless you actually ran it and observed the result. Stop after the audit.

# PROMPT 1 — Stabilize repository evidence/search (20 minutes)

Implement or repair the repository evidence engine in the current project. First read the existing code; preserve working functions and do not rewrite unrelated modules.

Requirements:
- Use `REPROMCP_WORKSPACE` as the only configured repository boundary.
- `inspect_repository` should report language/file counts and discovered tests, using paths relative to the configured root.
- `search_code(query, max_results)` should return only real matches with relative path, exact 1-based line number and a bounded snippet.
- Exclude `.git`, virtual environments, `node_modules`, generated/build directories, binary files, oversized files, `.env*`, private keys, credentials files and service-account JSON.
- Resolve paths and reject symlink/path traversal that escapes the workspace. Do not follow symlinks outside the root.
- Apply safe bounds to query length, max results, read sizes and returned output.
- Return structured errors, not stack traces or absolute home-directory paths.
- Do not add a database, embeddings or an unnecessary frontend.

Tests to add/run before completion:
1. Exact search returns correct file and line number.
2. Excluded secret files are not searchable and their content is never returned.
3. Outside-workspace paths and symlinks are rejected/skipped.
4. Missing workspace and empty/no-match query return understandable results.
5. Large files/output are bounded.

Run `python -m pytest -q tests` and `python -m compileall -q server.py repromcp`. Fix failures before moving on. Provide changed files, real test output and known limitations. Do not claim security is perfect.

# PROMPT 2 — Harden explicit test execution (15–20 minutes)

Repair the existing `run_safe_tests` tool without turning it into a general-purpose shell tool.

Security/product requirements:
- Only run Python `pytest` on an explicitly supplied target inside the configured trusted workspace.
- Require BOTH `REPROMCP_ALLOW_TEST_EXECUTION=true` in the server environment and `confirm_execution=true` on the tool call.
- Use argument arrays with `shell=False`; never accept a shell command string from the model/user.
- Bound timeout (maximum 60 seconds), output bytes/chars and target path; capture stdout, stderr, exit code, elapsed time and timeout status.
- Reject paths outside the workspace, missing paths, wrong file types and obvious attempt to target a workspace parent.
- Never claim a test ran when it was blocked, timed out before completion, or failed to start.
- Clearly return the warning that subprocess execution is NOT a sandbox and must only be used on trusted code. Do not describe a timeout/allowlist as sandboxing.

Tests:
- disabled environment blocks execution
- missing confirmation blocks execution
- traversal/outside path is rejected
- a known passing test produces exit code 0 and output
- a known failing test produces non-zero exit and captured assertion text
- timeout reports `timed_out=true`
- excessive timeout is clamped to <=60 seconds
- no arbitrary shell interpretation is possible

Run the project test suite after changes. Keep the deliberately buggy demo test in `demo_repo/` separate from normal unit tests so main tests can pass while the demo intentionally demonstrates a failure.

# PROMPT 3 — Make Gemma 4 multimodal analysis real and testable (25–30 minutes)

Audit and complete `repromcp/gemma.py`. Use Google's official `google-genai` Python SDK to call Gemma through the Gemini API. Use a configurable `GEMMA_MODEL`; default to `gemma-4-26b-a4b-it`. Permit `gemma-4-31b-it` through configuration, not a hardcoded code change. Never silently substitute a Gemini-branded model for Gemma.

Input: issue text, a screenshot validated as inside the workspace, bounded repository search evidence, and test-run evidence.

Implementation requirements:
- Pass both the image and text to the Gemma request using a documented SDK-supported image upload/input approach.
- Read `GEMINI_API_KEY` from the environment only. Never log, return or write the key to files.
- Validate screenshot suffix, signature, size (max 8 MiB), file existence and workspace boundaries. Handle invalid image and empty issue text without an API call.
- Prompt the model to return one JSON object with: `visual_observations`, `likely_root_cause`, `confidence` (`low|medium|high`), `supporting_evidence`, `reproduction_steps`, `suggested_regression_test`, `unknowns_and_limitations`.
- Tell the model never to fabricate file names, line numbers, test results or observations. A diagnosis is a hypothesis, not verification.
- Parse JSON robustly; handle markdown fences/malformed output without crashing. Validate required fields/types. If output cannot be parsed/validated, return `invalid_model_output` without pretending success.
- Distinguish `not_configured`, `dependency_missing`, API/network error, invalid image, and successful response.
- Do not include a stack trace or key in the tool response. Bound errors and output size.
- Ensure screenshots sent to the hosted API are demo/public data; document that the image leaves the local machine and is processed by Google's service.

Tests (the default test suite must NOT require a real API key or network):
- missing key produces `not_configured`
- invalid/out-of-workspace/oversized/mismatched image is rejected
- empty issue is rejected
- model JSON parser handles valid JSON, fenced JSON, malformed JSON and wrong types
- mock the SDK response to verify both screenshot and evidence are passed into the request
- API exception returns `api_error` without exposing the API key
- real network call is a separate manual smoke test, not part of unit tests

Add a small optional live smoke-test command or documented script that runs only when `GEMINI_API_KEY` is present. Use the exact official model ID. Test default `gemma-4-26b-a4b-it` first; only compare `gemma-4-31b-it` if time and API quota allow. Record observed latency, parse success and evidence adherence—do not claim one model is “better” without test results.

Run `python -m pytest -q tests` and compile checks. Do not continue until tests pass or a genuinely external blocker is clearly documented.

# PROMPT 4 — Integrate MCP workflow + useful report (15 minutes)

Integrate the tools without introducing duplicate logic. The MCP server should expose:
- `inspect_repository`
- `search_code`
- `run_safe_tests`
- `analyze_issue`

`analyze_issue` should:
1. Validate issue/screenshot/query inputs.
2. Collect code evidence using the deterministic search tool.
3. Use supplied test evidence or execute only when BOTH execution gates are satisfied and the requested target has been reviewed.
4. Send screenshot + issue + bounded tool evidence to Gemma.
5. Return a structured response with `verified_evidence` separate from `ai_analysis` and a rendered Markdown report.
6. Preserve evidence even if the model API is unavailable; return a useful explicit status and never invent an AI answer.

Report format should include issue summary, screenshot observations, exact source refs, test execution status/output, likely cause, confidence, reproduction steps, regression-test suggestion, unknowns, model ID, and a clear “AI hypothesis—not verified fact” notice.

Tests:
- MCP imports/initializes without making a live API call
- analyze_issue gives correct error when screenshot invalid
- analyze_issue can return evidence when AI is not configured
- report rendering works for success, error and no-analysis states
- model-generated paths/line numbers are not treated as verified repository evidence

Run all local tests and compile checks. If `mcp dev server.py` is available, start Inspector and verify the four tools are discoverable. If it is unavailable, report the exact missing dependency/command; do not claim the Inspector check passed.

# PROMPT 5 — End-to-end scenario and meaningful quality checks (10–15 minutes)

Use the existing synthetic checkout/discount demo or create the smallest needed fixture. Do not invent a polished UI.

Scenario: the screenshot and issue say that a price of 100 with a 20% discount shows 120 instead of 80. Repository code has an intentional incorrect formula; one demo test should fail with the expected assertion, while another demo test may pass.

Verify manually and with tests:
1. Repository inspection finds the demo files.
2. Code search returns the exact relevant function and 1-based line.
3. With execution disabled, the runner refuses to execute.
4. With the trusted demo target reviewed, opt-in plus explicit confirmation executes the demo test and returns a real failing assertion (120 vs 80).
5. Gemma receives the screenshot, issue text, code evidence and actual test result.
6. Structured report distinguishes visible screenshot facts, observed tool results and AI hypotheses.
7. With no API key, the system reports the missing configuration honestly while preserving evidence.
8. No secrets or absolute developer paths appear in logs/reports.

Run:
`python -m pytest -q tests`
`python -m compileall -q server.py repromcp`
`python -m pytest -q demo_repo/tests` (this should fail only on the known intentional discount assertion; confirm it does not fail due to imports/setup).

Create a short `TEST_REPORT.md` with actual commands, results and any limitations. Never change the normal test suite to be green by hiding real failures.

# PROMPT 6 — Release audit, GitHub readiness and submission freeze (10 minutes)

Do not add features. Audit the actual repo for release readiness:
- Root `LICENSE` exists and is appropriate for original code (MIT is fine if project owner intends it).
- README has product explanation, architecture, exact setup/launch instructions, MCP tool descriptions, demo sequence, environment variables, model name and link to official model terms, dependency list, image/API data disclosure, known limitations and test commands.
- `.env`, API keys, screenshots containing secrets, `.venv`, caches, `__pycache__`, local DBs and build folders are ignored/not staged.
- `requirements.txt`/`pyproject.toml` pin compatible dependencies. Keep `mcp[cli]>=1.12,<2` for FastMCP v1 unless the migration was explicitly implemented and tested end to end. Do not casually upgrade `mcp` to v2.
- Run all tests and compile checks; inspect `git diff --check`, `git status` and staged file list.
- Ensure demo test fails for the intended assertion only.
- If a public remote is already set, inspect it and don't overwrite unrelated code. Do not create/push a repository or publish secrets without my explicit approval.
- Do not mark the product “fully secure”; document that pytest subprocess execution is not a sandbox.
- Do not claim a real Gemma test passed unless one was actually executed with valid credentials.

Return a concise release report with actual evidence: commands run, pass/fail counts, live API result (or not run), MCP Inspector result (or not run), files changed and remaining blockers. Stop after this report.

---

## Execution rules for Antigravity

1. Run Prompt 0 first. Review the audit before applying changes.
2. Run one chunk at a time. Do not queue all prompts at once.
3. After each chunk, run the specified tests and fix failures before continuing.
4. Edit existing files where appropriate; do not make a parallel “v2” implementation or replace working code just to match a prompt.
5. Do not claim success without actual command output. Do not hide failed tests.
6. If a test cannot run due to missing dependencies, explain the blocker and install only the project dependencies if network access is available.
7. No dashboard, auto-fix execution, multi-agent framework, database, vector database or deployment during the deadline.
8. Keep the final 10 minutes for GitHub and OrganizerHQ submission rather than feature coding.
