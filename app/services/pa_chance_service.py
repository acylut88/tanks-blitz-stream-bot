"""
Сервис для расчёта шанса выпадения ПА из бокса
"""
import random
from app.services.settings_service import SettingsService
import structlog

logger = structlog.get_logger()


class PAChanceService:
    @staticmethod
    async def calculate_chance(boxes_since_last_pa: int) -> float:
        """Рассчитать шанс выпадения ПА"""
        base_chance = await SettingsService.get_setting("pa.base_chance", 0.005)
        chance_step = await SettingsService.get_setting("pa.chance_step", 0.001)
        pity_threshold = await SettingsService.get_setting("pa.pity_threshold", 50)
        
        # Если достигли порога гаранта
        if boxes_since_last_pa >= pity_threshold:
            return 1.0
        
        # Формула: base_chance + (boxes × step)
        chance = base_chance + (boxes_since_last_pa * chance_step)
        
        # Ограничиваем максимум
        return min(chance, 1.0)
    
    @staticmethod
    async def try_roll_pa(user, stream_stats) -> bool:
        """
        Попытаться выбить ПА.
        Возвращает True если ПА выпало.
        """
        # 🔥 БЕЗОПАСНАЯ ПРОВЕРКА: используем getattr с дефолтом
        max_per_stream = await SettingsService.get_setting("pa.max_per_stream", 1)
        pa_count = getattr(stream_stats, 'pa_received_this_stream', None) or 0
        
        if pa_count >= max_per_stream:
            logger.debug("PA limit reached for this stream", nick=user.nick, count=pa_count)
            return False
        
        # 🔥 БЕЗОПАСНОЕ УВЕЛИЧЕНИЕ: используем or 0
        user.boxes_since_last_pa = (getattr(user, 'boxes_since_last_pa', None) or 0) + 1
        
        # Рассчитываем шанс
        chance = await PAChanceService.calculate_chance(user.boxes_since_last_pa)
        
        # Бросаем кубик
        if random.random() < chance:
            # ПА выпало!
            user.premium_streams_left = (user.premium_streams_left or 0) + 1
            user.boxes_since_last_pa = 0  # Сбрасываем счётчик
            
            # 🔥 БЕЗОПАСНОЕ ПРИСВАИВАНИЕ: не используем +=
            stream_stats.pa_received_this_stream = pa_count + 1
            
            logger.info(
                "PA dropped from box!",
                nick=user.nick,
                boxes_opened=user.boxes_since_last_pa,
                chance=f"{chance*100:.2f}%",
                total_pa=user.premium_streams_left
            )
            return True
        
        logger.debug(
            "PA not dropped",
            nick=user.nick,
            boxes=user.boxes_since_last_pa,
            chance=f"{chance*100:.2f}%"
        )
        return False