from __future__ import annotations

from functools import wraps

from openinference.instrumentation.groq import GroqInstrumentor
from phoenix.otel import register
import structlog

logger = structlog.get_logger()

_tracer = None


def setup_tracing(collector_endpoint: str, api_key: str | None = None) -> None:
    global _tracer
    if not api_key:
        logger.warning("tracing_disabled_missing_api_key", endpoint=collector_endpoint)
        _tracer = None
        return

    try:
        tracer_provider = register(
            endpoint=collector_endpoint,
            project_name="habit-tracker",
            api_key=api_key,
        )
        GroqInstrumentor().instrument(tracer_provider=tracer_provider)
        _tracer = tracer_provider.get_tracer("habit-tracker")
        logger.info("tracing_enabled", endpoint=collector_endpoint)
    except Exception:
        logger.exception("tracing_setup_failed")
        _tracer = None


def trace(name: str, **attributes: str):
    """Decorator that wraps an async function in an OTEL span. No-op when tracing is disabled."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if _tracer is None:
                return await func(*args, **kwargs)
            with _tracer.start_as_current_span(name, attributes=attributes):
                return await func(*args, **kwargs)

        return wrapper

    return decorator
