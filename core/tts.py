"""
Text-to-speech — Kokoro (local, default), ElevenLabs streaming, or edge-tts fallback.

Kokoro: local ONNX model, 82M params, runs on CPU, ~50ms latency.
ElevenLabs: cloud streaming PCM.
Edge-tts: free Microsoft cloud fallback.

Supports speak_streamed() for real-time pipeline: brain streams text -> TTS streams audio.
"""

import io
import queue
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Generator

import numpy as np
import sounddevice as sd
from loguru import logger

from core import audio_io

# Flush boundary: sentence-ending punctuation OR comma/colon (speak sooner)
_SENTENCE_END = re.compile(r"(?<=[.!?;,:])\s+")


class TextToSpeech:
    def __init__(self, config: dict) -> None:
        self._cfg = config
        tts_cfg = config.get("tts", {})
        self._engine: str = tts_cfg.get("engine", "kokoro")

        # Edge-TTS settings (fallback)
        edge_cfg = tts_cfg.get("edge", {})
        self._edge_voice_en: str = edge_cfg.get("voice_en", "en-US-GuyNeural")
        self._edge_voice_ro: str = edge_cfg.get("voice_ro", "ro-RO-EmilNeural")
        self._edge_rate: str = edge_cfg.get("rate", "+0%")
        self._edge_volume: str = edge_cfg.get("volume", "+0%")

        # ElevenLabs settings
        el_cfg = config.get("apis", {}).get("elevenlabs", {})
        self._el_api_key: str = el_cfg.get("api_key", "")
        self._el_voice_id: str = el_cfg.get("voice_id", "")
        self._el_model_id: str = el_cfg.get("model_id", "eleven_multilingual_v2")
        self._el_fmt: str = el_cfg.get("output_format", "pcm_24000")
        self._el_sample_rate: int = int(self._el_fmt.split("_")[-1]) if "pcm" in self._el_fmt else 24000
        self._el_client = None

        # Kokoro settings
        kokoro_cfg = tts_cfg.get("kokoro", {})
        self._kokoro_voice: str = kokoro_cfg.get("voice", "am_michael")
        self._kokoro_speed: float = kokoro_cfg.get("speed", 1.0)
        self._kokoro_sr: int = 24000
        self._kokoro = None


    # ------------------------------------------------------------------
    # Lazy init
    # ------------------------------------------------------------------
    def _ensure_el_client(self):
        if self._el_client is None:
            from elevenlabs import ElevenLabs
            self._el_client = ElevenLabs(api_key=self._el_api_key)

    def _ensure_kokoro(self):
        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            data_dir = Path(__file__).resolve().parent.parent / "data"
            self._kokoro = Kokoro(
                str(data_dir / "kokoro-v1.0.onnx"),
                str(data_dir / "voices-v1.0.bin"),
            )
            logger.info(f"Kokoro TTS ready (voice={self._kokoro_voice})")

    # ------------------------------------------------------------------
    # Streaming TTS — accepts text generator from brain.think_stream()
    # ------------------------------------------------------------------
    def speak_streamed(self, text_chunks: Generator[str, None, None],
                       language: str = "en") -> None:
        """Buffer text into sentences, generate audio for each immediately.
        Guarantees a fallback response if the generator yields nothing."""
        if self._engine == "kokoro":
            self._stream_kokoro(text_chunks, language)
            return

        if self._engine != "elevenlabs":
            full = "".join(text_chunks)
            if full.strip():
                self.speak(full, language)
            else:
                self.speak("I have nothing to add, sir.", language)
            return

        self._stream_elevenlabs(text_chunks, language)

    # ------------------------------------------------------------------
    # Kokoro streaming (local, sentence-by-sentence)
    # ------------------------------------------------------------------
    def _stream_kokoro(self, text_chunks: Generator[str, None, None],
                       language: str = "en") -> None:
        """Overlap synthesis and playback: synthesize chunk N+1 while playing chunk N."""
        self._ensure_kokoro()
        audio_q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=4)
        spoke_something = False
        error_occurred = False

        # ── Player thread: pulls audio from queue, plays continuously ──
        def _player():
            out = sd.OutputStream(
                samplerate=self._kokoro_sr, channels=1, dtype="float32"
            )
            out.start()
            try:
                while True:
                    samples = audio_q.get()
                    if samples is None:  # sentinel → done
                        break
                    out.write(samples.reshape(-1, 1))
            finally:
                out.stop()
                out.close()

        player = threading.Thread(target=_player, daemon=True)
        player.start()

        try:
            buffer = ""
            for chunk in text_chunks:
                buffer += chunk
                sentences, buffer = self._flush_sentences(buffer)
                for sentence in sentences:
                    if not spoke_something:
                        logger.info(f"TTS [kokoro]: {sentence[:80]}"
                                    f"{'…' if len(sentence) > 80 else ''}")
                    audio = self._synth_kokoro(sentence)
                    if audio is not None:
                        audio_q.put(audio)
                        spoke_something = True

            # Flush remaining text
            if buffer.strip():
                if not spoke_something:
                    logger.info(f"TTS [kokoro]: {buffer.strip()[:80]}")
                audio = self._synth_kokoro(buffer.strip())
                if audio is not None:
                    audio_q.put(audio)
                    spoke_something = True

        except Exception as exc:
            logger.error(f"speak_streamed kokoro: {exc}")
            error_occurred = True
        finally:
            audio_q.put(None)  # signal player to stop
            player.join()

        if not spoke_something:
            if error_occurred:
                self.speak("Sorry sir, I ran into an error on that one.", language)
            else:
                self.speak("I have nothing to add, sir.", language)

    def _synth_kokoro(self, text: str) -> np.ndarray | None:
        """Synthesize one text chunk with Kokoro. Returns float32 array or None."""
        result = audio_io.synthesize_kokoro(
            self._kokoro, text, self._kokoro_voice, self._kokoro_speed
        )
        return result[0] if result else None

    # ------------------------------------------------------------------
    # ElevenLabs streaming (cloud)
    # ------------------------------------------------------------------
    def _stream_elevenlabs(self, text_chunks: Generator[str, None, None],
                           language: str = "en") -> None:
        self._ensure_el_client()
        buffer = ""
        spoke_something = False
        out: sd.RawOutputStream | None = None

        def _ensure_stream():
            nonlocal out
            if out is None:
                out = sd.RawOutputStream(
                    samplerate=self._el_sample_rate, channels=1, dtype="int16"
                )
                out.start()

        error_occurred = False
        try:
            for chunk in text_chunks:
                buffer += chunk
                sentences, buffer = self._flush_sentences(buffer)
                for sentence in sentences:
                    if not spoke_something:
                        logger.info(f"TTS [elevenlabs]: {sentence[:80]}"
                                    f"{'…' if len(sentence) > 80 else ''}")
                    _ensure_stream()
                    self._stream_el_sentence(sentence, out)
                    spoke_something = True

            if buffer.strip():
                if not spoke_something:
                    logger.info(f"TTS [elevenlabs]: {buffer.strip()[:80]}")
                _ensure_stream()
                self._stream_el_sentence(buffer.strip(), out)
                spoke_something = True

        except Exception as exc:
            logger.error(f"speak_streamed elevenlabs: {exc}")
            error_occurred = True
        finally:
            if out is not None:
                out.stop()
                out.close()

        if not spoke_something:
            if error_occurred:
                fallback = ("Sorry sir, I ran into an error on that one."
                            if language != "ro"
                            else "Am întâmpinat o eroare, sir.")
            else:
                fallback = ("I have nothing to add, sir."
                            if language != "ro"
                            else "Nu am nimic de adăugat, sir.")
            logger.warning(f"speak_streamed: fallback triggered")
            self.speak(fallback, language)

    def _stream_el_sentence(self, text: str, output: sd.RawOutputStream) -> None:
        """Send one sentence to ElevenLabs and play PCM chunks as they arrive."""
        try:
            for chunk in audio_io.stream_elevenlabs_pcm(
                self._el_client, text, self._el_voice_id,
                self._el_model_id, self._el_fmt,
            ):
                output.write(np.frombuffer(chunk, dtype=np.int16))
        except Exception as exc:
            logger.error(f"ElevenLabs stream error: {exc}")

    @staticmethod
    def _flush_sentences(buffer: str) -> tuple[list[str], str]:
        """Extract complete sentences from buffer, return (sentences, remainder)."""
        sentences = []
        while True:
            m = _SENTENCE_END.search(buffer)
            if m:
                sentences.append(buffer[: m.start() + 1].strip())
                buffer = buffer[m.end() :]
            else:
                break
        return sentences, buffer

    # ------------------------------------------------------------------
    # Non-streaming TTS (single text block)
    # ------------------------------------------------------------------
    def speak(self, text: str, language: str = "en") -> None:
        """Convert text to speech and play through default output."""
        if not text.strip():
            return
        logger.info(f"TTS [{self._engine}]: {text[:90]}"
                     f"{'…' if len(text) > 90 else ''}")
        try:
            if self._engine == "kokoro":
                self._speak_kokoro(text)
            elif self._engine == "elevenlabs":
                self._speak_elevenlabs(text)
            else:
                self._speak_edge(text, language)
        except Exception as exc:
            logger.error(f"TTS failed: {exc}")

    def greet(self, language: str = "ro") -> None:
        """Time-aware startup greeting in the active language."""
        hour = datetime.now().hour
        if language == "ro":
            tod = "dimineața" if hour < 12 else "ziua" if hour < 18 else "seara"
            self.speak(f"Bună {tod}, sir. Jarvis este online și pregătit.",
                       language="ro")
        else:
            tod = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
            self.speak(f"Good {tod}, sir. Jarvis is online and ready.",
                       language="en")

    # ------------------------------------------------------------------
    # Kokoro non-streaming
    # ------------------------------------------------------------------
    def _speak_kokoro(self, text: str) -> None:
        self._ensure_kokoro()
        samples, sr = self._kokoro.create(
            text, voice=self._kokoro_voice, speed=self._kokoro_speed
        )
        if samples is not None and len(samples) > 0:
            sd.play(samples, sr)
            sd.wait()

    # ------------------------------------------------------------------
    # ElevenLabs non-streaming
    # ------------------------------------------------------------------
    def _speak_elevenlabs(self, text: str) -> None:
        self._ensure_el_client()
        with sd.RawOutputStream(
            samplerate=self._el_sample_rate, channels=1, dtype="int16"
        ) as out:
            for chunk in audio_io.stream_elevenlabs_pcm(
                self._el_client, text, self._el_voice_id,
                self._el_model_id, self._el_fmt,
            ):
                out.write(np.frombuffer(chunk, dtype=np.int16))

    # ------------------------------------------------------------------
    # Edge-TTS (free fallback)
    # ------------------------------------------------------------------
    def _speak_edge(self, text: str, language: str = "en") -> None:
        voice = self._edge_voice_ro if language == "ro" else self._edge_voice_en
        mp3_bytes = audio_io.synthesize_edge_mp3(
            text, voice, rate=self._edge_rate, volume=self._edge_volume,
        )
        if mp3_bytes:
            self._play_mp3(mp3_bytes)

    # ------------------------------------------------------------------
    # Mobile API helper — synthesize to WAV bytes for /api/mobile/synthesize
    # ------------------------------------------------------------------
    def synthesize_to_wav(self, text: str, language: str = "en") -> bytes:
        """Render text using the configured engine and return WAV bytes (no playback).

        Used by the mobile HTTP endpoint to ship audio to the phone client.
        """
        if not text.strip():
            return b""
        engine = self._engine
        try:
            if engine == "kokoro":
                self._ensure_kokoro()
                result = audio_io.synthesize_kokoro(
                    self._kokoro, text, self._kokoro_voice, self._kokoro_speed,
                )
                if result is None:
                    return b""
                samples, sr = result
                return audio_io.float32_to_wav(samples, sr)
            if engine == "elevenlabs":
                self._ensure_el_client()
                return audio_io.synthesize_elevenlabs_wav(
                    self._el_client, text, self._el_voice_id,
                    self._el_model_id, self._el_fmt,
                )
            voice = self._edge_voice_ro if language == "ro" else self._edge_voice_en
            mp3 = audio_io.synthesize_edge_mp3(
                text, voice, rate=self._edge_rate, volume=self._edge_volume,
            )
            return audio_io.edge_mp3_to_wav(mp3)
        except Exception as exc:
            logger.error(f"synthesize_to_wav [{engine}] failed: {exc}")
            return b""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _play_mp3(mp3_bytes: bytes) -> None:
        import av
        container = av.open(io.BytesIO(mp3_bytes), format="mp3")
        frames = []
        sample_rate = 24000
        for frame in container.decode(audio=0):
            sample_rate = frame.sample_rate
            frames.append(frame.to_ndarray())
        container.close()
        if not frames:
            return
        audio = np.concatenate(frames, axis=1).T.astype(np.float32)
        if audio.max() > 1.0 or audio.min() < -1.0:
            audio = audio / 32768.0
        sd.play(audio, samplerate=sample_rate)
        sd.wait()
