"""Safe test runner for executing pytest in an authorized repository.

Security Note:
    Subprocess execution is not a security sandbox. Tests run with the current
    user's operating-system permissions. Execution is disabled by default and
    requires both an explicit environment variable opt-in
    (REPROMCP_ALLOW_TEST_EXECUTION=true) and per-call confirmation
    (confirm_execution=True). Only execute tests on trusted code.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Approved fixed pytest command representation and limits
FIXED_COMMAND_STR: str = "python -m pytest -q --disable-warnings --maxfail=3"
DEFAULT_TIMEOUT_SECONDS: int = 25
MAX_TIMEOUT_SECONDS: int = 60
MAX_STDOUT_CHARS: int = 7000
MAX_STDERR_CHARS: int = 3000

SECURITY_NOTE: str = (
    "Subprocess execution is not a security sandbox. Tests run with the current "
    "user's operating-system permissions; execute only on trusted repositories."
)

# Sensitive environment prefixes or substrings to scrub before passing env to child process
SENSITIVE_ENV_KEYS: tuple[str, ...] = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "CREDENTIAL",
    "AUTH",
)


def sanitize_child_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a sanitized copy of the environment, removing API keys and secrets."""
    source = os.environ if base_env is None else base_env
    sanitized: dict[str, str] = {}
    for k, v in source.items():
        k_upper = k.upper()
        if any(sensitive in k_upper for sensitive in SENSITIVE_ENV_KEYS):
            continue
        sanitized[k] = v
    return sanitized


def truncate_output(text: str | bytes | None, max_chars: int) -> str:
    """Safely truncate text/bytes to the tail max_chars characters."""
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        return text[-max_chars:]
    return text


def run_safe_pytest(
    root: Path,
    target_path: str = "",
    confirm_execution: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute a fixed pytest command on an authorized target in the repository.

    Policy & Security:
        1. Test execution is disabled by default.
        2. Requires REPROMCP_ALLOW_TEST_EXECUTION=true in the environment.
        3. Requires explicit confirm_execution=True on the tool call.
        4. Rejects execution if either condition is missing or false.
        5. Does not accept arbitrary shell commands or command strings.
        6. Uses argument array with shell=False.
        7. Targets must reside inside the validated workspace; outside paths
           and directory traversal attempts are rejected.
        8. Timeout is clamped to at most 60 seconds; outputs are strictly bounded.
        9. Distinguishes genuine failure from timeout, missing pytest, startup error,
           and denied authorization.

    Args:
        root: The resolved workspace directory.
        target_path: Optional relative target path to a test file or directory.
        confirm_execution: Explicit confirmation flag from caller.
        timeout_seconds: Subprocess timeout limit in seconds (clamped to <=60s).

    Returns:
        Structured test result dictionary.
    """
    cmd_repr = FIXED_COMMAND_STR

    # 1. Environment-level opt-in check (default: false)
    allow_env = os.environ.get("REPROMCP_ALLOW_TEST_EXECUTION", "false").lower().strip()
    if allow_env != "true":
        return {
            "status": "blocked",
            "command": cmd_repr,
            "exit_code": None,
            "passed": False,
            "timed_out": False,
            "reason": (
                "Test execution is disabled by default. Set REPROMCP_ALLOW_TEST_EXECUTION=true "
                "only for a repository you trust, then explicitly confirm the tool call."
            ),
            "note": SECURITY_NOTE,
        }

    # 2. Per-call explicit confirmation check
    if confirm_execution is not True:
        return {
            "status": "confirmation_required",
            "command": cmd_repr,
            "exit_code": None,
            "passed": False,
            "timed_out": False,
            "reason": (
                "Call again with confirm_execution=true after reviewing the repository and "
                "understanding that its tests execute code."
            ),
            "note": SECURITY_NOTE,
        }

    # 3. Workspace validation immediately before execution
    try:
        resolved_root = Path(root).resolve()
    except (TypeError, ValueError, OSError) as exc:
        return {
            "status": "error",
            "command": cmd_repr,
            "exit_code": None,
            "passed": False,
            "timed_out": False,
            "error": f"Invalid workspace path: {exc}",
            "note": SECURITY_NOTE,
        }

    if not resolved_root.exists() or not resolved_root.is_dir():
        return {
            "status": "error",
            "command": cmd_repr,
            "exit_code": None,
            "passed": False,
            "timed_out": False,
            "error": f"Workspace directory does not exist or is not a directory: {resolved_root}",
            "note": SECURITY_NOTE,
        }

    # 4. Target path validation inside workspace
    cmd_args: list[str] = []
    clean_target = (target_path or "").strip()
    if clean_target and clean_target not in {".", "./"}:
        # Reject obvious directory traversal patterns
        normalized = clean_target.replace("\\", "/")
        if normalized.startswith("..") or "/../" in normalized or normalized.endswith("/.."):
            return {
                "status": "error",
                "command": cmd_repr,
                "exit_code": None,
                "passed": False,
                "timed_out": False,
                "error": "Target path cannot escape or target workspace parent.",
                "note": SECURITY_NOTE,
            }

        candidate = (resolved_root / clean_target).resolve()
        try:
            rel_target = candidate.relative_to(resolved_root).as_posix()
        except ValueError:
            return {
                "status": "error",
                "command": cmd_repr,
                "exit_code": None,
                "passed": False,
                "timed_out": False,
                "error": "Target path must be inside the configured workspace.",
                "note": SECURITY_NOTE,
            }

        if not candidate.exists():
            return {
                "status": "error",
                "command": cmd_repr,
                "exit_code": None,
                "passed": False,
                "timed_out": False,
                "error": f"Target path does not exist: {clean_target}",
                "note": SECURITY_NOTE,
            }

        # Validate file type (must be Python file or directory)
        if candidate.is_file() and candidate.suffix.lower() != ".py":
            return {
                "status": "error",
                "command": cmd_repr,
                "exit_code": None,
                "passed": False,
                "timed_out": False,
                "error": f"Target file must be a Python (.py) file: {candidate.name}",
                "note": SECURITY_NOTE,
            }

        cmd_args = [rel_target]
        cmd_repr = f"{FIXED_COMMAND_STR} {rel_target}"

    # 5. Clamp timeout to safe range (max 60 seconds)
    safe_timeout = max(1, min(timeout_seconds, MAX_TIMEOUT_SECONDS))

    # 6. Prepare sanitized child environment with workspace on PYTHONPATH
    clean_env = sanitize_child_env()
    clean_env["PYTHONPATH"] = str(resolved_root)

    # 7. Execute process using argument array and shell=False
    fixed_cmd = [sys.executable, "-m", "pytest", "-q", "--disable-warnings", "--maxfail=3"] + cmd_args
    start_time = time.monotonic()
    try:
        completed = subprocess.run(
            fixed_cmd,
            cwd=str(resolved_root),
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=safe_timeout,
            shell=False,
            check=False,
        )
        duration = round(time.monotonic() - start_time, 3)
        stdout_bounded = truncate_output(completed.stdout, MAX_STDOUT_CHARS)
        stderr_bounded = truncate_output(completed.stderr, MAX_STDERR_CHARS)

        # Distinguish missing pytest installation from genuine test failure
        output_combined = (completed.stdout or "") + (completed.stderr or "")
        if "No module named pytest" in output_combined:
            return {
                "status": "missing_pytest",
                "command": cmd_repr,
                "exit_code": completed.returncode,
                "passed": False,
                "timed_out": False,
                "duration_seconds": duration,
                "stdout": stdout_bounded,
                "stderr": stderr_bounded,
                "error": "pytest is not installed in the target Python environment.",
                "note": SECURITY_NOTE,
            }

        return {
            "status": "completed",
            "command": cmd_repr,
            "exit_code": completed.returncode,
            "passed": completed.returncode == 0,
            "timed_out": False,
            "duration_seconds": duration,
            "stdout": stdout_bounded,
            "stderr": stderr_bounded,
            "note": (
                f"Observed process output; not an AI-generated summary. {SECURITY_NOTE}"
            ),
        }
    except subprocess.TimeoutExpired as exc:
        duration = round(time.monotonic() - start_time, 3)
        return {
            "status": "timeout",
            "command": cmd_repr,
            "exit_code": None,
            "passed": False,
            "timed_out": True,
            "timeout_seconds": safe_timeout,
            "duration_seconds": duration,
            "stdout": truncate_output(exc.stdout, MAX_STDOUT_CHARS),
            "stderr": truncate_output(exc.stderr, MAX_STDERR_CHARS),
            "reason": f"Test execution timed out after {safe_timeout} seconds.",
            "note": SECURITY_NOTE,
        }
    except OSError as exc:
        duration = round(time.monotonic() - start_time, 3)
        return {
            "status": "startup_error",
            "command": cmd_repr,
            "exit_code": None,
            "passed": False,
            "timed_out": False,
            "duration_seconds": duration,
            "error": f"Could not start pytest: {exc}",
            "note": SECURITY_NOTE,
        }
