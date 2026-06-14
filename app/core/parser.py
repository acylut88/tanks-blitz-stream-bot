"""
Парсер чата VK Live через Playwright
"""
import asyncio
from collections import deque
from typing import Callable, Optional, Dict, Any, List
from playwright.async_api import async_playwright, Page, BrowserContext
from sqlalchemy import select
from app.database.session import async_session
from app.database.models import ProcessedMessage
import structlog

logger = structlog.get_logger()

SELECTORS = {
    "message_root": "//div[contains(@class, 'ChatMessage_root')]",
    "text": 'span[data-role="markup"]',
    "sender": 'span[class*="ChatMessageAuthorPanel_name"]',
    "msg_id_attr": "data-message-id"
}

SYSTEM_SENDER = "ChatBot"


class ChatParser:
    def __init__(
        self,
        chat_url: str,
        on_message: Callable[[Dict[str, Any]], None],
        poll_interval: int = 2,
        cache_limit: int = 500
    ):
        self.chat_url = chat_url
        self.on_message = on_message
        self.poll_interval = poll_interval
        self.cache_limit = cache_limit
        
        self.processed_ids = deque(maxlen=cache_limit)
        
        self._is_running = False
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._last_element_count = 0

    async def load_processed_ids_from_db(self):
        """Загрузить последние ID сообщений из БД при старте"""
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(ProcessedMessage.msg_id)
                    .order_by(ProcessedMessage.created_at.desc())
                    .limit(self.cache_limit)
                )
                rows = result.scalars().all()
                # deque хранит в порядке добавления, поэтому разворачиваем
                for mid in reversed(rows):
                    self.processed_ids.append(mid)
                logger.info("Loaded processed IDs from DB", count=len(rows))
        except Exception as e:
            logger.error("Error loading processed IDs", error=str(e))

    async def is_message_processed(self, msg_id: str) -> bool:
        """Проверить, обработано ли сообщение (в памяти или БД)"""
        if msg_id in self.processed_ids:
            return True
        
        # Проверяем БД (на случай если сообщение старее кэша)
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(ProcessedMessage).filter(ProcessedMessage.msg_id == msg_id)
                )
                return result.scalar_one_or_none() is not None
        except Exception as e:
            logger.error("Error checking message in DB", error=str(e))
            return False

    async def mark_message_processed(self, msg_id: str):
        """Отметить сообщение как обработанное (в памяти и БД)"""
        self.processed_ids.append(msg_id)
        
        try:
            async with async_session() as session:
                # Используем merge/upsert
                existing = await session.execute(
                    select(ProcessedMessage).filter(ProcessedMessage.msg_id == msg_id)
                )
                if not existing.scalar_one_or_none():
                    session.add(ProcessedMessage(msg_id=msg_id))
                    await session.commit()
        except Exception as e:
            logger.error("Error saving processed message", error=str(e))

    async def start(self):
        logger.info("Starting ChatParser", url=self.chat_url)
        self._is_running = True
        
        # Загружаем ID из БД
        await self.load_processed_ids_from_db()
        
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir="./browser_profile",
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        
        try:
            await self._page.goto(self.chat_url, wait_until="networkidle", timeout=60000)
            logger.info("Page loaded, starting poll loop")
            await self._poll_loop()
        except Exception as e:
            logger.error("Parser start error", error=str(e))
            await self.stop()

    async def stop(self):
        self._is_running = False
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("ChatParser stopped")

    async def _poll_loop(self):
        while self._is_running:
            try:
                await self._process_messages()
                await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error("Poll loop error", error=str(e))
                await asyncio.sleep(5)

    async def _process_messages(self):
        if not self._page:
            return

        try:
            elements = await self._page.query_selector_all(SELECTORS["message_root"])
            current_count = len(elements)
            
            # Логируем ТОЛЬКО при изменении количества элементов
            if current_count != self._last_element_count:
                logger.debug("Found message elements", count=current_count)
                self._last_element_count = current_count
            
            if not elements:
                return

            for el in elements[-20:]:
                try:
                    mid = await el.get_attribute(SELECTORS["msg_id_attr"])
                    if not mid:
                        continue
                    
                    # КРИТИЧНО: Проверяем, обработано ли сообщение
                    if await self.is_message_processed(mid):
                        continue

                    text_el = await el.query_selector(SELECTORS["text"])
                    if not text_el:
                        continue
                    text = (await text_el.inner_text()).strip()

                    sender = None
                    sender_el = await el.query_selector(SELECTORS["sender"])
                    if sender_el:
                        sender = (await sender_el.inner_text()).strip().replace(':', '')
                    
                    if not sender:
                        continue

                    # Отмечаем как обработанное СРАЗУ
                    await self.mark_message_processed(mid)

                    msg_data = {
                        "id": mid,
                        "text": text,
                        "sender": sender,
                        "is_system": sender == SYSTEM_SENDER
                    }

                    logger.info("Message parsed successfully", sender=sender, text=text)
                    await self.on_message(msg_data)

                except Exception as e:
                    logger.warning("Error parsing single message", error=str(e))
                    
        except Exception as e:
            logger.error("Error in _process_messages", error=str(e))