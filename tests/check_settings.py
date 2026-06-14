"""
Проверить настройки в БД
"""
import asyncio
from app.database.session import async_session
from app.database.models import Setting
from sqlalchemy import select
import json

async def check_settings():
    async with async_session() as session:
        result = await session.execute(select(Setting))
        settings = result.scalars().all()
        
        print("=== НАСТРОЙКИ В БД ===")
        for s in settings:
            if 'raffle' in s.key:
                print(f"{s.key}: {json.loads(s.value)}")

if __name__ == "__main__":
    asyncio.run(check_settings())