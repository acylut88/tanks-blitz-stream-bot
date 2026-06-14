"""
WebSocket API для рулетки на вылет (Raffle) - Пошаговый режим
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

active_connections: List[WebSocket] = []

# Состояние рулетки (очередь событий)
raffle_state = {
    "queue": [],
    "is_active": False,
    "participants": []
}

class ConnectionManager:
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        active_connections.append(websocket)
        logger.info("New WebSocket client connected (OBS Overlay)")

    def disconnect(self, websocket: WebSocket):
        if websocket in active_connections:
            active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()


class RaffleService:
    @staticmethod
    async def get_eligible_participants(session_id: int) -> List[Dict]:
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
        total_bm = sum(p["bm"] for p in participants)
        weights = []
        for p in participants:
            elimination_chance = 1 - (p["bm"] / total_bm)
            weight = max(elimination_chance, 0.01)
            weights.append(weight)
        
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]
        
        eliminated = random.choices(participants, weights=normalized_weights, k=1)[0]
        participants.remove(eliminated)
        return eliminated


async def process_next_step():
    """Отправить следующее событие из очереди"""
    if raffle_state["queue"]:
        event = raffle_state["queue"].pop(0)
        await manager.broadcast(event)
        
        # Если очередь пуста, рулетка завершена
        if not raffle_state["queue"]:
            raffle_state["is_active"] = False
            await manager.broadcast({"event": "finish", "message": "🏆 Розыгрыш завершен!"})


@router.websocket("/ws/raffle")
async def websocket_raffle_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Ждём сигнал от фронтенда "Готов к следующему шагу"
            data = await websocket.receive_text()
            if data == "next_step":
                await process_next_step()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def run_raffle_process():
    """Подготовка и запуск рулетки"""
    async with async_session() as session:
        service = UserService(session)
        result = await session.execute(
            select(StreamSession.id)
            .filter(StreamSession.ended_at.is_(None))
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        active_session_id = result.scalar_one_or_none()
        
        if not active_session_id:
            await manager.broadcast({"event": "error", "message": "Нет активного стрима!"})
            return

        participants = await RaffleService.get_eligible_participants(active_session_id)
        
        if len(participants) < 4:
            await manager.broadcast({"event": "error", "message": "Недостаточно участников (минимум 4)!"})
            return

        # 1. Рассчитываем ВСЮ последовательность заранее
        steps = []
        temp_participants = list(participants)
        
        # Вылеты до Топ-3
        while len(temp_participants) > 3:
            eliminated = RaffleService.eliminate_one(temp_participants)
            steps.append({
                "event": "eliminate",
                "nick": eliminated["nick"],
                "bm": eliminated["bm"],
                "remaining": len(temp_participants)
            })
        
        # Финальная тройка - определяем 3-е место (первый вылет из тройки)
        third_place = RaffleService.eliminate_one(temp_participants)
        steps.append({
            "event": "place", 
            "place": 3, 
            "nick": third_place["nick"], 
            "bm": third_place["bm"], 
            "prize": "1 ПА"
        })
        
        # Определяем 2-е место (второй вылет из тройки)
        second_place = RaffleService.eliminate_one(temp_participants)
        steps.append({
            "event": "place", 
            "place": 2, 
            "nick": second_place["nick"], 
            "bm": second_place["bm"], 
            "prize": "2 ПА"
        })
        
        # 1-е место (остался последний)
        first_place = temp_participants[0]
        steps.append({
            "event": "place", 
            "place": 1, 
            "nick": first_place["nick"], 
            "bm": first_place["bm"], 
            "prize": "2 ПА + Главный приз"
        })

        # 2. Сохраняем результаты в БД
        session_obj = await session.get(StreamSession, active_session_id)
        session_obj.winner_1_nick = first_place["nick"]
        session_obj.winner_2_nick = second_place["nick"]
        session_obj.winner_3_nick = third_place["nick"]
        
        await service.grant_premium(first_place["nick"], 2)
        await service.grant_premium(second_place["nick"], 2)
        await service.grant_premium(third_place["nick"], 1)
        await session.commit()

        # 3. Заполняем очередь и отправляем старт
        raffle_state["queue"] = steps
        raffle_state["is_active"] = True
        raffle_state["participants"] = participants
        
        await manager.broadcast({
            "event": "start",
            "participants": participants,
            "total_count": len(participants)
        })
        
        logger.info("Raffle prepared and started", steps_count=len(steps))