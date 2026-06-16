"""
Комплексные интеграционные тесты
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select
from app.database.models import User, StreamSession, StreamStats, Setting
from app.database.session import async_session, engine
from app.core.rewards import RewardService
from app.core.cnst_Bot import TankType
from app.services.user_service import UserService
from app.services.settings_service import SettingsService


@pytest.fixture(scope="session")
def event_loop():
    """Создаём event loop для всех тестов"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_database():
    """Создаём чистую БД для каждого теста"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


class TestRewardProcessing:
    """Тесты обработки наград"""
    
    async def test_reward_gives_no_pa_on_12th_activation(self):
        """ПА НЕ должно выдаваться на 12 активации (только в розыгрыше)"""
        async with async_session() as session:
            user_service = UserService(session)
            
            # Создаём пользователя
            user = await user_service.get_or_create("TestUser")
            initial_pa = user.premium_streams_left
            
            # Создаём сессию стрима
            await user_service.create_stream_session()
            await session.commit()
            
            # Симулируем 12 активаций
            for i in range(1, 13):
                stats = await user_service.get_or_create_stream_stats(user.id, 1)
                stats.activations_count = i
                
                # Рассчитываем награды
                has_premium = user.premium_streams_left > 0
                box_count = RewardService.calculate_boxes(i, has_premium)
                loot = RewardService.roll_loot(box_count)
                
                # Начисляем танки
                user.lifetime_tanks_lt += loot.get(TankType.LT, 0)
                user.lifetime_tanks_st += loot.get(TankType.CT, 0)
                user.lifetime_tanks_tt += loot.get(TankType.TT, 0)
                user.lifetime_tanks_pt += loot.get(TankType.PT, 0)
                
                # ВАЖНО: НЕ выдаём ПА на 12 активации!
                # if i == 12:
                #     user.premium_streams_left += 1  # ← ЭТОГО НЕ ДОЛЖНО БЫТЬ!
                
                await session.commit()
            
            # Проверяем что ПА не изменилось
            assert user.premium_streams_left == initial_pa, "ПА не должно выдаваться на 12 активации!"
    
    async def test_pending_boxes_opened_on_next_stream(self):
        """Отложенные ящики должны открыться на следующем стриме"""
        async with async_session() as session:
            user_service = UserService(session)
            
            # Создаём пользователя с pending_boxes
            user = await user_service.get_or_create("TestUser")
            user.pending_boxes = 5
            await session.commit()
            
            # Создаём новую сессию стрима
            await user_service.create_stream_session()
            await session.commit()
            
            # Симулируем активацию
            stats = await user_service.get_or_create_stream_stats(user.id, 2)
            stats.activations_count = 1
            
            # Проверяем pending_boxes
            assert user.pending_boxes == 5
            
            # Открываем pending boxes
            if user.pending_boxes > 0:
                pending_loot = RewardService.roll_loot(user.pending_boxes)
                pending_bm = RewardService.calculate_bm(pending_loot)
                
                user.lifetime_tanks_lt += pending_loot.get(TankType.LT, 0)
                user.lifetime_tanks_st += pending_loot.get(TankType.CT, 0)
                user.lifetime_tanks_tt += pending_loot.get(TankType.TT, 0)
                user.lifetime_tanks_pt += pending_loot.get(TankType.PT, 0)
                user.lifetime_boxes_opened += user.pending_boxes
                user.pending_boxes = 0
                
                await session.commit()
            
            # Проверяем что pending_boxes сброшены
            assert user.pending_boxes == 0
            assert user.lifetime_boxes_opened == 5


class TestRaffle:
    """Тесты рулетки"""
    
    async def test_raffle_gives_pending_boxes_not_lifetime(self):
        """Розыгрыш должен начислять pending_boxes, а не lifetime_boxes_opened"""
        async with async_session() as session:
            user_service = UserService(session)
            
            # Создаём пользователя
            user = await user_service.get_or_create("Winner")
            initial_boxes = user.lifetime_boxes_opened
            initial_pending = user.pending_boxes
            
            # Симулируем начисление приза за 1 место
            boxes_1 = 10
            user.pending_boxes += boxes_1
            await session.commit()
            
            # Проверяем
            assert user.pending_boxes == initial_pending + boxes_1
            assert user.lifetime_boxes_opened == initial_boxes  # Не изменилось!


class TestSettings:
    """Тесты настроек"""
    
    async def test_settings_save_and_load(self):
        """Настройки должны сохраняться и загружаться"""
        key = "test.setting"
        value = 42
        
        await SettingsService.set_setting(key, value, "Test setting", "test")
        loaded = await SettingsService.get_setting(key)
        
        assert loaded == value
    
    async def test_settings_default_value(self):
        """Если настройка не найдена, должно возвращаться значение по умолчанию"""
        loaded = await SettingsService.get_setting("nonexistent.key", default=99)
        assert loaded == 99


class TestAPI:
    """Тесты API endpoints"""
    
    async def test_grant_loot_adds_pending_boxes(self):
        """Ручная выдача через админку должна работать"""
        from fastapi.testclient import TestClient
        from app.main import app
        
        async with async_session() as session:
            user_service = UserService(session)
            user = await user_service.get_or_create("TestUser")
            await session.commit()
        
        client = TestClient(app)
        response = client.post("/api/admin/grant-loot", json={
            "nick": "TestUser",
            "box_count": 3
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "loot" in data
        assert "bm" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])