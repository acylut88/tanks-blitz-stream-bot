"""
Сервис для работы с пользователями
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import User, StreamSession, StreamStats
import structlog

logger = structlog.get_logger()


class UserService:
    """Сервис для CRUD операций с пользователями"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_or_create(self, nick: str, vk_id: Optional[int] = None) -> User:
        """
        Получить пользователя по нику или создать нового
        """
        # Ищем по нику
        result = await self.session.execute(
            select(User).filter(User.nick == nick)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Обновляем last_seen
            user.last_seen = datetime.now(timezone.utc)
            if vk_id and not user.vk_id:
                user.vk_id = vk_id
            await self.session.flush()
            logger.debug("User found", nick=nick, id=user.id)
            return user
        
        # Создаём нового
        user = User(
            nick=nick,
            vk_id=vk_id,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc)
        )
        self.session.add(user)
        await self.session.flush()
        logger.info("User created", nick=nick, id=user.id, vk_id=vk_id)
        return user
    
    async def get_by_nick(self, nick: str) -> Optional[User]:
        """Получить пользователя по нику"""
        result = await self.session.execute(
            select(User).filter(User.nick == nick)
        )
        return result.scalar_one_or_none()
    
    async def get_by_vk_id(self, vk_id: int) -> Optional[User]:
        """Получить пользователя по VK ID"""
        result = await self.session.execute(
            select(User).filter(User.vk_id == vk_id)
        )
        return result.scalar_one_or_none()
    
    async def update_nick(self, vk_id: int, new_nick: str) -> bool:
        """Обновить ник пользователя по VK ID"""
        user = await self.get_by_vk_id(vk_id)
        if user and user.nick != new_nick:
            old_nick = user.nick
            user.nick = new_nick
            await self.session.flush()
            logger.info("Nick updated", vk_id=vk_id, old_nick=old_nick, new_nick=new_nick)
            return True
        return False
    
    async def grant_premium(self, nick: str, streams_count: int) -> bool:
        """Начислить жетоны ПА пользователю"""
        user = await self.get_by_nick(nick)
        if user:
            user.premium_streams_left += streams_count
            await self.session.flush()
            logger.info("Premium granted", nick=nick, streams=streams_count, total=user.premium_streams_left)
            return True
        return False
    
    async def get_active_session(self) -> Optional[StreamSession]:
        """Получить активную сессию стрима (последнюю незакрытую)"""
        result = await self.session.execute(
            select(StreamSession)
            .filter(StreamSession.ended_at.is_(None))
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def create_stream_session(self) -> StreamSession:
        """Создать новую сессию стрима"""
        session = StreamSession(started_at=datetime.now(timezone.utc))
        self.session.add(session)
        await self.session.flush()
        logger.info("Stream session created", id=session.id)
        return session
    
    async def end_stream_session(self, session_id: int) -> bool:
        """Завершить сессию стрима"""
        result = await self.session.execute(
            select(StreamSession).filter(StreamSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        
        if session:
            session.ended_at = datetime.now(timezone.utc)
            await self.session.flush()
            logger.info("Stream session ended", id=session_id)
            return True
        return False
    
    async def get_user_stream_stats(self, user_id: int, session_id: int) -> Optional[StreamStats]:
        """Получить статистику пользователя в текущем стриме"""
        result = await self.session.execute(
            select(StreamStats).filter(
                StreamStats.user_id == user_id,
                StreamStats.session_id == session_id
            )
        )
        return result.scalar_one_or_none()
    
    async def get_or_create_stream_stats(self, user_id: int, session_id: int) -> StreamStats:
        """Получить или создать статистику пользователя в текущем стриме"""
        stats = await self.get_user_stream_stats(user_id, session_id)
        
        if not stats:
            stats = StreamStats(
                user_id=user_id,
                session_id=session_id,
                current_bm=0,
                activations_count=0
            )
            self.session.add(stats)
            await self.session.flush()
        
        return stats