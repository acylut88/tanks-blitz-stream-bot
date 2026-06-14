"""
Настройка асинхронной сессии SQLAlchemy
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings

# Создание асинхронного движка
engine = create_async_engine(
    settings.database_url,
    echo=(settings.log_level == "DEBUG"),
    future=True
)

# Создание фабрики сессий
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_db() -> AsyncSession:
    """Получить сессию БД (для использования в зависимостях FastAPI)"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_session() -> AsyncSession:
    """Получить сессию БД (для использования вне FastAPI)"""
    async with async_session() as session:
        return session