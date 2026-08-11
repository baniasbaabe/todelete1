set dotenv-load := true

# Show available commands.
default:
    @just --list

# Create the local environment file without overwriting existing secrets.
init:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -f .env ]]; then
        echo ".env already exists; leaving it unchanged."
    else
        cp .env.example .env
        echo "Created .env. Add your Telegram, Groq, and Jina API keys."
    fi

# Verify that local credentials have been configured.
check-env:
    #!/usr/bin/env bash
    set -euo pipefail
    telegram_token="${TELEGRAM_BOT_TOKEN:-}"
    if [[ -z "${telegram_token}" || "${telegram_token}" == "your-token" ]]; then
        echo "Set TELEGRAM_BOT_TOKEN in .env (get one from @BotFather)." >&2
        exit 1
    fi
    groq_key="${GROQ_API_KEY:-}"
    jina_key="${JINA_API_KEY:-}"

    has_valid_key() {
        local key="$1"
        [[ -n "${key}" \
            && "${key}" != "your-key" \
            && "${key}" != "your-groq-api-key" \
            && "${key}" != "your-jina-api-key" ]]
    }

    if ! has_valid_key "${groq_key}"; then
        echo "Set GROQ_API_KEY in .env." >&2
        exit 1
    fi
    if ! has_valid_key "${jina_key}"; then
        echo "Set JINA_API_KEY in .env." >&2
        exit 1
    fi

# Stop local containers without deleting database data.
down:
    docker compose down

# Apply all database migrations.
migrate:
    uv run alembic upgrade head

# Prepare a local development environment.
setup: init
    uv sync
    docker compose up -d --wait --wait-timeout 30
    @just migrate
    @echo "Setup complete."

# Set up dependencies and run the bot locally using Telegram polling.
dev: init
    @just check-env
    @just setup
    uv run habit-tracker

# Run the test suite.
test:
    uv run pytest -n auto

# Record missing Groq and Jina API cassettes using credentials from .env.
record-cassettes:
    #!/usr/bin/env bash
    set -euo pipefail
    RECORD_CASSETTES=1 uv run pytest tests/integration/ -v

# Run lint and formatting checks.
check:
    uv run prek run --all-files
