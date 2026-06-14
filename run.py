"""
Скрипт запуска бота с правильной настройкой asyncio для Windows
"""
import sys
import asyncio
import logging

# КРИТИЧНО: Устанавливаем ProactorEventLoop для Windows ДО запуска uvicorn
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Подавляем шум от asyncio при разрыве WebSocket-соединений (Windows-specific)
def _suppress_connection_reset(loop, context):
    """Кастомный обработчик исключений event loop"""
    exception = context.get('exception')
    # Игнорируем разрывы соединений — это нормально при обновлении страницы
    if isinstance(exception, (ConnectionResetError, ConnectionAbortedError)):
        return
    # Всё остальное — логируем как обычно
    loop.default_exception_handler(context)

# Применяем обработчик к текущему event loop
loop = asyncio.new_event_loop()
loop.set_exception_handler(_suppress_connection_reset)
asyncio.set_event_loop(loop)

# Также приглушаем логгер asyncio (опционально)
logging.getLogger("asyncio").setLevel(logging.ERROR)

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info"
    )