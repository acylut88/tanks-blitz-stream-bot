"""
FastAPI приложение и управление жизненным циклом бота
"""
from app.api.routes import router as web_router
from app.api.websocket import router as websocket_router
from app.bot.handler import MessageHandler
from app.config import settings
from app.core.parser import ChatParser
from app.core.vk_api import VKLiveAPIClient
from app.services.message_dispatcher import MessageDispatcher
from app.services.settings_service import SettingsService
from app.services.user_sync import UserSyncService
from contextlib import asynccontextmanager
from fastapi import FastAPI
import structlog

logger = structlog.get_logger()

# Глобальные экземпляры сервисов
dispatcher = None
parser = None
handler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление запуском и остановкой фоновых задач"""
    global dispatcher, parser, handler
    
    logger.info("Starting Tanks Blitz Bot...")

    
    # 1. Инициализация сервисов
    vk_api = VKLiveAPIClient(settings.vk_channel_name)
    dispatcher = MessageDispatcher(
        send_delay=settings.message_delay,
        max_size=settings.queue_max_size,
        overload_threshold=settings.overload_threshold,
        on_overload=lambda msg: dispatcher.add_message(settings.vk_channel_owner_name, msg) if dispatcher else None
    )
    
    handler = MessageHandler(dispatcher)
    parser = ChatParser(
        chat_url=settings.chat_page_url,
        on_message=handler.handle,
        poll_interval=settings.bot_poll_interval,
        cache_limit=settings.bot_cache_limit
    )
    
    sync_service = UserSyncService(vk_api)
    
    # 2. Запуск фоновых задач
    await dispatcher.start()
    # 🔥 Добавляем в app.state
    app.state.dispatcher = dispatcher

    # parser.start() блокирует, поэтому запускаем в фоне
    import asyncio
    parser_task = asyncio.create_task(parser.start())
    sync_task = asyncio.create_task(sync_service.run_periodic_sync())
    
    logger.info("All background tasks started")
    
    yield  # Здесь работает FastAPI
    
    # 3. Корректное завершение
    logger.info("Shutting down...")
    parser_task.cancel()
    sync_task.cancel()
    await dispatcher.stop()
    await parser.stop()
    logger.info("Bot stopped")

    # 4. Инициализируем настройки по умолчанию
    await SettingsService.initialize_defaults()


app = FastAPI(title="Tanks Blitz Stream Bot", lifespan=lifespan)

app.include_router(web_router)
app.include_router(websocket_router)

@app.get("/")
async def root():
    return {"status": "ok", "bot": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy", "queue_size": dispatcher.queue.qsize() if dispatcher else 0}


# Запуск через uvicorn: uvicorn app.main:app --reload