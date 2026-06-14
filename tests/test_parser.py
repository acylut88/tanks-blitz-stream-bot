"""
Тесты для ChatParser (с моками Playwright)
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from app.core.parser import ChatParser


@pytest.mark.asyncio
async def test_parser_extracts_messages():
    """Тест извлечения сообщений из мокированного DOM"""
    received_msgs = []
    
    async def on_message(msg_data):
        received_msgs.append(msg_data)

    parser = ChatParser(
        chat_url="http://test",
        on_message=on_message,
        poll_interval=0.1
    )

    # Мокаем страницу и элементы
    mock_page = AsyncMock()
    parser._page = mock_page

    # Создаем фейковые элементы DOM
    mock_el1 = AsyncMock()
    mock_el1.get_attribute.return_value = "msg_1"
    mock_el1.query_selector.side_effect = [
        AsyncMock(inner_text=AsyncMock(return_value="Привет чат!")), # text
        AsyncMock(inner_text=AsyncMock(return_value="User1"))        # sender
    ]

    mock_el2 = AsyncMock()
    mock_el2.get_attribute.return_value = "msg_2"
    mock_el2.query_selector.side_effect = [
        AsyncMock(inner_text=AsyncMock(return_value="Получает награду...")), 
        AsyncMock(inner_text=AsyncMock(return_value="ChatBot"))        
    ]

    mock_page.query_selector_all.return_value = [mock_el1, mock_el2]

    # Запускаем один цикл обработки
    await parser._process_messages()

    assert len(received_msgs) == 2
    assert received_msgs[0]["sender"] == "User1"
    assert received_msgs[1]["is_system"] is True
    
    # Проверяем, что ID попали в кэш
    assert "msg_1" in parser.processed_ids
    assert "msg_2" in parser.processed_ids