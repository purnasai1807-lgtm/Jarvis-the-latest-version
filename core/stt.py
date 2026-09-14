"""
 Speech-to-text — Faster-Whisper, locked to English and Telugu.

Accepts WAV bytes, returns (transcript, language_code).
When no language is forced, Whisper auto-detects the spoken language so Telugu
commands are not decoded as English.
"""

import io
from typing import Tuple

from loguru import logger

_ALLOWED_LANGS = {"en", "te"}


class SpeechToText:
    def __init__(self, config: dict) -> None:
        cfg = config.get("stt", {})
        self._model_size: str = cfg.get("model_size", "small")
        self._device: str = cfg.get("device", "cuda")
        self._compute: str = cfg.get("compute_type", "float16")
        self._beam_size: int = cfg.get("beam_size", 1)
        self._auto_detect: bool = cfg.get("auto_detect", True)
        self._initial_prompt: str = cfg.get(
            "initial_prompt",
            "Jarvis voice commands. Open WhatsApp, WhatsApp Desktop, "
            "calculator, Chrome, Spotify, Discord, and Edge.",
        )
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
            # The recorder already trims silence. Faster-Whisper's second VAD
            # pass can discard short commands such as "open calculator".
            vad_filter=False,
            condition_on_previous_text=False,
            temperature=0.0,
            initial_prompt=self._initial_prompt,
        )
        text = " ".join(seg.text for seg in segments).strip()
        return text, info

    def transcribe(self, wav_bytes: bytes, force_language: str | None = None) -> Tuple[str, str]:
        """Return (text, language_code). Empty string on failure.

        If force_language is omitted and auto_detect is enabled, Whisper detects
        English or Telugu from the audio.
        """
        self._ensure_model()
        try:
            requested_language = (
                force_language
                if force_language is not None or not self._auto_detect
                else None
            )
            text, info = self._run_transcribe(
                wav_bytes, language=requested_language
            )
            detected = info.language or "en"
            lang = force_language or (
                detected if detected in _ALLOWED_LANGS else "en"
            )
            logger.info(f"STT [{lang} {info.language_probability:.0%}]: {text}")
            return text, lang

        except Exception as exc:
            logger.error(f"Transcription failed: {exc}")
            return "", force_language or "en"
