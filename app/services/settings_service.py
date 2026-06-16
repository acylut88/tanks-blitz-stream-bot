"""
Сервис для управления настройками
"""
import json
from typing import Any, Dict, Optional
from sqlalchemy import select
from app.database.session import async_session
from app.database.models import Setting
import structlog

logger = structlog.get_logger()


class SettingsService:
    @staticmethod
    async def get_setting(key: str, default: Any = None) -> Any:
        """Получить значение настройки"""
        async with async_session() as session:
            result = await session.execute(
                select(Setting).filter(Setting.key == key)
            )
            setting = result.scalar_one_or_none()
            
            if not setting:
                return default
            
            try:
                return json.loads(setting.value)
            except json.JSONDecodeError:
                return setting.value

    @staticmethod
    async def set_setting(key: str, value: Any, description: str = None, category: str = None) -> bool:
        """Установить значение настройки"""
        async with async_session() as session:
            result = await session.execute(
                select(Setting).filter(Setting.key == key)
            )
            setting = result.scalar_one_or_none()
            
            value_json = json.dumps(value, ensure_ascii=False)
            
            if not setting:
                setting = Setting(
                    key=key,
                    value=value_json,
                    description=description,
                    category=category
                )
                session.add(setting)
            else:
                setting.value = value_json
                if description:
                    setting.description = description
                if category:
                    setting.category = category
            
            await session.commit()
            logger.info("Setting updated", key=key, value=value)
            return True

    @staticmethod
    async def get_all_settings(category: str = None) -> Dict[str, Any]:
        """Получить все настройки (опционально по категории)"""
        async with async_session() as session:
            query = select(Setting)
            
            if category:
                # Фильтруем по категории ИЛИ по ключу (если category не задана)
                query = query.filter(
                    (Setting.category == category) | 
                    (Setting.key.like(f"{category}.%"))
                )
            
            result = await session.execute(query)
            settings = result.scalars().all()
            
            return {s.key: json.loads(s.value) for s in settings}

    @staticmethod
    async def get_settings_by_category(category: str) -> Dict[str, Any]:
        """Получить настройки по категории"""
        return await SettingsService.get_all_settings(category)

    @staticmethod
    async def initialize_defaults():
        """Инициализировать настройки по умолчанию"""
        defaults = {
            # Настройки рулетки
            "raffle.animSettings.totalDuration": {
                "value": 10.0,
                "description": "Общее время анимации рулетки (секунды)",
                "category": "raffle"
            },
            "raffle.animSettings.fastRatio": {
                "value": 0.80,
                "description": "Доля быстрого вращения (0.0-1.0)",
                "category": "raffle"
            },
            "raffle.animSettings.pausePhase": {
                "value": 3.0,
                "description": "Пауза после выбора жертвы (секунды)",
                "category": "raffle"
            },
            "raffle.prizes.1": {
                "value": "📦 10 лутбоксов (10 танков)",
                "description": "Приз за 1 место",
                "category": "raffle"
            },
            "raffle.prizes.2": {
                "value": "📦 8 лутбоксов (8 танков)",
                "description": "Приз за 2 место",
                "category": "raffle"
            },
            "raffle.prizes.3": {
                "value": "📦 6 лутбоксов (6 танков)",
                "description": "Приз за 3 место",
                "category": "raffle"
            },
            "raffle.prizes.eliminated": {
                "value": "📦 4 лутбокса (4 танка)",
                "description": "Утешительный приз для выбывших",
                "category": "raffle"
            },
            
            # Настройки диспетчера
            "dispatcher.send_delay": {
                "value": 0.4,
                "description": "Задержка между отправкой сообщений (секунды)",
                "category": "dispatcher"
            },
            "dispatcher.overload_threshold": {
                "value": 50,
                "description": "Порог перегрузки очереди сообщений",
                "category": "dispatcher"
            },
            
            # ЧИСЛОВЫЕ значения призов (для начисления)
            "raffle.boxes.1": {
                "value": 10,
                "description": "Количество лутбоксов за 1 место",
                "category": "raffle"
            },
            "raffle.boxes.2": {
                "value": 8,
                "description": "Количество лутбоксов за 2 место",
                "category": "raffle"
            },
            "raffle.boxes.3": {
                "value": 6,
                "description": "Количество лутбоксов за 3 место",
                "category": "raffle"
            },
            "raffle.boxes.eliminated": {
                "value": 4,
                "description": "Количество лутбоксов для выбывших",
                "category": "raffle"
            },
            "raffle.pa.1": {
                "value": 1,
                "description": "Количество ПА за 1 место",
                "category": "raffle"
            },
            "raffle.pa.2": {
                "value": 1,
                "description": "Количество ПА за 2 место",
                "category": "raffle"
            },
            "raffle.pa.3": {
                "value": 1,
                "description": "Количество ПА за 3 место",
                "category": "raffle"
            },

            # Настройки шанса выпадения ПА из бокса
            "pa.base_chance": {
                "value": 0.005,  # 0.5% базовый (итого 0.6% на 1 боксе)
                "description": "Базовый шанс выпадения ПА (добавляется к номеру бокса × step)",
                "category": "pa"
            },
            "pa.chance_step": {
                "value": 0.001,  # 0.1% за каждый бокс
                "description": "Шаг увеличения шанса за каждый открытый бокс",
                "category": "pa"
            },
            "pa.pity_threshold": {
                "value": 50,
                "description": "Гарантированное выпадение ПА на этом боксе",
                "category": "pa"
            },
            "pa.max_per_stream": {
                "value": 1,
                "description": "Максимум бесплатных ПА за один стрим",
                "category": "pa"
            },
        }
        
        for key, data in defaults.items():
            await SettingsService.set_setting(
                key, 
                data["value"], 
                data["description"], 
                data["category"]
            )
        
        logger.info("Default settings initialized")