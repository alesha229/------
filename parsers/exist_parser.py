import aiohttp
import logging
import json
from typing import List, Dict
import re
from bs4 import BeautifulSoup
import asyncio

logger = logging.getLogger(__name__)

class ExistParser:
    def __init__(self):
        self.session = None
        self.BASE_URL = "https://exist.ru"
        self.SEARCH_URL = "https://exist.ru/Price/?pcode={}"
        self.HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://exist.ru/',
            'Connection': 'keep-alive'
        }

    async def create_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(headers=self.HEADERS)
        return self.session

    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None

    def extract_data_from_script(self, html_content: str) -> List[Dict]:
        """
        Извлекает данные из JavaScript массива _data
        """
        try:
            # Ищем массив _data в скрипте
            data_match = re.search(r'var\s+_data\s*=\s*(\[.*?\]);', html_content, re.DOTALL)
            if not data_match:
                logger.error("_data array not found in script")
                return []

            # Получаем JSON строку и парсим её
            json_str = data_match.group(1)
            data = json.loads(json_str)
            
            logger.info(f"Found {len(data)} items in _data array")
            
            results = []
            for item in data:
                try:
                    # Получаем первое предложение из AggregatedParts
                    if item.get('AggregatedParts') and len(item['AggregatedParts']) > 0:
                        offer = item['AggregatedParts'][0]
                        
                        # Извлекаем цену из priceString (убираем "₽" и пробелы)
                        price_str = offer.get('priceString', '').replace('₽', '').replace(' ', '')
                        try:
                            price = float(price_str)
                        except ValueError:
                            price = 0.0
                        
                        result = {
                            'source': 'Exist.ru',
                            'part_name': item.get('Description', ''),
                            'part_number': item.get('PartNumber', ''),
                            'brand': item.get('Brand', {}).get('Name', 'Не указан'),
                            'price': price,
                            'url': f"{self.BASE_URL}/Price/?pcode={item.get('PartNumber', '')}",
                            'in_stock': offer.get('inStock', False),
                            'delivery_days': offer.get('deliveryPeriod', {}).get('max', None),
                            'rating': None,
                            'reviews_count': 0
                        }
                        results.append(result)
                        logger.info(f"Processed item: {result}")
                except Exception as e:
                    logger.error(f"Error processing item: {e}", exc_info=True)
                    continue
                    
            return results
            
        except Exception as e:
            logger.error(f"Error extracting data from script: {e}", exc_info=True)
            return []

    async def search_part(self, part_number: str) -> List[Dict]:
        """
        Поиск запчасти на exist.ru
        """
        try:
            logger.info(f"Starting search for part number: {part_number}")
            
            # Получаем страницу поиска
            search_url = self.SEARCH_URL.format(part_number)
            logger.info(f"Search URL: {search_url}")
            
            session = await self.create_session()
            
            try:
                async with session.get(search_url) as response:
                    if response.status != 200:
                        logger.error(f"Search page error: {response.status}")
                        return []
                    
                    html = await response.text()
                    
                    # Извлекаем данные из JavaScript
                    results = self.extract_data_from_script(html)
                    
                    logger.info(f"Total results found: {len(results)}")
                    return results
                    
            except Exception as e:
                logger.error(f"Error during search request: {e}", exc_info=True)
                return []
                
        except Exception as e:
            logger.error(f"Error in search_part: {e}", exc_info=True)
            return []
        finally:
            await self.close_session()

# Создаем экземпляр парсера
exist_parser = ExistParser()
