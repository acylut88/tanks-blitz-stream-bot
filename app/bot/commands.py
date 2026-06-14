"""
Обработчики команд чата
"""
from app.services.user_service import UserService
from app.services.message_dispatcher import MessageDispatcher
from app.database.session import async_session
from app.config import settings
from app.core.cnst_Bot import MSG_TEMPLATES
import structlog

logger = structlog.get_logger()


class CommandRouter:
    def __init__(self, dispatcher: MessageDispatcher):
        self.dispatcher = dispatcher
        self.whitelist = [n.strip() for n in settings.streamer_whitelist.split(",")]

    async def route(self, nick: str, text: str):
        """Маршрутизация команд"""
        cmd = text.split()[0].lower()
        
        # Команды зрителей
        if cmd in ("!стат", "!stats"):
            await self.cmd_stats(nick)
        elif cmd in ("!фулстат", "!fullstats", "!полнаястата"):
            await self.cmd_full_stats(nick)
        elif cmd in ("!топ", "!top"):
            await self.cmd_top(nick)
            
        # Команды стримера (требуют whitelist)
        elif not self._is_streamer(nick):
            await self.dispatcher.add_message(nick, "⚠️ Эта команда доступна только стримеру.")
            return
            
        elif cmd in ("!новыйстрим", "!start"):
            await self.cmd_new_stream(nick)
        elif cmd in ("!стопстрим", "!stop"):
            await self.cmd_stop_stream(nick)
        elif cmd in ("!розыгрыш", "!raffle"):
            await self.cmd_raffle(nick)
            
        else:
            await self.dispatcher.add_message(nick, "❓ Неизвестная команда. Доступно: !стат, !фулстат, !топ")

    def _is_streamer(self, nick: str) -> bool:
        return nick in self.whitelist

    async def cmd_stats(self, nick: str):
        """Показать статистику за ТЕКУЩИЙ стрим"""
        try:
            async with async_session() as session:
                service = UserService(session)
                user = await service.get_by_nick(nick)
                if not user:
                    await self.dispatcher.add_message(nick, "⚠️ Вы еще не участвовали в активностях.")
                    return

                session_obj = await service.get_active_session()
                stats = await service.get_user_stream_stats(user.id, session_obj.id) if session_obj else None
                bm = stats.current_bm if stats else 0
                acts = stats.activations_count if stats else 0
                premium_status = "Активен" if user.premium_streams_left > 0 else "Нет"

                msg = f"📊 Командир {nick} | ⚔️ {bm} БМ | 🎖 ОШ: {premium_status} | Активаций: {acts}/12"
                await self.dispatcher.add_message(nick, msg)
        except Exception as e:
            logger.error("Stats error", error=str(e))

    async def cmd_full_stats(self, nick: str):
        """Показать полную статистику за всё время"""
        try:
            async with async_session() as session:
                service = UserService(session)
                user = await service.get_by_nick(nick)
                if not user:
                    await self.dispatcher.add_message(nick, "⚠️ Вы еще не участвовали в активностях.")
                    return

                msg = (
                    f"📜 Полная статистика {nick} | "
                    f"📦 Ящиков: {user.lifetime_boxes_opened} | "
                    f"🛡 ЛТ×{user.lifetime_tanks_lt} СТ×{user.lifetime_tanks_st} ТТ×{user.lifetime_tanks_tt} ПТ×{user.lifetime_tanks_pt} | "
                    f"🎖 ОШ использован: {user.lifetime_streams_with_premium} стримов"
                )
                await self.dispatcher.add_message(nick, msg)
        except Exception as e:
            logger.error("Full stats error", error=str(e))

    async def cmd_top(self, nick: str):
        """Топ игроков по БМ"""
        try:
            async with async_session() as session:
                service = UserService(session)
                session_obj = await service.get_active_session()
                if not session_obj:
                    await self.dispatcher.add_message(nick, "📊 Стрим не активен.")
                    return

                # Простой запрос топ-5 (в реальном проде лучше оптимизировать)
                from sqlalchemy import select, desc
                from app.database.models import StreamStats, User
                
                result = await session.execute(
                    select(User.nick, StreamStats.current_bm)
                    .join(StreamStats, User.id == StreamStats.user_id)
                    .filter(StreamStats.session_id == session_obj.id)
                    .order_by(desc(StreamStats.current_bm))
                    .limit(5)
                )
                rows = result.all()
                
                lines = ["🏆 Топ полководцев:"]
                for i, (n, bm) in enumerate(rows, 1):
                    lines.append(f"{i}. {n} — {bm} БМ")
                    
                await self.dispatcher.add_message(nick, " | ".join(lines))
        except Exception as e:
            logger.error("Top error", error=str(e))

    async def cmd_new_stream(self, nick: str):
        """Начать новый стрим"""
        try:
            async with async_session() as session:
                service = UserService(session)
                await service.create_stream_session()
                
                await session.commit()
                
                msg = "🟢 Стрим начат! Счётчики сброшены. Командиры, занимайте позиции!"
                await self.dispatcher.add_message(nick, msg)
                logger.info("New stream started", by=nick)
        except Exception as e:
            logger.error("New stream error", error=str(e), exc_info=True)

    async def cmd_stop_stream(self, nick: str):
        """Завершить стрим и списать жетоны ПА"""
        try:
            async with async_session() as session:
                service = UserService(session)
                session_obj = await service.get_active_session()
                if not session_obj:
                    await self.dispatcher.add_message(nick, "⚠️ Нет активного стрима для завершения.")
                    return

                await service.end_stream_session(session_obj.id)
                await session.commit()
                
                # Списываем жетоны ПА у тех, кто участвовал (activations_count > 0)
                from sqlalchemy import select
                from app.database.models import StreamStats, User
                
                stmt = select(User).join(StreamStats).filter(
                    StreamStats.session_id == session_obj.id,
                    StreamStats.activations_count > 0,
                    User.premium_streams_left > 0
                )
                result = await session.execute(stmt)
                participants_with_pa = result.scalars().all()
                
                count = 0
                for u in participants_with_pa:
                    u.premium_streams_left -= 1
                    u.lifetime_streams_with_premium += 1
                    count += 1
                    
                await session.commit()
                msg = f"🔴 Стрим завершен. Списан 1 жетон ОШ у {count} командиров."
                await self.dispatcher.add_message(nick, msg)
                logger.info("Stream stopped", by=nick)
        except Exception as e:
            logger.error("Stop stream error", error=str(e))

    async def cmd_raffle(self, nick: str):
        """Запуск рулетки на вылет"""
        await self.dispatcher.add_message(nick, "🎰 Командиры, приготовьтесь! Рулетка запускается... Следите за оверлеем!")
        
        import asyncio
        from app.api.websocket import run_raffle_process
        # Запускаем в фоне, чтобы не блокировать чат
        asyncio.create_task(run_raffle_process())