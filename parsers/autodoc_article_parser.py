import aiohttp
import logging
import json
import os
from typing import Dict, List, Optional
from datetime import datetime
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
    
    def __init__(self):
        super().__init__()
        self.session = None
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

    async def get_part_details(self, session: aiohttp.ClientSession, category_id: str, 
                             brand: str, ssd: str) -> Optional[Dict]:
        """Получает детальную информацию о запчасти"""
        try:
            logger.info(f"Получаем детали для category_id={category_id}")
            url_units = f'https://catalogoriginal.autodoc.ru/api/catalogs/original/brands/{brand}/cars/0/quickgroups/{category_id}/units'
            data = {'ssd': ssd}
            
            response = await self._make_request(url_units, method='POST', json=data)
            if not response:
                return None
            
            json_data = response
            if not json_data:
                logger.error("Нет данных о запчастях")
                return None
            
            part_number = None
            try:
                for unit in json_data:
                    for part in unit.get('parts', []):
                        part_number = part['partNumber']
                        break
            except (IndexError, KeyError) as e:
                logger.error(f"Ошибка при извлечении номера детали: {e}", exc_info=True)
                return None
            
            if not part_number:
                logger.error("Номер детали не найден")
                return None
        
            details_url = f'https://catalogoriginal.autodoc.ru/api/spareparts/{part_number}'
            response = await self._make_request(details_url)
            if not response:
                return None
            
            details_data = response
            if not details_data:
                logger.error("Нет данных о детали")
                return None

            return {
                'part_number': part_number,
                'details': details_data
            }
                
        except Exception as e:
            logger.error(f"Ошибка при получении деталей запчасти: {e}", exc_info=True)
            return None

    async def get_part_details_manufacturer(self, manufacturer_id: int, part_number: str) -> Dict:
        """Получение детальной информации о запчасти конкретного производителя"""
        try:
            # URL для API получения деталей
            api_url = f'https://webapi.autodoc.ru/api/manufacturer/{manufacturer_id}/sparepart/{part_number}'
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Origin': 'https://autodoc.ru',
                'Referer': f'https://autodoc.ru/man/{manufacturer_id}/part/{part_number}'
            }

            logger.info(f"[REQUEST] GET {api_url}")
            logger.info(f"[REQUEST] Headers: {json.dumps(headers, indent=2, ensure_ascii=False)}")
            
            response = await self._make_request(api_url, headers=headers)
            if not response:
                return {}
            
            data = response
            
            # Сохраняем ответ для отладки
            os.makedirs('logs/responses', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            response_file = f'logs/responses/details_{manufacturer_id}_{part_number}_{timestamp}.json'
            with open(response_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[RESPONSE] Saved to file: {response_file}")
            logger.info(f"[DEBUG] API Response: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            # Извлекаем данные из ответа API
            price = float(data.get('minimalPrice', 0))
            quantity = int(data.get('priceQuantity', 0))
            delivery_days = data.get('deliveryDays')
            description = data.get('description', '')
            
            result = {
                'price': price,
                'in_stock': quantity,  # Теперь возвращаем количество вместо булева значения
                'delivery_days': delivery_days,
                'description': description,
                'url': f'https://autodoc.ru/man/{manufacturer_id}/part/{part_number}'
            }
            
            logger.info(f"[PARSED] Successfully parsed details: {json.dumps(result, ensure_ascii=False, indent=2)}")
            return result
                        
        except Exception as e:
            logger.error(f"[ERROR] Failed to get part details: {str(e)}", exc_info=True)
            return {}

    async def search_part(self, part_number: str) -> List[Dict]:
        """Поиск запчасти по номеру через API"""
        try:
            logger.info(f"[SEARCH] Starting search for part: {part_number}")
            
            # Нормализуем номер детали
            part_number = part_number.strip().upper()
            
            # URL для API поиска производителей
            api_url = f'https://webapi.autodoc.ru/api/manufacturers/{part_number}?showAll=true'
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Origin': 'https://autodoc.ru',
                'Referer': 'https://autodoc.ru/',
            }

            logger.info(f"[REQUEST] GET {api_url}")
            
            response = await self._make_request(api_url, headers=headers)
            if not response:
                return []
            
            manufacturers_data = response
            
            # Сохраняем ответ для отладки
            os.makedirs('logs/responses', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            manufacturers_file = f'logs/responses/{part_number}_manufacturers_{timestamp}.json'
            with open(manufacturers_file, 'w', encoding='utf-8') as f:
                json.dump(manufacturers_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[RESPONSE] Manufacturers saved to: {manufacturers_file}")
            
            if not manufacturers_data:
                logger.warning(f"[RESPONSE] No manufacturers found for {part_number}")
                return []
                
            manufacturer_count = len(manufacturers_data)
            logger.info(f"[SEARCH] Found {manufacturer_count} manufacturers")
            
            results = []
            
            # Обрабатываем каждого производителя
            for idx, manufacturer in enumerate(manufacturers_data, 1):
                try:
                    # Логируем данные производителя
                    logger.info(f"[DEBUG] Raw manufacturer data: {json.dumps(manufacturer, indent=2, ensure_ascii=False)}")
                    
                    manufacturer_id = manufacturer.get('id')
                    manufacturer_name = manufacturer.get('manufacturerName', 'Unknown')
                    part_name = manufacturer.get('partName', '')
                    
                    if not manufacturer_id:
                        logger.error(f"[ERROR] No manufacturer ID found in: {manufacturer}")
                        continue
                    
                    logger.info(f"[SEARCH] Processing {manufacturer_name} (ID: {manufacturer_id})")
                    
                    # Получаем детальную информацию о запчасти
                    details = await self.get_part_details_manufacturer(manufacturer_id, part_number)
                    
                    if not details:
                        logger.warning(f"[SEARCH] No details found for {manufacturer_name} (ID: {manufacturer_id})")
                        continue
                    
                    result = {
                        'source': 'Autodoc.ru',
                        'part_name': part_name,
                        'part_number': part_number,
                        'brand': manufacturer_name,
                        'price': details.get('price', 0),
                        'url': details.get('url', ''),
                        'in_stock': details.get('in_stock', 0),  # Теперь возвращаем количество вместо булева значения
                        'delivery_days': details.get('delivery_days'),
                        'manufacturer_name': manufacturer_name,
                        'minimal_price': details.get('price', 0),
                        'description': details.get('description', ''),
                        'properties': details.get('properties', [])
                    }
                    
                    # Логируем результат для отладки
                    logger.info(f"[RESULT] Part details: {json.dumps(result, ensure_ascii=False, indent=2)}")
                    
                    # Проверяем наличие обязательных полей
                    if result['price'] == 0:
                        logger.warning(f"[WARNING] Price is 0 for {manufacturer_name}")
                    if result['in_stock'] == 0:
                        logger.warning(f"[WARNING] Part not in stock for {manufacturer_name}")
                    
                    results.append(result)
                    
                except Exception as e:
                    logger.error(f"[ERROR] Failed to process manufacturer: {str(e)}", exc_info=True)
                    continue
            
            logger.info(f"[SEARCH] Total parts found: {len(results)}")
            return results
            
        except Exception as e:
            logger.error(f"[ERROR] Search failed: {str(e)}", exc_info=True)
            return []

    async def search_by_article(self, article: str) -> List[Dict]:
        """Поиск запчастей по артикулу"""
        try:
            logger.info(f"[ARTICLE SEARCH] Starting search for article: {article}")
            
            # Нормализуем артикул
            article = article.strip().upper()
            
            # URL для API поиска производителей
            api_url = f'https://webapi.autodoc.ru/api/manufacturers/{article}?showAll=true'
            
            logger.info(f"[REQUEST] GET {api_url}")
            
            try:
                response = await self._make_request(api_url)
                if not response:
                    return []
                
                manufacturers_data = response
                
                # Сохраняем ответ для отладки
                os.makedirs('logs/responses', exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                manufacturers_file = f'logs/responses/{article}_manufacturers_{timestamp}.json'
                with open(manufacturers_file, 'w', encoding='utf-8') as f:
                    json.dump(manufacturers_data, f, ensure_ascii=False, indent=2)
                
                logger.info(f"[RESPONSE] Manufacturers saved to: {manufacturers_file}")
                
                if not manufacturers_data:
                    logger.warning(f"[RESPONSE] No manufacturers found for {article}")
                    return []
                    
                manufacturer_count = len(manufacturers_data)
                logger.info(f"[SEARCH] Found {manufacturer_count} manufacturers")
                
                results = []
                
                # Обрабатываем каждого производителя
                for manufacturer in manufacturers_data:
                    try:
                        manufacturer_id = manufacturer.get('id')
                        manufacturer_name = manufacturer.get('manufacturerName', 'Unknown')
                        part_name = manufacturer.get('partName', '')
                        
                        if not manufacturer_id:
                            logger.error(f"[ERROR] No manufacturer ID found in: {manufacturer}")
                            continue
                        
                        logger.info(f"[SEARCH] Processing {manufacturer_name} (ID: {manufacturer_id})")
                        
                        # Получаем детальную информацию о запчасти
                        details = await self.get_part_details_manufacturer(manufacturer_id, article)
                        
                        if not details:
                            logger.warning(f"[SEARCH] No details found for {manufacturer_name} (ID: {manufacturer_id})")
                            continue
                        
                        # Convert in_stock to availability boolean
                        is_available = details.get('in_stock', 0) > 0
                        
                        result = {
                            'source': 'Autodoc.ru',
                            'name': part_name,
                            'number': article,
                            'brand': manufacturer_name,
                            'price': float(details.get('price', 0)),  # Ensure price is float
                            'url': details.get('url', ''),
                            'in_stock': details.get('in_stock', 0),
                            'delivery_days': details.get('delivery_days'),
                            'manufacturer': manufacturer_name,
                            'description': details.get('description', ''),
                            'availability': is_available  # Add availability field
                        }
                        
                        results.append(result)
                        
                    except Exception as e:
                        logger.error(f"[ERROR] Failed to process manufacturer: {str(e)}", exc_info=True)
                        continue
                
                logger.info(f"[SEARCH] Total parts found: {len(results)}")
                return results
            
            finally:
                await self.close()
                
        except Exception as e:
            logger.error(f"[ERROR] Failed to search by article: {str(e)}", exc_info=True)
            return []

    async def search(self, query: str) -> List[Dict]:
        """Универсальный метод поиска"""
        try:
            logger.info(f"Начинаем поиск по запросу: {query}")
            return await self.search_by_article(query)
        except Exception as e:
            logger.error(f"Ошибка при поиске: {e}", exc_info=True)
            return []
