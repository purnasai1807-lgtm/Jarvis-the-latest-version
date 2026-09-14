"""
Active language state — shared across all modules.

Default: English. Switch with set("en") or set("te").
"""

_lang: str = "en"


def get() -> str:
    return _lang


def set(lang: str) -> None:
    global _lang
    if lang not in ("en", "te"):
        raise ValueError(f"Unsupported language: {lang}")
    _lang = lang
