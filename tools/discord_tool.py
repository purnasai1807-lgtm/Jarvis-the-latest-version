"""
Phase 6 — Discord messaging via discord.py bot.

The bot runs in a background thread so Jarvis can send/read messages.
Requires a bot token in config: apis.discord.bot_token
Bot must be added to the target server(s) with message read/write permissions.

Tools: discord_send, discord_read
"""

import asyncio
import threading
from loguru import logger

_bot_token: str = ""
_bot = None
_bot_loop: asyncio.AbstractEventLoop | None = None
_bot_ready = threading.Event()


def init_discord(config: dict) -> None:
    global _bot_token
    _bot_token = config.get("apis", {}).get("discord", {}).get("bot_token", "")
    if _bot_token:
        _start_bot()
    else:
        logger.warning("Discord bot token not configured — discord tools disabled")


def _start_bot() -> None:
    """Launch the discord.py client in a daemon thread."""
    global _bot, _bot_loop
    import discord

    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.dm_messages = True

    _bot = discord.Client(intents=intents)

    @_bot.event
    async def on_ready():
        logger.info(f"Discord bot ready — logged in as {_bot.user}")
        _bot_ready.set()

    def _run():
        global _bot_loop
        _bot_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_bot_loop)
        _bot_loop.run_until_complete(_bot.start(_bot_token))

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Wait up to 10s for the bot to connect
    if not _bot_ready.wait(timeout=10):
        logger.warning("Discord bot did not become ready in time")


def _run_coroutine(coro):
    """Submit a coroutine to the bot's event loop and wait for the result."""
    if _bot_loop is None or _bot_loop.is_closed():
        raise RuntimeError("Discord bot loop is not running")
    future = asyncio.run_coroutine_threadsafe(coro, _bot_loop)
    return future.result(timeout=15)


def _find_channel(name_or_id: str):
    """Find a channel by name (fuzzy) or ID across all guilds."""
    import discord
    if not _bot:
        raise RuntimeError("Discord bot not running")

    # Try by ID first
    try:
        ch = _bot.get_channel(int(name_or_id))
        if ch:
            return ch
    except (ValueError, TypeError):
        pass

    # Fuzzy name match
    name_lower = name_or_id.lower()
    for guild in _bot.guilds:
        for channel in guild.text_channels:
            if name_lower in channel.name.lower() or channel.name.lower() in name_lower:
                return channel

    return None


def _find_dm_user(username: str):
    """Find a user by name for DM."""
    if not _bot:
        raise RuntimeError("Discord bot not running")
    name_lower = username.lower()
    for guild in _bot.guilds:
        for member in guild.members:
            if (name_lower in member.name.lower() or
                    (member.display_name and name_lower in member.display_name.lower())):
                return member
    return None


# ── Handlers ─────────────────────────────────────────────────────

def discord_send(message: str, channel: str = "", user: str = "") -> str:
    """Send a message to a Discord channel or DM a user."""
    try:
        if not _bot_token:
            return "Discord bot not configured. Add apis.discord.bot_token to config.yaml."
        if not _bot_ready.is_set():
            return "Discord bot is not connected yet."

        async def _send():
            if user:
                member = _find_dm_user(user)
                if not member:
                    return f"User '{user}' not found in any server the bot is in."
                dm = await member.create_dm()
                await dm.send(message)
                return f"DM sent to {member.display_name}: '{message}'"
            elif channel:
                ch = _find_channel(channel)
                if not ch:
                    return f"Channel '{channel}' not found."
                await ch.send(message)
                return f"Message sent to #{ch.name}: '{message}'"
            else:
                return "Specify a channel or user to send to."

        result = _run_coroutine(_send())
        logger.info(f"discord_send: {result}")
        return result

    except Exception as exc:
        logger.error(f"discord_send failed: {exc}")
        return f"Could not send Discord message: {exc}"


def discord_read(channel: str, limit: int = 5) -> str:
    """Read the most recent messages from a Discord channel."""
    try:
        if not _bot_token:
            return "Discord bot not configured."
        if not _bot_ready.is_set():
            return "Discord bot is not connected yet."

        async def _read():
            ch = _find_channel(channel)
            if not ch:
                return f"Channel '{channel}' not found."
            messages = [m async for m in ch.history(limit=limit)]
            if not messages:
                return f"No messages in #{ch.name}."
            lines = [f"Last {len(messages)} messages in #{ch.name}:"]
            for m in reversed(messages):
                lines.append(f"  {m.author.display_name}: {m.content[:200]}")
            return "\n".join(lines)

        result = _run_coroutine(_read())
        logger.info(f"discord_read: {channel}")
        return result

    except Exception as exc:
        logger.error(f"discord_read failed: {exc}")
        return f"Could not read Discord messages: {exc}"


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "discord_send",
        "description": (
            "Send a message to a Discord channel or DM a user. "
            "Use when the user says 'tell X on Discord Y', 'send a message to #channel', "
            "'DM Alex on Discord', etc. "
            "Provide either 'channel' (channel name) or 'user' (username for DM), not both."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message text to send"},
                "channel": {"type": "string", "description": "Channel name to send to (e.g. 'general')"},
                "user": {"type": "string", "description": "Username to DM (e.g. 'Alex')"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "discord_read",
        "description": (
            "Read recent messages from a Discord channel. "
            "Use when the user says 'what's happening in #channel', "
            "'read the last messages in general', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name to read from"},
                "limit": {"type": "integer", "description": "Number of messages to fetch (default 5)"},
            },
            "required": ["channel"],
        },
    },
]

HANDLERS = {
    "discord_send": discord_send,
    "discord_read": discord_read,
}
