from fastapi import APIRouter, HTTPException
import yaml
from pathlib import Path
import subprocess
from datetime import datetime

router = APIRouter(prefix="/api/projects", tags=["projects"])
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

def load_projects():
    path = _DATA_DIR / "projects.yaml"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if data else []
    except Exception:
        return []

def save_projects(data):
    path = _DATA_DIR / "projects.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f)

@router.get("")
async def get_projects():
    projects = load_projects()
    if not projects:
        # Generate some mock data if empty initially
        mock = [{
            "id": "jarvis-v2",
            "name": "J.A.R.V.I.S Dashboard",
            "path": "c:/Projects/jarvis",
            "description": "Building the V2 Iron Man themed dashboard.",
            "status": "In Progress",
            "todos": [
                {"text": "Setup FastAPI routers", "done": True},
                {"text": "Create UI Frontend", "done": False}
            ]
        }]
        save_projects(mock)
        return mock
    return projects

@router.get("/{project_id}/git")
async def get_git_log(project_id: str):
    projects = load_projects()
    proj = next((p for p in projects if p.get("id") == project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    
    path = Path(proj.get("path", ""))
    if not path.is_dir():
        return {"commits": [], "branch": "unknown", "error": "Invalid directory path."}
    
    # get Branch
    try:
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=path, text=True, stderr=subprocess.PIPE).strip()
    except subprocess.CalledProcessError:
        return {"commits": [], "branch": "unknown", "error": "Not a git repository."}
    except Exception:
        return {"commits": [], "branch": "unknown", "error": "Git not installed or accessible."}
    
    # get Commits
    try:
        # format: hash|message|author|timestamp
        log = subprocess.check_output(
            ["git", "log", "-n", "15", "--pretty=format:%h|%s|%an|%ar"],
            cwd=path, text=True, stderr=subprocess.PIPE
        )
        commits = []
        for line in log.split("\n"):
            if not line.strip(): continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({"hash": parts[0], "message": parts[1], "author": parts[2], "time": parts[3]})
        return {"commits": commits, "branch": branch}
    except subprocess.CalledProcessError:
        return {"commits": [], "branch": branch, "error": "Failed to retrieve logs."}

@router.post("/{project_id}/todos")
async def add_todo(project_id: str, data: dict):
    projects = load_projects()
    proj = next((p for p in projects if p.get("id") == project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if "todos" not in proj:
        proj["todos"] = []
    proj["todos"].append({"text": data.get("text", "New task"), "done": False})
    save_projects(projects)
    return proj["todos"]

@router.put("/{project_id}/todos/{index}")
async def toggle_todo(project_id: str, index: int, data: dict):
    projects = load_projects()
    proj = next((p for p in projects if p.get("id") == project_id), None)
    if not proj or "todos" not in proj or index >= len(proj["todos"]):
        raise HTTPException(status_code=404, detail="Todo not found")
    
    proj["todos"][index]["done"] = data.get("done", False)
    save_projects(projects)
    return proj["todos"]

@router.delete("/{project_id}/todos/{index}")
async def delete_todo(project_id: str, index: int):
    projects = load_projects()
    proj = next((p for p in projects if p.get("id") == project_id), None)
    if not proj or "todos" not in proj or index >= len(proj["todos"]):
        raise HTTPException(status_code=404, detail="Todo not found")
    
    proj["todos"].pop(index)
    save_projects(projects)
    return proj["todos"]
