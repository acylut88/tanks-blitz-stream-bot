"""
Web и API маршруты для админки, дашборда и оверлеев
"""
from fastapi import APIRouter, Request, Response, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.services.user_service import UserService
from app.database.session import async_session
from app.database.models import User, StreamStats, StreamSession
from sqlalchemy import select, func, desc, distinct
from datetime import datetime, timezone
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
    return {"message": "🎰 Рулетка скоро будет подключена!"}

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