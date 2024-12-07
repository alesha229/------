import asyncio
import json
from pathlib import Path
import re
from typing import Dict, List, Optional, Union, Tuple
import logging
from .base_parser import BaseParser

import aiohttp

logger = logging.getLogger(__name__)

class AutodocCarParser(BaseParser):
    """Парсер для поиска модификаций автомобилей и запчастей"""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://catalogoriginal.autodoc.ru/api/catalogs/original"
        self.wizard_url = f"{self.base_url}/brands/BMW202301/wizzard"
        

    async def get_brand_code(self, brand: str) -> Optional[str]:
        """Get manufacturer code by brand name"""
        url = f"{self.base_url}/brands"
        
        try:
            response = await self._make_request(url)
            if not response:
                logger.info("No response from API")
                return None
                
            brand_lower = brand.lower()
            items = response if isinstance(response, list) else response.get("items", [])
            
            for item in items:
                if not isinstance(item, dict):
                    continue
                    
                current_brand = item.get("brand", "")
                if current_brand.lower() == brand_lower:
                    return item.get("code")
            
            return None
            
        except Exception as e:
            logger.error(f"Error processing API response: {e}")
            return None


    async def get_models(self, brand_code: str, year: str) -> List[Dict]:
        """Get models by brand, year"""
        url = f"{self.base_url}/brands/{brand_code}/wizzard"
        logger.info(f"[REQUEST] GET {url}")
        
        try:
            response = await self._make_request(url)
            if not response or "items" not in response:
                return []
            
            # Список возможных названий поля модели
            model_field_names = ["Модель", "Серия", "Семейство", "Vehicle Family"]
            
            for item in response["items"]:
                if item["name"] in model_field_names:
                    logger.info(f"Found model field: {item['name']}")
                    return item["options"]
                    
            logger.warning(f"Model field not found in response. Available fields: {[item['name'] for item in response['items']]}")
            return []
            
        except Exception as e:
            logger.error(f"Error getting models: {e}")
            return []

    async def get_year_options(self, brand_code: str, model_key: str) -> List[Dict]:
        """Get available years after selecting model"""
        url = f"{self.base_url}/brands/{brand_code}/wizzard?ssd={model_key}"
        logger.info(f"[REQUEST] GET {url}")
        
        try:
            response = await self._make_request(url)
            if not response or "items" not in response:
                return []
                
            for item in response["items"]:
                if item["name"] == "Год":
                    return item["options"]
            return []
            
        except Exception as e:
            logger.error(f"Error getting years: {e}")
            return []

    async def get_modifications(self, brand: str, model: str, year: str, region: str = None) -> List[Dict]:
        """Get car modifications by brand, model, year and region"""
        try:
            # 1. Get brand code once
            brand_code = await self.get_brand_code(brand)
            if not brand_code:
                logger.info(f"Brand code not found for {brand}")
                return []

            # 4. Get models with region key
            models = await self.get_models(brand_code, year)
            if not models:
                logger.info(f"No models found for {brand}")
                return []

            # 5. Filter and find matching model
            model_key = None
            model_lower = model.lower()
            
            for m in models:
                m_value = m.get("value", "").lower()
                if model_lower in m_value or m_value in model_lower:
                    model_key = m.get("key")
                    break

            if not model_key:
                logger.info(f"Model key not found for {model}")
                return []

            # 6. Get years with model key
            years = await self.get_year_options(brand_code, model_key)
            if not years:
                logger.info(f"No years found for {brand} {model}")
                return []

            # 7. Find matching year key with fuzzy matching
            year_key = None
            for y in years:
                if str(y.get("value")) == str(year):
                    year_key = y.get("key")
                    break
                    
            if not year_key and years:
                # Если год не найден точно, ищем ближайший
                try:
                    target_year = int(year)
                    closest_year = min(years, key=lambda x: abs(int(x.get("value", 0)) - target_year))
                    year_key = closest_year.get("key")
                    logger.info(f"Using closest year: {closest_year.get('value')} for {year}")
                except (ValueError, TypeError):
                    pass

            if not year_key:
                logger.info(f"Year key not found for {year}")
                return []

            # 8. Get modifications using year key
            url = f"{self.base_url}/brands/{brand_code}/wizzard/0/modifications?ssd={year_key}"
            logger.info(f"[REQUEST] GET {url}")
            
            try:
                response = await self._make_request(url)
                if not response:
                    logger.info("No response from modifications API")
                    return []
                    
                # Проверяем наличие модификаций в ответе
                if not response.get("specificAttributes"):
                    logger.info(f"No modifications in response for {brand} {model} {year}")
                    return []
                
                return response
                
            except Exception as e:
                logger.error(f"Error getting modifications: {e}")
                return []

        except Exception as e:
            logger.error(f"Error getting modifications: {e}")
            return []

    async def display_modifications(self, brand_code: str, ssd: str) -> Optional[Tuple[str, str]]:
        """Display available modifications and return selected car_id and ssd"""
        try:
            modifications = await self._get_modifications(brand_code, ssd)
            if not modifications:
                return None
                
            # Вместо вывода в консоль возвращаем список модификаций
            return modifications
            
        except Exception as e:
            logger.error(f"Error displaying modifications: {e}")
            return None

    def format_modification(self, mod: Dict) -> Dict:
        """Форматирование модификации для отображения"""
        attributes = mod.get('attributes', [])
        return {
            'id': mod.get('carId'),
            'grade': next((attr['value'] for attr in attributes if attr['key'] == 'grade'), 'Н/Д'),
            'doors': next((attr['value'] for attr in attributes if attr['key'] == 'doors'), 'Н/Д'),
            'transmission': next((attr['value'] for attr in attributes if attr['key'] == 'transmission'), 'Н/Д'),
            'country': next((attr['value'] for attr in attributes if attr['key'] == 'country'), 'Н/Д'),
            'dest_region': next((attr['value'] for attr in attributes if attr['key'] == 'destinationRegion'), 'Н/Д'),
            'car_ssd': next((attr['value'] for attr in attributes if attr['key'] == 'Ssd'), None)
        }

    def format_common_info(self, common_attrs: List[Dict]) -> Dict:
        """Format common attributes for display"""
        result = {}
        for attr in common_attrs:
            if attr['value']:
                result[attr['key']] = attr['value']
        return result

    async def search_modifications(self, brand: str, model: str, year: str) -> Optional[Dict]:
        """Search modifications with region selection"""
        try:
            modifications = await self.get_modifications(
                brand=brand,
                model=model,
                year=year
            )
            
            if not modifications:
                logger.info(f"No modifications found for {brand} {model} {year}")
                return None
                
            return {
                'common_info': self.format_common_info(modifications.get('commonAttributes', [])),
                'modifications': [
                    self.format_modification(mod) 
                    for mod in modifications.get('specificAttributes', [])
                ]
            }
            
        except Exception as e:
            logger.error(f"Error searching modifications: {e}")
            return None

    async def get_wizard_state(self, brand_code: str, ssd: str = None) -> Dict:
        """Get current wizard state with options"""
        url = f"{self.base_url}/brands/{brand_code}/wizzard"
        if ssd:
            url = f"{url}?ssd={ssd}"
        
        logger.info(f"[REQUEST] GET {url}")
        try:
            response = await self._make_request(url)
            return response if response else {}
        except Exception as e:
            logger.error(f"Error getting wizard state: {e}")
            return {}

    async def get_wizard_modifications(self, brand_code: str, ssd: str) -> Dict:
        """Get modifications for final wizard state"""
        url = f"{self.base_url}/brands/{brand_code}/wizzard/0/modifications?ssd={ssd}"
        logger.info(f"[REQUEST] GET {url}")
        
        try:
            response = await self._make_request(url)
            return response if response else {}
        except Exception as e:
            logger.error(f"Error getting wizard modifications: {e}")
            return {}

    async def process_wizard_step(self, brand: str, model: Optional[str] = None, 
                                year: Optional[str] = None, current_ssd: Optional[str] = None) -> Dict:
        """Process wizard selection with automatic parameter matching"""
        try:
            # Get brand code
            brand_code = await self.get_brand_code(brand)
            if not brand_code:
                logger.info(f"Brand code not found for {brand}")
                return {"error": "Brand not found"}

            # Start with initial state
            state = await self.get_wizard_state(brand_code, current_ssd)
            if not state or "items" not in state:
                return {"error": "Failed to get wizard state"}

            # First, try to set region to Europe
            for item in state["items"]:
                if item["name"].lower() == "регион" and "options" in item:
                    for option in item["options"]:
                        if "europe" in option["value"].lower():
                            state = await self.get_wizard_state(brand_code, option["key"])
                            current_ssd = option["key"]
                            break
                    break

            # If we have a model, try to match it
            if model and state and "items" in state:
                for item in state["items"]:
                    if item["name"].lower() in ["серия", "модель"] and "options" in item:
                        for option in item["options"]:
                            if model.lower() in option["value"].lower():
                                state = await self.get_wizard_state(brand_code, option["key"])
                                current_ssd = option["key"]
                                break
                        break

            # If we have a year and previous steps were successful, try to match it
            if year and state and "items" in state:
                for item in state["items"]:
                    if item["name"].lower() == "год" and "options" in item:
                        # Try exact match first
                        exact_match = None
                        closest_match = None
                        min_diff = float('inf')
                        
                        target_year = int(year)
                        for option in item["options"]:
                            try:
                                option_year = int(option["value"])
                                diff = abs(option_year - target_year)
                                
                                if diff == 0:
                                    exact_match = option
                                    break
                                elif diff < min_diff:
                                    min_diff = diff
                                    closest_match = option
                            except ValueError:
                                continue

                        # Use exact match if found, otherwise use closest match
                        matched_option = exact_match or closest_match
                        if matched_option:
                            state = await self.get_wizard_state(brand_code, matched_option["key"])
                            current_ssd = matched_option["key"]
                            break

            # Check if we've reached a final state
            if state and "items" in state:
                undetermined_items = [item for item in state["items"] 
                                   if not item.get("determined", False) and 
                                   not item.get("automatic", False)]
                
                if not undetermined_items:
                    # If all items are determined, get modifications
                    modifications = await self.get_wizard_modifications(brand_code, current_ssd)
                    return {
                        "status": "complete",
                        "ssd": current_ssd,
                        "modifications": modifications
                    }

            # Return current state for further selection
            return {
                "status": "in_progress",
                "ssd": current_ssd,
                "state": state
            }

        except Exception as e:
            logger.error(f"Error processing wizard step: {e}")
            return {"error": str(e)}

    async def _process_next_state(self, state: Dict, brand_code: str, ssd: str) -> Dict:
        """Helper method to process the next state"""
        # Check if we have any undetermined items
        has_undetermined = any(
            not item.get("determined", False) and not item.get("automatic", False)
            for item in state.get("items", [])
        )
        
        if not has_undetermined:
            modifications = await self.get_wizard_modifications(brand_code, ssd)
            return {
                "status": "complete",
                "ssd": ssd,
                "modifications": modifications
            }
            
        return {
            "status": "in_progress",
            "ssd": ssd,
            "state": state
        }

    async def step_by_step_search(self, query_or_params: Union[str, Dict] = None) -> Dict:
        """
        Пошаговый поиск с выводом доступных полей для выбора
        Args:
            query_or_params: Начальный запрос (строка) или выбранные параметры (словарь)
        Returns:
            Словарь с доступными полями и текущими выборами
        """
        try:
            # Определяем тип входных данных
            if isinstance(query_or_params, str):
                # Обработка начального строкового запроса
                initial_params = {}
                parts = query_or_params.strip().split()
                if len(parts) >= 1:
                    initial_params["Марка"] = parts[0]
                if len(parts) >= 2:
                    initial_params["Модель"] = ' '.join(parts[1:-1]) if len(parts) > 2 else parts[1]
                if len(parts) >= 3 and parts[-1].isdigit():
                    initial_params["Год"] = parts[-1]

                # Получаем код бренда
                brand = initial_params.get("Марка")
                if not brand:
                    logger.error("Необходимо указать марку автомобиля")
                    return {}

                brand_code = await self.get_brand_code(brand)
                if not brand_code:
                    logger.error(f"Код марки не найден для {brand}")
                    return {}

                # Получаем начальное состояние
                state = await self.get_wizard_state(brand_code)
                
            elif isinstance(query_or_params, dict):
                # Получаем текущее состояние с учетом выбранного значения
                brand_code = query_or_params.get('brand_code')
                ssd = query_or_params.get('ssd')
                if not brand_code:
                    logger.error("Missing brand_code in parameters")
                    return {}
                    
                state = await self.get_wizard_state(brand_code, ssd)
                
            else:
                logger.error("Неверный тип входных данных")
                return {}

            # Получаем доступные поля из текущего состояния
            fields = {}
            if state and "items" in state:
                for item in state["items"]:
                    if not item.get("determined", False):
                        fields[item["name"]] = {
                            "options": item.get("options", []),
                            "required": item.get("required", False)
                        }

            return {
                "available_fields": fields,
                "state": state,
                "brand_code": query_or_params.get('brand_code') if isinstance(query_or_params, dict) else brand_code
            }

        except Exception as e:
            logger.error(f"Ошибка в пошаговом поиске: {e}")
            return {}

    async def get_parts_list(self, brand_code: str, car_id: str, car_ssd: str) -> Dict:
        """Получение списка доступных категорий запчастей для выбранной машины"""
        url = f"{self.base_url}/brands/{brand_code}/cars/{car_id}/quickgroups?ssd={car_ssd}"
        logger.error(f"[ЗАПРОС] URL дерева запчастей: {url}")
            
        response = await self._make_request(url)
        if not response:
            logger.error("[ОТВЕТ] Пустой ответ от API списка запчастей")
            return {}
            
        if 'data' not in response:
            logger.error(f"[ОТВЕТ] Неожиданный формат ответа: {response}")
            return {}
        
        # Подсчитываем количество категорий
        total_categories = len(response.get('data', []))
        total_items = 0
        for category in response.get('data', []):
            total_items += self._count_all_items(category)
            
        logger.info(f"[ОТВЕТ] Успешно получено дерево запчастей:")
        logger.info(f"[ОТВЕТ] - Всего корневых категорий: {total_categories}")
        logger.info(f"[ОТВЕТ] - Всего элементов в дереве: {total_items}")

        return response

    async def get_group_parts(self, brand_code: str, car_id: str, quick_group_id: str, car_ssd: str) -> Dict:
        """Получение списка запчастей для выбранной группы"""
        url = f"{self.base_url}/brands/{brand_code}/cars/{car_id}/quickgroups/{quick_group_id}/units"
        logger.info(f"[ЗАПРОС] URL запчастей группы: {url}")
        
        payload = {
            "Ssd": car_ssd
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status != 200:
                        logger.error(f"[ОТВЕТ] Ошибка API: {response.status}")
                        return {}
                        
                    response_data = await response.json()
                    if not response_data:
                        logger.error("[ОТВЕТ] Пустой ответ от API запчастей")
                        return {}
                
            items = response_data.get('items', [])
            if not items:
                logger.error("[ОТВЕТ] Нет доступных запчастей в группе")
                return {}
            
            # Если только один элемент, показываем его запчасти
            if len(items) == 1:
                self._display_spare_parts(items[0])
                return response_data
            
            # Если несколько элементов, даем выбрать
            return response_data
            
        except Exception as e:
            logger.error(f"[ОШИБКА] Ошибка при получении запчастей: {e}")
            return {}

    def _display_spare_parts(self, item: Dict) -> None:
        """Отображение запчастей для выбранного элемента"""
        return {
            'name': item.get('name', ''),
            'code': item.get('code', ''),
            'imageUrl': item.get('imageUrl', '').replace('%size%', 'source'),
            'spareParts': item.get('spareParts', [])
        }

    def display_parts_tree(self, parts_data: Dict, level: int = 0) -> List[Dict]:
        """Format and return parts tree data"""
        # Вместо вывода в консоль возвращаем структурированные данные
        return parts_data.get('data', [])

    async def search(self, query: str) -> List[Dict]:
        parser = AutodocCarParser()
        parts = query.strip().split()
        if len(parts) < 2:
            logger.error(f"Invalid car search query format: {query}")
            return []
            
        brand = parts[0]
        # Join all middle parts as model name
        model = ' '.join(parts[1:-1]) if len(parts) > 2 else parts[1]
        # Last part is year if it's a number
        year = parts[-1] if parts[-1].isdigit() else None
       
        print("Начинаем поиск машины...")
        # brand = "HONDA"
        # model = "CIVIC"
        # year = "1996"
        initial_query = f"{brand} {model} {year}"
        
        search_result = await parser.step_by_step_search(initial_query)
        current_ssd = None
        known_values = {
            'Модель': model,
            'Год': year
        }
        
        while True:
           
            print("\nAvailable fields:")
            fields = list(search_result.get('available_fields', {}).items())
            if not fields:
                print("No more fields available.")
                if current_ssd:
                    # Get and select modification
                    mod_result = await parser.display_modifications(search_result.get('brand_code'), current_ssd)
                    if mod_result:
                        car_id, ssd = mod_result
                        # Get and display parts list
                        parts_data = await parser.get_parts_list(search_result.get('brand_code'), car_id, ssd)
                        return parser.display_parts_tree(parts_data)
                print("Search complete!")
                break
                
            # Check if we can auto-fill any fields
            auto_filled = False
            for field_name, field_data in fields:
                if field_name in known_values:
                    # Find matching option
                    target_value = known_values[field_name]
                    for option in field_data['options']:
                        if target_value.upper() in option['value'].upper():
                            print(f"Auto-filling {field_name} with {option['value']}")
                            current_ssd = option['key']
                            search_result = await parser.step_by_step_search({
                                'brand_code': search_result.get('brand_code'),
                                'ssd': current_ssd
                            })
                            auto_filled = True
                            break
                    if auto_filled:
                        break
        
            if auto_filled:
                continue
                
            # Display available fields for manual selection
            for idx, (field_name, field_data) in enumerate(fields, 1):
                print(f"{idx}. {field_name}")
            print(f"{len(fields) + 1}. Show current modifications")
            
            # Get user choice
            try:
                choice = int(input("\nВыберите поле (0 для выхода): "))
                if choice == 0:
                    break
                if choice == len(fields) + 1:
                    if current_ssd:
                        mod_result = await parser.display_modifications(search_result.get('brand_code'), current_ssd)
                        if mod_result:
                            car_id, ssd = mod_result
                            # Get and display parts list
                            parts_data = await parser.get_parts_list(search_result.get('brand_code'), car_id, ssd)
                            return parser.display_parts_tree(parts_data)
                    continue
                if 1 <= choice <= len(fields):
                    field_name, field_data = fields[choice - 1]
                    
                    # Display available values for the selected field
                    print(f"\nAvailable values for {field_name}:")
                    options = field_data['options']
                    for idx, option in enumerate(options, 1):
                        print(f"{idx}. {option['value']} (key: {option['key']})")
                    
                    # Get value choice
                    value_choice = int(input("\nSelect value number: "))
                    if 1 <= value_choice <= len(options):
                        selected_option = options[value_choice - 1]
                        current_ssd = selected_option['key']
                        
                        # Update search with the selected field and value
                        search_result = await parser.step_by_step_search({
                            'brand_code': search_result.get('brand_code'),
                            'ssd': current_ssd
                        })
                        
                        # Show modifications after each selection
                        mod_result = await parser.display_modifications(search_result.get('brand_code'), current_ssd)
                        if mod_result:
                            car_id, ssd = mod_result
                            # Get and display parts list
                            parts_data = await parser.get_parts_list(search_result.get('brand_code'), car_id, ssd)
                            return parser.display_parts_tree(parts_data)
                    else:
                        print("Invalid value selection")
                else:
                    print("Invalid field selection")
            except ValueError:
                print("Please enter a valid number")
            except Exception as e:
                print(f"Error occurred: {e}")
                break


    def _count_all_items(self, category: Dict) -> int:
        """Подсчет всех элементов в категории и её подкатегориях"""
        if not category:
            return 0
            
        count = 1  # Считаем текущую категорию
        children = category.get('children', [])
        for child in children:
            count += self._count_all_items(child)
        return count
