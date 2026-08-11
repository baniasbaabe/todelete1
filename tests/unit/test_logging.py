from __future__ import annotations

import logging

from habit_tracker.infrastructure.logging.logger import _SecretRedactionFilter, configure_logging


def test_secret_redaction_filter_removes_telegram_bot_token() -> None:
    record = logging.LogRecord(
        name="httpx",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg='HTTP Request: %s %s "%s"',
        args=("POST", "https://api.telegram.org/bot123456:secret/sendMessage", "HTTP/1.1 500"),
        exc_info=None,
    )

    assert _SecretRedactionFilter().filter(record) is True
    assert record.getMessage() == (
        'HTTP Request: POST https://api.telegram.org/bot<redacted>/sendMessage "HTTP/1.1 500"'
    )
    assert "123456:secret" not in record.getMessage()


def test_configure_logging_suppresses_http_client_info_logs() -> None:
    logger_levels = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    try:
        configure_logging()

        for logger_name in logger_levels:
            dependency_logger = logging.getLogger(logger_name)
            assert dependency_logger.level == logging.WARNING
            assert any(isinstance(filter_, _SecretRedactionFilter) for filter_ in dependency_logger.filters)
    finally:
        for logger_name, level in logger_levels.items():
            logging.getLogger(logger_name).setLevel(level)
