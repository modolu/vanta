"""Logging setup shared by all Vanta entry points."""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"


def configure_logging(level: str = "INFO") -> None:
    """Attach a single stderr handler to the ``vanta`` logger.

    Idempotent: repeated calls replace the handler rather than stacking duplicates.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=_FORMAT, datefmt=_DATEFMT))

    root = logging.getLogger("vanta")
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under ``vanta``."""
    suffix = name.removeprefix("vanta.")
    return logging.getLogger("vanta" if suffix in ("", "vanta") else f"vanta.{suffix}")
