from __future__ import annotations

import io
import logging

from vanta.log import configure_logging, get_logger


def test_configure_logging_is_idempotent() -> None:
    configure_logging("INFO")
    configure_logging("DEBUG")
    root = logging.getLogger("vanta")
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG


def test_get_logger_is_namespaced() -> None:
    assert get_logger("vanta.validator.scorer").name == "vanta.validator.scorer"
    assert get_logger("market.provider").name == "vanta.market.provider"
    assert get_logger("vanta").name == "vanta"


def test_records_reach_the_configured_handler() -> None:
    configure_logging("INFO")
    stream = io.StringIO()
    logging.getLogger("vanta").handlers[0].setStream(stream)

    get_logger("smoke").info("resolution complete")

    written = stream.getvalue()
    assert "resolution complete" in written
    assert "vanta.smoke" in written
    assert "INFO" in written


def test_app_logs_do_not_propagate_to_root() -> None:
    configure_logging("INFO")
    assert logging.getLogger("vanta").propagate is False
