import aiohttp
import logging
import os
import random
from typing import Dict, List, Optional, Union
from aiohttp_proxy import ProxyConnector

logger = logging.getLogger(__name__)

class BaseParser:
    """Базовый класс для парсеров"""
    
    def __init__(self):
        self.session = None
        self.last_request_time = 0
        self.min_delay = 2
        self.max_delay = 5
        
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
        ]
        
        self.proxies = self._load_proxies()
        
        self.base_headers = {
            'Accept': 'application/json',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://autodoc.ru',
            'Referer': 'https://autodoc.ru/'
        }
        
    def _load_proxies(self) -> List[str]:
        """Загрузка списка прокси из файла"""
        proxies = []
        try:
            proxy_file = 'config/proxy_list.txt'
            if os.path.exists(proxy_file):
                with open(proxy_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            proxies.append(line)
            logger.info(f"Загружено {len(proxies)} прокси серверов")
        except Exception as e:
            logger.error(f"Ошибка при загрузке прокси: {e}")
        return proxies
        
    def _get_random_user_agent(self) -> str:
        """Получение случайного User-Agent"""
        return random.choice(self.user_agents)
        
    def _get_random_proxy(self) -> Optional[str]:
        """Получение случайного прокси"""
        return random.choice(self.proxies) if self.proxies else None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение сессии с прокси и случайным User-Agent"""
        if not self.session or self.session.closed:
            proxy = self._get_random_proxy()
            connector = ProxyConnector.from_url(proxy) if proxy else None
            
            headers = self.base_headers.copy()
            headers['User-Agent'] = self._get_random_user_agent()
            
            self.session = aiohttp.ClientSession(
                connector=connector,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.session
        
    async def _make_request(self, url: str, method: str = 'GET', **kwargs) -> Optional[Union[Dict, List]]:
        """Выполняет HTTP запрос с обработкой ошибок и прокси"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }
        
        if 'headers' in kwargs:
            headers.update(kwargs['headers'])
        kwargs['headers'] = headers
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, **kwargs) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"Request failed with status {response.status}: {url}")
                        return None
        except Exception as e:
            logger.error(f"Error making request to {url}: {e}")
            return None
            
    async def close(self):
        """Закрытие сессии"""
        if self.session and not self.session.closed:
            await self.session.close()
