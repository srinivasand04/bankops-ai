"""Logging configuration. Request bodies are never logged to avoid leaking sensitive data."""

import logging
import sys


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
        force=True,
    )
    # SQL echo would print bound parameters; keep it off.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
