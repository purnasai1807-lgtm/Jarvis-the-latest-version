"""
Audio I/O primitives — pure synthesis functions extracted from core/tts.py.

These return raw bytes/PCM with no playback side effects, so they can be
reused by both the local PC TTS player (TextToSpeech.speak*) and the mobile
HTTP endpoints (/api/mobile/synthesize, /api/mobile/voice).

WAV header helper produces a standard RIFF stream that Android / iOS can
play directly via just_audio without extra decoding.

No imports of sounddevice — keep this module headless.
"""

from __future__ import annotations

import asyncio
import io
import struct
import wave
from typing import Iterable, Iterator

import numpy as np
from loguru import logger


# ─────────────────────────────────────────────────────────────────
# WAV packaging
# ─────────────────────────────────────────────────────────────────

def pcm_int16_to_wav(pcm_bytes: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap raw 16-bit PCM bytes in a WAV (RIFF) container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def float32_to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    """Convert float32 mono samples in [-1, 1] to a 16-bit PCM WAV."""
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16).tobytes()
    return pcm_int16_to_wav(pcm, sample_rate, channels=1)


# ─────────────────────────────────────────────────────────────────
# Kokoro (local ONNX)
# ─────────────────────────────────────────────────────────────────

def synthesize_kokoro(kokoro, text: str, voice: str, speed: float
                      ) -> tuple[np.ndarray, int] | None:
    """Run one Kokoro inference. Returns (float32 mono samples, sample_rate) or None."""
    try:
        samples, sr = kokoro.create(text, voice=voice, speed=speed)
        if samples is None or len(samples) == 0:
            return None
        return samples, sr
    except Exception as exc:
        logger.error(f"Kokoro synth error: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────
# ElevenLabs (cloud streaming)
# ─────────────────────────────────────────────────────────────────

def stream_elevenlabs_pcm(client, text: str, voice_id: str, model_id: str,
                          output_format: str) -> Iterator[bytes]:
    """Yield raw int16 PCM chunks from ElevenLabs as they arrive."""
    audio_iter = client.text_to_speech.stream(
        voice_id=voice_id,
        text=text,
        model_id=model_id,
        output_format=output_format,
    )
    for chunk in audio_iter:
        if chunk:
            yield chunk


def synthesize_elevenlabs_wav(client, text: str, voice_id: str, model_id: str,
                              output_format: str) -> bytes:
    """Collect the full ElevenLabs PCM stream and wrap in WAV."""
    sample_rate = int(output_format.split("_")[-1]) if "pcm" in output_format else 24000
    pcm = b"".join(stream_elevenlabs_pcm(
        client, text, voice_id, model_id, output_format
    ))
    return pcm_int16_to_wav(pcm, sample_rate, channels=1)


# ─────────────────────────────────────────────────────────────────
# Edge-TTS (free Microsoft cloud — returns MP3)
# ─────────────────────────────────────────────────────────────────

async def _edge_collect(text: str, voice: str, rate: str, volume: str) -> bytes:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


def synthesize_edge_mp3(text: str, voice: str, rate: str = "+0%",
                        volume: str = "+0%") -> bytes:
    """Synthesize one block via edge-tts. Returns raw MP3 bytes."""
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_edge_collect(text, voice, rate, volume))
        finally:
            loop.close()
    except Exception as exc:
        logger.error(f"edge-tts synth error: {exc}")
        return b""


def edge_mp3_to_wav(mp3_bytes: bytes) -> bytes:
    """Decode edge-tts MP3 bytes to WAV (24kHz mono int16) using PyAV."""
    if not mp3_bytes:
        return b""
    import av
    container = av.open(io.BytesIO(mp3_bytes), format="mp3")
    frames = []
    sample_rate = 24000
    for frame in container.decode(audio=0):
        sample_rate = frame.sample_rate
        frames.append(frame.to_ndarray())
    container.close()
    if not frames:
        return b""
    audio = np.concatenate(frames, axis=1).T.astype(np.float32)
    if audio.max() > 1.0 or audio.min() < -1.0:
        audio = audio / 32768.0
    mono = audio if audio.ndim == 1 else audio.mean(axis=1)
    return float32_to_wav(mono, sample_rate)
