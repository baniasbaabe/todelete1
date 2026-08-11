from __future__ import annotations

import ssl

import pytest

from habit_tracker.infrastructure.database.connection import (
    DatabaseSessionManager,
    _connect_args_for,
    _normalize_url,
    verified_ssl_context,
)

AZURE_URL = "postgresql://user:pw@srv.postgres.database.azure.com:5432/habit_tracker"


class TestNormalizeUrl:
    @pytest.mark.parametrize(
        "scheme",
        ["postgresql", "postgres", "postgresql+psycopg2"],
    )
    def test_sync_schemes_are_upgraded_to_asyncpg(self, scheme: str) -> None:
        """create_async_engine rejects sync dialects with 'requires an async driver'."""
        url = _normalize_url(f"{scheme}://user:pw@host:5432/db")
        assert url.drivername == "postgresql+asyncpg"

    def test_asyncpg_scheme_is_left_alone(self) -> None:
        url = _normalize_url("postgresql+asyncpg://user:pw@host:5432/db")
        assert url.drivername == "postgresql+asyncpg"

    def test_libpq_ssl_params_are_stripped(self) -> None:
        """SQLAlchemy forwards unknown query args to asyncpg.connect() as kwargs.

        asyncpg has no sslmode/sslrootcert kwarg, so leaving them raises TypeError.
        """
        url = _normalize_url(f"{AZURE_URL}?sslmode=require&sslrootcert=/ca.pem")
        assert "sslmode" not in url.query
        assert "sslrootcert" not in url.query

    def test_unrelated_query_params_survive(self) -> None:
        url = _normalize_url("postgresql://user:pw@host:5432/db?application_name=bot")
        assert url.query["application_name"] == "bot"

    def test_credentials_are_preserved(self) -> None:
        url = _normalize_url(AZURE_URL)
        assert url.username == "user"
        assert url.password == "pw"  # noqa: S105
        assert url.database == "habit_tracker"


class TestVerifiedSslContext:
    def test_authenticates_the_server(self) -> None:
        """asyncpg's ssl='require' yields CERT_NONE — encrypted but unauthenticated."""
        context = verified_ssl_context()
        assert context.check_hostname is True
        assert context.verify_mode is ssl.CERT_REQUIRED

    def test_has_trust_anchors_loaded(self) -> None:
        assert verified_ssl_context().get_ca_certs()


class TestConnectArgs:
    def test_azure_host_gets_verifying_ssl_context(self) -> None:
        args = _connect_args_for(_normalize_url(AZURE_URL))
        assert isinstance(args["ssl"], ssl.SSLContext)
        assert args["ssl"].check_hostname is True
        assert args["ssl"].verify_mode is ssl.CERT_REQUIRED

    def test_local_host_gets_no_ssl(self) -> None:
        args = _connect_args_for(_normalize_url("postgresql+asyncpg://u:p@localhost:5432/db"))
        assert args == {}

    def test_azure_substring_in_password_does_not_trigger_tls(self) -> None:
        """The host must be matched, not the raw URL text."""
        url = _normalize_url("postgresql+asyncpg://u:x.database.azure.com@localhost:5432/db")
        assert _connect_args_for(url) == {}


class TestDatabaseSessionManager:
    def test_azure_url_is_rewritten_to_async_driver(self) -> None:
        manager = DatabaseSessionManager(AZURE_URL)
        assert manager._engine.url.drivername == "postgresql+asyncpg"

    def test_local_host_does_not_request_tls(self) -> None:
        """Local development against docker-compose has no server certificate."""
        manager = DatabaseSessionManager("postgresql+asyncpg://u:p@localhost:5432/db")
        assert manager._engine.url.host == "localhost"
