from __future__ import annotations

from functools import wraps

from openinference.instrumentation.groq import GroqInstrumentor
from opentelemetry.context import attach, detach
from opentelemetry.propagate import extract, inject
from phoenix.otel import register
import structlog

logger = structlog.get_logger()

_tracer = None

# Key used to carry OTEL trace context across Telegram messages in PTB user_data.
TRACE_CARRIER_KEY = "_otel_carrier"


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


def trace(name: str, save_context: bool = False, **attributes: str):
    """Decorator that wraps an async function in an OTEL span. No-op when tracing is disabled.

    If save_context=True, the span context is serialised into PTB user_data so that
    subsequent handler calls in the same check-in session attach as child spans.
    Any handler whose PTB context already carries a serialised trace context will
    automatically become a child of that root span.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if _tracer is None:
                return await func(*args, **kwargs)

            # Locate PTB ContextTypes (has .user_data) among the positional args.
            user_data = None
            for arg in args:
                if hasattr(arg, "user_data"):
                    user_data = arg.user_data
                    break

            # Restore parent context from session carrier so this span is a child.
            token = None
            if user_data is not None:
                carrier = user_data.get(TRACE_CARRIER_KEY)
                if carrier:
                    token = attach(extract(carrier))

            try:
                with _tracer.start_as_current_span(name, attributes=attributes):
                    if save_context and user_data is not None:
                        carrier: dict[str, str] = {}
                        inject(carrier)
                        user_data[TRACE_CARRIER_KEY] = carrier
                    return await func(*args, **kwargs)
            finally:
                if token is not None:
                    detach(token)

        return wrapper

    return decorator
