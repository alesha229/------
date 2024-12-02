import os
import json
import logging
from typing import Dict, List
from datetime import datetime
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

class AutodocVinParser(BaseParser):
    """Парсер для поиска запчастей по VIN номеру"""
    async def get_car_data(self, vin: str) -> Optional[Dict]:
        """Получает данные об автомобиле по VIN номеру"""
        try:
            logger.info(f"Получаем данные автомобиля по VIN: {vin}")
            url = f'https://catalogoriginal.autodoc.ru/api/catalogs/original/cars/{vin}/modifications'
            
            response = await self._make_request(url)
            if not response:
                return None
            
            json_data = response
            common_attrs = json_data.get('commonAttributes', [])
            
            if not common_attrs or len(common_attrs) < 9:
                logger.error("Неверный формат данных автомобиля")
                return None

            try:
                return {
                    'brand': common_attrs[0]['value'],
                    'model': common_attrs[1]['value'],
                    'modification': common_attrs[2]['value'],
                    'year': common_attrs[3]['value'],
                    'catalog': common_attrs[4]['value'],
                    'date': common_attrs[8]['value']
                }
            except (IndexError, KeyError) as e:
                logger.error(f"Ошибка при извлечении данных автомобиля: {e}", exc_info=True)
                return None
                
        except Exception as e:
            logger.error(f"Ошибка при получении данных автомобиля: {e}", exc_info=True)
            return None

    
    async def search_by_vin(self, vin: str) -> List[Dict]:
        """Поиск запчастей по VIN номеру"""
        try:
            api_url = f'https://webapi.autodoc.ru/api/vehicles/vin/{vin}'
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Origin': 'https://autodoc.ru',
                'Referer': 'https://autodoc.ru/'
            }

            logger.info(f"[VIN SEARCH] Starting search for VIN: {vin}")
            
            response = await self._make_request(api_url, headers=headers)
            if not response:
                return []
            
            data = response
            
            # Сохраняем ответ для отладки
            os.makedirs('logs/responses', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            response_file = f'logs/responses/vin_search_{vin}_{timestamp}.json'
            with open(response_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Получаем информацию о модификации автомобиля
            modification = data.get('modification', {})
            if not modification:
                logger.warning(f"[WARNING] No modification found for VIN: {vin}")
                return []
            
            # Получаем список групп запчастей
            groups_url = f'https://webapi.autodoc.ru/api/vehicles/{modification["id"]}/groups'
            
            response = await self._make_request(groups_url, headers=headers)
            if not response:
                return []
            
            groups_data = response
            
            results = []
            for group in groups_data:
                # Получаем список запчастей для каждой группы
                parts_url = f'https://webapi.autodoc.ru/api/vehicles/{modification["id"]}/groups/{group["id"]}/parts'
                
                response = await self._make_request(parts_url, headers=headers)
                if not response:
                    continue
                
                parts_data = response
                
                for part in parts_data:
                    result = {
                        'part_number': part.get('number'),
                        'part_name': part.get('name'),
                        'brand': part.get('brand', {}).get('name'),
                        'group_name': group.get('name'),
                        'source': 'Autodoc',
                        'url': f'https://autodoc.ru/catalogs/vehicle/{modification["id"]}/group/{group["id"]}'
                    }
                    results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"[ERROR] Failed to search by VIN: {str(e)}", exc_info=True)
            return []

    async def search(self, query: str) -> List[Dict]:
        """Основной метод поиска по VIN"""
        try:
            logger.info(f"Начинаем поиск по VIN: {query}")
            return await self.search_by_vin(query)
        except Exception as e:
            logger.error(f"Ошибка при поиске по VIN: {e}", exc_info=True)
            return []
