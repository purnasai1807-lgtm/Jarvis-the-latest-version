from fastapi import APIRouter
from ui.db_managers import brain_db, voice_db

router = APIRouter(prefix="/api/brain", tags=["brain"])

@router.get("/stats")
async def get_stats():
    stats = brain_db.get_stats_today()
    latency = brain_db.get_avg_latency()
    return {
        "cost_today": round(stats["total_cost"], 4),
        "tokens_today": stats["total_tokens"],
        "calls_today": stats["total_calls"],
        "avg_latency": round(latency, 2)
    }

@router.get("/voice-history")
async def get_voice_history():
    """Return today's voice interactions (what goes through the GPT brain)."""
    return voice_db.get_today_logs()

@router.get("/tools")
async def get_tools_usage():
    return brain_db.get_tool_usage()

@router.get("/cost-over-time")
async def get_cost_over_time():
    return brain_db.get_cost_over_time()

@router.get("/token-breakdown")
async def get_token_breakdown():
    return brain_db.get_token_breakdown()
