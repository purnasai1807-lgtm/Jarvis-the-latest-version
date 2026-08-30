# Project J.A.R.V.I.S.

Voice-controlled AI personal assistant for Windows, inspired by Iron Man's Jarvis.
Full spec: `Project_JARVIS_Build_Spec.docx`

## Current State: Phases 1–9 Complete

**Wake word → STT → GPT-4.1 mini Brain (streaming) → TTS (streaming) → Speaker**
**47 tools registered** across OS control, browser, vision, smart home, communications, long-term memory, and Claude Code.

Target latency: **< 3-5 seconds** from end of speech to hearing the response.

---

## Phases Completed

### Phase 1 — Voice Pipeline ✅
- **Wake word**: OpenWakeWord "hey_jarvis", threshold 0.3, HyperX SoloCast mic
- **STT**: Faster-Whisper small on CUDA, beam_size=1, preloaded. Locked to EN/RO — re-transcribes as EN if another language is detected
- **Brain**: GPT-4.1 mini (OpenAI API) streaming, conversation history, 60s tool timeout. Ollama optional fallback (disabled). Connection pre-warmed at boot
- **TTS**: Kokoro local TTS (default, speed 1.1), ElevenLabs streaming PCM fallback, edge-tts fallback. Producer-consumer pattern: separate player thread for zero-gap playback. `speak_streamed()` catches all exceptions and always speaks a fallback — Jarvis never goes silent
- **Pipeline**: brain streams text → TTS buffers sentences (flush on `.!?;,:`) → plays audio in real-time. Empty recording triggers "I didn't catch that" (on_empty callback)
- **Continuous conversation**: if Jarvis's reply ends with "?", listens 6s for follow-up without wake word
- **Streaming STT**: partial transcription shown on HUD during recording (every ~2s)

### Phase 2 — OS & App Control ✅
12 tools: `open_app`, `open_url`, `close_app`, `volume_control`, `type_text`, `hotkey`, `clipboard_read`, `clipboard_write`, `find_file`, `move_file`, `screenshot`, `spotify_control`
**Spotify API** (3 extra tools): `spotify_now_playing`, `spotify_volume`, `spotify_queue` — OAuth2 via spotipy (PKCE), falls back to media keys if API not configured
- Discord: launched via `%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe` (Squirrel install)
- WhatsApp: launched via `explorer.exe shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App` (UWP)
- Spotify: opens app → Ctrl+L → paste query → Enter (no API key needed)

### Phase 3 — Browser Automation ✅
8 tools: `web_search`, `get_weather`, `read_page`, `fill_form`, `click_element`, `summarize_article`, `summarize_youtube`, `close_browser`
- **web_search**: uses `ddgs` package (NOT `duckduckgo_search` — renamed/deprecated)
- **get_weather**: fetches wttr.in JSON and parses into human-readable text
- **summarize_article / summarize_youtube**: auto-grab active Chrome tab URL via PowerShell UI Automation — no URL dictation needed. Falls back to provided URL if given
- Chrome URL reading: `Add-Type -AssemblyName UIAutomationClient` PowerShell script reads address bar without focus stealing

### Phase 4 — Screen Awareness ✅
4 tools: `see_screen`, `see_all_screens`, `find_on_screen`, `read_screen_text`
- mss captures screenshots, OpenAI Vision (GPT-4.1 mini) analyzes them
- Images resized to max 1920px wide before sending to save tokens
- `init_vision(config)` reads API key at startup

### Phase 5 — Smart Home ✅
**Philips Hue** (3 tools): `lights_control`, `hue_scene`, `hue_status`
- Bridge IP: configured via `smart_home.hue_bridge_ip` in config.yaml, 2 color lamps (IDs 1 & 3), group "Home"
- Colors: red/green/blue/yellow/orange/purple/pink/cyan/warm/white/cool/daylight
- Scenes: Relax, Read, Concentrate, Energize, Nightlight, Red light, Rosu portocaliu, etc.
- Credentials in `~/.python_hue` (one-time pairing done)

**Google Nest Audio** (3 tools): `speaker_announce`, `speaker_volume`, `speaker_control`
- Device IP: configured via `smart_home.nest_ip` in config.yaml (blank = auto-discover), connected via pychromecast
- Announcements use Google Translate TTS URL — Nest Audio fetches directly from Google, no local HTTP server, no firewall issues

### Phase 6 — Communications ✅
**Gmail** (2 tools): `read_emails`, `send_email`
- OAuth2 token: `data/google_token.json`
- Credentials: `data/google_credentials.json` (Google Cloud Console OAuth Desktop app)

**Google Calendar** (2 tools): `get_schedule`, `create_event`
- OAuth2 token: `data/google_calendar_token.json`
- Timezone: Europe/Bucharest

**Discord** (2 tools): `discord_send`, `discord_read`
- Bot "jarvis#5736", server "10i", token in `config.yaml` under `apis.discord.bot_token`
- Runs in a background daemon thread; message_content + server_members privileged intents enabled

**WhatsApp** (2 tools): `whatsapp_send`, `whatsapp_read`
- Uses **WhatsApp Desktop app** (NOT WhatsApp Web/Playwright)
- win32gui finds/focuses the window, Ctrl+N to open search, clipboard-paste contact + message, Enter to send
- Handles unicode/Romanian characters via clipboard paste

---

## Architecture

```
main.py                     — Entry point, wires wake→STT→brain→TTS, NVIDIA DLLs
config.yaml                 — All settings, API keys, thresholds, persona
core/
  config.py                 — YAML loader (cached singleton)
  logger.py                 — Loguru setup (console + rotating files in data/logs/)
  wake_word.py              — OpenWakeWord + silence recording, on_empty callback
  stt.py                    — Faster-Whisper, EN/RO lock, re-transcribes wrong languages
  tts.py                    — Kokoro local TTS, ElevenLabs fallback, edge-tts fallback
  brain.py                  — GPT-4.1 mini (OpenAI) streaming, tool loop, ollama optional
tools/
  __init__.py               — Registry: register_all() wires all 47 tools
  system.py                 — OS tools (open/close apps, volume, URLs)
  input.py                  — Keyboard/mouse tools (type_text, hotkey)
  files.py                  — File management (find_file, move_file)
  screen.py                 — Screenshot (mss)
  spotify.py                — Spotify control + API (now_playing, volume, queue)
  browser.py                — Web search, weather, Playwright browser tools (headless)
  vision.py                 — Screen awareness via OpenAI Vision (GPT-4.1 mini)
  hue.py                    — Philips Hue light control
  chromecast.py             — Google Nest Audio speaker control
  gmail.py                  — Gmail read/send
  calendar_tool.py          — Google Calendar events
  discord_tool.py           — Discord bot messaging
  whatsapp.py               — WhatsApp Desktop automation
  memory_tool.py            — Long-term memory tools (5 tools)
  claude_code.py            — Claude Code CLI integration (--continue for context)
core/
  memory.py                 — MemoryManager: SQLite + ChromaDB, FTS5 fallback
ui/
  hud.py                    — Phase 8: tkinter HUD overlay
  dashboard.py              — Phase 9: FastAPI backend + WebSocket Claude terminal
  static/dashboard.html     — Phase 9: Iron Man themed dashboard frontend
scripts/
  autostart.py              — Windows Startup folder installer
data/
  logs/                     — Rotating log files
  screenshots/              — Saved screenshots
  google_credentials.json   — Google OAuth client credentials
  google_token.json         — Gmail OAuth token (auto-refreshed)
  google_calendar_token.json — Calendar OAuth token (auto-refreshed)
  whatsapp_session/         — (unused — WhatsApp uses Desktop app now)
```

## Technical Decisions

| Decision | Original Spec | What We Used | Why |
|---|---|---|---|
| LLM brain | Claude API only | **GPT-4.1 mini (OpenAI API)** | Best tool calling at lowest cost. Ollama local models tested (GLM-4.7-Flash, Qwen 3.5) but unreliable with 43 tools. Claude Haiku removed — single vendor |
| Wake word engine | Porcupine | **OpenWakeWord** | No API key, open-source, has "hey_jarvis" model |
| Wake phrase | "Jarvis" | **"Hey Jarvis"** | OWW pre-trained model uses two-word phrase |
| TTS engine | ElevenLabs API | **Kokoro local** (free) + edge-tts fallback | $0 TTS, English only. ElevenLabs config kept for optional use |
| Audio library | PyAudio | **sounddevice** | No prebuilt wheel for Python 3.14 |
| CUDA libs | System toolkit | **nvidia-cublas-cu12** (pip) | cuBLAS not on PATH despite CUDA 12.6 |
| Web search | duckduckgo_search | **ddgs** | duckduckgo_search renamed/deprecated |
| Weather | web_search | **get_weather tool** (wttr.in) | web_search returned empty; dedicated tool parses JSON |
| WhatsApp | Playwright Web | **win32gui + Desktop app** | Web automation had thread/selector/timeout issues |
| Speaker announce | Local HTTP server | **Google Translate TTS URL** | Firewall blocked local server; Nest fetches from Google directly |
| Chrome URL grab | pygetwindow (blocked) | **PowerShell UIAutomation** | pygetwindow.activate() hangs indefinitely |

## How to Run

```bash
cd C:\Projects\jarvis
python main.py
```

Say **"Hey Jarvis"** followed by your command. One Jarvis instance only — kill any existing `python.exe` before restarting.

## Key Config Values

- `wake_word.threshold: 0.3` — detection sensitivity
- `stt.model_size: "small"` — fast CUDA transcription
- `tts.engine: "kokoro"` — free local TTS (speed 1.1); switch to `"elevenlabs"` or `"edge"` for alternatives
- `apis.openai.model: "gpt-4.1-mini"` — primary LLM (fast, cheap, excellent tool calling)
- `audio.silence_duration: 1.5` — seconds of silence before stopping recording
- `smart_home.hue_bridge_ip` — Philips Hue bridge (set in config.yaml)

### Phase 7 — Long-term Memory ✅
**SQLite + ChromaDB**, 5 tools: `remember_fact`, `recall_fact`, `forget_fact`, `list_memories`, `morning_briefing`
- SQLite (`data/memory.db`) stores facts: key/value/category, FTS5 full-text search
- ChromaDB (`data/chroma`) adds semantic vector search via all-MiniLM-L6-v2 embeddings
- Fallback chain: ChromaDB → FTS5 → recent facts (graceful if ChromaDB unavailable)
- Brain automatically injects up to 5 relevant memories into every system prompt
- Morning briefing: wttr.in weather + Google Calendar today + memory highlights
- `config.yaml`: `memory.max_context_facts: 5` controls injection limit

---

### Phase 8 — HUD Overlay ✅
**tkinter** always-on-top semi-transparent overlay (no new deps), Iron Man style.
- `ui/hud.py`: `JarvisHUD` class — frameless, 88% opacity, bottom-right corner, draggable
- States: STANDBY (dim) → LISTENING (green) → THINKING (amber) → SPEAKING (cyan)
- Shows: status badge, transcribed speech (italic), streaming response text
- Thread-safe: voice pipeline pushes to a `queue.Queue`, tkinter polls every 50 ms
- Text auto-clears 10 s after going idle
- `on_wake` callback added to `WakeWordDetector` to flip to LISTENING before chime
- `main.py`: `hud.run()` replaces `while True: sleep(1)` — tkinter owns the main thread
- Pipeline started in a daemon thread before mainloop

### Phase 9 — Web Dashboard ✅
**FastAPI** + Iron Man themed frontend, served on `http://127.0.0.1:9000`.
- `ui/dashboard.py`: FastAPI backend, uvicorn in daemon thread alongside tkinter HUD
- `ui/static/dashboard.html`: Orbitron + Share Tech Mono fonts, dark navy (#050d1a), cyan accents (#00c8e8)
- **Dashboard cards** (left column): Weather (wttr.in), System (CPU/RAM/uptime), Calendar, Email, Spotify, Lights
- **Claude Code terminal** (right column): WebSocket streaming, full conversation history
- `/api/dashboard` — all card data in one call
- `/api/system` — live CPU/RAM stats (auto-refresh every 5s)
- `/ws/claude` — WebSocket for Claude Code terminal (real-time line-by-line streaming)
- **Toolbar**: CLEAR, BOTTOM, COPY LAST, STOP buttons
- **Screenshot paste**: Ctrl+V to attach image, preview bar, fullscreen overlay on click
- **Working indicator**: green dot → amber pulsing + "WORKING..." while Claude processes
- **History**: deduplicated via `_add_to_history()`, replayed as single ordered message on connect
- **ANSI stripping**: escape codes removed from CLI output before display
- Type commands directly in the terminal or use voice via Jarvis ("tell Claude to...")
- Voice shortcut: "Hey Jarvis, open the dashboard" → opens http://127.0.0.1:9000

### Claude Code Integration ✅
1 tool: `run_claude_code`
- Runs `claude -p "prompt" --continue --output-format text --dangerously-skip-permissions`
- Short output (<400 chars) spoken by Jarvis; long output summarized with pointer to dashboard
- Real-time streaming to dashboard WebSocket via `broadcast_to_clients()`
- Conversation history deduplicated and shared across voice + dashboard paths
- Cannot type into live Claude Code TUI (ink-based renderer ignores simulated input)

### Auto-start ✅
- `scripts/autostart.py`: installs/removes VBS script in Windows Startup folder
- Usage: `python scripts/autostart.py` (install) / `python scripts/autostart.py remove`

## Next Steps

- Nothing planned — all 9 phases complete

## Python Environment
- Python 3.14 on Windows 10 Pro
- CUDA 12.6 (NVIDIA GPU), cuBLAS via pip
- All dependencies in `requirements.txt`
