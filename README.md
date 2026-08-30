<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/GPU-CUDA%2012.x-76B900?logo=nvidia&logoColor=white" alt="CUDA">
  <img src="https://img.shields.io/badge/LLM-GPT--4.1%20mini-412991?logo=openai&logoColor=white" alt="GPT-4.1 mini">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
</p>

<h1 align="center">J.A.R.V.I.S.</h1>
<h3 align="center">Just A Rather Very Intelligent System</h3>

<p align="center">
  A voice-controlled AI personal assistant for Windows, inspired by Iron Man's Jarvis.<br>
  Wake word &rarr; local STT &rarr; GPT-4.1 mini brain (streaming) &rarr; local TTS &rarr; speaker.<br>
  <b>47 tools</b> across OS control, browser, vision, smart home, communications, memory & Claude Code.
</p>

---

## Features

**Voice Pipeline** &mdash; always listening, instant response
- "Hey Jarvis" wake word (OpenWakeWord, no API key)
- Local speech-to-text (Faster-Whisper on CUDA, < 1s)
- GPT-4.1 mini brain with streaming tool calls
- Local TTS (Kokoro, free) with ElevenLabs & Edge fallbacks
- Continuous conversation &mdash; follow-up without wake word when Jarvis asks a question

**47 Registered Tools**

| Category | Tools |
|---|---|
| OS Control | `open_app`, `close_app`, `open_url`, `volume_control`, `find_file`, `move_file`, `screenshot` |
| Input | `type_text`, `hotkey`, `clipboard_read`, `clipboard_write` |
| Browser | `web_search`, `get_weather`, `read_page`, `fill_form`, `click_element`, `summarize_article`, `summarize_youtube`, `close_browser` |
| Vision | `see_screen`, `see_all_screens`, `find_on_screen`, `read_screen_text` |
| Spotify | `spotify_control`, `spotify_now_playing`, `spotify_volume`, `spotify_queue` |
| Smart Home | `lights_control`, `hue_scene`, `hue_status`, `speaker_announce`, `speaker_volume`, `speaker_control` |
| Communications | `read_emails`, `send_email`, `get_schedule`, `create_event`, `discord_send`, `discord_read`, `whatsapp_send`, `whatsapp_read` |
| Memory | `remember_fact`, `recall_fact`, `forget_fact`, `list_memories`, `morning_briefing` |
| Claude Code | `run_claude_code` |

**Iron Man Dashboard** &mdash; `http://localhost:9000`
- Arc reactor HUD with live CPU/RAM/GPU rings
- Weather, calendar, email, Spotify, smart home cards
- Full Claude Code IDE with file explorer, terminal & file preview
- Brain analytics &mdash; API cost tracking, token usage, voice interaction log
- Morning briefing page with agenda, news & memory highlights
- Project management with git activity & todo lists
- Settings panel with live API connection status

**HUD Overlay** &mdash; always-on-top tkinter overlay
- States: STANDBY &rarr; LISTENING &rarr; THINKING &rarr; SPEAKING
- Live transcription & streaming response display

---

## Architecture

```
main.py                     Entry point — wires wake word -> STT -> brain -> TTS
config.yaml                 All settings & API keys (not committed, see config.example.yaml)

core/
  brain.py                  GPT-4.1 mini streaming, tool loop, usage tracking
  wake_word.py              OpenWakeWord "hey_jarvis", silence detection
  stt.py                    Faster-Whisper (CUDA), EN/RO language lock
  tts.py                    Kokoro local TTS, ElevenLabs/edge-tts fallbacks
  memory.py                 SQLite + ChromaDB semantic search
  config.py                 YAML config loader (cached singleton)
  logger.py                 Loguru with rotating log files

tools/                      47 tool handlers across 15 modules

ui/
  hud.py                    tkinter HUD overlay (always-on-top, semi-transparent)
  dashboard.py              FastAPI backend + WebSocket Claude terminal
  db_managers.py            SQLite managers for brain usage & voice logging
  routes/                   Modular API routers (brain, briefing, projects, IDE, settings)
  static/                   Iron Man themed frontend (HTML/CSS/JS)
```

---

## Quick Start

### Prerequisites
- **Windows 10/11**
- **Python 3.12+**
- **NVIDIA GPU** with CUDA 12.x (for local STT)
- **OpenAI API key** (for GPT-4.1 mini brain)

### Install

```bash
git clone https://github.com/purnasai1807-lgtm/Jarvis-the-latest-version.git
cd jarvis

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install CUDA support for Faster-Whisper
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12

# Download Kokoro TTS model (place in data/)
# kokoro-v1.0.onnx (~325 MB) + voices-v1.0.bin (~28 MB)
# See: https://github.com/remsky/Kokoro-FastAPI#models

# Install Playwright browser (for web tools)
playwright install chromium
```

### Configure

```bash
# Copy example config and fill in your API keys
cp config.example.yaml config.yaml
```

Edit `config.yaml` and add at minimum:
- `apis.openai.api_key` &mdash; **required** for the brain
- Other keys are optional (Spotify, Discord, ElevenLabs, etc.)

### Smart Home Setup (Optional)
- **Philips Hue**: Set `smart_home.hue_bridge_ip`, then press the bridge button and run once to pair
- **Google Nest Audio**: Set the device IP for speaker announcements

### Google APIs (Optional)
- Create a Google Cloud project with Gmail & Calendar APIs enabled
- Download OAuth credentials to `data/google_credentials.json`
- First run will open browser for consent, tokens auto-refresh after that

### Run

```bash
python main.py
```

Say **"Hey Jarvis"** followed by your command. Dashboard at `http://localhost:9000`.

---

## Key Design Decisions

| Decision | What We Used | Why |
|---|---|---|
| LLM Brain | GPT-4.1 mini (OpenAI) | Best tool calling at lowest cost. Local models (Ollama) unreliable with 47 tools |
| Wake Word | OpenWakeWord | Open-source, no API key, has "hey_jarvis" model |
| TTS | Kokoro local (free) | $0 cost, English-only. ElevenLabs kept as optional fallback |
| STT | Faster-Whisper (CUDA) | Local, fast, accurate. Small model for speed |
| Audio | sounddevice | No prebuilt PyAudio wheel for Python 3.14 |
| Web Search | ddgs | duckduckgo_search package was renamed/deprecated |
| WhatsApp | win32gui + Desktop app | Web automation had thread/timeout issues |
| Chrome URLs | PowerShell UIAutomation | pygetwindow.activate() hangs indefinitely |

---

## Configuration Reference

All settings live in `config.yaml`. See `config.example.yaml` for the full template.

| Setting | Default | Description |
|---|---|---|
| `wake_word.threshold` | `0.3` | Wake word detection sensitivity (0.0-1.0) |
| `stt.model_size` | `small` | Whisper model (`small` = fast, `large-v3` = accurate) |
| `tts.engine` | `kokoro` | TTS engine (`kokoro`, `elevenlabs`, `edge`) |
| `apis.openai.model` | `gpt-4.1-mini` | LLM model for the brain |
| `audio.silence_duration` | `1.5` | Seconds of silence before stopping recording |
| `memory.max_context_facts` | `5` | Long-term memories injected per query |

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<p align="center">
  Built with obsession by <a href="https://github.com/purnasai1807-lgtm">@purnasai1807-lgtm</a>
</p>
