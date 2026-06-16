"""
Главный обработчик сообщений и маршрутизатор
"""
from app.config import settings
from app.core.rewards import RewardService
from app.core.cnst_Bot import TankType, MSG_TEMPLATES
from app.database.session import async_session
from app.services.message_dispatcher import MessageDispatcher
from app.services.pa_chance_service import PAChanceService
from app.services.user_service import UserService
from sqlalchemy import text
from typing import Dict, Any
import re
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
        
        # Игнорируем собственные сообщения
        if sender == settings.vk_channel_owner_name:
            logger.debug("Ignoring own message", text=text)
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

        # 3. Извлекаем переменные
        nick = match.group(1).strip()
        reward_name = match.group(2).strip()
        _count = int(match.group(3))

        # 4. Фильтр по названию награды
        if reward_name != settings.allowed_reward_name:
            logger.debug("Ignored reward: wrong name", reward=reward_name, expected=settings.allowed_reward_name)
            return

        logger.info("Reward notification detected", nick=nick, reward=reward_name)

        # 5. Основная логика
        try:
            async with async_session() as session:
                user_service = UserService(session)
                
                # 1. Находим или создаем пользователя
                user = await user_service.get_or_create(nick)
                
                # 🔥 ДОБАВЛЕНО: Явное обновление объекта из БД
                await session.refresh(user)
                
                # 2. Получаем активную сессию стрима
                stream_session = await user_service.get_active_session()
                if not stream_session:
                    logger.warning("Reward received but no active stream session", nick=nick)
                    await session.commit()
                    return

                # 3. Получаем или создаем статистику
                stats = await user_service.get_or_create_stream_stats(user.id, stream_session.id)
                
                # 4. Инкрементируем счетчик активаций
                stats.activations_count += 1
                current_activation = stats.activations_count
                
                # 🔥 НОВОЕ: Проверяем отложенные ящики
                pending_boxes = user.pending_boxes if hasattr(user, 'pending_boxes') else 0
                
                # 🔥 ЛОГИРОВАНИЕ: Показываем текущее значение pending_boxes
                logger.info(f"User {nick} has {pending_boxes} pending boxes")
                
                pending_bm = 0
                pending_drops = ""
                
                if pending_boxes > 0:
                    logger.info(f"Opening {pending_boxes} pending boxes for {nick}")
                    
                    # Открываем все pending boxes
                    pending_loot = RewardService.roll_loot(pending_boxes)
                    pending_bm = RewardService.calculate_bm(pending_loot)
                    
                    # Начисляем танки из pending boxes
                    user.lifetime_tanks_lt += pending_loot.get(TankType.LT, 0)
                    user.lifetime_tanks_st += pending_loot.get(TankType.CT, 0)
                    user.lifetime_tanks_tt += pending_loot.get(TankType.TT, 0)
                    user.lifetime_tanks_pt += pending_loot.get(TankType.PT, 0)
                    user.lifetime_boxes_opened += pending_boxes
                    
                    # 🔥 ВАЖНО: Добавляем БМ в текущую сессию!
                    stats.current_bm += pending_bm

                    # Форматируем дропы
                    pending_drops = RewardService.format_drops(pending_loot)
                    
                    # Сбрасываем счетчик
                    user.pending_boxes = 0
                    
                    logger.info(f"Pending boxes opened: {pending_bm} BM gained", loot=pending_loot)
                
                # 5. Рассчитываем награды для текущей активации
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
                
                # 🔥 НОВОЕ: Проверяем шанс выпадения ПА
                pa_dropped = await PAChanceService.try_roll_pa(user, stats)
                
                # Коммитим
                await session.commit()
                
                # 8. Формируем сообщения
                drops_str = RewardService.format_drops(loot)
                template_key = "reward_peak" if current_activation == 6 else ("reward_final" if current_activation == 12 else "reward_normal")
                
                # 🔥 Если были pending boxes, отправляем бонус
                if pending_boxes > 0:
                    bonus_msg = f"🎁 Бонус за прошлый стрим:\n{pending_drops}\n+{pending_bm} БМ"
                    await self.dispatcher.add_message(nick, bonus_msg, priority=1)
                    logger.info(f"Bonus message sent to {nick}")
                
                # Основное сообщение
                msg_text = MSG_TEMPLATES[template_key].format(
                    activation=current_activation,
                    drops=drops_str,
                    bm=gained_bm,
                    total_bm=stats.current_bm
                )
                
                await self.dispatcher.add_message(nick, msg_text, priority=1)
                
                # 🔥 НОВОЕ: Если выпало ПА - отправляем отдельное сообщение
                if pa_dropped:
                    pa_msg = MSG_TEMPLATES["pa_drop"]
                    await self.dispatcher.add_message(nick, pa_msg, priority=2)
                    logger.info("PA drop notification sent", nick=nick)

                # 9. Отдельное сообщение для редкого дропа (ПТ-САУ)
                if loot.get(TankType.PT, 0) > 0:
                    rare_msg = MSG_TEMPLATES["rare_drop"].format(activation=current_activation)
                    await self.dispatcher.add_message(nick, rare_msg, priority=2)

                logger.info("Reward processed", nick=nick, activation=current_activation, bm=gained_bm, boxes=box_count)

        except Exception as e:
            logger.error("Error processing reward", nick=nick, error=str(e), exc_info=True)