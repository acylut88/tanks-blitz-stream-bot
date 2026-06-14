"""
Тесты для UserService
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.database.models import Base
from app.services.user_service import UserService


# Тестовая БД (SQLite in-memory)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session():
    """Создать тестовую сессию БД"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=True)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session_factory() as session:
        yield session
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_user(db_session):
    """Тест создания пользователя"""
    service = UserService(db_session)
    
    user = await service.get_or_create("TestUser")
    
    assert user is not None
    assert user.nick == "TestUser"
    assert user.id is not None
    assert user.premium_streams_left == 0


@pytest.mark.asyncio
async def test_get_existing_user(db_session):
    """Тест получения существующего пользователя"""
    service = UserService(db_session)
    
    # Создаём
    user1 = await service.get_or_create("TestUser")
    
    # Получаем
    user2 = await service.get_or_create("TestUser")
    
    assert user1.id == user2.id


@pytest.mark.asyncio
async def test_update_nick(db_session):
    """Тест обновления ника"""
    service = UserService(db_session)
    
    # Создаём с vk_id
    user = await service.get_or_create("OldNick", vk_id=12345)
    
    # Обновляем ник
    result = await service.update_nick(12345, "NewNick")
    
    assert result is True
    assert user.nick == "NewNick"


@pytest.mark.asyncio
async def test_grant_premium(db_session):
    """Тест начисления ПА"""
    service = UserService(db_session)
    
    user = await service.get_or_create("TestUser")
    
    result = await service.grant_premium("TestUser", 5)
    
    assert result is True
    assert user.premium_streams_left == 5


@pytest.mark.asyncio
async def test_create_stream_session(db_session):
    """Тест создания сессии стрима"""
    service = UserService(db_session)
    
    session = await service.create_stream_session()
    
    assert session is not None
    assert session.id is not None
    assert session.ended_at is None


@pytest.mark.asyncio
async def test_end_stream_session(db_session):
    """Тест завершения сессии стрима"""
    service = UserService(db_session)
    
    session = await service.create_stream_session()
    result = await service.end_stream_session(session.id)
    
    assert result is True
    assert session.ended_at is not None