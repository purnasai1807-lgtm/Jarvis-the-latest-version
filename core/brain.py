"""
LLM brain — OpenAI API (GPT-4.1 mini, primary) + Ollama (local, optional).

think_stream() handles EVERYTHING: simple queries, tool calls, multi-round tool loops.
"""

import concurrent.futures
import inspect
import json
import re
from datetime import datetime
from typing import Any, Generator

from loguru import logger

from core import conversation, routines
from core.voice_normalization import normalize_voice_command

_TOOL_TIMEOUT = 60  # seconds before a tool call is abandoned
_MAX_TOOL_ROUNDS = 5
_HISTORY_LIMIT = 40  # how many recent turns to include in each prompt
_LOCAL_HISTORY_LIMIT = 12


# ── Think-block filter (strips <think>...</think> reasoning from local models) ──

class _ThinkFilter:
    """Streaming filter that strips <think>...</think> blocks."""

    def __init__(self) -> None:
        self._in_think = False
        self._buf = ""

    def feed(self, text: str) -> str:
        self._buf += text
        out: list[str] = []

        while self._buf:
            if self._in_think:
                end = self._buf.find("</think>")
                if end >= 0:
                    self._in_think = False
                    self._buf = self._buf[end + 8:]
                else:
                    self._buf = ""  # still inside, consume all
                    break
            else:
                start = self._buf.find("<think>")
                if start >= 0:
                    out.append(self._buf[:start])
                    self._in_think = True
                    self._buf = self._buf[start + 7:]
                else:
                    # Hold back potential partial "<think>" at end
                    hold = 0
                    for i in range(1, min(7, len(self._buf) + 1)):
                        if self._buf.endswith("<think>"[:i]):
                            hold = i
                            break
                    out.append(self._buf[:len(self._buf) - hold])
                    self._buf = self._buf[len(self._buf) - hold:]
                    break

        return "".join(out)

    def flush(self) -> str:
        if self._in_think:
            self._buf = ""
            self._in_think = False
            return ""
        result = self._buf
        self._buf = ""
        return result


# ── Brain ─────────────────────────────────────────────────────────────────

class Brain:
    def __init__(self, config: dict) -> None:
        # -- OpenAI API (primary) --
        oai_cfg = config.get("apis", {}).get("openai", {})
        self._openai_key: str = oai_cfg.get("api_key", "")
        self._openai_model: str = oai_cfg.get("model", "gpt-4.1-mini")
        self._max_tokens: int = oai_cfg.get("max_tokens", 1024)
        self._openai_client = None

        self._persona: str = config.get("persona", {}).get("system_prompt", "You are Jarvis.")
        self._tools: list[dict[str, Any]] = []   # Anthropic format (canonical, converted on the fly)
        self._tool_handlers: dict[str, Any] = {}
        self._memory = None
        self._on_api_call = None  # callback(model, prompt_tokens, completion_tokens, latency_ms, tool_names)

        # -- Ollama (local, optional) --
        ollama_cfg = config.get("ollama", {})
        self._ollama_enabled: bool = ollama_cfg.get("enabled", False)
        self._ollama_url: str = ollama_cfg.get("base_url", "http://localhost:11434/v1")
        self._ollama_model: str = ollama_cfg.get("model", "qwen3.5:35b-a3b")
        self._ollama_client = None

        if self._ollama_enabled:
            logger.info(f"Ollama enabled: {self._ollama_url} → {self._ollama_model}")
        logger.info(f"OpenAI model: {self._openai_model}")

        # Pre-warm OpenAI connection (HTTPS handshake) in background
        if self._openai_key:
            import threading
            threading.Thread(target=self._warmup, daemon=True).start()

    def _warmup(self) -> None:
        """Pre-warm the OpenAI HTTPS connection so first query is fast."""
        try:
            client = self._get_openai()
            client.models.list()  # lightweight call, warms TLS + connection pool
            logger.info("OpenAI connection pre-warmed")
        except Exception:
            pass  # non-critical

    def set_memory(self, memory) -> None:
        """Attach the long-term memory manager (Phase 7)."""
        self._memory = memory

    def set_api_callback(self, callback) -> None:
        """Set callback for API usage logging: callback(model, prompt_tokens, completion_tokens, latency_ms, tool_names)."""
        self._on_api_call = callback

    # ------------------------------------------------------------------
    # Lazy clients
    # ------------------------------------------------------------------
    def _get_openai(self):
        if self._openai_client is None:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self._openai_key)
        return self._openai_client

    def _get_ollama(self):
        if self._ollama_client is None:
            from openai import OpenAI
            self._ollama_client = OpenAI(base_url=self._ollama_url, api_key="ollama")
        return self._ollama_client

    # ------------------------------------------------------------------
    # Tool registration & format conversion
    # ------------------------------------------------------------------
    def register_tools(self, tool_definitions: list[dict[str, Any]],
                       handlers: dict[str, Any] | None = None) -> None:
        self._tools.extend(tool_definitions)
        if handlers:
            self._tool_handlers.update(handlers)
        logger.info(f"Registered {len(tool_definitions)} tool(s)")

    def has_tools(self) -> bool:
        return bool(self._tools)

    def _tools_openai(self) -> list[dict]:
        """Convert Anthropic tool definitions → OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema",
                                        {"type": "object", "properties": {}}),
                },
            }
            for t in self._tools
        ]

    def _request_needs_tools(self, text: str) -> bool:
        """Detect if a request likely needs tool calling.
        
        Tool-requiring keywords: open, control, turn on/off, play, send,
        search, read, get weather, fetch, etc.
        """
        text_lower = text.lower().strip()
        
        # Keywords that strongly indicate tool use
        tool_keywords = [
            "open ", "launch ", "run ", "start ",
            "control ", "turn on", "turn off", "switch ",
            "play ", "pause ", "skip ", "volume ",
            "send ", "message ", "email ", "post ",
            "call ", "search ", "find ", "look ",
            "get ", "fetch ", "read ", "show ",
            "write code", "review code", "review ", "fix ",
            "debug ", "refactor ", "build ", "implement ",
            "edit ", "modify ", "change code", "coding ",
            "claude ", "ask claude", "tell claude",
            "what's the weather", "weather ", "temperature",
            "lights ", "hue ", "nest ", "speaker ",
            "lights_control", "hue_", "lights on", "lights off"
        ]
        telugu_tool_keywords = [
            "తెరవ", "తెరువ", "ఓపెన్", "మూస", "పంప", "చదవ", "వెతక",
            "వాల్యూమ్", "పెంచ", "తగ్గించ", "మ్యూట్", "ప్లే", "పాజ్",
            "లైట్స్", "లైట్లు", "స్పీకర్", "వాతావరణం", "మెసేజ్",
        ]
        
        return (
            any(text_lower.startswith(kw) or f" {kw}" in text_lower
                for kw in tool_keywords)
            or any(kw in text for kw in telugu_tool_keywords)
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def think_stream(self, text: str, language: str = "en",
                     source: str = "voice") -> Generator[str, None, None]:
        """Stream response. Priority: Ollama when enabled, then OpenAI,
        with a quota-aware fallback to Ollama if the OpenAI key is exhausted.

        `source` tags this turn's origin (voice / mobile / dashboard / scheduler)
        in the cross-device conversation store.
        """
        if not text.strip():
            return

        if source == "mobile":
            fast_result = self._mobile_fast_path(text)
            if fast_result is not None:
                conversation.append("user", text, source=source, lang=language)
                conversation.append("assistant", fast_result,
                                    source=source, lang=language)
                yield fast_result
                return

        # ── Routine fast-path ──────────────────────────────────────
        # If the spoken text matches a voice-trigger routine, run it instead
        # of calling the LLM. The brain still streams a single acknowledgement
        # line so the existing TTS pipeline speaks something cohesive; the
        # rest of the routine fires asynchronously through core.router.
        if source == "voice":
            matched = routines.match_voice(text)
            if matched is not None:
                ack = (routines.first_speak_text(matched)
                       or f"Running {matched.name}.")
                logger.info(f"Brain → routine fast-path: {matched.name}")
                conversation.append("user", text, source=source, lang=language)
                yield ack
                conversation.append("assistant", ack,
                                    source=source, lang=language)
                routines.run_async(matched.name, skip_first_speak=True)
                return

        conversation.append("user", text, source=source, lang=language)
        history_limit = (0 if source == "mobile" else
                 _LOCAL_HISTORY_LIMIT
                 if self._ollama_enabled and source == "voice"
                 else _HISTORY_LIMIT)
        history = conversation.history_for_brain(history_limit)

        system = self._build_system(language, user_text=text)
        full_reply = ""
        backend_name = "openai"

        try:
            if self._ollama_enabled:
                backend_name = "ollama"
                try:
                    for chunk in self._stream_ollama(
                            system, history, request_text=text):
                        full_reply += chunk
                        yield chunk
                except Exception as exc:
                    if full_reply:
                        logger.error(f"Ollama failed mid-stream: {exc}")
                        conversation.append("assistant", full_reply,
                                            source=source, lang=language)
                        return
                    logger.warning(f"Ollama failed, falling back to OpenAI: {exc}")
                    backend_name = "openai"
                    for chunk in self._stream_openai(system, history):
                        full_reply += chunk
                        yield chunk
            else:
                backend_name = "openai"
                try:
                    for chunk in self._stream_openai(system, history):
                        full_reply += chunk
                        yield chunk
                except Exception as exc:
                    msg = str(exc).lower()
                    if "credit" in msg or "quota" in msg or "429" in msg or "insufficient" in msg:
                        logger.warning(f"OpenAI quota exhausted, attempting Ollama fallback: {exc}")
                        backend_name = "ollama"
                        for chunk in self._stream_ollama(
                            system, history, request_text=text):
                            full_reply += chunk
                            yield chunk
                    else:
                        raise

            conversation.append("assistant", full_reply, source=source, lang=language)
            logger.info(
                f"Brain [{backend_name}]: "
                f"{full_reply[:120]}{'…' if len(full_reply) > 120 else ''}"
            )

        except Exception as exc:
            logger.error(f"Brain stream error: {exc}")
            fallback = (
                "క్షమించండి, లోపం సంభవించింది." if language == "te"
                else "Sorry sir, I hit a snag."
            )
            conversation.append("assistant", fallback, source=source, lang=language)
            yield fallback

    # ------------------------------------------------------------------
    # OpenAI streaming (GPT-4.1 mini — primary)
    # ------------------------------------------------------------------
    def _stream_openai(self, system: str,
                       history: list[dict]) -> Generator[str, None, None]:
        import time as _time
        client = self._get_openai()

        messages: list[dict] = [{"role": "system", "content": system}]
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        tools = self._tools_openai() if self._tools else None
        all_tool_names: list[str] = []
        t0 = _time.perf_counter()
        usage_prompt = 0
        usage_completion = 0

        for round_num in range(1):
            text_buf = ""
            tool_calls: dict[int, dict] = {}

            stream = client.chat.completions.create(
                model=self._openai_model,
                messages=messages,
                tools=tools,
                stream=True,
                stream_options={"include_usage": True},
            )

            for chunk in stream:
                if chunk.usage:
                    usage_prompt = chunk.usage.prompt_tokens
                    usage_completion = chunk.usage.completion_tokens

                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                if delta.content:
                    text_buf += delta.content
                    yield delta.content

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls:
                            tool_calls[idx] = {"id": "", "name": "",
                                               "arguments": ""}
                        if tc.id:
                            tool_calls[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls[idx]["arguments"] += tc.function.arguments

            if not tool_calls:
                # Log API usage after final round
                latency_ms = (_time.perf_counter() - t0) * 1000
                if self._on_api_call:
                    try:
                        self._on_api_call(
                            self._openai_model, usage_prompt, usage_completion,
                            latency_ms, ",".join(all_tool_names),
                        )
                    except Exception:
                        pass
                break

            # ── Execute tool calls ────────────────────────────────────
            tc_list = [
                {
                    "id": tc.get("id") or f"call_{idx}",
                    "type": "function",
                    "function": {"name": tc["name"],
                                 "arguments": tc["arguments"]},
                }
                for idx, tc in sorted(tool_calls.items())
            ]
            messages.append({
                "role": "assistant",
                "content": text_buf or None,
                "tool_calls": tc_list,
            })

            for tc_msg in tc_list:
                name = tc_msg["function"]["name"]
                raw_args = tc_msg["function"]["arguments"]
                all_tool_names.append(name)
                logger.info(f"Tool call: {name}({raw_args[:120]})")

                handler = self._tool_handlers.get(name)
                if not handler:
                    result = f"Unknown tool: {name}"
                else:
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        args = {}
                    result = self._run_tool(name, handler, args)

                logger.info(f"Tool result: {str(result)[:120]}")
                yield str(result)

            break

    # ------------------------------------------------------------------
    # Ollama streaming (local, optional — OpenAI-compatible API)
    # ------------------------------------------------------------------
    def _stream_ollama(self, system: str,
                       history: list[dict],
                       request_text: str = "") -> Generator[str, None, None]:
        client = self._get_ollama()

        messages: list[dict] = [{"role": "system", "content": system}]
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        needs_tools = self._request_needs_tools(request_text)
        tools = self._tools_openai() if self._tools and needs_tools else None

        for round_num in range(_MAX_TOOL_ROUNDS):
            text_buf = ""
            tool_calls: dict[int, dict] = {}
            think_filter = _ThinkFilter()

            stream = client.chat.completions.create(
                model=self._ollama_model,
                messages=messages,
                tools=tools,
                stream=True,
                temperature=0.2,
                max_tokens=256,
                extra_body={
                    "options": {
                        "num_ctx": 4096,
                        "num_predict": 256,
                    },
                },
            )

            for chunk in stream:
                choice = chunk.choices[0]
                delta = choice.delta

                if delta.content:
                    clean = think_filter.feed(delta.content)
                    if clean:
                        text_buf += clean
                        yield clean

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls:
                            tool_calls[idx] = {"id": "", "name": "",
                                               "arguments": ""}
                        if tc.id:
                            tool_calls[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls[idx]["arguments"] += tc.function.arguments

            remaining = think_filter.flush()
            if remaining:
                text_buf += remaining
                yield remaining

            # Try to extract tool calls from text (Ollama doesn't reliably call tools)
            extracted_tools = self._extract_tool_calls_from_text(text_buf)
            if extracted_tools:
                logger.info(f"Ollama: extracted {len(extracted_tools)} tool call(s) from text")
                for tool_name, args in extracted_tools:
                    if tool_name in self._tool_handlers:
                        handler = self._tool_handlers[tool_name]
                        result = self._run_tool(tool_name, handler, args)
                        logger.info(f"Extracted tool '{tool_name}' result: {str(result)[:120]}")

            if not tool_calls:
                break

            tc_list = [
                {
                    "id": tc.get("id") or f"call_{idx}",
                    "type": "function",
                    "function": {"name": tc["name"],
                                 "arguments": tc["arguments"]},
                }
                for idx, tc in sorted(tool_calls.items())
            ]
            messages.append({
                "role": "assistant",
                "content": text_buf or None,
                "tool_calls": tc_list,
            })

            for tc_msg in tc_list:
                name = tc_msg["function"]["name"]
                raw_args = tc_msg["function"]["arguments"]
                logger.info(f"Tool call: {name}({raw_args[:120]})")

                handler = self._tool_handlers.get(name)
                if not handler:
                    result = f"Unknown tool: {name}"
                else:
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        args = {}
                    result = self._run_tool(name, handler, args)

                logger.info(f"Tool result: {str(result)[:120]}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_msg["id"],
                    "content": str(result),
                })

            logger.debug(f"Tool round {round_num + 1} complete, continuing…")
            text_buf = ""

    def _extract_tool_calls_from_text(self, text: str) -> list[tuple[str, dict]]:
        """Extract local-model tool calls returned as plain text or JSON."""
        if not self._tool_handlers:
            return []
        extracted = []

        # Small local models sometimes emit the OpenAI function envelope as
        # response text instead of populating delta.tool_calls. Recover valid
        # JSON objects and tolerate trailing commas in the generated payload.
        decoder = json.JSONDecoder()
        for start, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                candidate = re.sub(r",\s*([}\]])", r"\1", text[start:])
                try:
                    value, _ = decoder.raw_decode(candidate)
                except json.JSONDecodeError:
                    continue
            if not isinstance(value, dict):
                continue
            name = value.get("name")
            args = value.get("parameters", value.get("arguments", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if isinstance(name, str) and name in self._tool_handlers and isinstance(args, dict):
                extracted.append((name, args))

        if extracted:
            return extracted

        text_lower = text.lower()
        if "opened " in text_lower or "open " in text_lower:
            for app in ["calculator", "notepad", "chrome", "firefox", "spotify", "discord", "whatsapp", "edge"]:
                if app in text_lower:
                    extracted.append(("open_app", {"app": app}))
                    break
        if ("turned on" in text_lower or "turned off" in text_lower or "turn on" in text_lower or "turn off" in text_lower) and "light" in text_lower:
            state = "on" if ("turned on" in text_lower or "turn on" in text_lower) else "off"
            extracted.append(("lights_control", {"state": state}))
        return extracted

    def _mobile_fast_path(self, text: str) -> str | None:
        """Handle unambiguous phone actions without asking a small LLM."""
        normalized = normalize_voice_command(text).lower()
        handlers = self._tool_handlers

        if "whatsapp" in normalized:
            if normalized.startswith(("open ", "launch ", "start ")):
                handler = handlers.get("open_app")
                if handler:
                    return self._run_tool("open_app", handler, {"name": "whatsapp"})

            match = re.search(
                r"(?:send|text).*?(?:to|for)\s+([\w .'-]+?)\s+"
                r"(?:saying|message|that says|with)\s+(.+)$",
                text.strip(),
                flags=re.IGNORECASE,
            )
            if match and handlers.get("whatsapp_send"):
                contact = match.group(1).strip(" .,'\"")
                message = match.group(2).strip(" .,'\"")
                return self._run_tool(
                    "whatsapp_send", handlers["whatsapp_send"],
                    {"contact": contact, "message": message},
                )

        app_match = re.match(
            r"(?:open|launch|start)\s+(?:the\s+)?"
            r"(calculator|notepad|chrome|firefox|spotify|discord|whatsapp|edge)$",
            normalized,
        )
        if app_match and handlers.get("open_app"):
            return self._run_tool(
                "open_app", handlers["open_app"], {"name": app_match.group(1)},
            )

        if normalized in ("mute", "mute volume", "unmute", "unmute volume"):
            action = "mute" if normalized.startswith("mute") else "unmute"
            if handlers.get("volume_control"):
                return self._run_tool("volume_control", handlers["volume_control"],
                                      {"action": action})

        volume_match = re.match(r"(?:set )?(?:the )?volume(?: to)?\s+(\d{1,3})%?$", normalized)
        if volume_match and handlers.get("volume_control"):
            level = max(0, min(100, int(volume_match.group(1))))
            return self._run_tool("volume_control", handlers["volume_control"],
                                  {"action": "set", "level": level})

        if normalized in ("volume up", "increase volume", "turn volume up"):
            if handlers.get("volume_control"):
                return self._run_tool("volume_control", handlers["volume_control"],
                                      {"action": "up"})
        if normalized in ("volume down", "decrease volume", "turn volume down"):
            if handlers.get("volume_control"):
                return self._run_tool("volume_control", handlers["volume_control"],
                                      {"action": "down"})

        spotify_actions = {
            "play music": "play", "pause music": "pause", "pause spotify": "pause",
            "resume music": "play", "next song": "next", "skip song": "next",
            "previous song": "previous", "previous track": "previous",
        }
        if normalized in spotify_actions and handlers.get("spotify_control"):
            return self._run_tool("spotify_control", handlers["spotify_control"],
                                  {"action": spotify_actions[normalized]})

        search_match = re.match(r"(?:search|look up|google)\s+(?:for\s+)?(.+)$", text.strip(), re.I)
        if search_match and handlers.get("web_search"):
            return self._run_tool("web_search", handlers["web_search"],
                                  {"query": search_match.group(1).strip()})

        weather_match = re.match(r"(?:weather|what(?:'s| is) the weather)(?:\s+in\s+(.+))?$", text.strip(), re.I)
        if weather_match and handlers.get("get_weather"):
            return self._run_tool("get_weather", handlers["get_weather"],
                                  {"city": (weather_match.group(1) or "Bucharest").strip()})

        if normalized in ("take a screenshot", "take screenshot", "screenshot"):
            if handlers.get("screenshot"):
                return self._run_tool("screenshot", handlers["screenshot"], {"monitor": 0})

        return None

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------
    def _run_tool(self, name: str, handler, args: dict) -> str:
        """Execute a single tool with timeout."""
        while isinstance(args, dict):
            nested = args.get("parameters")
            if isinstance(nested, dict):
                args = nested
                continue
            function = args.get("function")
            if isinstance(function, dict) and isinstance(function.get("parameters"), dict):
                args = function["parameters"]
                continue
            raw_arguments = args.get("arguments")
            if isinstance(raw_arguments, str):
                try:
                    parsed = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    break
                if isinstance(parsed, dict):
                    args = parsed
                    continue
            break

        parameters = inspect.signature(handler).parameters
        for source, target in {
            "app": "name",
            "application": "name",
            "link": "url",
            "query": "text",
            "recipient": "contact",
            "body": "message",
        }.items():
            if source in args and target in parameters and target not in args:
                args[target] = args.pop(source)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(handler, **args)
            try:
                return future.result(timeout=_TOOL_TIMEOUT)
            except concurrent.futures.TimeoutError:
                logger.error(f"Tool {name} timed out after {_TOOL_TIMEOUT}s")
                return f"{name} timed out — took longer than {_TOOL_TIMEOUT} seconds."
            except Exception as exc:
                logger.error(f"Tool {name} raised: {exc}")
                return f"Error executing {name}: {exc}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_system(self, language: str, user_text: str = "") -> str:
        now = datetime.now().strftime("%A, %B %d, %Y — %H:%M")
        lang_hint = (
            "The user spoke in Telugu — reply in Telugu."
            if language == "te"
            else "The user spoke in English — reply in English."
        )
        base = (
            f"{self._persona.strip()}\n\nCurrent date/time: {now}\n{lang_hint}"
            "\n\nKnown shortcuts: 'the dashboard' or 'my dashboard' = open_url('dashboard') — "
            "this opens the Jarvis web dashboard at localhost:9000. Never ask which dashboard."
        )
        if language == "te":
            base += (
                "\n\nTelugu command handling: understand Telugu requests as commands, "
                "not as questions requiring translation. Map తెరవండి/ఓపెన్ to open, "
                "మూసేయండి to close, పంపండి to send, చదవండి to read, "
                "వెతకండి to search, వాల్యూమ్ పెంచండి/తగ్గించండి to volume up/down, "
                "and లైట్లు ఆన్/ఆఫ్ to lights on/off. Use the matching tool."
            )

        # Local models need stronger tool-use instructions
        if self._ollama_enabled and self._tools:
            base += (
                "\n\nCRITICAL TOOL RULES:"
                "\n- You have tools available. When asked to perform ANY action "
                "(open app, play music, control lights, send message, etc.), "
                "you MUST call the appropriate tool. NEVER pretend you did something "
                "without calling a tool first."
                "\n- If you say 'I opened X', you must have called open_app first."
                "\n- If you say 'I turned on the lights', you must have called "
                "lights_control first."
                "\n- NEVER narrate or simulate an action. ALWAYS use your tools."
                "\n- After calling a tool, confirm what you did in 1 sentence."
            )

        # Inject live PC context (active app/window/clipboard) so the brain
        # can resolve "this", "that file", "the tab" without asking.
        try:
            from core import context as _ctx
            brief = _ctx.active_brief()
            if brief:
                base += (f"\n\nLive PC context (right now): {brief}"
                         "\nUse this to resolve 'this', 'that file', 'the tab' "
                         "etc. — call get_active_context, read_active_tab, "
                         "or clipboard_history for details.")
        except Exception:
            pass

        # Inject relevant long-term memories when available
        if self._memory and user_text:
            memory_context = self._memory.get_context_for(user_text)
            if memory_context:
                base += f"\n\n{memory_context}"

        # Inject last Claude Code response only when user mentions "claude"
        if user_text and "claude" in user_text.lower():
            try:
                from tools.claude_code import _last_response
                if _last_response.get("summary"):
                    base += (
                        f"\n\n── Last Claude Code interaction ──"
                        f"\nUser asked Claude: {_last_response['prompt'][:300]}"
                        f"\nClaude responded: {_last_response['summary'][:800]}"
                    )
            except Exception:
                pass

        return base

    def clear_history(self) -> None:
        n = conversation.clear()
        logger.info(f"Conversation history cleared ({n} turns)")
