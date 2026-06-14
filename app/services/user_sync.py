"""
Сервис синхронизации зрителей с VK Live API
"""
import asyncio
from typing import List, Dict
from app.core.vk_api import VKLiveAPIClient
from app.services.user_service import UserService
from app.database.session import async_session
import structlog

logger = structlog.get_logger()


class UserSyncService:
    """Сервис для синхронизации списка зрителей с БД"""
    
    def __init__(self, vk_api: VKLiveAPIClient, sync_interval: int = 300):
        self.vk_api = vk_api
        self.sync_interval = sync_interval  # 5 минут
    
    async def sync_viewers(self):
        """Синхронизировать список зрителей с БД"""
        try:
            # Получаем список зрителей из API
            viewers = await self.vk_api.get_online_viewers()
            
            if not viewers:
                logger.warning("No viewers fetched from API")
                return
            
            async with async_session() as session:
                user_service = UserService(session)
                
                for viewer in viewers:
                    vk_id = viewer.get('id')
                    nick = viewer.get('nick')
                    
                    if not vk_id or not nick:
                        continue
                    
                    # Ищем пользователя по vk_id
                    user = await user_service.get_by_vk_id(vk_id)
                    
                    if user:
                        # Найден по vk_id — обновляем ник (если изменился)
                        if user.nick != nick:
                            logger.info("Nick changed", vk_id=vk_id, old_nick=user.nick, new_nick=nick)
                            user.nick = nick
                    else:
                        # Не найден по vk_id — ищем по nick
                        user = await user_service.get_by_nick(nick)
                        
                        if user:
                            # Найден по nick — привязываем vk_id
                            logger.info("Linked vk_id", vk_id=vk_id, nick=nick)
                            user.vk_id = vk_id
                        else:
                            # Не найден — создаём нового
                            logger.info("New viewer", vk_id=vk_id, nick=nick)
                            await user_service.get_or_create(nick, vk_id)
                
                await session.commit()
                logger.info("Viewers synced", count=len(viewers))
        
        except Exception as e:
            logger.error("Error syncing viewers", error=str(e))
    
    async def run_periodic_sync(self):
        """Фоновая задача: синхронизация каждые N секунд"""
        logger.info("Starting periodic user sync", interval=self.sync_interval)
        
        while True:
            try:
                await self.sync_viewers()
                await asyncio.sleep(self.sync_interval)
            except Exception as e:
                logger.error("Error in periodic sync", error=str(e))
                await asyncio.sleep(60)  # При ошибке ждём минуту