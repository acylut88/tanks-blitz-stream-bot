"""
WebSocket API для рулетки на вылет (Raffle)
"""
import asyncio
import random
from typing import List, Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, desc
from app.database.session import async_session
from app.database.models import User, StreamStats, StreamSession
from app.services.user_service import UserService
import structlog

logger = structlog.get_logger()

router = APIRouter()

# Хранилище активных подключений (для OBS оверлея)
active_connections: List[WebSocket] = []

class ConnectionManager:
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        active_connections.append(websocket)
        logger.info("New WebSocket client connected (OBS Overlay)")

    def disconnect(self, websocket: WebSocket):
        if websocket in active_connections:
            active_connections.remove(websocket)
        logger.info("WebSocket client disconnected")

    async def broadcast(self, message: dict):
        """Отправить событие всем подключенным клиентам (OBS)"""
        for connection in active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()


class RaffleService:
    """Логика рулетки на вылет"""
    
    @staticmethod
    async def get_eligible_participants(session_id: int) -> List[Dict]:
        """Получить всех участников ТЕКУЩЕЙ сессии с БМ >= 1"""
        async with async_session() as session:
            result = await session.execute(
                select(User.nick, StreamStats.current_bm)
                .join(StreamStats, User.id == StreamStats.user_id)
                .filter(
                    StreamStats.session_id == session_id,
                    StreamStats.current_bm >= 1
                )
                .order_by(desc(StreamStats.current_bm))
            )
            return [{"nick": row[0], "bm": row[1]} for row in result.all()]

    @staticmethod
    def eliminate_one(participants: List[Dict]) -> Dict:
        """
        Выбрать одного на вылет.
        Формула: Шанс вылета = 1 - (БМ_игрока / Сумма_всех_БМ)
        """
        total_bm = sum(p["bm"] for p in participants)
        
        weights = []
        for p in participants:
            elimination_chance = 1 - (p["bm"] / total_bm)
            weight = max(elimination_chance, 0.01) # Защита от нулевых весов
            weights.append(weight)
        
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]
        
        eliminated = random.choices(participants, weights=normalized_weights, k=1)[0]
        participants.remove(eliminated)
        
        return eliminated


@router.websocket("/ws/raffle")
async def websocket_raffle_endpoint(websocket: WebSocket):
    """Эндпоинт для подключения OBS оверлея"""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() # Держим соединение открытым
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def run_raffle_process():
    """
    Основная функция, которую вызывает команда !розыгрыш.
    """
    async with async_session() as session:
        service = UserService(session)
        # Берем ПОСЛЕДНЮЮ активную сессию (как мы делали в дашборде)
        result = await session.execute(
            select(StreamSession.id)
            .filter(StreamSession.ended_at.is_(None))
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        active_session_id = result.scalar_one_or_none()
        
        if not active_session_id:
            logger.warning("Cannot start raffle: no active stream session")
            await manager.broadcast({"event": "error", "message": "Нет активного стрима!"})
            return

        participants = await RaffleService.get_eligible_participants(active_session_id)
        
        if len(participants) < 4:
            logger.warning("Not enough participants for raffle", count=len(participants))
            await manager.broadcast({"event": "error", "message": "Недостаточно участников (минимум 4)!"})
            return

        # 1. Старт
        await manager.broadcast({
            "event": "start",
            "participants": participants,
            "total_count": len(participants)
        })
        await asyncio.sleep(3)

        # 2. Цикл вылетов до Топ-3
        while len(participants) > 3:
            eliminated = RaffleService.eliminate_one(participants)
            
            await manager.broadcast({
                "event": "eliminate",
                "nick": eliminated["nick"],
                "bm": eliminated["bm"],
                "remaining": len(participants)
            })
            await asyncio.sleep(2.5) # Пауза между вылетами

        # 3. Финальная тройка (определяем 3, 2, 1 места)
        third_place = RaffleService.eliminate_one(participants)
        await manager.broadcast({
            "event": "place", "place": 3, "nick": third_place["nick"], 
            "bm": third_place["bm"], "prize": "1 ПА"
        })
        await asyncio.sleep(3)

        second_place = RaffleService.eliminate_one(participants)
        await manager.broadcast({
            "event": "place", "place": 2, "nick": second_place["nick"], 
            "bm": second_place["bm"], "prize": "2 ПА"
        })
        await asyncio.sleep(3)

        first_place = participants[0]
        await manager.broadcast({
            "event": "place", "place": 1, "nick": first_place["nick"], 
            "bm": first_place["bm"], "prize": "2 ПА + Главный приз"
        })

        # 4. Сохраняем результаты и начисляем призы в БД
        session_obj = await session.get(StreamSession, active_session_id)
        session_obj.winner_1_nick = first_place["nick"]
        session_obj.winner_2_nick = second_place["nick"]
        session_obj.winner_3_nick = third_place["nick"]
        
        await service.grant_premium(first_place["nick"], 2)
        await service.grant_premium(second_place["nick"], 2)
        await service.grant_premium(third_place["nick"], 1)
        
        await session.commit()
        
        await manager.broadcast({"event": "finish", "message": "🏆 Розыгрыш завершен!"})
        logger.info("Raffle completed", winner1=first_place["nick"])