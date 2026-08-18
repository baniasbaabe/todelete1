FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS builder

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY alembic/ alembic/
COPY alembic.ini .

RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.13-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8

WORKDIR /app

# Root CA bundle for verifying the Azure PostgreSQL server certificate.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --home-dir /app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /app/.venv /app/.venv

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/startup.sh scripts/startup.sh

RUN chmod +x scripts/startup.sh \
    && chown -R 10001:10001 /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# TLS for every libpq-based consumer in the image (Alembic via psycopg2, and
# mem0's pgvector store). verify-full authenticates the server and checks the
# hostname; the libpq default of "prefer" would silently accept plaintext.
# The asyncpg paths configure an equivalent SSLContext in code.
ENV PGSSLMODE=verify-full
ENV PGSSLROOTCERT=/etc/ssl/certs/ca-certificates.crt

EXPOSE 8443

USER 10001:10001

ENTRYPOINT ["/app/scripts/startup.sh"]
