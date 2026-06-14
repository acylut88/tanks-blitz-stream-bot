"""
Клиент для работы с VK Live API
"""
import httpx
from typing import List, Dict, Optional
import structlog

logger = structlog.get_logger()


class VKLiveAPIClient:
    """Клиент для получения данных из VK Live API"""
    
    def __init__(self, channel_name: str):
        self.channel_name = channel_name
        self.base_url = f"https://api.live.vkvideo.ru/v1/channel/{channel_name}"
        self.bearer_token: Optional[str] = None
        
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru,en-US;q=0.9,en;q=0.8",
            "Origin": "https://live.vkvideo.ru",
            "Referer": f"https://live.vkvideo.ru/{channel_name}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-App": "streams_web"
        }
    
    def update_token(self, token: str):
        """Обновить Bearer token (вызывается из Playwright при перехвате)"""
        self.bearer_token = token
        self.headers["Authorization"] = f"Bearer {token}"
        logger.info("Bearer token updated", token_prefix=token[:20])
    
    async def get_online_viewers(self) -> List[Dict]:
        """
        Получить список зрителей онлайн
        
        Returns:
            List[Dict]: Список зрителей с полями {id, nick, displayName}
        """
        if not self.bearer_token:
            logger.warning("Bearer token not set, cannot fetch viewers")
            return []
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/stream/slot/default/chat/user/?with_bans=true",
                    headers=self.headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    viewers = data.get('data', {}).get('users', [])
                    logger.info("Fetched viewers", count=len(viewers))
                    return viewers
                else:
                    logger.error("Failed to fetch viewers", status_code=response.status_code)
                    return []
        
        except Exception as e:
            logger.error("Error fetching viewers", error=str(e))
            return []
    
    async def get_channel_owner(self) -> Optional[Dict]:
        """Получить информацию о владельце канала"""
        if not self.bearer_token:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/stream/slot/default/chat/user/?with_bans=true",
                    headers=self.headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get('data', {}).get('owner')
                return None
        
        except Exception as e:
            logger.error("Error fetching channel owner", error=str(e))
            return None