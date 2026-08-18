"""Integration harness configuration remains typed and recording-safe."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from tests.settings import IntegrationTestSettings


def test_cassette_recording_rejects_replay_credentials() -> None:
    with pytest.raises(ValidationError, match="must be set to real credentials"):
        IntegrationTestSettings(
            record_cassettes=True,
            groq_api_key="groq-test",
            jina_api_key="jina-test",
        )


def test_cassette_recording_accepts_explicit_provider_credentials() -> None:
    settings = IntegrationTestSettings(
        record_cassettes=True,
        groq_api_key="recording-groq-key",
        jina_api_key="recording-jina-key",
    )

    assert settings.record_cassettes is True
