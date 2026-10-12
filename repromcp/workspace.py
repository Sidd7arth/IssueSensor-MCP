"""Workspace exploration, secret filtering, repository inspection, and code search."""
from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Generator

IGNORE_DIRS: set[str] = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "bower_components", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "dist", "build", "coverage", ".next", ".nuxt",
    "target", "vendor", ".idea", ".vscode", "secrets", "credentials", ".ssh",
}

SECRET_FILENAMES: set[str] = {
    ".env", ".env.local", ".env.development", ".env.test",
    ".env.production", ".env.staging", "id_rsa", "id_ed25519",
    "id_ecdsa", "id_dsa", "credentials.json", "secrets.json",
    "service-account.json", "service_account.json", ".htpasswd", ".netrc",
}

SECRET_SUFFIXES: set[str] = {
    ".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db", ".bak",
}

BINARY_OR_NON_TEXT_SUFFIXES: set[str] = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico", ".tiff", ".svg",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".iso", ".o", ".obj",
    ".pyc", ".pyo", ".pyd", ".class",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm", ".flv",
}

ALLOWED_IMAGE_SUFFIXES: set[str] = {".png", ".jpg", ".jpeg", ".webp"}

MAX_FILE_BYTES: int = 512_000
MAX_IMAGE_BYTES: int = 8 * 1024 * 1024
MAX_FILES_DISCOVERED: int = 250
MAX_SEARCH_COLLECTION_CAP: int = 200
MAX_QUERY_LENGTH: int = 200
MAX_MATCHES: int = 30

MANIFEST_FILENAMES: set[str] = {
    "pyproject.toml", "requirements.txt", "package.json", "cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "readme.md", "pytest.ini",
    "setup.py", "setup.cfg", "gemfile", "composer.json", "dockerfile",
    "docker-compose.yml", "docker-compose.yaml",
}

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".sh": "Shell",
    ".bash": "Bash",
    ".ps1": "PowerShell",
    ".sql": "SQL",
    ".xml": "XML",
}

TEST_DIR_NAMES: set[str] = {"tests", "test", "__tests__", "spec", "specs"}


def resolve_workspace(workspace_path: str | Path | None = None) -> Path:
    """Resolve and validate the configured repository workspace.

    Args:
        workspace_path: Optional path to the workspace. If omitted,
            the REPROMCP_WORKSPACE environment variable is used.

    Returns:
        The resolved absolute Path.

    Raises:
        ValueError: If REPROMCP_WORKSPACE is unset, empty, does not exist,
            or is not a directory.
    """
    configured = str(workspace_path) if workspace_path is not None else os.environ.get("REPROMCP_WORKSPACE", "").strip()
    if not configured:
        raise ValueError(
            "REPROMCP_WORKSPACE is not set. Set it to the absolute path of the repository to inspect."
        )

    try:
        candidate = Path(configured).expanduser()
        root = candidate.resolve(strict=True)
    except OSError:
        raise ValueError(f"Configured workspace directory does not exist: {Path(configured).name}") from None

    if not root.is_dir():
        raise ValueError(f"Configured workspace is not a directory: {root.name}")
    return root


def is_safe_relative(path: Path, root: Path) -> bool:
    """Ensure path resolves strictly inside root, preventing directory traversal and symlink escapes."""
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
        resolved_path.relative_to(resolved_root)
        return True
    except (ValueError, OSError):
        return False


def is_dir_ignored(dirname: str) -> bool:
    """Determine whether a directory name should be pruned during traversal."""
    low = dirname.lower()
    return low in IGNORE_DIRS or low.startswith((".git", ".venv", "__pycache__"))


def is_ignored(path: Path, root: Path) -> bool:
    """Check if a file or directory should be ignored from search and inspection."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True

    # Path containment check (symlink pointing outside workspace)
    if not is_safe_relative(path, root):
        return True

    # Directory component check
    if any(is_dir_ignored(part) for part in rel.parts):
        return True

    name = path.name.lower()
    if name in SECRET_FILENAMES or name.startswith(".env.") or name.endswith(".env"):
        return True

    if path.suffix.lower() in SECRET_SUFFIXES:
        return True

    if name.endswith((".min.js", ".min.css", ".map")):
        return True

    return False


def relative(path: Path, root: Path) -> str:
    """Format path relative to root using POSIX forward slashes."""
    return path.relative_to(root).as_posix()


def iter_workspace_files(root: Path) -> Generator[Path, None, None]:
    """Iterate over eligible workspace files, pruning ignored directories during traversal.

    Unlike rglob, this prunes directories like .git and node_modules immediately,
    preventing deep disk walks through huge directory trees. Rejects symlinks escaping root.
    """
    for dirpath, dirnames, filenames in os.walk(str(root), topdown=True, followlinks=False):
        # In-place prune of ignored directory trees to avoid recursion
        dirnames[:] = [d for d in dirnames if not is_dir_ignored(d)]

        current_dir = Path(dirpath)
        for fname in filenames:
            file_path = current_dir / fname

            # Symlink escape defense
            if file_path.is_symlink():
                try:
                    symlink_target = file_path.resolve(strict=True)
                    if not is_safe_relative(symlink_target, root):
                        continue
                except (OSError, ValueError):
                    continue

            if is_ignored(file_path, root):
                continue

            try:
                if not file_path.is_file():
                    continue
                yield file_path
            except OSError:
                continue


def iter_text_files(root: Path) -> Generator[Path, None, None]:
    """Iterate over readable text files within workspace below MAX_FILE_BYTES."""
    for path in iter_workspace_files(root):
        if path.suffix.lower() in BINARY_OR_NON_TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            yield path
        except OSError:
            continue


def inspect_workspace(root: Path, max_files: int = MAX_FILES_DISCOVERED) -> dict[str, Any]:
    """Inspect repository structure, files, extensions, manifests, and test files/directories."""
    files: list[str] = []
    extensions: Counter[str] = Counter()
    detected_languages: set[str] = set()
    manifests: list[str] = []
    test_dirs: set[str] = set()
    test_files: list[str] = []
    total_scanned = 0

    for path in iter_workspace_files(root):
        total_scanned += 1
        rel = relative(path, root)
        if len(files) < max_files:
            files.append(rel)

        suffix = path.suffix.lower() or "[no extension]"
        extensions[suffix] += 1
        if suffix in EXTENSION_LANGUAGE_MAP:
            detected_languages.add(EXTENSION_LANGUAGE_MAP[suffix])

        if path.name.lower() in MANIFEST_FILENAMES:
            manifests.append(rel)

        # Check if file is a test file or inside a test directory
        rel_parts = Path(rel).parts
        for part in rel_parts[:-1]:
            if part.lower() in TEST_DIR_NAMES:
                test_dirs.add(part)

        file_name_lower = path.name.lower()
        if (
            file_name_lower.startswith("test_")
            or file_name_lower.endswith("_test.py")
            or ".test." in file_name_lower
            or ".spec." in file_name_lower
        ):
            test_files.append(rel)

    return {
        "workspace": root.name,
        "absolute_path": str(root),
        "files_listed": len(files),
        "file_list_truncated": total_scanned > max_files,
        "total_files_scanned": total_scanned,
        "files": files,
        "top_extensions": dict(extensions.most_common(12)),
        "detected_languages": sorted(detected_languages),
        "project_manifests_and_docs": sorted(set(manifests)),
        "test_directories": sorted(test_dirs),
        "discovered_test_files": sorted(test_files),
        "test_execution_enabled": os.environ.get("REPROMCP_ALLOW_TEST_EXECUTION", "false").lower() == "true",
    }


def search_workspace(root: Path, query: str, max_results: int = 12) -> list[dict[str, Any]]:
    """Search readable text files deterministically and return file, line, and snippet evidence.

    Supports exact phrase matching with high priority and multi-term ranked matching.
    Never searches ignored directories, secrets, or binary files.
    """
    clean_query = (query or "").strip()
    if len(clean_query) < 2:
        return []

    # Enforce safe upper bound on query length
    clean_query = clean_query[:MAX_QUERY_LENGTH]

    # Extract alphanumeric search tokens
    terms = [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z_0-9]{1,}", clean_query)]
    terms = list(dict.fromkeys(terms))[:12]
    exact_lower = clean_query.lower()

    if not terms and not exact_lower:
        return []

    limit = max(1, min(max_results, 50))
    results: list[dict[str, Any]] = []

    for path in iter_text_files(root):
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        lines = content.splitlines()
        for number, line in enumerate(lines, start=1):
            low = line.lower()
            matched_terms = [t for t in terms if t in low]
            exact_match = exact_lower in low

            if not matched_terms and not exact_match:
                continue

            # Exact match gets high bonus score; terms add individual points
            score = (100 if exact_match else 0) + len(matched_terms)

            # Build bounded 3-line context snippet (max 280 chars per line)
            start_ctx = max(0, number - 2)
            end_ctx = min(len(lines), number + 1)
            snippet_lines = [
                f"{idx + 1:4d} | {lines[idx][:280]}"
                for idx in range(start_ctx, end_ctx)
            ]
            snippet_text = "\n".join(snippet_lines)

            results.append({
                "file": relative(path, root),
                "absolute_path": str(path.resolve()),
                "line": number,
                "text": line.strip()[:280],
                "snippet": snippet_text,
                "matched_terms": matched_terms if matched_terms else [exact_lower],
                "score": score,
            })

            # Prevent excessive memory allocation on huge result sets
            if len(results) >= MAX_SEARCH_COLLECTION_CAP:
                break
        if len(results) >= MAX_SEARCH_COLLECTION_CAP:
            break

    # Sort deterministically: highest score first, then filename, then line number
    results.sort(key=lambda r: (-r["score"], r["file"], r["line"]))
    return results[:limit]


def ranked_matches(root: Path, query: str, limit: int = 12) -> list[dict[str, Any]]:
    """Backward-compatible search wrapper matching legacy signature."""
    return search_workspace(root, query, limit)


def resolve_screenshot(root: Path, supplied_path: str) -> Path:
    """Resolve an explicitly supplied screenshot, restricted to the configured workspace."""
    if not supplied_path or not supplied_path.strip():
        raise ValueError("screenshot_path cannot be empty.")
    candidate = Path(supplied_path.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Screenshot does not exist or cannot be accessed: {supplied_path}") from exc
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("Screenshot must be inside the configured REPROMCP_WORKSPACE.") from exc
    if not resolved.is_file():
        raise ValueError("screenshot_path must point to a file.")
    if resolved.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("Supported screenshot formats: PNG, JPG, JPEG, WEBP.")
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise ValueError("Screenshot cannot be accessed.") from exc
    if size <= 0:
        raise ValueError("Screenshot file is empty.")
    if size > MAX_IMAGE_BYTES:
        raise ValueError("Screenshot exceeds the 8 MiB limit.")
    try:
        with resolved.open("rb") as image_file:
            signature = image_file.read(12)
    except OSError as exc:
        raise ValueError("Screenshot cannot be accessed.") from exc
    suffix = resolved.suffix.lower()
    is_valid = (
        (suffix == ".png" and signature.startswith(b"\x89PNG\r\n\x1a\n"))
        or (suffix in {".jpg", ".jpeg"} and signature.startswith(b"\xff\xd8\xff"))
        or (suffix == ".webp" and signature.startswith(b"RIFF") and signature[8:12] == b"WEBP")
    )
    if not is_valid:
        raise ValueError("Screenshot extension does not match a supported image file signature.")
    return resolved
