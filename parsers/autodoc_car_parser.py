from typing import Dict, List, Optional
import logging
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

class AutodocCarParser(BaseParser):
    """Парсер для поиска запчастей по марке/модели автомобиля"""

    async def get_brand_code(self, brand_name: str) -> Optional[str]:
        """
        Получение кода бренда по его названию
        
        :param brand_name: Название бренда (например, 'HONDA')
        :return: Код бренда или None если не найден
        """
        url = "https://catalogoriginal.autodoc.ru/api/catalogs/original/brands"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        
        try:
            brands = await self._make_request(url, headers=headers)
            if not brands:
                return None
                
            # Ищем бренд по названию (регистронезависимо)
            brand_name = brand_name.upper()
            for brand in brands:
                if brand.get('name', '').upper() == brand_name:
                    return brand.get('code')
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get brand code for {brand_name}: {e}")
            return None

    async def get_wizard_data(self, brand_name: str, ssd: str = None) -> Dict:
        """
        Получение данных мастера выбора модели
        
        :param brand_name: Название бренда (например, 'HONDA')
        :param ssd: Параметр сессии (опционально)
        :return: Словарь с данными мастера
        """
        # Получаем код бренда
        brand_code = await self.get_brand_code(brand_name)
        if not brand_code:
            logger.error(f"Brand code not found for {brand_name}")
            return {}
            
        url = f"https://catalogoriginal.autodoc.ru/api/catalogs/original/brands/{brand_code}/wizzard"
        if ssd:
            url += f"?ssd={ssd}"
            
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        
        try:
            data = await self._make_request(url, headers=headers)
            if not data:
                return {}
                
            return data
            
        except Exception as e:
            logger.error(f"Failed to get wizard data for brand {brand_name}: {e}")
            return {}

    def extract_models(self, wizard_data: Dict) -> List[Dict]:
        """
        Извлечение списка моделей из данных мастера
        
        :param wizard_data: Данные мастера
        :return: Список моделей с их ключами
        """
        models = []
        try:
            # Получаем SSD ключ из ответа API
            ssd = wizard_data.get('ssd')
            if ssd:
                models.append({
                    'key': ssd,
                    'name': wizard_data.get('selectedModel', {}).get('name', '')
                })
            
            # Получаем остальные модели из списка опций
            for item in wizard_data.get('items', []):
                if item.get('name') == 'Модель':
                    for option in item.get('options', []):
                        models.append({
                            'key': option.get('key'),
                            'name': option.get('value')
                        })
            return models
        except Exception as e:
            logger.error(f"Failed to extract models: {e}")
            return []

    def extract_years(self, wizard_data: Dict) -> List[Dict]:
        """
        Извлечение списка годов из данных мастера
        
        :param wizard_data: Данные мастера
        :return: Список годов выпуска с их SSD ключами
        """
        years = []
        try:
            # Получаем SSD ключ из ответа API если год уже выбран
            ssd = wizard_data.get('ssd')
            if ssd:
                selected_year = wizard_data.get('selectedYear')
                if selected_year:
                    years.append({
                        'key': ssd,
                        'year': selected_year
                    })
            
            # Получаем остальные годы из списка опций
            for item in wizard_data.get('items', []):
                if item.get('name') == 'Год':
                    for option in item.get('options', []):
                        years.append({
                            'key': option.get('key'),
                            'year': option.get('value')
                        })
            return years
        except Exception as e:
            logger.error(f"Failed to extract years: {e}")
            return []

    async def get_modifications(self, brand_name: str, ssd: str) -> List[Dict]:
        """
        Получение списка модификаций для выбранной модели и года
        
        :param brand_name: Название бренда (например, 'HONDA')
        :param ssd: SSD параметр с выбранным годом
        :return: Список модификаций
        """
        # Получаем код бренда
        brand_code = await self.get_brand_code(brand_name)
        if not brand_code:
            logger.error(f"Brand code not found for {brand_name}")
            return []
            
        url = f"https://catalogoriginal.autodoc.ru/api/catalogs/original/brands/{brand_code}/wizzard/0/modifications"
        params = {'ssd': ssd}
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        
        try:
            data = await self._make_request(url, headers=headers, params=params)
            if not data:
                return []
            
            modifications = []
            for mod in data:
                modifications.append({
                    'key': mod.get('key'),
                    'name': mod.get('name'),
                    'engine': mod.get('engine'),
                    'power': mod.get('power'),
                    'year': mod.get('year')
                })
            return modifications
            
        except Exception as e:
            logger.error(f"Failed to get modifications: {e}")
            return []

    async def search(self, brand_name: str, model_key: str = None, year_key: str = None) -> List[Dict]:
        """
        Пошаговый поиск запчастей по марке/модели
        
        :param brand_name: Название бренда (например, 'HONDA')
        :param model_key: SSD ключ модели
        :param year_key: SSD ключ с выбранным годом
        :return: Список найденных запчастей или информация для следующего шага
        """
        try:
            # Если нет модели, получаем список моделей
            if not model_key:
                wizard_data = await self.get_wizard_data(brand_name)
                return self.extract_models(wizard_data)
                
            # Если есть модель, но нет года
            if not year_key:
                wizard_data = await self.get_wizard_data(brand_name, model_key)
                return self.extract_years(wizard_data)
                
            # Если есть и модель и год, получаем модификации
            return await self.get_modifications(brand_name, year_key)
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def get_parts(self, brand_name: str, model_key: str, modification_key: str) -> List[Dict]:
        """Получение списка запчастей для выбранной модификации"""
        # Получаем код бренда
        brand_code = await self.get_brand_code(brand_name)
        if not brand_code:
            logger.error(f"Brand code not found for {brand_name}")
            return []
            
        url = f"https://catalogoriginal.autodoc.ru/api/catalogs/original/brands/{brand_code}/parts"
        params = {
            'modelKey': model_key,
            'modificationKey': modification_key
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        
        try:
            data = await self._make_request(url, headers=headers, params=params)
            if not data:
                return []
                
            parts = []
            for part in data:
                parts.append({
                    'number': part.get('number'),
                    'name': part.get('name'),
                    'brand': part.get('brand', {}).get('name'),
                    'price': part.get('price', {}).get('value'),
                    'availability': 'В наличии' if part.get('isAvailable') else 'Нет в наличии',
                    'description': part.get('description'),
                    'category': part.get('category', {}).get('name')
                })
            return parts
            
        except Exception as e:
            logger.error(f"Failed to get parts: {e}")
            return []
