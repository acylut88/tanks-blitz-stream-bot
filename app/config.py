"""
Конфигурация приложения через Pydantic Settings
"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # VK Live Channel
    vk_channel_name: str = "scr"
    vk_channel_owner_name: str = "SkilloCrabs"
    vk_channel_owner_id: int = 29850510
    chat_page_url: str = "https://live.vkvideo.ru/scr/stream/default/only-chat"

    # VK Live API настройки
    vk_live_token: str = ""  # Токен авторизации (получаем из браузера)

    # Веб-интерфейс и авторизация
    admin_username: str = "admin"
    admin_password: str = "supersecretpassword"  

    # Награды
    allowed_reward_name: str = "Поставка техники"  # 
    
    # Streamer whitelist
    streamer_whitelist: str = "SkilloCrabs"
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./tanksbot_test.db"
    
    # Dispatcher
    message_delay: float = 0.4
    queue_max_size: int = 200
    overload_threshold: int = 50
    
    # Logging
    log_level: str = "INFO"
    
    # Bot constants
    bot_poll_interval: int = 2
    bot_cache_limit: int = 500
    debounce_seconds: int = 1
    
    @property
    def streamer_whitelist_list(self) -> List[str]:
        """Получить whitelist как список"""
        return [nick.strip() for nick in self.streamer_whitelist.split(',')]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Глобальный экземпляр настроек
settings = Settings()