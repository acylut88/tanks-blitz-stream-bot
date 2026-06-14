"""
Скрипт для добавления тестовых пользователей с БМ
"""
import asyncio
from datetime import datetime, timezone
from app.database.session import async_session
from app.database.models import User, StreamSession, StreamStats
from sqlalchemy import select


async def add_test_data():
    async with async_session() as session:
        # 1. Проверяем, есть ли активная сессия
        result = await session.execute(
            select(StreamSession).filter(StreamSession.ended_at.is_(None))
        )
        active_session = result.scalar_one_or_none()
        
        if not active_session:
            print("Нет активной сессии. Создаю...")
            active_session = StreamSession(started_at=datetime.now(timezone.utc))
            session.add(active_session)
            await session.flush()
            print(f"Создана сессия ID={active_session.id}")
        
        # 2. Создаём тестовых пользователей
        test_nicks = [
            ("TestUser1", 150),
            ("TestUser2", 120),
            ("TestUser3", 95),
            ("TestUser4", 80),
            ("TestUser5", 60),
            ("SkilloCrabs", 200),  # Ты сам
        ]
        
        for nick, bm in test_nicks:
            # Проверяем, есть ли пользователь
            result = await session.execute(
                select(User).filter(User.nick == nick)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(
                    nick=nick,
                    first_seen=datetime.now(timezone.utc),
                    last_seen=datetime.now(timezone.utc)
                )
                session.add(user)
                await session.flush()
                print(f"Создан пользователь: {nick}")
            
            # Проверяем, есть ли статистика для этой сессии
            result = await session.execute(
                select(StreamStats).filter(
                    StreamStats.user_id == user.id,
                    StreamStats.session_id == active_session.id
                )
            )
            stats = result.scalar_one_or_none()
            
            if not stats:
                stats = StreamStats(
                    user_id=user.id,
                    session_id=active_session.id,
                    current_bm=bm,
                    activations_count=5
                )
                session.add(stats)
                print(f"Добавлена статистика: {nick} = {bm} БМ")
            else:
                stats.current_bm = bm
                print(f"Обновлена статистика: {nick} = {bm} БМ")
        
        await session.commit()
        print("\n✅ Тестовые данные добавлены!")
        print(f"Активная сессия: ID={active_session.id}")
        print(f"Участников: {len(test_nicks)}")


if __name__ == "__main__":
    asyncio.run(add_test_data())