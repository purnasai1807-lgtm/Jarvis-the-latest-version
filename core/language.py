"""
Active language state — shared across all modules.

Default: Romanian. Switch with set("en") / set("ro").
"""

_lang: str = "ro"


def get() -> str:
    return _lang


def set(lang: str) -> None:
    global _lang
    if lang not in ("ro", "en"):
        raise ValueError(f"Unsupported language: {lang}")
    _lang = lang
