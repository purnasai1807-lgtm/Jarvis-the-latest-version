from fastapi import APIRouter, HTTPException
import os
from pathlib import Path
import subprocess

router = APIRouter(prefix="/api/files", tags=["files"])
# We default the workspace root to the project directory for the IDE.
_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

@router.get("")
async def list_directory(path: str = ""):
    target = (_PROJECT_DIR / path).resolve()
    # Security: ensure target is within _PROJECT_DIR
    if not str(target).startswith(str(_PROJECT_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    items = []
    try:
        for entry in target.iterdir():
            # Skip hidden files by default or handle them. We'll skip .git
            if entry.name == ".git" or entry.name == "__pycache__":
                continue
            
            items.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "path": str(entry.relative_to(_PROJECT_DIR)).replace("\\", "/")
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # Sort: directories first, then alphabetical
    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return items

@router.get("/content")
async def get_file_content(path: str):
    target = (_PROJECT_DIR / path).resolve()
    if not str(target).startswith(str(_PROJECT_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
        
    try:
        content = target.read_text(encoding="utf-8")
        return {"content": content}
    except UnicodeDecodeError:
        return {"content": "Binary file cannot be displayed.", "binary": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/diff")
async def get_file_diff(path: str):
    target = (_PROJECT_DIR / path).resolve()
    try:
        diff_text = subprocess.check_output(
            ["git", "diff", "--", str(target)], 
            cwd=_PROJECT_DIR, text=True, stderr=subprocess.PIPE
        )
        return {"diff": diff_text}
    except Exception:
        return {"diff": ""}
