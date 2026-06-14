"""
Скрипт запуска бота с правильной настройкой asyncio для Windows
"""
import sys
import asyncio

# КРИТИЧНО: Устанавливаем ProactorEventLoop для Windows ДО запуска uvicorn
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    # ВАЖНО: reload=False, чтобы policy применился корректно
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,  # Отключаем автоперезагрузку
        log_level="info"
    )