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
            data = await websocket.receive_text()
            if data == "next_step":
                await process_next_step()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket client disconnected normally")
    except ConnectionResetError:
        # Клиент закрыл соединение (обновил страницу)
        manager.disconnect(websocket)
        logger.info("WebSocket connection reset by client (page refresh)")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


async def run_raffle_process():
    """Подготовка и запуск рулетки"""
    from app.services.settings_service import SettingsService
    
    async with async_session() as session:
        service = UserService(session)
        
        # 🔥 Читаем настройки призов из БД
        boxes_1 = await SettingsService.get_setting("raffle.boxes.1", 10)
        boxes_2 = await SettingsService.get_setting("raffle.boxes.2", 8)
        boxes_3 = await SettingsService.get_setting("raffle.boxes.3", 6)
        boxes_eliminated = await SettingsService.get_setting("raffle.prizes.eliminated", 4)
        
        pa_1 = await SettingsService.get_setting("raffle.pa.1", 1)
        pa_2 = await SettingsService.get_setting("raffle.pa.2", 1)
        pa_3 = await SettingsService.get_setting("raffle.pa.3", 1)
        
        # 1. Получаем активную сессию
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

        # 2. Получаем участников
        participants = await RaffleService.get_eligible_participants(active_session_id)
        
        if len(participants) < 4:
            await manager.broadcast({"event": "error", "message": "Недостаточно участников (минимум 4)!"})
            return

        # 3. Рассчитываем последовательность
        steps = []
        temp_participants = list(participants)
        
        while len(temp_participants) > 3:
            eliminated = RaffleService.eliminate_one(temp_participants)
            steps.append({
                "event": "eliminate",
                "nick": eliminated["nick"],
                "bm": eliminated["bm"],
                "remaining": len(temp_participants)
            })
        
        third_place = RaffleService.eliminate_one(temp_participants)
        steps.append({
            "event": "place", "place": 3, 
            "nick": third_place["nick"], "bm": third_place["bm"], 
            "prize": f"{boxes_3} лутбоксов + {pa_3} ПА"
        })
        
        second_place = RaffleService.eliminate_one(temp_participants)
        steps.append({
            "event": "place", "place": 2, 
            "nick": second_place["nick"], "bm": second_place["bm"], 
            "prize": f"{boxes_2} лутбоксов + {pa_2} ПА"
        })
        
        first_place = temp_participants[0]
        steps.append({
            "event": "place", "place": 1, 
            "nick": first_place["nick"], "bm": first_place["bm"], 
            "prize": f"{boxes_1} лутбоксов + {pa_1} ПА"
        })

        # 4. Сохраняем результаты
        session_obj = await session.get(StreamSession, active_session_id)
        session_obj.winner_1_nick = first_place["nick"]
        session_obj.winner_2_nick = second_place["nick"]
        session_obj.winner_3_nick = third_place["nick"]
        
        # 5. Находим пользователей
        first_user_result = await session.execute(
            select(User).filter(User.nick == first_place["nick"])
        )
        first_user = first_user_result.scalar_one_or_none()
        
        second_user_result = await session.execute(
            select(User).filter(User.nick == second_place["nick"])
        )
        second_user = second_user_result.scalar_one_or_none()
        
        third_user_result = await session.execute(
            select(User).filter(User.nick == third_place["nick"])
        )
        third_user = third_user_result.scalar_one_or_none()
        
        # 6. 🔥 Начисляем ОТЛОЖЕННЫЕ ящики (pending_boxes)
        if first_user:
            first_user.pending_boxes = (first_user.pending_boxes or 0) + boxes_1
            first_user.premium_streams_left = (first_user.premium_streams_left or 0) + pa_1
            logger.info(f"1st place {first_user.nick}: +{boxes_1} pending boxes, +{pa_1} PA")

        if second_user:
            second_user.pending_boxes = (second_user.pending_boxes or 0) + boxes_2
            second_user.premium_streams_left = (second_user.premium_streams_left or 0) + pa_2
            logger.info(f"2nd place {second_user.nick}: +{boxes_2} pending boxes, +{pa_2} PA")

        if third_user:
            third_user.pending_boxes = (third_user.pending_boxes or 0) + boxes_3
            third_user.premium_streams_left = (third_user.premium_streams_left or 0) + pa_3
            logger.info(f"3rd place {third_user.nick}: +{boxes_3} pending boxes, +{pa_3} PA")
        
        await session.commit()

        # 7. Запускаем анимацию
        raffle_state["queue"] = steps
        raffle_state["is_active"] = True
        raffle_state["participants"] = participants
        
        await manager.broadcast({
            "event": "start",
            "participants": participants,
            "total_count": len(participants)
        })
        
        logger.info("Raffle prepared and started", steps_count=len(steps))