"""
Disk hygiene — find old, large files in known dump dirs (Downloads, Temp).

Used in two ways:
  • Daily job (18:00) — scans + notifies via router if anything found
  • Brain tools — `find_old_files` and `delete_files` so the user can ask
    Jarvis "clean up Downloads" and review/confirm before deletion (the
    brain should always wrap deletes in propose_plan for safety).

Defaults: files >100 MB, untouched for >30 days. Configurable per call.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from loguru import logger


_DEFAULT_DIRS = [
    Path.home() / "Downloads",
    Path(os.environ.get("TEMP", "")) if os.environ.get("TEMP") else None,
]


def _scan_dir(directory: Path, days: int, min_mb: int) -> list[dict]:
    """Walk a single directory (one level deep) and find candidates."""
    if not directory or not directory.is_dir():
        return []
    cutoff = datetime.now().timestamp() - days * 86400
    min_bytes = min_mb * 1024 * 1024
    results: list[dict] = []
    try:
        for p in directory.iterdir():
            if not p.is_file():
                continue
            try:
                st = p.stat()
            except Exception:
                continue
            if st.st_size < min_bytes:
                continue
            if st.st_mtime > cutoff:
                continue
            results.append({
                "path": str(p),
                "size_mb": round(st.st_size / (1024 * 1024), 1),
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes"),
                "age_days": int((datetime.now().timestamp() - st.st_mtime) / 86400),
            })
    except Exception as exc:
        logger.debug(f"scan {directory} failed: {exc}")
    results.sort(key=lambda r: r["size_mb"], reverse=True)
    return results


# ── Brain tools ─────────────────────────────────────────────────
def find_old_files(directory: str = "", days: int = 30, min_mb: int = 100) -> str:
    """List old, large files in a directory (default: Downloads).
    Read-only — never deletes."""
    dirs: list[Path]
    if directory:
        dirs = [Path(directory).expanduser()]
    else:
        dirs = [d for d in _DEFAULT_DIRS if d]

    findings: list[dict] = []
    for d in dirs:
        findings.extend(_scan_dir(d, int(days), int(min_mb)))

    if not findings:
        return f"No files larger than {min_mb}MB and older than {days} days."

    findings.sort(key=lambda r: r["size_mb"], reverse=True)
    total = round(sum(f["size_mb"] for f in findings) / 1024, 2)
    lines = [f"Found {len(findings)} candidate(s) totalling {total} GB:"]
    for f in findings[:15]:
        lines.append(
            f"  • {f['size_mb']} MB · {f['age_days']}d old · {f['path']}"
        )
    if len(findings) > 15:
        lines.append(f"  …and {len(findings) - 15} more.")
    return "\n".join(lines)


def delete_files(paths: list[str]) -> str:
    """Delete a list of file paths. WARNING: irreversible. The brain MUST
    wrap calls to this in propose_plan() so the user explicitly confirms."""
    if not paths:
        return "No paths provided."
    deleted: list[str] = []
    failed: list[str] = []
    for raw in paths:
        try:
            p = Path(raw).expanduser()
            if not p.is_file():
                failed.append(f"{raw}: not a file")
                continue
            p.unlink()
            deleted.append(str(p))
        except Exception as exc:
            failed.append(f"{raw}: {exc}")

    parts = [f"Deleted {len(deleted)} file(s)"]
    if failed:
        parts.append(f"failed: {len(failed)} ({failed[0][:80]}…)")
    return ". ".join(parts)


# ── Daily job entry point ───────────────────────────────────────
def daily_cleanup_check() -> None:
    """Daily 18:00 sweep — notify the user if there's stuff worth cleaning."""
    from core import router
    findings: list[dict] = []
    for d in _DEFAULT_DIRS:
        if not d:
            continue
        findings.extend(_scan_dir(d, days=30, min_mb=100))
    if not findings:
        return
    total_gb = round(sum(f["size_mb"] for f in findings) / 1024, 2)
    body = (f"{len(findings)} large old files (~{total_gb} GB) in Downloads/Temp. "
            "Ask me to 'review old files' for the list.")
    router.notify(
        title="🧹 Disk hygiene",
        body=body,
        urgency="low",
        kind="cleanup",
    )


# ── Tool definitions ────────────────────────────────────────────
TOOLS = [
    {
        "name": "find_old_files",
        "description": (
            "List large old files in a directory (default: Downloads + Temp). "
            "Read-only. Use when the user asks 'what can I clean up', "
            "'review old files', 'show me large files in Downloads'. After "
            "the user picks specific files to delete, you MUST call "
            "propose_plan with delete_files steps so they confirm before "
            "anything is removed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": ("Directory to scan. Empty = Downloads + Temp."),
                },
                "days": {
                    "type": "integer",
                    "description": "Min file age in days. Default 30.",
                },
                "min_mb": {
                    "type": "integer",
                    "description": "Min file size in MB. Default 100.",
                },
            },
        },
    },
    {
        "name": "delete_files",
        "description": (
            "Delete a list of file paths IRREVERSIBLY. ALWAYS wrap calls to "
            "this tool in propose_plan() with summaries of each file — "
            "never call it directly without prior user confirmation through "
            "a plan. Returns counts of deleted/failed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute paths to files to delete.",
                },
            },
            "required": ["paths"],
        },
    },
]

HANDLERS = {
    "find_old_files": find_old_files,
    "delete_files": delete_files,
}
