import aiohttp
import logging
import json
import re
from typing import Dict, List, Optional
from bs4 import BeautifulSoup

class AvtotoParser:
    BASE_URL = "https://avtoto.ru"
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }

    def extract_data_from_script(self, html: str) -> List[Dict]:
        """Извлекает данные о товарах из JavaScript на странице"""
        try:
            # Ищем JSON с данными о товарах
            data_pattern = r'window\.initialState\s*=\s*({.*?});'
            match = re.search(data_pattern, html, re.DOTALL)
            if not match:
                logging.error("Не найдены данные о товарах в JavaScript")
                return []

            # Парсим JSON
            data = json.loads(match.group(1))
            
            # Извлекаем товары из структуры данных
            products = data.get('searchResult', {}).get('items', [])
            
            results = []
            for product in products:
                try:
                    result = {
                        'source': 'Avtoto.ru',
                        'part_name': product.get('name', ''),
                        'part_number': product.get('article', ''),
                        'brand': product.get('brand', {}).get('name', ''),
                        'price': float(product.get('price', 0)),
                        'url': f"{self.BASE_URL}/catalog/product/{product.get('id', '')}",
                        'in_stock': product.get('inStock', False),
                        'delivery_days': product.get('deliveryDays', 0),
                        'rating': None,  # Avtoto не предоставляет рейтинги
                        'reviews_count': 0
                    }
                    results.append(result)
                except Exception as e:
                    logging.error(f"Ошибка при обработке товара: {e}")
                    continue
                    
            return results
        except Exception as e:
            logging.error(f"Ошибка при извлечении данных из JavaScript: {e}")
            return []

    async def search_part(self, part_number: str) -> List[Dict]:
        """Поиск запчасти по номеру"""
        try:
            logger.info(f"Начинаем поиск детали {part_number}")
            
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Первый запрос для получения cookies
                async with session.get(
                    self.BASE_URL,
                    headers=self.headers,
                    allow_redirects=True
                ) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка при начальном запросе: {response.status}")
                        return []
                
                # Основной запрос поиска
                search_url = f"{self.BASE_URL}/search/search?article={part_number}"
                logger.info(f"Запрос поиска: {search_url}")
                
                async with session.get(
                    search_url,
                    headers=self.headers,
                    allow_redirects=True
                ) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка при поиске: {response.status}")
                        logger.error(f"Ответ: {await response.text()}")
                        return []
                    
                    html = await response.text()
                    return self.extract_data_from_script(html)

        except aiohttp.ClientError as e:
            logger.error(f"Ошибка сети при запросе к Avtoto.ru: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Общая ошибка в парсере Avtoto.ru: {e}", exc_info=True)
            return []
