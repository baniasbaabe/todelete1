from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import habit_tracker.infrastructure.observability.tracing as tracing_module


@pytest.fixture(autouse=True)
def reset_tracer():
    """Ensure _tracer is None before and after each test."""
    tracing_module._tracer = None
    yield
    tracing_module._tracer = None


class TestTraceNoOp:
    """trace() is a no-op when _tracer is None."""

    async def test_decorated_function_executes(self):
        @tracing_module.trace("test_handler", handler="test_handler")
        async def handler():
            return "ok"

        assert await handler() == "ok"

    async def test_decorated_function_receives_args(self):
        @tracing_module.trace("test_handler", handler="test_handler")
        async def handler(a, b, *, c=10):
            return a + b + c

        assert await handler(1, 2, c=3) == 6

    async def test_decorated_function_propagates_exception(self):
        @tracing_module.trace("test_handler", handler="test_handler")
        async def handler():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await handler()

    async def test_wraps_preserves_function_name(self):
        @tracing_module.trace("test_handler", handler="test_handler")
        async def my_handler():
            pass

        assert my_handler.__name__ == "my_handler"

    async def test_custom_attributes(self):
        @tracing_module.trace("test_op", op_type="repo")
        async def operation():
            return 42

        assert await operation() == 42


class TestTraceWithTracer:
    """trace() creates spans when _tracer is set."""

    async def test_handler_span(self):
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        tracing_module._tracer = mock_tracer

        @tracing_module.trace("my_handler", handler="my_handler")
        async def handler():
            return "traced"

        assert await handler() == "traced"
        mock_tracer.start_as_current_span.assert_called_once_with("my_handler", attributes={"handler": "my_handler"})

    async def test_operation_span(self):
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        tracing_module._tracer = mock_tracer

        @tracing_module.trace("my_op", op_type="repo")
        async def operation():
            return "traced"

        assert await operation() == "traced"
        mock_tracer.start_as_current_span.assert_called_once_with("my_op", attributes={"op_type": "repo"})


class TestSetupTracing:
    """setup_tracing disables tracing when setup fails."""

    def test_setup_tracing_instruments_groq(self):
        tracer_provider = MagicMock()
        tracer = MagicMock()
        tracer_provider.get_tracer.return_value = tracer

        with (
            patch.object(tracing_module, "register", return_value=tracer_provider) as register,
            patch.object(tracing_module.GroqInstrumentor, "instrument") as instrument,
        ):
            tracing_module.setup_tracing("http://localhost:6006/v1/traces", "phoenix-key")

        register.assert_called_once_with(
            endpoint="http://localhost:6006/v1/traces",
            project_name="habit-tracker",
            api_key="phoenix-key",
        )
        instrument.assert_called_once_with(tracer_provider=tracer_provider)
        assert tracing_module._tracer is tracer

    def test_setup_tracing_skips_exporter_without_api_key(self):
        with patch.object(tracing_module, "register") as register:
            tracing_module.setup_tracing("http://localhost:6006/v1/traces")

        register.assert_not_called()
        assert tracing_module._tracer is None

    async def test_setup_tracing_handles_setup_error(self):
        with patch.object(tracing_module, "register", side_effect=RuntimeError("test setup failure")):
            tracing_module.setup_tracing("http://localhost:6006/v1/traces", "phoenix-key")

        assert tracing_module._tracer is None
