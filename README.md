# IssueSensor-MCP: ReproMCP Visual

**Multimodal, evidence-first bug triage for AI coding agents.** **IssueSensor-MCP** implements **ReproMCP Visual** — an original Python MCP server combining visual issue screenshots and bug descriptions with deterministic repository inspection, exact code/line references, and real test execution. It asks Google's open-weight **Gemma 4** (`gemma-4-26b-a4b-it` or `gemma-4-31b-it`) to interpret visual symptoms alongside source code context, returning a structured diagnosis that strictly separates deterministic evidence from AI hypotheses.

> **Important Security & Privacy Disclosure:** Test execution runs repository code and **is NOT a sandbox**. Subprocesses run with the local user's operating-system permissions. Execution is disabled by default and requires both an explicit environment variable opt-in (`REPROMCP_ALLOW_TEST_EXECUTION=true`) and per-call confirmation (`confirm_execution=true`). Screenshots supplied to Gemma are uploaded to the Google Gemini API for multimodal inference; never supply images containing secrets, API keys, credentials, or confidential personal data.


## Why this exists

Issue reports often mix a vague description, a screenshot of unexpected behavior, source code, and failing tests. A coding agent may misread the symptom or invent a root cause. ReproMCP separates the workflow into inspectable steps: see the symptom, search the authorized codebase, gather actual test evidence, and ask a model to explain the evidence without inventing file references.

## Hackathon challenge fit

### DeepMind Google — Best Use of Gemma 4

- The default AI provider is the Gemini API running open-weight **`gemma-4-26b-a4b-it`** (with **`gemma-4-31b-it`** supported via configuration). Gemini-branded model substitutions are explicitly blocked to ensure genuine Gemma 4 evaluation.
- `analyze_issue` accepts issue text, observed test output, and an optional screenshot path. With an image, the tool uploads it to the Gemini Files API and provides the image plus the issue context to Gemma 4.
- The visual input matters: it gives the model symptom context that is not necessarily present in the code or stack trace.
- Official documentation: [Run Gemma with the Gemini API](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api).
- Official terms & licensing: [Gemma Terms of Use and Model Information](https://ai.google.dev/gemma/terms).


### DigitalOcean — Best Open-Source AI Project

- ReproMCP is a new, reusable tool with an original implementation, not a renamed copy of another server.
- Open-weight AI is central to the issue-analysis workflow rather than a decorative chat feature.
- This repository includes the MIT license and instructions to configure and run the server.
- This is an **MCP application/server**, not a claimed Agent Skill or model-harness fork. If you later submit it as an agent skill, first implement the [Agent Skills open standard](https://agentskills.io/); do not claim that compliance for this server as-is.
- MLH requirements and judging guidance: [Open Source AI challenge](https://www.mlh.com/opensource-ai).

## Architecture

```text
MCP-compatible coding client / MCP Inspector
                  |
                  v
           ReproMCP server
                  |
      +-----------+-------------+
      |                         |
      v                         v
Repository evidence       AI diagnosis
- configured root         - Gemma 4 via Gemini API (default)
- secret/build exclusions - screenshot + issue + evidence context
- literal search          - JSON-structured hypothesis
- exact file/line refs    - optional Ollama text-only fallback
- opt-in pytest runner
      |                         |
      +------------+------------+
                   v
      Evidence-backed triage report
```

The model does **not** execute commands or edit files. Repository search and test execution are deterministic server tools. Any diagnosis remains a hypothesis and must be verified.

## MCP tools

| Tool | Purpose | Side effects |
|---|---|---|
| `inspect_repository` | Lists relevant project files, extensions, manifests, AI provider and execution setting | Read-only |
| `search_code` | Finds exact file/line matches in readable repository files | Read-only |
| `run_safe_tests` | Runs `python -m pytest` in the configured workspace after opt-in and per-call confirmation | Executes project code; not sandboxed |
| `analyze_issue` | Combines issue text, snippets and optional real test output with Gemma 4; can include a screenshot | Sends prompt and optional image to configured AI provider |

### Screenshot rules

- Use `screenshot_path` on `analyze_issue` with a path relative to the configured repository, such as `evidence/discount-bug.png`.
- Supported formats: PNG, JPG/JPEG, and WEBP.
- The image must be inside `REPROMCP_WORKSPACE` and at most 8 MiB. Paths outside the configured workspace are rejected.
- The screenshot is sent to the Gemini API when `AI_PROVIDER=gemma`. Use only images you are comfortable submitting to that API.

## Requirements

- Python 3.10+
- An API key from [Google AI Studio](https://aistudio.google.com/apikey) for the primary Gemma 4 multimodal path
- A Gemini API model available to your key: default `gemma-4-26b-a4b-it`
- MCP Python SDK, `google-genai`, pytest
- Optional: Ollama and a supported local model for text-only fallback

Gemma is **open-weight**, which does not necessarily mean all parts of its licensing are OSI-approved open source. Read and link the current provider terms in your submission rather than making broader claims.

## Setup — Windows PowerShell

### 1. Create the environment and install dependencies

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If activation is blocked in the current PowerShell process:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 2. Configure Gemma 4 and the authorized repository

From the `repromcp-starter` project root:

```powershell
$env:REPROMCP_WORKSPACE = (Resolve-Path .\demo_repo).Path
$env:REPROMCP_ALLOW_TEST_EXECUTION = "false"
$env:AI_PROVIDER = "gemma"
$env:GEMINI_API_KEY = "PASTE_YOUR_AI_STUDIO_KEY_IN_THIS_TERMINAL"
$env:GEMMA_MODEL = "gemma-4-26b-a4b-it"
```

Do not put a real API key in the README, source code, MCP arguments, screenshots, or committed `.env` files. These environment variables are for the current terminal session. Restart the MCP server after changing them.

### 3. Run the project's own tests and compilation checks

```powershell
python -m compileall -q server.py repromcp
python -m pytest -q tests
python -m pytest -q demo_repo/tests
```

- `python -m pytest -q tests`: Runs the full 63-test hermetic test suite (100% offline, 0 API key required).
- `python -m pytest -q demo_repo/tests`: Executes the synthetic demo fixture, which is intentionally expected to fail strictly on the checkout discount assertion (`assert 120.0 == 80.0`).


### 4. Start MCP Inspector

```powershell
mcp dev server.py
```

Open the URL printed in the terminal. The Inspector should discover the four tools.

## 90-second demo walkthrough

This fixture deliberately shows a checkout UI reporting `₹120.00` for a ₹100 order after a 20% discount. The correct total is `₹80.00`.

1. Call `inspect_repository` and show the explicit workspace.
2. Call `search_code` with `calculate_discount` and show the literal file/line result.
3. Call `run_safe_tests` with `confirm_execution=false` while the environment opt-in is still `false`; show that execution is blocked.
4. After reviewing this trusted fixture, enable test execution in the terminal:

   ```powershell
   $env:REPROMCP_ALLOW_TEST_EXECUTION = "true"
   ```

   Call `run_safe_tests` with `confirm_execution=true`. The expected **demo** failure is `120.0` instead of `80.0`. This is intentional evidence, not a failing test of ReproMCP's helper suite.
5. Call `analyze_issue` with:
   - `issue_text`: `A 20% discount on a price of 100 returns 120 instead of 80. Find the likely cause and propose a regression test.`
   - `observed_test_output`: paste the actual output from `run_safe_tests`.
   - `screenshot_path`: `evidence/discount-bug.png`
6. Point out how Gemma receives image + text; compare its hypothesis against the actual repository snippets and captured test output. Do not imply that the screenshot proves the code-level cause.

Example inputs are shipped in `demo_repo/evidence/discount-bug.png` and `demo_repo/tests/test_discounts.py`.

## Optional offline/text-only fallback

If the Gemini API is unavailable, text-only diagnosis can use Ollama. This fallback **does not analyze screenshots** and will not demonstrate the Gemma category.

```powershell
ollama pull qwen2.5-coder:3b
$env:AI_PROVIDER = "ollama"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "qwen2.5-coder:3b"
```

Set `AI_PROVIDER=gemma` again before the multimodal demo. Screenshot analysis is rejected in Ollama mode.

## Security and limitations

- Only inspect repositories you are authorized to access.
- `pytest` execution is not sandboxed. The runner uses a fixed command, `shell=False`, a timeout, an environment opt-in, and per-call confirmation, but tests still run with the current user's permissions. Do not use it on untrusted repositories.
- Screenshot paths are constrained to the configured workspace, validated for supported image extension/signature, and limited to 8 MiB. The screenshot is still uploaded to the Gemini API for analysis.
- `.env`, key files, common credential files and generated directories are excluded from repository text search. Treat this as a best-effort filter, not a complete secret scanner.
- Search is lexical, not semantic retrieval or full AST analysis.
- The initial test runner supports Python/pytest only.
- The model may hallucinate. All file/line references must be checked against deterministic evidence.
- No automated patch is applied. A future version could prepare a patch diff for a user to review and approve.

## Release checklist

- [ ] Publish the project in a **public GitHub repository**.
- [ ] Confirm `LICENSE` is present at repository root (MIT in this starter).
- [ ] README names the actual model and links its terms, documents dependencies, and explains how to run the tool.
- [ ] The Gemma path works using a real API key and analyzes both screenshot and text.
- [ ] MCP Inspector discovers and executes the tools.
- [ ] The demo displays actual test output and labels AI conclusions as hypotheses.
- [ ] No real API key, `.env`, local virtual environment, or private repository data is committed.
- [ ] Submit the same project to both categories if the event submission form permits selecting multiple eligible challenges.

## License

MIT. See [`LICENSE`](LICENSE).
