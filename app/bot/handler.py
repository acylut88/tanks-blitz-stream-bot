"""
Главный обработчик сообщений и маршрутизатор
"""
import re
from typing import Dict, Any

from sqlalchemy import text
from app.core.rewards import RewardService
from app.core.cnst_Bot import TankType, MSG_TEMPLATES
from app.services.user_service import UserService
from app.services.message_dispatcher import MessageDispatcher
from app.database.session import async_session
from app.config import settings
import structlog

logger = structlog.get_logger()

# Паттерн системного сообщения VK Live о награде
# Пример: "Indigo_ получает награду: Снарядный ящик за 1"
REWARD_PATTERN = re.compile(r'^(.+?)\s+получает награду:\s+(.+?)\s+за\s+(\d+)')


class MessageHandler:
    """Обрабатывает входящие сообщения и распределяет по логике"""

    def __init__(self, dispatcher: MessageDispatcher):
        self.dispatcher = dispatcher

    async def handle(self, msg_data: Dict[str, Any]):
        """Точка входа для каждого нового сообщения"""
        mid = msg_data.get("id")
        text = (msg_data.get("text") or "").strip()
        sender = (msg_data.get("sender") or "").strip().replace(":", "")
        is_system = msg_data.get("is_system", False)

        if not mid or not text:
            return

        logger.debug("Message received", sender=sender, text=text)

        # 1. Системные сообщения от ChatBot (уведомления о наградах)
        if is_system or sender == "ChatBot":
            await self._process_reward_notification(text, sender)
            return

        # 2. Команды зрителей (начинаются с !)
        if text.startswith("!"):
            # Импортируем команды тут, чтобы избежать циклических зависимостей
            from app.bot.commands import CommandRouter
            router = CommandRouter(self.dispatcher)
            await router.route(sender, text)
            return

        # 3. Обычные сообщения (пока игнорируем, но можно добавить для активностей)
        logger.debug("Ignoring regular message", sender=sender)

    async def _process_reward_notification(self, text: str, sender: str):
        """Обработка системного сообщения о получении награды"""
        # 1. Очищаем текст от переносов строк
        clean_text = ' '.join(text.split())
        
        # 2. Парсим паттерн
        match = REWARD_PATTERN.match(clean_text)
        if not match:
            logger.debug("Not a reward notification", text=clean_text)
            return

        # 3. ИЗВЛЕКАЕМ ПЕРЕМЕННЫЕ (строго до проверки!)
        nick = match.group(1).strip()
        reward_name = match.group(2).strip()  # ← Вот здесь определяется reward_name
        _count = int(match.group(3))

        # 4. 🔒 КРИТИЧНО: Фильтр по названию награды
        if reward_name != settings.allowed_reward_name:
            logger.debug("Ignored reward: wrong name", reward=reward_name, expected=settings.allowed_reward_name)
            return

        logger.info("Reward notification detected", nick=nick, reward=reward_name)

        # 5. Дальше идёт остальная логика (БД, рулетка, начисление БМ...)
        try:
            async with async_session() as session:
                user_service = UserService(session)
                
                # 1. Находим или создаем пользователя
                user = await user_service.get_or_create(nick)
                
                # 2. Получаем активную сессию стрима
                stream_session = await user_service.get_active_session()
                if not stream_session:
                    logger.warning("Reward received but no active stream session", nick=nick)
                    await session.commit()  # Коммитим создание пользователя
                    return

                # 3. Получаем или создаем статистику для текущего стрима
                stats = await user_service.get_or_create_stream_stats(user.id, stream_session.id)
                
                # 4. Инкрементируем счетчик активаций
                stats.activations_count += 1
                
                current_activation = stats.activations_count
                
                # 5. Рассчитываем награды
                has_premium = user.premium_streams_left > 0
                box_count = RewardService.calculate_boxes(current_activation, has_premium)
                
                # 6. Крутим рулетку
                loot = RewardService.roll_loot(box_count)
                gained_bm = RewardService.calculate_bm(loot)
                
                # 7. Обновляем БД
                stats.current_bm += gained_bm
                user.lifetime_boxes_opened += box_count
                user.lifetime_tanks_lt += loot.get(TankType.LT, 0)
                user.lifetime_tanks_st += loot.get(TankType.CT, 0)
                user.lifetime_tanks_tt += loot.get(TankType.TT, 0)
                user.lifetime_tanks_pt += loot.get(TankType.PT, 0)
                
                # Если это 12-я активация — выдаём ПА
                if current_activation == 12:
                    user.premium_streams_left += 1
                    user.lifetime_streams_with_premium += 1
                    logger.info("PA token granted for 12 activations", nick=nick)
                
                # Коммитим изменения в БД
                await session.commit()
                
                # 8. Формируем и отправляем отчет в ЛС
                drops_str = RewardService.format_drops(loot)
                template_key = "reward_peak" if current_activation == 6 else ("reward_final" if current_activation == 12 else "reward_normal")
                
                msg_text = MSG_TEMPLATES[template_key].format(
                    activation=current_activation,
                    drops=drops_str,
                    bm=gained_bm,
                    total_bm=stats.current_bm
                )
                
                await self.dispatcher.add_message(nick, msg_text, priority=1)
                
                # 9. Отдельное сообщение для редкого дропа (ПТ-САУ)
                if loot.get(TankType.PT, 0) > 0:
                    rare_msg = MSG_TEMPLATES["rare_drop"].format(activation=current_activation)
                    await self.dispatcher.add_message(nick, rare_msg, priority=2)

                logger.info("Reward processed", nick=nick, activation=current_activation, bm=gained_bm, boxes=box_count)

        except Exception as e:
            logger.error("Error processing reward", nick=nick, error=str(e), exc_info=True)