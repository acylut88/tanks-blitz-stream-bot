"""
Исправить NULL значения pending_boxes в БД
"""
import asyncio
from app.database.session import async_session
from app.database.models import User
from sqlalchemy import select, update

async def fix_pending_boxes():
    async with async_session() as session:
        # Обновляем все записи где pending_boxes IS NULL
        result = await session.execute(
            update(User)
            .where(User.pending_boxes.is_(None))
            .values(pending_boxes=0)
        )
        await session.commit()
        print(f"✅ Исправлено записей: {result.rowcount}")

if __name__ == "__main__":
    asyncio.run(fix_pending_boxes())