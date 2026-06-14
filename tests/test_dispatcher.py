"""
Тесты для MessageDispatcher
"""
import pytest
import asyncio
from app.services.message_dispatcher import MessageDispatcher


@pytest.mark.asyncio
async def test_dispatcher_add_and_process():
    """Тест добавления сообщений в очередь"""
    processed = []
    
    # Создаем диспетчер с очень быстрой задержкой для теста
    dispatcher = MessageDispatcher(send_delay=0.01)
    
    # Мокаем метод отправки (в реальном коде там будет Playwright)
    async def mock_worker():
        while dispatcher._is_running:
            try:
                msg = await asyncio.wait_for(dispatcher.queue.get(), timeout=0.1)
                processed.append(msg)
                dispatcher.queue.task_done()
            except asyncio.TimeoutError:
                break

    dispatcher._worker_task = asyncio.create_task(mock_worker())
    dispatcher._is_running = True
    
    await dispatcher.add_message("TestUser", "Hello!")
    await asyncio.sleep(0.1) # Ждем обработки
    
    assert len(processed) == 1
    assert processed[0]["nick"] == "TestUser"
    
    await dispatcher.stop()


@pytest.mark.asyncio
async def test_dispatcher_overload():
    """Тест срабатывания уведомления о перегрузке"""
    overload_msgs = []
    
    async def mock_overload(text):
        overload_msgs.append(text)

    # Порог перегрузки = 5
    dispatcher = MessageDispatcher(
        send_delay=10.0, # Очень медленно, чтобы очередь росла
        overload_threshold=5,
        on_overload=mock_overload
    )
    
    # Наполняем очередь
    for i in range(6):
        await dispatcher.add_message(f"User{i}", f"Msg{i}")
        
    # Должно сработать уведомление
    assert len(overload_msgs) == 1
    assert "перегружен" in overload_msgs[0]