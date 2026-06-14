"""
Сервис расчета наград и рулетки дропов
"""
import random
from typing import Dict, List
from app.core.cnst_Bot import (
    TankType, TANK_POWER, DROP_CHANCES, REWARD_MATRIX
)


class RewardService:
    """Бизнес-логика начисления наград"""

    @staticmethod
    def calculate_boxes(activation_num: int, has_premium: bool) -> int:
        """
        Рассчитать количество боксов за активацию.
        """
        if activation_num < 1:
            return 0
        
        # Если зритель умудрился сделать больше 12 активаций (например, лимит VK позволяет)
        if activation_num > 12:
            return 5 if has_premium else 3

        no_prem, with_prem = REWARD_MATRIX.get(activation_num, (3, 5))
        return with_prem if has_premium else no_prem

    @staticmethod
    def roll_loot(box_count: int) -> Dict[TankType, int]:
        """
        Крутить рулетку для заданного количества боксов.
        Возвращает словарь {Тип_танка: количество}.
        """
        if box_count <= 0:
            return {t: 0 for t in TankType}

        types = list(DROP_CHANCES.keys())
        weights = list(DROP_CHANCES.values())

        # random.choices делает взвешенный рандом с возвратом
        rolled = random.choices(types, weights=weights, k=box_count)

        # Подсчитываем результаты
        result = {t: 0 for t in TankType}
        for tank in rolled:
            result[tank] += 1

        return result

    @staticmethod
    def calculate_bm(tanks: Dict[TankType, int]) -> int:
        """
        Рассчитать Боевую Мощь (БМ) на основе выпавших танков.
        """
        total_bm = 0
        for tank_type, count in tanks.items():
            total_bm += count * TANK_POWER[tank_type]
        return total_bm

    @staticmethod
    def should_drop_premium(activation_num: int) -> bool:
        """
        Проверить, должен ли выпасть ПА (Офицерский Штаб).
        Только на 12-й активации (100% шанс).
        """
        return activation_num == 12

    @staticmethod
    def format_drops(tanks: Dict[TankType, int]) -> str:
        """
        Форматировать дропы для отправки в чат (например: ЛТ×3 СТ×2 ТТ×1)
        """
        parts = []
        # Порядок: от редкого к частому, чтобы ПТ-САУ бросалась в глаза
        order = [TankType.PT, TankType.TT, TankType.CT, TankType.LT]
        
        for tank in order:
            count = tanks.get(tank, 0)
            if count > 0:
                parts.append(f"{tank.value}×{count}")
                
        return " ".join(parts) if parts else "Пусто"