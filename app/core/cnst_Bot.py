"""
Константы и матрицы наград для бота
"""
from enum import Enum
from typing import Dict, Tuple


class TankType(str, Enum):
    """Типы техники"""
    LT = "ЛТ"
    CT = "СТ"
    TT = "ТТ"
    PT = "ПТ"


# Сила (Боевая Мощь) каждого типа техники
TANK_POWER: Dict[TankType, int] = {
    TankType.LT: 1,
    TankType.CT: 2,
    TankType.TT: 3,
    TankType.PT: 4,
}

# Шансы выпадения (сумма = 1.0)
DROP_CHANCES: Dict[TankType, float] = {
    TankType.LT: 0.55,
    TankType.CT: 0.25,
    TankType.TT: 0.15,
    TankType.PT: 0.05,
}

# Матрица наград: (номер активации) -> (без ПА, с ПА)
# 12-я активация также дает ПА (обрабатывается отдельно)
REWARD_MATRIX: Dict[int, Tuple[int, int]] = {
    1: (2, 3),
    2: (3, 5),
    3: (4, 6),
    4: (5, 8),
    5: (6, 9),
    6: (10, 15),  # Пик первого часа
    7: (3, 5),
    8: (3, 5),
    9: (3, 5),
    10: (3, 5),
    11: (3, 5),
    12: (3, 5),  # Финал + ПА
}

# Шаблоны сообщений (одна строка, эмодзи-разделители)
MSG_TEMPLATES = {
    "reward_normal": "📦 Поставка #{activation} | 🛡 {drops} | ⚔️ +{bm} БМ | 📈 Армия: {total_bm} БМ",
    "reward_peak": "🚀 Поставка #{activation} (Пик!) | 🛡 {drops} | ️ +{bm} БМ | 📈 Армия: {total_bm} БМ",
    "reward_final": "🏆 Поставка #{activation} | 🛡 {drops} | ️ +{bm} БМ | 📈 Армия: {total_bm} БМ |  ОШ на след. стрим!",
    "rare_drop": "✨ РЕДКОСТЬ! ПТ-САУ (+4 БМ) в поставке #{activation}!",
    "stats": "📊 Командир {nick} | ️ {bm} БМ | 🛡 ЛТ×{lt} СТ×{ct} ТТ×{tt} ПТ×{pt} | 🎖 ОШ: {premium} | Активаций: {activations}/12",
    "pa_drop": "🎉🎖️ РЕДЧАЙШИЙ ДРОП! Командир, вам выпал жетон Офицерского Штаба! Активируется со след. стрима!"
}