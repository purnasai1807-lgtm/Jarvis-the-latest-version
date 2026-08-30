"""Tool registry — phases 2-7."""

from loguru import logger

from tools.system import TOOLS as _SYS_T, HANDLERS as _SYS_H
from tools.input import TOOLS as _INP_T, HANDLERS as _INP_H
from tools.files import TOOLS as _FIL_T, HANDLERS as _FIL_H
from tools.screen import TOOLS as _SCR_T, HANDLERS as _SCR_H
from tools.spotify import TOOLS as _SPO_T, HANDLERS as _SPO_H
from tools.browser import TOOLS as _BRW_T, HANDLERS as _BRW_H
from tools.vision import TOOLS as _VIS_T, HANDLERS as _VIS_H
from tools.hue import TOOLS as _HUE_T, HANDLERS as _HUE_H
from tools.chromecast import TOOLS as _CC_T, HANDLERS as _CC_H
from tools.gmail import TOOLS as _GMAIL_T, HANDLERS as _GMAIL_H
from tools.calendar_tool import TOOLS as _CAL_T, HANDLERS as _CAL_H
from tools.discord_tool import TOOLS as _DISC_T, HANDLERS as _DISC_H
from tools.whatsapp import TOOLS as _WA_T, HANDLERS as _WA_H
from tools.memory_tool import TOOLS as _MEM_T, HANDLERS as _MEM_H
from tools.claude_code import TOOLS as _CC2_T, HANDLERS as _CC2_H
from tools.task_tool import TOOLS as _TSK_T, HANDLERS as _TSK_H
from tools.watch_tool import TOOLS as _WCH_T, HANDLERS as _WCH_H
from tools.context_tool import TOOLS as _CTX_T, HANDLERS as _CTX_H
from tools.plan_tool import TOOLS as _PLN_T, HANDLERS as _PLN_H
from tools.cleanup_tool import TOOLS as _CLN_T, HANDLERS as _CLN_H
from tools.spotify import init_spotify
from tools.vision import init_vision
from tools.hue import init_hue
from tools.chromecast import init_chromecast
from tools.discord_tool import init_discord
from tools.memory_tool import init_memory

ALL_TOOLS = (_SYS_T + _INP_T + _FIL_T + _SCR_T + _SPO_T + _BRW_T + _VIS_T
             + _HUE_T + _CC_T + _GMAIL_T + _CAL_T + _DISC_T + _WA_T + _MEM_T
             + _CC2_T + _TSK_T + _WCH_T + _CTX_T + _PLN_T + _CLN_T)
ALL_HANDLERS = {**_SYS_H, **_INP_H, **_FIL_H, **_SCR_H, **_SPO_H, **_BRW_H, **_VIS_H,
                **_HUE_H, **_CC_H, **_GMAIL_H, **_CAL_H, **_DISC_H, **_WA_H, **_MEM_H,
                **_CC2_H, **_TSK_H, **_WCH_H, **_CTX_H, **_PLN_H, **_CLN_H}


def register_all(brain, config: dict) -> None:
    """Register every tool with the brain."""
    from core.memory import MemoryManager
    memory = MemoryManager(config)
    init_spotify(config)
    init_vision(config)
    init_hue(config)
    init_chromecast(config)
    init_discord(config)
    init_memory(memory)
    brain.set_memory(memory)
    brain.register_tools(ALL_TOOLS, ALL_HANDLERS)
    logger.info(f"Phases 2-7: {len(ALL_TOOLS)} tools registered — "
                + ", ".join(t["name"] for t in ALL_TOOLS))
