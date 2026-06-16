"""
Тесты системы прогрессивного шанса выпадения ПА из боксов
Unit-тесты без зависимости от БД
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.pa_chance_service import PAChanceService


class TestPACalculation:
    """Тесты расчёта шанса ПА (чистая математика)"""
    
    @pytest.mark.asyncio
    async def test_base_chance_on_first_box(self):
        """На 1-м боксе шанс = 0.6% (0.005 + 1×0.001)"""
        with patch('app.services.pa_chance_service.SettingsService') as mock_service:
            mock_service.get_setting = AsyncMock(side_effect=[
                0.005,  # base_chance
                0.001,  # chance_step
                50      # pity_threshold
            ])
            
            chance = await PAChanceService.calculate_chance(1)
            assert abs(chance - 0.006) < 0.0001, f"Ожидалось 0.006, получено {chance}"
    
    @pytest.mark.asyncio
    async def test_chance_on_fifth_box(self):
        """На 5-м боксе шанс = 1.0%"""
        with patch('app.services.pa_chance_service.SettingsService') as mock_service:
            mock_service.get_setting = AsyncMock(side_effect=[
                0.005,  # base_chance
                0.001,  # chance_step
                50      # pity_threshold
            ])
            
            chance = await PAChanceService.calculate_chance(5)
            assert abs(chance - 0.010) < 0.0001, f"Ожидалось 0.010, получено {chance}"
    
    @pytest.mark.asyncio
    async def test_chance_on_twenty_fifth_box(self):
        """На 25-м боксе шанс = 3.0%"""
        with patch('app.services.pa_chance_service.SettingsService') as mock_service:
            mock_service.get_setting = AsyncMock(side_effect=[
                0.005,  # base_chance
                0.001,  # chance_step
                50      # pity_threshold
            ])
            
            chance = await PAChanceService.calculate_chance(25)
            assert abs(chance - 0.030) < 0.0001, f"Ожидалось 0.030, получено {chance}"
    
    @pytest.mark.asyncio
    async def test_chance_on_fiftieth_box_guarantee(self):
        """На 50-м боксе гарант = 100%"""
        with patch('app.services.pa_chance_service.SettingsService') as mock_service:
            mock_service.get_setting = AsyncMock(side_effect=[
                0.005,  # base_chance
                0.001,  # chance_step
                50      # pity_threshold
            ])
            
            chance = await PAChanceService.calculate_chance(50)
            assert chance == 1.0, f"Ожидалось 1.0 (гарант), получено {chance}"
    
    @pytest.mark.asyncio
    async def test_chance_beyond_fifty_stays_100(self):
        """После 50-го бокса шанс остаётся 100%"""
        with patch('app.services.pa_chance_service.SettingsService') as mock_service:
            mock_service.get_setting = AsyncMock(side_effect=[
                0.005,  # base_chance
                0.001,  # chance_step
                50      # pity_threshold
            ])
            
            chance = await PAChanceService.calculate_chance(100)
            assert chance == 1.0


class TestPARollLogic:
    """Тесты логики броска кубика на ПА (с моками)"""
    
    @pytest.mark.asyncio
    async def test_pa_dropped_on_guarantee(self):
        """На 50-м боксе ПА должно выпасть гарантированно"""
        # Создаём моки объектов
        user = MagicMock()
        user.nick = "TestUser"
        user.boxes_since_last_pa = 50
        user.premium_streams_left = 0
        
        stats = MagicMock()
        stats.pa_received_this_stream = 0
        
        with patch('app.services.pa_chance_service.SettingsService') as mock_service:
            mock_service.get_setting = AsyncMock(side_effect=[
                1,      # max_per_stream
                0.005,  # base_chance
                0.001,  # chance_step
                50      # pity_threshold
            ])
            
            result = await PAChanceService.try_roll_pa(user, stats)
            
            assert result is True, "ПА должно выпасть на 50-м боксе!"
            assert user.premium_streams_left == 1
            assert user.boxes_since_last_pa == 0  # Счётчик сброшен
            assert stats.pa_received_this_stream == 1
    
    @pytest.mark.asyncio
    async def test_pa_not_dropped_on_low_chance(self):
        """На 1-м боксе (0.6%) ПА не выпадет при random=0.5"""
        user = MagicMock()
        user.nick = "TestUser"
        user.boxes_since_last_pa = 1
        user.premium_streams_left = 0
        
        stats = MagicMock()
        stats.pa_received_this_stream = 0
        
        with patch('app.services.pa_chance_service.SettingsService') as mock_service:
            mock_service.get_setting = AsyncMock(side_effect=[
                1,      # max_per_stream
                0.005,  # base_chance
                0.001,  # chance_step
                50      # pity_threshold
            ])
            
            with patch('random.random', return_value=0.5):
                result = await PAChanceService.try_roll_pa(user, stats)
            
            assert result is False, "ПА не должно выпасть при шансе 0.6% и random=0.5"
            assert user.boxes_since_last_pa == 2  # Счётчик увеличился
    
    @pytest.mark.asyncio
    async def test_pa_limit_per_stream(self):
        """Максимум 1 ПА за стрим"""
        user = MagicMock()
        user.nick = "TestUser"
        user.boxes_since_last_pa = 50  # Гарант
        user.premium_streams_left = 0
        
        stats = MagicMock()
        stats.pa_received_this_stream = 1  # Лимит достигнут
        
        with patch('app.services.pa_chance_service.SettingsService') as mock_service:
            mock_service.get_setting = AsyncMock(return_value=1)  # max_per_stream = 1
            
            result = await PAChanceService.try_roll_pa(user, stats)
            
            assert result is False, "ПА не должно выпасть, если лимит за стрим достигнут!"
            assert user.premium_streams_left == 0


class TestEdgeCases:
    """Тесты граничных случаев"""
    
    @pytest.mark.asyncio
    async def test_zero_boxes_since_last_pa(self):
        """Если boxes_since_last_pa = 0, шанс = base_chance"""
        with patch('app.services.pa_chance_service.SettingsService') as mock_service:
            mock_service.get_setting = AsyncMock(side_effect=[
                0.005,  # base_chance
                0.001,  # chance_step
                50      # pity_threshold
            ])
            
            chance = await PAChanceService.calculate_chance(0)
            assert abs(chance - 0.005) < 0.0001, f"Ожидалось 0.005, получено {chance}"
    
    @pytest.mark.asyncio
    async def test_custom_pity_threshold(self):
        """Если изменить pity_threshold на 25, гарант на 25"""
        with patch('app.services.pa_chance_service.SettingsService') as mock_service:
            mock_service.get_setting = AsyncMock(side_effect=[
                0.005,  # base_chance
                0.001,  # chance_step
                25      # pity_threshold = 25
            ])
            
            chance = await PAChanceService.calculate_chance(25)
            assert chance == 1.0, f"Ожидалось 1.0 (гарант на 25), получено {chance}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])