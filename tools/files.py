"""File management tools: find and move/rename files."""

import os
import shutil
import subprocess

from loguru import logger


def find_file(query: str, directory: str = None) -> str:
    """Search for files matching a name pattern."""
    search_dir = directory or os.path.expanduser("~")

    if not os.path.isdir(search_dir):
        return f"Directory not found: {search_dir}"

    # Use PowerShell Get-ChildItem for indexed search (fast on Windows)
    ps_cmd = (
        f'Get-ChildItem -Path "{search_dir}" -Recurse -Filter "*{query}*" '
        f"-Depth 5 -ErrorAction SilentlyContinue "
        f"| Select-Object -First 15 -ExpandProperty FullName"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
        )
        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        if files:
            logger.info(f"find_file({query}): {len(files)} results")
            return "Found files:\n" + "\n".join(files)
    except subprocess.TimeoutExpired:
        logger.warning(f"find_file({query}) timed out")
    except Exception as exc:
        logger.error(f"find_file search failed: {exc}")

    return f"No files matching '{query}' found in {search_dir}."


def move_file(source: str, destination: str) -> str:
    """Move or rename a file/folder."""
    if not os.path.exists(source):
        return f"Source not found: {source}"

    # Create destination directory if needed
    dest_dir = os.path.dirname(destination)
    if dest_dir and not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)

    try:
        shutil.move(source, destination)
        logger.info(f"Moved: {source} → {destination}")
        return f"Moved {os.path.basename(source)} to {destination}."
    except Exception as exc:
        logger.error(f"move_file failed: {exc}")
        return f"Failed to move file: {exc}"


# ── Tool definitions ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "find_file",
        "description": "Search for files by name. Searches recursively up to 5 levels deep. Returns up to 15 matching file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "File name or pattern to search for (e.g. 'report', '.pdf', 'budget')",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search in. Defaults to user home folder.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "move_file",
        "description": "Move or rename a file or folder. Creates destination directories if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Full path of the source file/folder",
                },
                "destination": {
                    "type": "string",
                    "description": "Full path of the destination",
                },
            },
            "required": ["source", "destination"],
        },
    },
]

HANDLERS = {
    "find_file": find_file,
    "move_file": move_file,
}
