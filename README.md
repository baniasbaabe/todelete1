# AI Habit Tracker Bot

A Telegram habit tracker that can verify check-ins with text, photos, or a
short quiz. It uses Groq's native SDK for AI proof verification, PostgreSQL with pgvector
for data and memory, and Phoenix for optional tracing.

## Run it locally

You need Docker, [uv](https://docs.astral.sh/uv/),
[just](https://just.systems/), a Telegram bot token from
[BotFather](https://t.me/botfather), a Groq API key, and a Jina AI API key.

```bash
git clone <repository-url>
cd ai-habit-bot
just init
```

Open `.env` and set:

```dotenv
TELEGRAM_BOT_TOKEN=your-token
GROQ_API_KEY=your-groq-api-key
JINA_API_KEY=your-jina-api-key
JINA_EMBEDDING_MODEL=jina-embeddings-v5-text-small
LLM_MODEL=qwen/qwen3.6-27b
```

Then run:

```bash
just dev
```

`just dev` installs the Python dependencies, starts PostgreSQL and the local
Arize Phoenix observability UI, waits for the services, applies the Alembic
migrations, and starts the bot with Telegram polling.

The only supported AI stack is Groq plus Jina. The native Groq SDK sends all
chat, JSON, and photo-proof requests to the multimodal `qwen/qwen3.6-27b` model. Mem0
uses the same Groq model for memory extraction and Jina through LangChain for
embeddings:

```dotenv
JINA_API_KEY=your-jina-api-key
JINA_EMBEDDING_MODEL=jina-embeddings-v5-text-small
MEM0_EMBEDDING_DIMS=1024
MEM0_COLLECTION_NAME=memories
```


### Bot commands

```text
/start
/add_habit <name>
/list_habits
/delete_habit <name>
/checkin
/help
```

### Useful development commands

```bash
just                 # List all recipes
just setup           # Prepare the app without running the bot
just down            # Stop containers without deleting database data
just test            # Run the test suite
just check           # Run Ruff lint and formatting checks
```

Unit tests use in-process fakes. Integration tests use a real PostgreSQL
Testcontainer and replay committed VCR.py recordings. To create missing API
recordings with the Groq and Jina keys in `.env`, run `just record-cassettes`.

Phoenix is available at `http://localhost:6006` after `just setup` or `just dev`.
The default credentials are `admin@localhost` / `admin`. Log in, create a
project (e.g. `habit-tracker`), then go to **Settings → API Keys** to generate
a key. Set `PHOENIX_API_KEY` to that key and `ENABLE_TRACING=true` when you
want the bot to send local traces.

## Project layout

```text
src/habit_tracker/
├── domain/          Entities, value objects, and domain rules
├── application/     Use cases and ports
├── infrastructure/  PostgreSQL, Groq, mem0, logging, and tracing
└── presentation/    Telegram handlers and application startup
```

## Database changes

Alembic owns the schema. Application code must not create or alter tables.

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

## Deploy to Azure

Azure deployment uses GitHub Actions with OIDC. There is no Azure client secret
and no `.env.azure` file.

The one-time bootstrap needs an Azure subscription, permission to create role
assignments and a Microsoft Entra application, and a resource-group name chosen
by you.

```bash
az login
az account set --subscription "<subscription ID or name>"
./scripts/bootstrap-azure-github.sh <owner>/<repository> <resource-group>
```

The script creates the resource group, GitHub OIDC identity, and encrypted state
storage. It prints the generated Azure IDs, state settings, and the remaining
secrets to add to the GitHub `production` environment. After adding them, open
**Actions -> Deploy -> Run workflow** and leave both deployment options enabled.

Terragrunt then creates ACR, Key Vault, PostgreSQL, Phoenix, and the Web App.
Future pushes to `main` deploy only the paths that changed.

Read the [Azure deployment guide](docs/azure-deployment.md) for the full setup,
security model, troubleshooting, and cleanup.

## Configuration

Local defaults are documented in [.env.example](.env.example). The required
application settings are:

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot authentication |
| `GROQ_API_KEY` | Required for all LLM calls |
| `JINA_API_KEY` | Required for the LangChain Jina embedder |
| `JINA_EMBEDDING_MODEL` | Jina embedding model, default `jina-embeddings-v5-text-small` |
| `DATABASE_URL` | Async PostgreSQL connection |
| `LLM_MODEL` | Native Groq model ID, default `qwen/qwen3.6-27b` |
| `LLM_TEMPERATURE` | Model temperature, default `0.2` |
| `MEM0_EMBEDDING_DIMS` | Embedding vector dimensions; `1024` for Jina v5 text small |
| `MEM0_COLLECTION_NAME` | Mem0 pgvector collection/table name |
| `MEM0_TELEMETRY` | Keep Mem0's anonymous PostHog telemetry disabled; default `false` |
| `COLLECTOR_ENDPOINT` | Phoenix OTLP HTTP endpoint; local default `http://localhost:6006/v1/traces` |
| `PHOENIX_API_KEY` | Required when tracing is enabled against the authenticated Phoenix service |
| `ENABLE_TRACING` | Enable Groq and application traces; default `false` |

`WEBHOOK_URL` and `WEBHOOK_SECRET` stay empty locally. Azure derives its webhook
URL from the Web App hostname and generates the verification secret in Key
Vault.
