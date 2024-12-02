import re
import aiohttp
import logging
from typing import Optional, Tuple, List, Dict
from .autodoc_article_parser import AutodocArticleParser
from .autodoc_car_parser import AutodocCarParser
from .autodoc_vin_parser import AutodocVinParser

logger = logging.getLogger(__name__)

class AutodocParserFactory:
    """Фабрика для создания парсеров Autodoc"""
    
    _brands_cache: List[Dict] = []
    
    @classmethod
    async def _fetch_brands(cls) -> List[Dict]:
        """Получает список брендов с API Autodoc"""
        if cls._brands_cache:
            return cls._brands_cache
            
        url = "https://catalogoriginal.autodoc.ru/api/catalogs/original/brands"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        brands = await response.json()
                        cls._brands_cache = brands
                        return brands
                    else:
                        logger.error(f"Failed to fetch brands: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching brands: {e}")
            return []
    
    @classmethod
    async def get_brand_names(cls) -> List[str]:
        """Возвращает список названий брендов"""
        brands = await cls._fetch_brands()
        return [brand['name'] for brand in brands]
    
    @staticmethod
    def is_vin(query: str) -> bool:
        """Проверяет, является ли запрос VIN номером"""
        pattern = r'^[A-HJ-NPR-Z0-9]{17}$'
        return bool(re.match(pattern, query))

    @staticmethod
    def is_article_number(query: str) -> bool:
        """Проверяет, является ли запрос артикулом"""
        # Более строгий паттерн для артикула:
        # - Должен содержать хотя бы одну цифру
        # - Может содержать буквы, цифры и дефис
        # - Длина от 5 до 20 символов
        pattern = r'^(?=.*\d)[A-Za-z0-9-]{5,20}$'
        return bool(re.match(pattern, query))

    @classmethod
    async def is_car_search(cls, query: str) -> bool:
        """
        Проверяет, является ли запрос поиском по марке/модели автомобиля
        :param query: поисковый запрос
        :return: True если это поиск по авто, False если нет
        """
        # Если запрос содержит цифры и дефисы, это скорее всего артикул
        if cls.is_article_number(query):
            return False
            
        # Получаем список брендов
        brands = await cls.get_brand_names()
        query_words = query.lower().split()
        normalized_brands = [brand.lower() for brand in brands]
        
        # Проверяем, есть ли название бренда в запросе
        for brand in normalized_brands:
            if brand in query_words:
                return True
                
        return False

    @classmethod
    async def extract_car_info(cls, query: str) -> Optional[Tuple[str, str, Optional[int]]]:
        """
        Извлекает информацию об автомобиле из запроса
        Возвращает (производитель, модель, год) или None
        """
        brands = await cls.get_brand_names()
        
        # Ищем год в запросе
        year_match = re.search(r'\b(19|20)\d{2}\b', query)
        year = int(year_match.group()) if year_match else None
        
        # Нормализуем запрос и бренды
        query_lower = query.lower()
        normalized_brands = [(brand.lower(), brand) for brand in brands]
        
        # Ищем бренд в запросе
        found_brand = None
        for norm_brand, original_brand in normalized_brands:
            if norm_brand in query_lower:
                found_brand = original_brand
                # Убираем бренд из запроса для извлечения модели
                model_text = query_lower.replace(norm_brand, '').strip()
                if year_match:
                    # Убираем год из текста модели
                    model_text = model_text.replace(year_match.group(), '').strip()
                if model_text:
                    return found_brand, model_text, year
                    
        return None

    @classmethod
    async def create_parser(cls, query: str):
        """
        Создает соответствующий парсер на основе запроса
        :param query: запрос
        :return: парсер
        """
        if cls.is_vin(query):
            return AutodocVinParser()
        elif await cls.is_car_search(query):
            return AutodocCarParser()
        elif cls.is_article_number(query):
            return AutodocArticleParser()
        else:
            # Если запрос состоит из одного слова и это похоже на название бренда
            if len(query.split()) == 1 and not query.isdigit():
                return AutodocCarParser()
            return AutodocArticleParser()

    @classmethod
    async def get_search_type(cls, query: str) -> str:
        """
        Определяет тип поиска на основе запроса
        :param query: поисковый запрос
        :return: тип поиска ('vin', 'car', 'article')
        """
        if cls.is_vin(query):
            return "vin"
        elif await cls.is_car_search(query):
            return "car"
        elif cls.is_article_number(query):
            return "article"
        else:
            # Если запрос состоит из одного слова и это похоже на название бренда
            if len(query.split()) == 1 and not query.isdigit():
                return "car"
            return "article"