"""
Loguru setup — console + rotating file output.
"""

import sys
from pathlib import Path
from loguru import logger


def setup_logging(config: dict) -> None:
    cfg = config.get("logging", {})
    level = cfg.get("level", "INFO")
    log_dir = Path(cfg.get("dir", "data/logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()

    # Console
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level:<8}</level> | "
            "<cyan>{name}</cyan> — <level>{message}</level>"
        ),
    )

    # File
    logger.add(
        log_dir / "jarvis_{time:YYYY-MM-DD}.log",
        level=level,
        rotation=cfg.get("rotation", "10 MB"),
        retention=cfg.get("retention", "1 week"),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name} — {message}",
    )
