"""
LLM brain — OpenAI API (GPT-4.1 mini, primary) + Ollama (local, optional).

think_stream() handles EVERYTHING: simple queries, tool calls, multi-round tool loops.
"""

import concurrent.futures
import json
from datetime import datetime
from typing import Any, Generator

from loguru import logger

from core import conversation, routines

_TOOL_TIMEOUT = 60  # seconds before a tool call is abandoned
_MAX_TOOL_ROUNDS = 5
_HISTORY_LIMIT = 40  # how many recent turns to include in each prompt


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

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def think_stream(self, text: str, language: str = "en",
                     source: str = "voice") -> Generator[str, None, None]:
        """Stream response.  Priority: ollama (if enabled) → OpenAI.

        `source` tags this turn's origin (voice / mobile / dashboard / scheduler)
        in the cross-device conversation store.
        """
        if not text.strip():
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
        history = conversation.history_for_brain(_HISTORY_LIMIT)

        system = self._build_system(language, user_text=text)
        full_reply = ""

        try:
            if self._ollama_enabled:
                backend_name = "ollama"
                try:
                    for chunk in self._stream_ollama(system, history):
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
                for chunk in self._stream_openai(system, history):
                    full_reply += chunk
                    yield chunk

            conversation.append("assistant", full_reply, source=source, lang=language)
            logger.info(
                f"Brain [{backend_name}]: "
                f"{full_reply[:120]}{'…' if len(full_reply) > 120 else ''}"
            )

        except Exception as exc:
            logger.error(f"Brain stream error: {exc}")
            fallback = ("Scuze, am avut o eroare." if language == "ro"
                        else "Sorry sir, I hit a snag.")
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

        for round_num in range(_MAX_TOOL_ROUNDS):
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
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_msg["id"],
                    "content": str(result),
                })

            logger.debug(f"Tool round {round_num + 1} complete, continuing…")
            text_buf = ""

    # ------------------------------------------------------------------
    # Ollama streaming (local, optional — OpenAI-compatible API)
    # ------------------------------------------------------------------
    def _stream_ollama(self, system: str,
                       history: list[dict]) -> Generator[str, None, None]:
        client = self._get_ollama()

        messages: list[dict] = [{"role": "system", "content": system}]
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        tools = self._tools_openai() if self._tools else None

        for round_num in range(_MAX_TOOL_ROUNDS):
            text_buf = ""
            tool_calls: dict[int, dict] = {}
            think_filter = _ThinkFilter()

            stream = client.chat.completions.create(
                model=self._ollama_model,
                messages=messages,
                tools=tools,
                stream=True,
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

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------
    def _run_tool(self, name: str, handler, args: dict) -> str:
        """Execute a single tool with timeout."""
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
            "The user spoke in Romanian — reply in Romanian."
            if language == "ro"
            else "The user spoke in English — reply in English."
        )
        base = (
            f"{self._persona.strip()}\n\nCurrent date/time: {now}\n{lang_hint}"
            "\n\nKnown shortcuts: 'the dashboard' or 'my dashboard' = open_url('dashboard') — "
            "this opens the Jarvis web dashboard at localhost:9000. Never ask which dashboard."
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
