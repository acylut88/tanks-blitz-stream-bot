"""
Тесты для RewardService (бизнес-логика)
"""
import pytest
from app.core.rewards import RewardService
from app.core.cnst_Bot import TankType, REWARD_MATRIX


class TestRewardMatrix:
    """Тесты матрицы наград"""

    def test_first_activation_no_premium(self):
        assert RewardService.calculate_boxes(1, False) == 2

    def test_first_activation_with_premium(self):
        assert RewardService.calculate_boxes(1, True) == 3

    def test_peak_activation_6(self):
        assert RewardService.calculate_boxes(6, False) == 10
        assert RewardService.calculate_boxes(6, True) == 15

    def test_second_hour_activations(self):
        for i in range(7, 13):
            assert RewardService.calculate_boxes(i, False) == 3
            assert RewardService.calculate_boxes(i, True) == 5

    def test_invalid_activation(self):
        assert RewardService.calculate_boxes(0, False) == 0
        assert RewardService.calculate_boxes(-1, False) == 0


class TestLootRoulette:
    """Тесты рулетки дропов"""

    def test_zero_boxes(self):
        result = RewardService.roll_loot(0)
        assert sum(result.values()) == 0

    def test_total_count_matches(self):
        """Общее количество выпавших танков должно равняться количеству боксов"""
        boxes = 15
        result = RewardService.roll_loot(boxes)
        assert sum(result.values()) == boxes

    def test_drop_rates_simulation(self):
        """
        Статистический тест: делаем 10,000 бросков и проверяем, 
        что распределение близко к заданным шансам (±2%).
        """
        total_rolls = 10000
        # Симулируем 10,000 отдельных боксов
        aggregated = {t: 0 for t in TankType}
        
        for _ in range(total_rolls):
            rolls = RewardService.roll_loot(1)
            for tank, count in rolls.items():
                aggregated[tank] += count

        # Проверяем проценты
        lt_percent = aggregated[TankType.LT] / total_rolls
        ct_percent = aggregated[TankType.CT] / total_rolls
        tt_percent = aggregated[TankType.TT] / total_rolls
        pt_percent = aggregated[TankType.PT] / total_rolls

        # Допускаем погрешность 2%
        assert 0.53 <= lt_percent <= 0.57, f"ЛТ выпадает слишком часто/редко: {lt_percent}"
        assert 0.23 <= ct_percent <= 0.27, f"СТ выпадает слишком часто/редко: {ct_percent}"
        assert 0.13 <= tt_percent <= 0.17, f"ТТ выпадает слишком часто/редко: {tt_percent}"
        assert 0.03 <= pt_percent <= 0.07, f"ПТ выпадает слишком часто/редко: {pt_percent}"


class TestBattlePower:
    """Тесты расчета Боевой Мощи"""

    def test_calculate_bm(self):
        tanks = {
            TankType.LT: 5,  # 5 * 1 = 5
            TankType.CT: 3,  # 3 * 2 = 6
            TankType.TT: 2,  # 2 * 3 = 6
            TankType.PT: 1,  # 1 * 4 = 4
        }
        # Итого: 5 + 6 + 6 + 4 = 21
        assert RewardService.calculate_bm(tanks) == 21

    def test_format_drops(self):
        tanks = {
            TankType.LT: 3,
            TankType.CT: 2,
            TankType.TT: 1,
            TankType.PT: 0,
        }
        formatted = RewardService.format_drops(tanks)
        assert formatted == "ТТ×1 СТ×2 ЛТ×3"  # От редкого к частому