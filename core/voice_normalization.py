"""Normalize common speech-recognition variants before command routing."""

from __future__ import annotations

import re


_PHRASE_REPLACEMENTS = (
    (re.compile(r"(?:వాట్సాప్|వాట్స్\s*యాప్)\s+(?:తెరవండి|తెరువు|ఓపెన్\s+చేయి)", re.IGNORECASE), "open WhatsApp"),
    (re.compile(r"(?:క్యాలిక్యులేటర్|కాలిక్యులేటర్)\s+(?:తెరవండి|తెరువు|ఓపెన్\s+చేయి)", re.IGNORECASE), "open calculator"),
    (re.compile(r"(?:క్రోమ్|గూగుల్\s+క్రోమ్)\s+(?:తెరవండి|తెరువు|ఓపెన్\s+చేయి)", re.IGNORECASE), "open Chrome"),
    (re.compile(r"స్పాటిఫై\s+(?:తెరవండి|తెరువు|ఓపెన్\s+చేయి)", re.IGNORECASE), "open Spotify"),
    (re.compile(r"వాల్యూమ్\s+(?:పెంచండి|పెంచు)", re.IGNORECASE), "volume up"),
    (re.compile(r"వాల్యూమ్\s+(?:తగ్గించండి|తగ్గించు)", re.IGNORECASE), "volume down"),
    (re.compile(r"(?:మ్యూట్|నిశ్శబ్దం)\s+(?:చేయి|చేయండి)?", re.IGNORECASE), "mute"),
    (re.compile(r"\bwhat(?:'|’)?\s*s?\s*app\b", re.IGNORECASE), "WhatsApp"),
    (re.compile(r"\bwhat\s*sap\b", re.IGNORECASE), "WhatsApp"),
    (re.compile(r"\bwats?app\b", re.IGNORECASE), "WhatsApp"),
    (re.compile(r"\bwhatsup\b", re.IGNORECASE), "WhatsApp"),
)


def normalize_voice_command(text: str) -> str:
    """Canonicalize high-confidence app-name variants without rewriting intent."""
    normalized = " ".join(text.strip().split())
    for pattern, replacement in _PHRASE_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    return normalized
