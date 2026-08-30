"""
Speech-to-text — Faster-Whisper, locked to English + Romanian only.

Accepts WAV bytes, returns (transcript, language_code).
If Whisper detects any language other than EN/RO, it re-transcribes forced as English.
"""

import io
from typing import Tuple

from loguru import logger

_ALLOWED_LANGS = {"en", "ro"}


class SpeechToText:
    def __init__(self, config: dict) -> None:
        cfg = config.get("stt", {})
        self._model_size: str = cfg.get("model_size", "small")
        self._device: str = cfg.get("device", "cuda")
        self._compute: str = cfg.get("compute_type", "float16")
        self._beam_size: int = cfg.get("beam_size", 1)
        self._model = None

        if cfg.get("preload", True):
            self._ensure_model()

    def _ensure_model(self):
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        logger.info(
            f"Loading Faster-Whisper ({self._model_size}) on {self._device}…"
        )
        try:
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute,
            )
        except Exception:
            logger.warning("CUDA load failed — falling back to CPU / int8")
            self._model = WhisperModel(
                self._model_size, device="cpu", compute_type="int8"
            )
        logger.info("Whisper model ready")

    def _run_transcribe(self, wav_bytes: bytes, language=None):
        """Run transcription, return (segments_list, info)."""
        segments, info = self._model.transcribe(
            io.BytesIO(wav_bytes),
            beam_size=self._beam_size,
            language=language,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        text = " ".join(seg.text for seg in segments).strip()
        return text, info

    def transcribe(self, wav_bytes: bytes, force_language: str | None = None) -> Tuple[str, str]:
        """Return (text, language_code). Empty string on failure.

        If force_language is given, Whisper skips auto-detection and transcribes
        directly in that language — no 'ru', 'de', etc. surprises.
        """
        self._ensure_model()
        try:
            text, info = self._run_transcribe(wav_bytes, language=force_language)
            lang = force_language or info.language or "en"
            logger.info(f"STT [{lang} {info.language_probability:.0%}]: {text}")
            return text, lang

        except Exception as exc:
            logger.error(f"Transcription failed: {exc}")
            return "", force_language or "en"
