"""
J.A.R.V.I.S. — Just A Rather Very Intelligent System
=====================================================
Main entry point.  Wires up wake-word → STT → Brain (streaming) → TTS (streaming).
Phase 8: HUD overlay runs on the main thread via tkinter mainloop.
"""

import ctypes
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Generator

from loguru import logger

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Add NVIDIA DLL directories to PATH so ctranslate2 can find cuBLAS
_nvidia_base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
if _nvidia_base.exists():
    for dll_dir in _nvidia_base.glob("*/bin"):
        os.add_dll_directory(str(dll_dir))
        os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")

from core.config import load_config
from core.logger import setup_logging
from core.wake_word import WakeWordDetector
from core.stt import SpeechToText
from core.tts import TextToSpeech
from core.brain import Brain
from core import (context, continue_session, language, plans, presence,
                  router, routines, scheduler, jobs)
from tools import register_all
from ui.hud import JarvisHUD, STANDBY, LISTENING, THINKING, SPEAKING, PAUSED


# ------------------------------------------------------------------
# Language-switch detection — runs before brain, no tool call needed
# ------------------------------------------------------------------

_EN_TRIGGERS = {"english", "engleza", "engleză", "engleaza"}
_RO_TRIGGERS = {"romanian", "romana", "română", "romina", "romaneste", "românești"}
_SWITCH_VERBS = {
    "schimba", "schimbă", "switch", "change", "treci", "vorbeste",
    "vorbești", "speak", "language", "limba", "set",
}


def _wants_english(text: str) -> bool:
    words = set(text.lower().split())
    return bool(words & _EN_TRIGGERS) and bool(words & _SWITCH_VERBS)


def _wants_romanian(text: str) -> bool:
    words = set(text.lower().split())
    return bool(words & _RO_TRIGGERS) and bool(words & _SWITCH_VERBS)


# ------------------------------------------------------------------
# HUD text-stream tee — mirrors brain chunks to HUD while TTS consumes them
# ------------------------------------------------------------------

def _hud_tee(gen: Generator[str, None, None], hud: JarvisHUD) -> Generator[str, None, None]:
    """Wrap the brain generator to also push each chunk to the HUD."""
    first = True
    for chunk in gen:
        if first:
            hud.set_state(SPEAKING)
            first = False
        hud.append_response(chunk)
        yield chunk


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    # Single-instance guard — prevent duplicate HUDs on startup
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "JarvisAssistantSingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("Jarvis is already running — exiting duplicate instance.")
        sys.exit(0)

    config = load_config()
    setup_logging(config)

    # Honour config default language (falls back to "ro")
    default_lang = config.get("language", {}).get("default", "ro")
    language.set(default_lang)
    logger.info(f"Active language: {language.get()}")

    logger.info("Booting Jarvis…")

    stt    = SpeechToText(config)       # preloads Whisper model
    tts    = TextToSpeech(config)
    brain  = Brain(config)
    # HUD needs detector reference for pause — created after detector
    hud    = JarvisHUD()
    register_all(brain, config)         # Phases 2-7 tools

    # Wire brain API usage logging to dashboard DB
    from ui.db_managers import brain_db, voice_db

    # GPT-4.1 mini pricing (per 1M tokens)
    _COST_PER_1M_PROMPT = 0.40
    _COST_PER_1M_COMPLETION = 1.60

    def _on_api_call(model, prompt_tokens, completion_tokens, latency_ms, tool_names):
        cost = (prompt_tokens * _COST_PER_1M_PROMPT + completion_tokens * _COST_PER_1M_COMPLETION) / 1_000_000
        brain_db.log_api_call(model, prompt_tokens, completion_tokens, cost, latency_ms, tool_names)

    brain.set_api_callback(_on_api_call)

    # Phase 9: Web dashboard
    from ui.dashboard import start_dashboard
    start_dashboard(config, port=9000, brain=brain, tts=tts, stt=stt)

    # ── Context + presence + router + scheduler + routines ──────────
    context.init()                     # active window + clipboard pollers
    presence.init(config)
    router.wire(hud=hud, tts=tts)
    routines.set_brain(brain)
    routines.load()
    plans.set_brain(brain)             # propose/confirm plans use brain handlers
    scheduler.init()
    jobs.register_all(config)
    scheduler.get().start()

    # -- callback: wake word detected — user is now speaking -------------
    def on_wake() -> None:
        hud.set_state(LISTENING)
        hud.set_response("")            # clear previous response

    # -- callback: recording done, audio ready ---------------------------
    def on_speech(wav_bytes: bytes) -> None:
        lang = language.get()
        hud.set_state(THINKING)
        try:
            while True:
                # STT: force active language
                transcript, _detected = stt.transcribe(wav_bytes, force_language=lang)

                if not transcript:
                    _say_empty(tts, lang)
                    break

                logger.info(f"[{lang.upper()}] {transcript}")
                hud.set_transcript(transcript)
                voice_db.log("user", transcript)

                # -- Language switch commands (instant, no brain) -------
                if _wants_english(transcript):
                    language.set("en")
                    logger.info("Language switched → EN")
                    hud.set_response("Switched to English, sir.")
                    hud.set_state(SPEAKING)
                    tts.speak("Switched to English, sir.", language="en")
                    break

                if _wants_romanian(transcript):
                    language.set("ro")
                    logger.info("Language switched → RO")
                    hud.set_response("Am trecut pe română, sir.")
                    hud.set_state(SPEAKING)
                    tts.speak("Am trecut pe română, sir.", language="ro")
                    break

                # -- Normal pipeline -----------------------------------
                lang = language.get()
                hud.set_state(THINKING)
                stream = brain.think_stream(transcript, lang)
                reply_chunks: list[str] = []
                def _collecting_tee(gen):
                    for chunk in _hud_tee(gen, hud):
                        reply_chunks.append(chunk)
                        yield chunk
                tts.speak_streamed(_collecting_tee(stream), language=lang)

                # -- Follow-up only if Jarvis asked a question ---------
                full_reply = "".join(reply_chunks).strip()
                if full_reply:
                    voice_db.log("jarvis", full_reply)
                if not full_reply.endswith("?"):
                    break

                hud.set_state(LISTENING)
                hud.set_response("")
                logger.debug("Jarvis asked a question — listening for follow-up…")
                followup = detector.record_followup(timeout=6.0)
                if followup is None:
                    logger.debug("No follow-up detected")
                    break
                logger.info("Follow-up speech detected")
                wav_bytes = followup
                hud.set_state(THINKING)

        except Exception as exc:
            logger.error(f"on_speech error: {exc}")
            err_msg = ("Scuze, ceva n-a mers bine." if lang == "ro"
                       else "Sorry sir, something went wrong.")
            tts.speak(err_msg, language=lang)
        finally:
            hud.set_state(STANDBY)

    def on_empty() -> None:
        hud.set_state(STANDBY)
        _say_empty(tts, language.get())

    # -- streaming STT: partial transcription while recording -----------
    def on_partial(wav_bytes: bytes) -> None:
        try:
            lang = language.get()
            text, _ = stt.transcribe(wav_bytes, force_language=lang)
            if text:
                hud.set_transcript(text + "…")
        except Exception:
            pass  # non-critical — final transcription is authoritative

    detector = WakeWordDetector(config, on_speech, on_empty=on_empty,
                                on_wake=on_wake, on_partial=on_partial)

    # Wire HUD pause button to detector
    def on_pause_toggle(paused: bool) -> None:
        if paused:
            detector.pause()
        else:
            detector.resume()

    hud._on_pause_toggle = on_pause_toggle

    # -- graceful shutdown ---------------------------------------------
    def shutdown(*_):
        logger.info("Shutting down…")
        detector.stop()
        hud.quit()

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # -- start voice pipeline in background ----------------------------
    def _start_pipeline():
        detector.start()
        tts.greet(language=language.get())
        # Brief carry-over from yesterday — only if there's something to say
        try:
            brief = continue_session.compose_brief()
            if brief:
                logger.info(f"continue-brief: {brief[:120]}")
                tts.speak(brief, language=language.get())
        except Exception as exc:
            logger.debug(f"continue-brief skipped: {exc}")
        logger.info("Jarvis is online — say 'Hey Jarvis' to begin.")

    threading.Thread(target=_start_pipeline, daemon=True).start()

    # -- run HUD on main thread (blocks until quit) --------------------
    hud.run()


def _say_empty(tts: TextToSpeech, lang: str) -> None:
    msg = ("Nu am înțeles, mai repetați?" if lang == "ro"
           else "I didn't catch that, could you repeat?")
    tts.speak(msg, language=lang)


if __name__ == "__main__":
    main()
