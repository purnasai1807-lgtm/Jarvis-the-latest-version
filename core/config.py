"""
Configuration loader — reads config.yaml once, shares it everywhere.
"""

from pathlib import Path
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_cache: dict | None = None


def load_config(path: Path | None = None) -> dict:
    global _cache
    if _cache is not None and path is None:
        return _cache
    cfg_path = path or (_ROOT / "config.yaml")
    with open(cfg_path, encoding="utf-8") as f:
        _cache = yaml.safe_load(f)
    return _cache
