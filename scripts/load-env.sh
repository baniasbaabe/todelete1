#!/bin/bash
# Helper script to load environment variables from an env file.

ENV_FILE="${1:-.env}"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: Environment file '$ENV_FILE' not found"
    echo "Usage: source scripts/load-env.sh [env-file]"
    echo ""
    echo "Example:"
    echo "  source scripts/load-env.sh .env"
    return 1 2>/dev/null || exit 1
fi

echo "Loading environment variables from $ENV_FILE..."

# Export variables (skip comments and empty lines)
set -a
source "$ENV_FILE"
set +a

echo "Environment variables loaded"
echo ""
echo "Loaded variables:"
echo "  TELEGRAM_BOT_TOKEN: $([ -n "${TELEGRAM_BOT_TOKEN:-}" ] && echo set || echo missing)"
echo "  GROQ_API_KEY: $([ -n "${GROQ_API_KEY:-}" ] && echo set || echo missing)"
echo "  JINA_API_KEY: $([ -n "${JINA_API_KEY:-}" ] && echo set || echo missing)"
echo "  JINA_EMBEDDING_MODEL: ${JINA_EMBEDDING_MODEL:-jina-embeddings-v5-text-small}"
echo "  LLM_MODEL: ${LLM_MODEL:-qwen/qwen3.6-27b}"
echo "  LLM_TEMPERATURE: ${LLM_TEMPERATURE:-0.2}"
echo ""
echo "You can now run: cd infra/live/<module> && terragrunt apply"
