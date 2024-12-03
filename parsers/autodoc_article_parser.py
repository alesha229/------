import os
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
import aiohttp
import random
import asyncio
import time
from .base_parser import BaseParser

# Настройка логирования
def setup_logger():
    logger = logging.getLogger('autodoc_parser')
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Создаем директорию для логов если её нет
        os.makedirs('logs', exist_ok=True)
        
        # Хендлер для файла
        fh = logging.FileHandler('logs/autodoc_parser.log', encoding='utf-8')
        fh.setLevel(logging.INFO)
        
        # Хендлер для консоли
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # Форматтер
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger

logger = setup_logger()

class AutodocArticleParser(BaseParser):
    """Парсер для сайта Autodoc.ru"""
    
    def __init__(self, session: aiohttp.ClientSession = None):
        super().__init__()
        self.session = session or aiohttp.ClientSession()
        self.last_request_time = 0
        self.min_delay = 2  # минимальная задержка между запросами в секундах
        self.max_delay = 5  # максимальная задержка
        
        # Список User-Agent для ротации
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
        ]
        
        self.base_headers = {
            'Accept': 'application/json',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://autodoc.ru',
            'Referer': 'https://autodoc.ru/'
        }
        
        logger.info("Инициализация парсера Autodoc")
        
    def _get_random_user_agent(self) -> str:
        """Получение случайного User-Agent"""
        return random.choice(self.user_agents)
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение сессии с случайным User-Agent"""
        if not self.session or self.session.closed:
            headers = self.base_headers.copy()
            headers['User-Agent'] = self._get_random_user_agent()
            
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.session
        
    async def _make_request(self, url: str, method: str = 'GET', **kwargs) -> Optional[Dict]:
        """Выполнение запроса с защитой от блокировки"""
        try:
            # Задержка между запросами
            current_time = time.time()
            if self.last_request_time:
                elapsed = current_time - self.last_request_time
                if elapsed < self.min_delay:
                    delay = random.uniform(self.min_delay, self.max_delay)
                    await asyncio.sleep(delay)
            
            session = await self._get_session()
            
            # Обновляем User-Agent для каждого запроса
            session.headers['User-Agent'] = self._get_random_user_agent()
            
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    async with session.request(method, url, **kwargs) as response:
                        self.last_request_time = time.time()
                        
                        if response.status == 429:  # Too Many Requests
                            retry_count += 1
                            wait_time = 30 * retry_count
                            logger.warning(f"[RATE LIMIT] Rate limit hit, waiting {wait_time} seconds...")
                            await asyncio.sleep(wait_time)
                            continue
                            
                        if response.status != 200:
                            logger.error(f"[REQUEST ERROR] Status: {response.status}, URL: {url}")
                            return None
                            
                        return await response.json()
                        
                except aiohttp.ClientError as e:
                    retry_count += 1
                    logger.error(f"[REQUEST ERROR] Attempt {retry_count}/{max_retries}: {str(e)}")
                    if retry_count == max_retries:
                        raise
                    await asyncio.sleep(5)
                    
        except Exception as e:
            logger.error(f"[REQUEST ERROR] {str(e)}", exc_info=True)
            return None
            
    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def close(self):
        """Закрытие сессии"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def get_manufacturers(self, article: str) -> List[Dict]:
        """Получает список производителей для артикула"""
        try:
            url = f'https://webapi.autodoc.ru/api/manufacturers/{article}?showAll=true'
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Origin': 'https://autodoc.ru',
                'Referer': 'https://autodoc.ru'
            }
            
            async with self.session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"[ERROR] Failed to get manufacturers: {response.status}")
                    return []
                    
                data = await response.json()
                
                # Сохраняем ответ в файл для логирования
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_file = f"logs/responses/manufacturers_{article}_{timestamp}.json"
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                with open(log_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                return data if isinstance(data, list) else []
                
        except Exception as e:
            logger.error(f"[ERROR] Failed to get manufacturers: {str(e)}", exc_info=True)
            return []

    async def get_part_details(self, manufacturer_id: int, part_number: str) -> Dict:
        """Получает детальную информацию о запчасти"""
        try:
            url = f"https://webapi.autodoc.ru/api/manufacturer/{manufacturer_id}/sparepart/{part_number}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Origin': 'https://autodoc.ru',
                'Referer': 'https://autodoc.ru'
            }
            
            async with self.session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"[ERROR] Failed to get part details: {response.status}")
                    return {}
                    
                data = await response.json()
                
                # Сохраняем ответ в файл для логирования
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_file = f"logs/responses/details_{manufacturer_id}_{part_number}_{timestamp}.json"
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                with open(log_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                quantity = data.get('priceQuantity', 0)
                
                # Парсим результат
                result = {
                    'source': 'Autodoc.ru',
                    'name': data.get('partName', ''),
                    'number': data.get('partNumber', ''),
                    'brand': data.get('manufacturerName', ''),
                    'price': data.get('minimalPrice', 0),
                    'quantity': quantity,  # Добавляем количество в наличии
                    'in_stock': quantity > 0,  # Флаг наличия
                    'delivery_days': 1 if quantity > 0 else None,
                    'description': data.get('description', ''),
                    'url': f"https://autodoc.ru/man/{manufacturer_id}/part/{part_number}",
                    'image': data.get('galleryModel', {}).get('imgUrls', [])[0] if data.get('galleryModel', {}).get('imgUrls') else None,
                    'rating': data.get('mark', {}).get('avg', 0),
                    'reviews': data.get('mark', {}).get('cnt', 0)
                }
                
                return result
                
        except Exception as e:
            logger.error(f"[ERROR] Failed to get part details: {str(e)}", exc_info=True)
            return {}

    async def search_by_article(self, article: str) -> List[Dict]:
        """Поиск запчастей по артикулу"""
        try:
            # Получаем список производителей для артикула
            manufacturers = await self.get_manufacturers(article)
            logger.info(f"[SEARCH] Found {len(manufacturers)} manufacturers")
            
            results = []
            for manufacturer in manufacturers:
                manufacturer_id = manufacturer.get('id')
                logger.info(f"[SEARCH] Processing {manufacturer.get('name')} (ID: {manufacturer_id})")
                
                # Получаем детали по производителю
                details = await self.get_part_details(manufacturer_id, article)
                
                if details:
                    results.append(details)
            
            logger.info(f"[SEARCH] Total parts found: {len(results)}")
            return results
            
        except Exception as e:
            logger.error(f"[ERROR] Search failed: {str(e)}", exc_info=True)
            return []

    async def search(self, query: str) -> List[Dict]:
        """Универсальный метод поиска"""
        try:
            logger.info(f"Начинаем поиск по запросу: {query}")
            return await self.search_by_article(query)
        except Exception as e:
            logger.error(f"Ошибка при поиске: {e}", exc_info=True)
            return []

    async def parse_details(self, response_data: dict) -> dict:
        """Парсит детальную информацию о запчасти"""
        try:
            return {
                'name': response_data.get('partName', ''),
                'brand': response_data.get('manufacturerName', ''),
                'article': response_data.get('partNumber', ''),
                'description': response_data.get('description', ''),
                'price': response_data.get('minimalPrice', 0),
                'quantity': response_data.get('priceQuantity', 0),
                'delivery_days': 1 if response_data.get('priceQuantity', 0) > 0 else None,
                'url': f"https://autodoc.ru/man/{response_data.get('manufacturerId')}/part/{response_data.get('partNumber')}",
                'image_url': response_data.get('galleryModel', {}).get('imgUrls', [])[0] if response_data.get('galleryModel', {}).get('imgUrls') else None,
                'rating': response_data.get('mark', {}).get('avg', 0),
                'reviews_count': response_data.get('mark', {}).get('cnt', 0)
            }
        except Exception as e:
            logger.error(f"Error parsing details: {e}", exc_info=True)
            return {}
