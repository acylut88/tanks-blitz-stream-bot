"""
Web и API маршруты для админки, дашборда и оверлеев
"""
from app.api.websocket import run_raffle_process
from app.config import settings
from app.core.cnst_Bot import TankType
from app.core.cnst_Bot import MSG_TEMPLATES
from app.core.rewards import RewardService
from app.database.models import User, StreamStats, StreamSession
from app.services.pa_chance_service import PAChanceService
from app.database.session import async_session
from app.services.settings_service import SettingsService
from app.services.user_service import UserService
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Response, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc, distinct
import asyncio
import structlog

logger = structlog.get_logger()

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

# --- Простая авторизация через Cookie ---
def check_auth(request: Request):
    return request.cookies.get("auth_token") == settings.admin_password

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if check_auth(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == settings.admin_username and password == settings.admin_password:
        # ✅ ПРАВИЛЬНО: устанавливаем cookie НА RedirectResponse
        response = RedirectResponse(url="/dashboard", status_code=302)
        response.set_cookie(
            key="auth_token", 
            value=settings.admin_password, 
            httponly=True,
            samesite="lax",
            max_age=86400  # 24 часа
        )
        return response
    
    # Неверный пароль — показываем ошибку
    return templates.TemplateResponse(
        "login.html", 
        {"request": request, "error": "Неверный логин или пароль"}, 
        status_code=401
    )

@router.get("/logout")
async def logout(response: Response):
    response.delete_cookie("auth_token")
    return RedirectResponse(url="/login", status_code=302)

# --- Защищённые страницы ---
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("dashboard.html", {"request": request})

@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("admin.html", {"request": request})

# --- Публичные оверлеи (без защиты) ---
@router.get("/overlay/leaderboard", response_class=HTMLResponse)
async def overlay_lb(request: Request):
    return templates.TemplateResponse("overlay_leaderboard.html", {"request": request})

@router.get("/overlay/raffle", response_class=HTMLResponse)
async def overlay_raffle(request: Request):
    return templates.TemplateResponse("overlay_raffle.html", {"request": request})

# --- API Эндпоинты для фронтенда ---
@router.get("/api/stream/stats")
async def get_stream_stats():
    async with async_session() as session:
        # Сначала находим ПОСЛЕДНЮЮ активную сессию
        result = await session.execute(
            select(StreamSession.id)
            .filter(StreamSession.ended_at.is_(None))
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        active_session_id = result.scalar_one_or_none()
        
        if not active_session_id:
            # Нет активной сессии
            return {"active_users": 0, "total_bm": 0, "queue_size": 0}
        
        # Считаем статистику ТОЛЬКО для этой сессии
        result = await session.execute(
            select(func.count(distinct(User.id)), func.sum(StreamStats.current_bm))
            .join(StreamStats, User.id == StreamStats.user_id)
            .filter(StreamStats.session_id == active_session_id)
        )
        active_users, total_bm = result.one()
        
        from app.main import dispatcher
        queue_size = dispatcher.queue.qsize() if dispatcher else 0
        
        return {
            "active_users": active_users or 0, 
            "total_bm": total_bm or 0, 
            "queue_size": queue_size
        }

@router.get("/api/stream/top")
async def get_stream_top():
    async with async_session() as session:
        # Находим последнюю активную сессию
        result = await session.execute(
            select(StreamSession.id)
            .filter(StreamSession.ended_at.is_(None))
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        active_session_id = result.scalar_one_or_none()
        
        if not active_session_id:
            return []
        
        # Получаем топ только для этой сессии
        result = await session.execute(
            select(User.nick, StreamStats.current_bm)
            .join(StreamStats, User.id == StreamStats.user_id)
            .filter(StreamStats.session_id == active_session_id)
            .order_by(desc(StreamStats.current_bm))
            .limit(5)
        )
        return [{"nick": row[0], "bm": row[1]} for row in result.all()]

@router.post("/api/stream/start")
async def start_stream_api():
    async with async_session() as session:
        service = UserService(session)
        
        # ЗАКРЫВАЕМ все предыдущие активные сессии
        result = await session.execute(
            select(StreamSession).filter(StreamSession.ended_at.is_(None))
        )
        old_sessions = result.scalars().all()
        
        for old_session in old_sessions:
            old_session.ended_at = datetime.now(timezone.utc)
            logger.info("Auto-closed old session", id=old_session.id)
        
        # Создаем новую сессию
        new_session = await service.create_stream_session()
        await session.commit()
        
        logger.info("Stream started via API", new_id=new_session.id)
        return {"message": "🟢 Стрим начат! Предыдущие сессии закрыты."}

@router.post("/api/stream/stop")
async def stop_stream_api():
    # Здесь можно добавить логику списания ПА, аналогичную cmd_stop_stream
    return {"message": "🔴 Стрим остановлен! (Логика списания ПА будет добавлена)"}

@router.post("/api/stream/raffle")
async def raffle_api():
   
    
    # Запускаем рулетку в фоне
    asyncio.create_task(run_raffle_process())
    
    return {"message": "🎰 Рулетка запущена! Открой оверлей для просмотра."}

@router.post("/api/admin/grant-premium")
async def grant_premium_api(request: dict):
    nick = request.get("nick")
    streams = request.get("streams", 1)
    
    async with async_session() as session:
        service = UserService(session)
        success = await service.grant_premium(nick, streams)
        await session.commit()
        
        if success:
            logger.info("Premium granted via API", nick=nick, streams=streams)
            return {"message": f"✅ Начислено {streams} ПА для {nick}"}
        else:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

@router.patch("/api/admin/dispatcher-delay")
async def update_delay_api(request: dict):
    new_delay = request.get("delay", 0.4)
    from app.main import dispatcher
    if dispatcher:
        dispatcher.send_delay = new_delay
        logger.info("Dispatcher delay updated", delay=new_delay)
    return {"message": f"Задержка изменена на {new_delay} сек"}

@router.post("/api/admin/grant-loot")
async def grant_loot_api(request: Request, body: dict):
    """Ручная выдача лутбоксов/танков через админку"""
    user_nick = body.get("nick")
    box_count = body.get("box_count", 1)
    
    if not user_nick or box_count <= 0:
        raise HTTPException(status_code=400, detail="Укажите ник и количество > 0")
    
    async with async_session() as session:
        # 1. Ищем пользователя
        user_result = await session.execute(select(User).filter(User.nick == user_nick))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        # 2. Крутим рулетку
        loot = RewardService.roll_loot(box_count)
        gained_bm = RewardService.calculate_bm(loot)
        
        # 3. Обновляем пожизненную статистику
        user.lifetime_tanks_lt += loot.get(TankType.LT, 0)
        user.lifetime_tanks_st += loot.get(TankType.CT, 0)
        user.lifetime_tanks_tt += loot.get(TankType.TT, 0)
        user.lifetime_tanks_pt += loot.get(TankType.PT, 0)
        user.lifetime_boxes_opened += box_count
        
        # 4. Получаем активную сессию
        active_session_result = await session.execute(
            select(StreamSession.id)
            .filter(StreamSession.ended_at.is_(None))
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        active_session_id = active_session_result.scalar_one_or_none()
        
        stats = None
        if active_session_id:
            stats_result = await session.execute(
                select(StreamStats).filter(
                    StreamStats.user_id == user.id,
                    StreamStats.session_id == active_session_id
                )
            )
            stats = stats_result.scalar_one_or_none()
            if not stats:
                stats = StreamStats(user_id=user.id, session_id=active_session_id)
                session.add(stats)
            stats.current_bm += gained_bm
        
        # 5. 🔥 Проверяем шанс выпадения ПА (только если есть активная сессия)
        pa_dropped = False
        if stats:
            from app.services.pa_chance_service import PAChanceService
            pa_dropped = await PAChanceService.try_roll_pa(user, stats)
        
        # 6. 🔥 ОДИН КОММИТ НА ВСЁ
        await session.commit()
        
        # 7. Отправляем ЛС
        dispatcher = request.app.state.dispatcher
        drops_str = RewardService.format_drops(loot)
        msg_text = f"Ручная выдача от админа: {drops_str} | +{gained_bm} БМ"
        await dispatcher.add_message(user_nick, msg_text, priority=1)
        
        if pa_dropped:
            pa_msg = MSG_TEMPLATES["pa_drop"]
            await dispatcher.add_message(user_nick, pa_msg, priority=2)
        
        logger.info(f"Admin granted {box_count} boxes to {user_nick}: {loot}")
        
        return {
            "message": f"Выдано {box_count} боксов",
            "loot": drops_str,
            "bm": gained_bm
        }

@router.get("/api/admin/users-list")
async def get_users_list_api():
    """Получить список всех ников для автодополнения"""
    async with async_session() as session:
        result = await session.execute(
            select(User.nick).order_by(User.nick)
        )
        nicks = result.scalars().all()
        return {"users": nicks}


# --- API для настроек ---
@router.get("/api/admin/settings")
async def get_all_settings_api(category: str = None):
    """Получить все настройки или по категории"""
    settings = await SettingsService.get_all_settings(category)
    return {"settings": settings}

@router.get("/api/admin/settings/{key}")
async def get_setting_api(key: str):
    """Получить одну настройку"""
    value = await SettingsService.get_setting(key)
    if value is None:
        raise HTTPException(status_code=404, detail="Setting not found")
    return {"key": key, "value": value}

@router.patch("/api/admin/settings/{key}")
async def update_setting_api(key: str, request: dict):
    """Обновить настройку"""
    value = request.get("value")
    description = request.get("description")
    category = request.get("category")
    
    if value is None:
        raise HTTPException(status_code=400, detail="Value is required")
    
    # 🔥 Добавим логирование
    logger.info(f"Updating setting: key={key}, value={value}")
    
    await SettingsService.set_setting(key, value, description, category)
    
    # 🔥 Проверяем, что сохранилось
    saved_value = await SettingsService.get_setting(key)
    logger.info(f"Saved value: {saved_value}")
    
    return {"message": f"Setting '{key}' updated", "value": value}

@router.post("/api/admin/settings/initialize")
async def initialize_defaults_api():
    """Инициализировать настройки по умолчанию"""
    await SettingsService.initialize_defaults()
    return {"message": "Default settings initialized"}

# --- API для пользователей ---
@router.get("/api/admin/users")
async def get_all_users_api():
    """Получить список всех пользователей с корректным расчётом БМ"""
    async with async_session() as session:
        # Получить активную сессию
        active_session_result = await session.execute(
            select(StreamSession.id)
            .filter(StreamSession.ended_at.is_(None))
            .order_by(StreamSession.started_at.desc())
            .limit(1)
        )
        active_session = active_session_result.scalar_one_or_none()
        
        # Получить всех пользователей
        result = await session.execute(
            select(User).order_by(User.last_seen.desc())
        )
        users = result.scalars().all()
        
        users_data = []
        for user in users:
            # БМ за текущий стрим
            stream_bm = 0
            if active_session:
                stream_stats_result = await session.execute(
                    select(StreamStats.current_bm)
                    .filter(
                        StreamStats.user_id == user.id,
                        StreamStats.session_id == active_session
                    )
                )
                stats = stream_stats_result.scalar_one_or_none()
                stream_bm = stats if stats else 0
            
            # БМ за ВСЁ время = БМ за все прошлые стримы + БМ за текущий стрим
            # Для этого нужно получить все завершённые сессии пользователя
            all_sessions_result = await session.execute(
                select(func.sum(StreamStats.current_bm))
                .filter(
                    StreamStats.user_id == user.id,
                    StreamStats.session_id != active_session if active_session else True
                )
            )
            past_bm = all_sessions_result.scalar() or 0
            
            # Итоговая БМ за всё время
            total_lifetime_bm = past_bm + stream_bm
            
            users_data.append({
                "id": user.id,
                "nick": user.nick,
                "vk_id": user.vk_id,
                "premium_streams_left": user.premium_streams_left,
                "lifetime_streams_with_premium": user.lifetime_streams_with_premium,
                "lifetime_boxes_opened": user.lifetime_boxes_opened,
                "lifetime_tanks_lt": user.lifetime_tanks_lt,
                "lifetime_tanks_st": user.lifetime_tanks_st,
                "lifetime_tanks_tt": user.lifetime_tanks_tt,
                "lifetime_tanks_pt": user.lifetime_tanks_pt,
                "first_seen": user.first_seen.isoformat() if user.first_seen else None,
                "last_seen": user.last_seen.isoformat() if user.last_seen else None,
                "stream_bm": stream_bm,
                "lifetime_bm": total_lifetime_bm,  # Теперь включает и текущий стрим
            })
        
        return users_data

@router.patch("/api/admin/users/{user_id}")
async def update_user_api(user_id: int, request: dict):
    """Обновить данные пользователя"""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Обновляем только разрешённые поля
        allowed_fields = [
            "premium_streams_left",
            "lifetime_tanks_lt",
            "lifetime_tanks_st",
            "lifetime_tanks_tt",
            "lifetime_tanks_pt",
            "lifetime_boxes_opened",
        ]
        
        for field in allowed_fields:
            if field in request:
                setattr(user, field, request[field])
        
        await session.commit()
        logger.info("User updated via API", user_id=user_id, nick=user.nick)
        return {"message": f"Пользователь {user.nick} обновлён"}
    
@router.post("/api/admin/users/{user_id}/add-tanks")
async def add_tanks_to_user(user_id: int, request: dict):
    """Добавить танки пользователю (для тестирования)"""
    tank_type = request.get("tank_type")  # "lt", "st", "tt", "pt"
    count = request.get("count", 1)
    
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Добавляем танки
        if tank_type == "lt":
            user.lifetime_tanks_lt += count
        elif tank_type == "st":
            user.lifetime_tanks_st += count
        elif tank_type == "tt":
            user.lifetime_tanks_tt += count
        elif tank_type == "pt":
            user.lifetime_tanks_pt += count
        else:
            raise HTTPException(status_code=400, detail="Invalid tank type")
        
        # Пересчитываем БМ
        total_bm = (user.lifetime_tanks_lt * 1 + 
                   user.lifetime_tanks_st * 2 + 
                   user.lifetime_tanks_tt * 3 + 
                   user.lifetime_tanks_pt * 4)
        
        await session.commit()
        
        logger.info(f"Added {count} {tank_type} tanks to user {user.nick}")
        return {
            "message": f"Добавлено {count} {tank_type.upper()} танков",
            "total_bm": total_bm
        }