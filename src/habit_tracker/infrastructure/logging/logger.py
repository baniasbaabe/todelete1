from __future__ import annotations

import logging
import re

import structlog

_TELEGRAM_BOT_URL_PATTERN = re.compile(r"(https://api\.telegram\.org/bot)[^/\s]+")


class _SecretRedactionFilter(logging.Filter):
    """Remove credentials that third-party clients may include in request URLs."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted_message = _TELEGRAM_BOT_URL_PATTERN.sub(r"\1<redacted>", message)
        if redacted_message != message:
            record.msg = redacted_message
            record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Configure structlog with JSON rendering, bound to Python's logging module."""
    logging.basicConfig(
        format="%(message)s",
        level=level,
    )

    # HTTPX logs complete URLs at INFO. Telegram embeds the bot token in its URL,
    # so suppress routine request logs and redact the token from warnings/errors.
    for logger_name in ("httpx", "httpcore"):
        dependency_logger = logging.getLogger(logger_name)
        dependency_logger.setLevel(logging.WARNING)
        if not any(isinstance(filter_, _SecretRedactionFilter) for filter_ in dependency_logger.filters):
            dependency_logger.addFilter(_SecretRedactionFilter())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
