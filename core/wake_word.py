"""
Wake-word detection (OpenWakeWord) + post-wake audio capture.

Flow:
  1. OpenWakeWord listens for "Hey Jarvis" on a sounddevice stream.
  2. On detection a short chime plays, then we record until silence.
  3. The recorded WAV bytes are handed to the callback provided by main.py.

No API key required — fully open-source, runs locally.
Uses sounddevice instead of PyAudio (ships its own PortAudio binary on Windows).
"""

import io
import math
import struct
import threading
import time
import wave
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
from loguru import logger

# OpenWakeWord expects 16-bit 16 kHz mono, in 1280-sample chunks (80 ms)
_OWW_CHUNK = 1280


class WakeWordDetector:
    """Blocks the mic while the assistant is thinking / speaking."""

    def __init__(self, config: dict, on_speech: Callable[[bytes], None],
                 on_empty: Callable[[], None] | None = None,
                 on_wake: Callable[[], None] | None = None,
                 on_partial: Callable[[bytes], None] | None = None) -> None:
        self._cfg = config
        self._on_speech = on_speech
        self._on_partial = on_partial   # streaming STT callback

        ww_cfg = config.get("wake_word", {})
        self._model_name: str = ww_cfg.get("model", "hey_jarvis")
        self._threshold: float = ww_cfg.get("threshold", 0.5)

        audio_cfg = config.get("audio", {})
        self._input_device = audio_cfg.get("input_device", None)  # None = system default
        self._sample_rate: int = audio_cfg.get("sample_rate", 16000)
        self._silence_thresh: int = audio_cfg.get("silence_threshold", 500)
        self._silence_dur: float = audio_cfg.get("silence_duration", 1.5)
        self._max_rec: float = audio_cfg.get("max_record_seconds", 30)

        self._on_empty = on_empty
        self._on_wake = on_wake
        self._oww_model = None
        self._stream: sd.RawInputStream | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._busy = False  # True while processing a request
        self._paused = False  # True when user pauses via HUD

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self) -> None:
        # Download models on first run (cached afterwards)
        import openwakeword
        openwakeword.utils.download_models()

        from openwakeword.model import Model
        self._oww_model = Model(
            wakeword_models=[self._model_name],
            inference_framework="onnx",
        )

        self._stream = sd.RawInputStream(
            device=self._input_device,
            samplerate=self._sample_rate,
            blocksize=_OWW_CHUNK,
            dtype="int16",
            channels=1,
        )
        # Log which device we're actually using
        dev_info = sd.query_devices(self._stream.device, "input")
        logger.info(f"Microphone: [{self._stream.device}] {dev_info['name']}")
        self._stream.start()

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(
            f"Wake-word detector started (model='{self._model_name}', "
            f"threshold={self._threshold})"
        )

    def pause(self) -> None:
        self._paused = True
        logger.info("Wake-word detector paused")

    def resume(self) -> None:
        self._paused = False
        logger.info("Wake-word detector resumed")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._stream:
            self._stream.stop()
            self._stream.close()
        logger.info("Wake-word detector stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _read_chunk(self) -> bytes:
        """Read one chunk from the input stream (blocking)."""
        raw, overflowed = self._stream.read(_OWW_CHUNK)
        return bytes(raw)

    def _loop(self) -> None:
        while self._running:
            if self._busy or self._paused:
                time.sleep(0.05)
                continue
            try:
                raw = self._read_chunk()
                pcm = np.frombuffer(raw, dtype=np.int16)

                # Feed audio to OpenWakeWord
                prediction = self._oww_model.predict(pcm)

                # Check all model scores against threshold
                for model_name, score in prediction.items():
                    if score >= self._threshold:
                        logger.info(
                            f"Wake word detected! ({model_name}: {score:.2f})"
                        )
                        self._oww_model.reset()
                        self._busy = True
                        if self._on_wake:
                            threading.Thread(
                                target=self._on_wake, daemon=True
                            ).start()
                        self._play_chime()
                        audio = self._record_until_silence()
                        if audio:
                            threading.Thread(
                                target=self._dispatch,
                                args=(audio,),
                                daemon=True,
                            ).start()
                        else:
                            self._busy = False
                            if self._on_empty:
                                threading.Thread(
                                    target=self._on_empty, daemon=True
                                ).start()
                        break

            except Exception as exc:
                logger.error(f"Listener error: {exc}")
                # Reconnect stream on driver errors (e.g. MME -9999)
                try:
                    if self._stream:
                        self._stream.stop()
                        self._stream.close()
                except Exception:
                    pass
                time.sleep(1)
                try:
                    self._stream = sd.RawInputStream(
                        device=self._input_device,
                        samplerate=self._sample_rate,
                        blocksize=_OWW_CHUNK,
                        dtype="int16",
                        channels=1,
                    )
                    self._stream.start()
                    logger.info("Audio stream reconnected")
                except Exception as re_exc:
                    logger.error(f"Stream reconnect failed: {re_exc}")
                    time.sleep(3)

    def _dispatch(self, audio: bytes) -> None:
        try:
            self._on_speech(audio)
        except Exception as exc:
            logger.error(f"Callback error: {exc}")
        finally:
            self._busy = False

    # ---- follow-up (continuous conversation) -------------------------
    def record_followup(self, timeout: float = 4.0) -> Optional[bytes]:
        """Listen for follow-up speech for up to *timeout* seconds.

        Returns WAV bytes if speech is detected, None if only silence.
        Must be called while _busy is True (i.e. from the speech callback).
        """
        max_wait = int(timeout * self._sample_rate / _OWW_CHUNK)
        frames: list[bytes] = []
        speech_heard = False

        # Phase 1: wait for speech to start (or timeout)
        for _ in range(max_wait):
            raw = self._read_chunk()
            frames.append(raw)
            if self._rms(raw) >= self._silence_thresh:
                speech_heard = True
                break

        if not speech_heard:
            return None

        # Phase 2: speech started — record until silence (reuse normal logic)
        silence_frames_needed = int(
            self._silence_dur * self._sample_rate / _OWW_CHUNK
        )
        max_rec = int(self._max_rec * self._sample_rate / _OWW_CHUNK)
        silent_count = 0

        for _ in range(max_rec):
            raw = self._read_chunk()
            frames.append(raw)
            if self._rms(raw) < self._silence_thresh:
                silent_count += 1
                if silent_count >= silence_frames_needed:
                    break
            else:
                silent_count = 0

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(b"".join(frames))
        return buf.getvalue()

    # ---- recording ---------------------------------------------------
    _PARTIAL_INTERVAL = 25  # chunks between partial transcriptions (~2 s at 80 ms/chunk)

    def _frames_to_wav(self, frames: list[bytes]) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(b"".join(frames))
        return buf.getvalue()

    def _record_until_silence(self) -> Optional[bytes]:
        silence_frames_needed = int(
            self._silence_dur * self._sample_rate / _OWW_CHUNK
        )
        max_frames = int(self._max_rec * self._sample_rate / _OWW_CHUNK)

        frames: list[bytes] = []
        silent_count = 0
        since_partial = 0

        for _ in range(max_frames):
            raw = self._read_chunk()
            frames.append(raw)
            since_partial += 1

            if self._rms(raw) < self._silence_thresh:
                silent_count += 1
                if silent_count >= silence_frames_needed:
                    break
            else:
                silent_count = 0

            # Streaming STT: fire partial transcription every ~2 s
            if (self._on_partial
                    and since_partial >= self._PARTIAL_INTERVAL
                    and len(frames) > silence_frames_needed):
                since_partial = 0
                snapshot = self._frames_to_wav(frames)
                threading.Thread(
                    target=self._on_partial,
                    args=(snapshot,),
                    daemon=True,
                ).start()

        # Discard if only silence was captured
        if len(frames) <= silence_frames_needed:
            logger.debug("No speech captured after wake word")
            return None

        return self._frames_to_wav(frames)

    # ---- helpers -----------------------------------------------------
    @staticmethod
    def _rms(chunk: bytes) -> float:
        samples = struct.unpack(f"{len(chunk) // 2}h", chunk)
        return math.sqrt(sum(s * s for s in samples) / len(samples))

    def _play_chime(self) -> None:
        """Quick single beep to confirm wake (~80 ms)."""
        try:
            sr = 22050
            dur = 0.08
            t = np.linspace(0, dur, int(sr * dur), dtype=np.float32)
            chime = np.sin(2 * np.pi * 1200 * t) * 0.3
            # Fade out to avoid click
            fade = np.linspace(1, 0, len(chime) // 4, dtype=np.float32)
            chime[-len(fade):] *= fade
            sd.play(chime, samplerate=sr)
            sd.wait()
        except Exception:
            pass  # non-critical
