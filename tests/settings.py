"""Typed configuration used only by the integration test harness."""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class IntegrationTestSettings(BaseSettings):
    """Control cassette replay and authenticated recording."""

    model_config = SettingsConfigDict(extra="ignore")

    record_cassettes: bool = False
    groq_api_key: str = Field(default="groq-test", min_length=1)
    jina_api_key: str = Field(default="jina-test", min_length=1)

    @model_validator(mode="after")
    def require_real_recording_credentials(self) -> IntegrationTestSettings:
        """Reject recording mode when only deterministic replay keys exist."""
        if self.record_cassettes and (self.groq_api_key == "groq-test" or self.jina_api_key == "jina-test"):
            raise ValueError("GROQ_API_KEY and JINA_API_KEY must be set to real credentials when recording cassettes")
        return self
