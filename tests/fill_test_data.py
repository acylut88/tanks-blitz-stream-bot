"""
Заполнить тестовые данные для пользователей
"""
import asyncio
from app.database.session import async_session
from app.database.models import User
from sqlalchemy import select
import random

async def fill_test_data():
    async with async_session() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        for user in users:
            # Случайное количество танков
            user.lifetime_tanks_lt = random.randint(5, 15)
            user.lifetime_tanks_st = random.randint(3, 10)
            user.lifetime_tanks_tt = random.randint(1, 5)
            user.lifetime_tanks_pt = random.randint(0, 2)
            user.lifetime_boxes_opened = random.randint(10, 30)
            
            # Расчёт БМ
            total_bm = (user.lifetime_tanks_lt * 1 + 
                       user.lifetime_tanks_st * 2 + 
                       user.lifetime_tanks_tt * 3 + 
                       user.lifetime_tanks_pt * 4)
            
            print(f"{user.nick}: ЛТ={user.lifetime_tanks_lt}, СТ={user.lifetime_tanks_st}, "
                  f"ТТ={user.lifetime_tanks_tt}, ПТ={user.lifetime_tanks_pt} => БМ={total_bm}")
        
        await session.commit()
        print("\n✅ Тестовые данные заполнены!")

if __name__ == "__main__":
    asyncio.run(fill_test_data())