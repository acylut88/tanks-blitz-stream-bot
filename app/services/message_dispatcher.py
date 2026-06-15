"""
Диспетчер очереди сообщений (Message Dispatcher)
"""
import asyncio
from typing import Callable, Optional
import httpx
import uuid
import urllib.parse
import json
from app.config import settings
import structlog

logger = structlog.get_logger()


class MessageDispatcher:
    """Асинхронная очередь для отправки ЛС с rate-limiting и автоудалением из чата"""
    
    def __init__(
        self,
        send_delay: float = 0.4,
        max_size: int = 200,
        overload_threshold: int = 50,
        on_overload: Optional[Callable] = None,
        auto_delete: bool = True  # 🔥 НОВОЕ: автоудаление из чата
    ):
        self.queue = asyncio.Queue(maxsize=max_size)
        self.send_delay = send_delay
        self.overload_threshold = overload_threshold
        self.on_overload = on_overload
        self.auto_delete = auto_delete
        
        self._is_running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._overload_notified = False

    async def start(self):
        """Запустить фоновый worker"""
        if self._is_running:
            return
        self._is_running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("MessageDispatcher started", delay=self.send_delay, auto_delete=self.auto_delete)

    async def stop(self):
        """Остановить worker"""
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("MessageDispatcher stopped")

    async def add_message(self, nick: str, text: str, priority: int = 0):
        """Добавить сообщение в очередь"""
        if self.queue.full():
            logger.warning("Queue is full, dropping message", nick=nick)
            return

        await self.queue.put({
            "nick": nick,
            "text": text,
            "priority": priority,
            "timestamp": asyncio.get_event_loop().time()
        })

        # Проверка на перегруз
        if self.queue.qsize() >= self.overload_threshold:
            await self._handle_overload()

    async def _handle_overload(self):
        """Обработка перегрузки очереди"""
        if not self._overload_notified and self.on_overload:
            queue_size = self.queue.qsize()
            estimated_wait = int(queue_size * self.send_delay)
            msg = f"⚠️ Командиры, штаб перегружен! В очереди {queue_size} донесений. Ожидание ~{estimated_wait} сек. Не паникуйте! 🛡"
            await self.on_overload(msg)
            self._overload_notified = True
            logger.warning("Overload notification sent", size=queue_size)
        elif self.queue.qsize() < (self.overload_threshold * 0.5):
            self._overload_notified = False

    async def _send_private_message(self, nick: str, text: str) -> Optional[int]:
        """
        Отправить ЛС через VK Live API
        Возвращает ID сообщения если успешно, None если ошибка
        """
        if not settings.vk_live_token:
            logger.error("VK Live token not configured")
            return None
        
        try:
            # Убираем переносы строк
            clean_text = text.replace('\n', ' ').strip()
            
            # Формируем команду /w
            message_content = f"/w {nick} {clean_text}"
            
            # Формируем JSON с экранированием
            content_json = json.dumps([message_content, "unstyled", []], ensure_ascii=False)
            content_json = content_json.replace('/', '\\/')
            
            # Основной payload
            payload = [
                {
                    "type": "text",
                    "content": content_json,
                    "modificator": ""
                },
                {
                    "type": "text",
                    "content": "",
                    "modificator": "BLOCK_END"
                }
            ]
            
            # URL-encoding
            data = urllib.parse.urlencode({"data": json.dumps(payload, ensure_ascii=False)})
            
            # Заголовки
            headers = {
                "Authorization": f"Bearer {settings.vk_live_token}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://live.vkvideo.ru",
                "Referer": f"https://live.vkvideo.ru/{settings.vk_channel_name}/stream/default/only-chat",
                "X-App": "streams_web",
                "X-From-Id": str(uuid.uuid4()),
                "X-Trans-Path": str(uuid.uuid4()),
                "X-Trans-Target": "blog_url_stream_slot_url_only-chat",
                "X-Trans-Via": "chat",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            }
            
            # URL API
            url = f"https://api.live.vkvideo.ru/v1/channel/{settings.vk_channel_name}/stream/slot/default/chat"
            
            # Отправляем запрос
            async with httpx.AsyncClient() as client:
                response = await client.post(url, content=data, headers=headers, timeout=10.0)
                
                if response.status_code == 200:
                    result = response.json()
                    message_id = result.get("id")
                    
                    if result.get("isPrivate"):
                        logger.info("PM sent successfully", nick=nick, message_id=message_id)
                        return message_id
                    else:
                        logger.warning("Message sent but not private", nick=nick, message_id=message_id)
                        return message_id  # Всё равно возвращаем ID для удаления
                else:
                    logger.error("Failed to send PM", status=response.status_code, text=response.text)
                    return None
                    
        except Exception as e:
            logger.error("Error sending PM", nick=nick, error=str(e), exc_info=True)
            return None

    async def _delete_message(self, message_id: int) -> bool:
        """
        Удалить сообщение из чата
        """
        if not settings.vk_live_token:
            logger.error("VK Live token not configured")
            return False
        
        try:
            # URL для удаления
            url = f"https://api.live.vkvideo.ru/v1/blog/{settings.vk_channel_name}/public_video_stream/chat/{message_id}"
            
            # Заголовки
            headers = {
                "Authorization": f"Bearer {settings.vk_live_token}",
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://live.vkvideo.ru",
                "Referer": f"https://live.vkvideo.ru/{settings.vk_channel_name}/stream/default/only-chat",
                "X-App": "streams_web",
                "X-From-Id": str(uuid.uuid4()),
                "X-Trans-Path": str(uuid.uuid4()),
                "X-Trans-Target": "blog_url_stream_slot_url_only-chat",
                "X-Trans-Via": "chat",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            }
            
            # Отправляем DELETE запрос
            async with httpx.AsyncClient() as client:
                response = await client.delete(url, headers=headers, timeout=10.0)
                
                if response.status_code == 200:
                    logger.info("Message deleted from chat", message_id=message_id)
                    return True
                else:
                    logger.warning("Failed to delete message", message_id=message_id, status=response.status_code)
                    return False
                    
        except Exception as e:
            logger.error("Error deleting message", message_id=message_id, error=str(e))
            return False

    async def _worker(self):
        """Основной цикл отправки"""
        while self._is_running:
            try:
                msg = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                
                # Проверяем возраст сообщения
                wait_time = asyncio.get_event_loop().time() - msg["timestamp"]
                if wait_time > 30:
                    logger.warning("Message too old, skipping", nick=msg["nick"], wait_time=wait_time)
                    self.queue.task_done()
                    continue
                
                # Отправляем через API и получаем ID
                message_id = await self._send_private_message(msg["nick"], msg["text"])
                
                if message_id:
                    # 🔥 НОВОЕ: Удаляем сообщение из чата
                    if self.auto_delete:
                        await asyncio.sleep(0.5)  # Небольшая задержка для доставки ЛС
                        await self._delete_message(message_id)
                else:
                    logger.warning("Failed to send, retrying in 5s", nick=msg["nick"])
                    await asyncio.sleep(5)
                    message_id = await self._send_private_message(msg["nick"], msg["text"])
                    if message_id and self.auto_delete:
                        await asyncio.sleep(0.5)
                        await self._delete_message(message_id)
                
                # Rate limiting
                await asyncio.sleep(self.send_delay)
                self.queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Worker error", error=str(e), exc_info=True)
                await asyncio.sleep(1)