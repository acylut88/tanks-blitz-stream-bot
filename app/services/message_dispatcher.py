"""
Диспетчер очереди сообщений (Message Dispatcher)
"""
import asyncio
from typing import Callable, Optional
import structlog

logger = structlog.get_logger()


class MessageDispatcher:
    """Асинхронная очередь для отправки ЛС с rate-limiting"""

    def __init__(
        self,
        send_delay: float = 0.4,
        max_size: int = 200,
        overload_threshold: int = 50,
        on_overload: Optional[Callable] = None
    ):
        self.queue = asyncio.Queue(maxsize=max_size)
        self.send_delay = send_delay
        self.overload_threshold = overload_threshold
        self.on_overload = on_overload  # Колбэк для уведомления о перегрузе
        
        self._is_running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._overload_notified = False

    async def start(self):
        """Запустить фоновый worker"""
        if self._is_running:
            return
        self._is_running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("MessageDispatcher started", delay=self.send_delay)

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
        """
        Добавить сообщение в очередь.
        priority: 0 = обычное, 1 = высокое (команды, редкие дропы)
        """
        if self.queue.full():
            logger.warning("Queue is full, dropping message", nick=nick)
            return

        # Простая реализация приоритета: высокие кидаем в начало (через отдельную очередь или просто сразу)
        # Для простоты используем одну очередь, но в реальном проде лучше PriorityQueue
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

    async def _worker(self):
        """Основной цикл отправки"""
        while self._is_running:
            try:
                msg = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                
                # Здесь будет реальный вызов VK API через Playwright
                # Пока просто логируем
                logger.info("Sending PM", nick=msg["nick"], text=msg["text"])
                
                # Имитация задержки сети
                await asyncio.sleep(self.send_delay)
                
                self.queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Dispatcher worker error", error=str(e))
                await asyncio.sleep(1)