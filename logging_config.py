"""Central logging configuration for the web application."""

from __future__ import annotations

import logging
import os
from pathlib import Path


def configure_logging() -> int:
    """Configure root logging from the environment and return its level.

    Add-on logs belong on stdout so Supervisor can collect them. A file handler
    is only enabled when ``LOG_FILE`` is explicitly set (useful for local
    debugging); writing ``web_ui.log`` unconditionally used persistent storage
    and ignored the add-on's configured log level.
    """
    requested = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, requested, logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    log_file = os.getenv("LOG_FILE", "").strip()
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, mode="a", encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )
    return level
