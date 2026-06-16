# 📚 Документация проекта VK Stream Tanks Bot

## 🎯 Описание проекта

Бот для стримов VK Live (Танки Блиц/Леста), который:
- Отслеживает активации наград зрителями
- Начисляет Боевую Мощь (БМ) через рулетку танков
- Проводит розыгрыши на вылет с анимацией
- Отправляет результаты в ЛС через VK Live API
- Имеет веб-интерфейс (дашборд, админка, оверлей)

---

## 🏗️ Структура проекта
VKStream_TanksBlitzLesta_Qwen/
├── app/
│ ├── api/
│ │ ├── routes.py # REST API endpoints
│ │ └── websocket.py # WebSocket для рулетки
│ ├── bot/
│ │ ├── handler.py # Обработчик сообщений чата
│ │ └── commands.py # Команды (!стат, !топ, !розыгрыш)
│ ├── core/
│ │ ├── cnst_Bot.py # Константы, шаблоны сообщений
│ │ └── rewards.py # Логика рулетки, расчёт БМ
│ ├── database/
│ │ ├── models.py # SQLAlchemy модели (User, StreamSession, StreamStats, Setting)
│ │ ├── session.py # Асинхронная сессия БД
│ │ └── migrations/ # Alembic миграции
│ ├── services/
│ │ ├── user_service.py # Бизнес-логика пользователей
│ │ ├── message_dispatcher.py # Очередь ЛС с автоудалением из чата
│ │ └── settings_service.py # Управление настройками
│ ├── web/
│ │ ├── templates/
│ │ │ ├── admin.html # Админка (управление пользователями, настройками)
│ │ │ ├── dashboard.html # Дашборд (статистика стрима)
│ │ │ ├── login.html # Страница входа
│ │ │ └── overlay_raffle.html # Оверлей рулетки для OBS
│ │ └── auth.py # Аутентификация
│ ├── config.py # Настройки из .env
│ └── main.py # FastAPI приложение, lifespan
├── tests/ # Тестовые скрипты
├── .env.test.txt # Конфиг для тестового канала (scr)
├── .env.prod.txt # Конфиг для продакшена (acylut)
├── run.py # Точка входа
└── PROJECT_DOCUMENTATION.md # Этот файл


---

## 🗄️ База данных

### Таблицы:

#### `users` - Пользователи
id: int                    # Primary key
vk_id: str                 # VK ID (nullable)
nick: str                  # Никнейм (unique)
premium_streams_left: int  # Осталось ПА жетонов
lifetime_streams_with_premium: int  # Всего стримов с ПА
lifetime_boxes_opened: int # Всего открыто ящиков
pending_boxes: int         # Отложенные ящики (за прошлый стрим)
lifetime_tanks_lt: int     # Лёгкие танки (×1 БМ)
lifetime_tanks_st: int     # Средние танки (×2 БМ)
lifetime_tanks_tt: int     # Тяжёлые танки (×3 БМ)
lifetime_tanks_pt: int     # ПТ-САУ (×4 БМ)
first_seen: datetime       # Первое появление
last_seen: datetime        # Последнее появление

#### `stream_sessions` - Сессии стримов
id: int                    # Primary key
started_at: datetime       # Начало стрима
ended_at: datetime         # Конец стрима (nullable)
winner_1_nick: str         # 1 место
winner_2_nick: str         # 2 место
winner_3_nick: str         # 3 место

#### `stream_stats` - Статистика за стрим
id: int                    # Primary key
user_id: int               # Foreign key → users.id
session_id: int            # Foreign key → stream_sessions.id
activations_count: int     # Кол-во активаций (0-12)
current_bm: int            # БМ за текущий стрим

#### `settings` - Настройки (key-value)
key: str                   # Primary key (например, "raffle.animSettings.totalDuration")
value: text                # JSON строка
description: str           # Описание
category: str              # Категория (raffle, dispatcher, general)
updated_at: datetime       # Последнее обновление

### 🔑 Ключевые настройки (в БД)
Рулетка:
raffle.animSettings.totalDuration - Время анимации (сек)
raffle.animSettings.fastRatio - Доля быстрого вращения (0-1)
raffle.animSettings.pausePhase - Пауза после выбора (сек)
raffle.prizes.1/2/3 - Тексты призов (для отображения)
raffle.boxes.1/2/3 - Кол-во лутбоксов за места
raffle.pa.1/2/3 - Кол-во ПА за места
Диспетчер:
dispatcher.send_delay - Задержка между сообщениями (сек)
dispatcher.overload_threshold - Порог перегрузки очереди


## 🌐 API Endpoints
### Публичные:
GET / - Дашборд
GET /admin - Админка (требует авторизацию)
GET /overlay/raffle - Оверлей рулетки
WS /ws/raffle - WebSocket для рулетки

### Админка:
GET /api/admin/users - Список пользователей
PATCH /api/admin/users/{id} - Обновить пользователя
POST /api/admin/users/{id}/add-tanks - Добавить танки
GET /api/admin/users-list - Список ников (для автодополнения)
POST /api/admin/grant-premium - Начислить ПА
POST /api/admin/grant-loot - Ручная выдача лутбоксов
GET /api/admin/settings - Все настройки
PATCH /api/admin/settings/{key} - Обновить настройку
POST /api/admin/settings/initialize - Сброс настроек

### Стрим:
GET /api/stream/stats - Статистика текущего стрима




## 🤖 Логика бота
### Обработка наград (handler.py):
- Парсит системное сообщение: "{nick} получает награду: {reward_name} за {count}"
- Фильтрует по settings.allowed_reward_name (например, "Поставка техники")
- Инкрементирует activations_count
- Рассчитывает кол-во ящиков через RewardService.calculate_boxes(activation, has_premium)
- Крутит рулетку: RewardService.roll_loot(box_count)
- Начисляет БМ и танки
- Отправляет ЛС через dispatcher.add_message()
- Если 12-я активация → выдаёт ПА жетон

### Розыгрыш (websocket.py):
- Получает всех участников с БМ >= 1
- Рассчитывает последовательность вылетов (взвешенная случайность по БМ)
- Определяет Топ-3
- Начисляет призы (лутбоксы + ПА) в pending_boxes
- Отправляет события через WebSocket: start, eliminate, place, finish
### Отправка ЛС (message_dispatcher.py):
- Формирует команду /w {nick} {text}
- Отправляет POST запрос в VK Live API
- Получает message_id из ответа
- Удаляет сообщение из чата через DELETE запрос
- ЛС доставлено, но в чате не видно


## 🎮 Команды чата
### Зрители:
- `!стат` / `!stats` - Статистика за текущий стрим
- `!фулстат` / `!fullstats` - Полная статистика
- `!топ` / `!top` - Топ-5 по БМ

### Стимер (whitelist):
- `!новыйстрим` / `!start` - Начать новый стрим
- `!стопстрим` / `!stop` - Завершить стрим, списать ПА
- `!розыгрыш` / `!raffle` - Запустить рулетку


## 🔧 Конфигурация (.env)
### Тестовый канал:
VK_CHANNEL_NAME=scr
VK_CHANNEL_OWNER_NAME=SkilloCrabs
VK_CHANNEL_OWNER_ID=29850510
CHAT_PAGE_URL=https://live.vkvideo.ru/scr/stream/default/only-chat
VK_LIVE_TOKEN=<токен из браузера>
STREAMER_WHITELIST=SkilloCrabs
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/tanksbot_test
MESSAGE_DELAY=0.4
QUEUE_MAX_SIZE=200
OVERLOAD_THRESHOLD=50
LOG_LEVEL=DEBUG
ALLOWED_REWARD_NAME=Поставка техники
ADMIN_USERNAME=admin
ADMIN_PASSWORD=Password

### Продакшен:
VK_CHANNEL_NAME=acylut
VK_CHANNEL_OWNER_NAME=Acylut Games
VK_CHANNEL_OWNER_ID=19847703
VK_LIVE_TOKEN=<токен из браузера>
STREAMER_WHITELIST=Acylut,Acylut Games
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/tanksbot_prod
MESSAGE_DELAY=0.3
QUEUE_MAX_SIZE=200
OVERLOAD_THRESHOLD=50
LOG_LEVEL=INFO
ALLOWED_REWARD_NAME=Поставка техники
ADMIN_USERNAME=admin
ADMIN_PASSWORD=Password


## 🚀 Запуск
# Активировать виртуальное окружение
.venv\Scripts\activate

# Запустить бота
python run.py

# Бот доступен на http://127.0.0.1:8000
# Админка: http://127.0.0.1:8000/admin
# Дашборд: http://127.0.0.1:8000/
# Оверлей: http://127.0.0.1:8000/overlay/raffle


## 📝 Важные моменты
`Токен VK Live` - получается из браузера через DevTools (Network → POST запрос → Authorization header). Протухает через несколько дней.
`Автоудаление из чата` - после отправки ЛС бот автоматически удаляет сообщение /w из чата, чтобы не спамить.
`Pending boxes` - награды за розыгрыш не начисляются сразу, а сохраняются в pending_boxes и открываются при первой активации на следующем стриме.
`Настройки в БД` - все параметры рулетки и диспетчера хранятся в таблице settings и могут меняться через админку без перезапуска.
`WebSocket` - оверлей рулетки подключается через WebSocket и получает события в реальном времени.


## 🐛 Известные проблемы
`ConnectionResetError` - Windows-specific ошибка при обновлении страницы оверлея. Не критична, игнорируется.
`Токен протухает` - нужно периодически обновлять VK_LIVE_TOKEN в .env.

### PA из бокса (прогрессивный шанс):
- `pa.base_chance = 0.005` - базовый шанс
- `pa.chance_step = 0.001` - шаг за каждый бокс
- `pa.pity_threshold = 50` - гарант
- `pa.max_per_stream = 1` - макс ПА за стрим
- Формула: `chance = 0.005 + (boxes_since_last_pa × 0.001)`
- Поле `boxes_since_last_pa` в User - счётчик
- Поле `pa_received_this_stream` в StreamStats - ограничение за стрим


## 📅 История изменений
### 15.06.2026
Этап 8: Ручная выдача наград через админку
Этап 9: Отправка ЛС через VK Live API с автоудалением из чата
### 14.06.2026
Этап 1-4: Базовая логика бота, обработка наград, рулетка танков
Этап 5: Веб-интерфейс (дашборд, админка, логин)
Этап 6: Рулетка на вылет с WebSocket и анимацией
Этап 7: Админка с настройками, автообновление


## 🎯 Планы на будущее
Интеграция с VK API для автоматического получения токена
Система достижений для зрителей
Экспорт статистики в CSV/Excel
Мобильное приложение для стримера
Интеграция с другими стриминговыми платформами
!ВАЖНО! Убрать выдачу ПА в 12 ящике. Сделаем ПА только за покупки и врозыгрыше и можно добавить 0,1-1% на выпадение