from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from habit_tracker.infrastructure.ai.llm_client import GroqLLMClient
from habit_tracker.infrastructure.ai.pattern_analyzer import LLMPatternAnalyzer
from habit_tracker.infrastructure.ai.proof_verifier import LLMProofVerifier
from habit_tracker.infrastructure.config.settings import Settings
from habit_tracker.infrastructure.database.connection import DatabaseSessionManager
from habit_tracker.infrastructure.logging.logger import configure_logging
from habit_tracker.infrastructure.memory.mem0_store import Mem0MemoryStore
from habit_tracker.infrastructure.observability.tracing import setup_tracing
from habit_tracker.infrastructure.persistence.postgres_persistence import PostgresPersistence
from habit_tracker.presentation.dependencies import Dependencies, install
from habit_tracker.presentation.handlers.checkin_handlers import checkin_handler
from habit_tracker.presentation.handlers.command_handlers import (
    add_habit_handler,
    delete_habit_handler,
    help_handler,
    list_habits_handler,
    start_handler,
)
from habit_tracker.presentation.handlers.proof_handlers import (
    photo_response_handler,
    text_response_handler,
)

logger = structlog.get_logger()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("unhandled_exception", error=str(context.error), exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("Something went wrong. Please try again later.")


def main() -> None:
    configure_logging()
    settings = Settings()

    if settings.enable_tracing and settings.collector_endpoint:
        setup_tracing(settings.collector_endpoint, settings.phoenix_api_key)

    db = DatabaseSessionManager(settings.database_url)
    llm = GroqLLMClient(settings.groq_api_key, settings.llm_model, settings.llm_temperature)
    proof_verifier = LLMProofVerifier(llm)
    memory_store = Mem0MemoryStore(settings.get_mem0_config(), telemetry_enabled=settings.mem0_telemetry)
    pattern_analyzer = LLMPatternAnalyzer(llm, memory_store)
    persistence = PostgresPersistence(settings.database_url)

    app = ApplicationBuilder().token(settings.telegram_bot_token).persistence(persistence).build()

    dependencies = Dependencies(
        db=db,
        proof_verifier=proof_verifier,
        memory_store=memory_store,
        pattern_analyzer=pattern_analyzer,
    )

    # post_init runs after Application.initialize(), which reassigns bot_data
    # from persistence. Wiring any earlier is silently discarded.
    async def wire_dependencies(app_instance: object) -> None:
        install(app_instance, dependencies)

    app.post_init = wire_dependencies

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("add_habit", add_habit_handler))
    app.add_handler(CommandHandler("list_habits", list_habits_handler))
    app.add_handler(CommandHandler("delete_habit", delete_habit_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("checkin", checkin_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_response_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_response_handler))
    app.add_error_handler(error_handler)

    async def shutdown_cleanup(app_instance: object) -> None:
        await llm.close()
        await db.close()
        await persistence.close()

    app.post_shutdown = shutdown_cleanup

    logger.info("bot_starting", webhook_url=settings.webhook_url)

    if settings.webhook_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=8443,
            webhook_url=f"{settings.webhook_url}/webhook",
            secret_token=settings.webhook_secret,
        )
    else:
        app.run_polling()


if __name__ == "__main__":
    main()
