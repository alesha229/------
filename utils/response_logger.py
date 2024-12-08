import json
import os
from datetime import datetime
import logging
from typing import Any, Dict

class ResponseLogger:
    def __init__(self):
        self.log_dir = 'logs/responses'
        self.ensure_log_dirs()
        
        # Словарь алиасов для входных параметров
        self.input_aliases = {
            # Основные параметры модели
            'Модель': ['Model', 'model', 'Модель', 'модель', 'ModelName', 'model_name'],
            'Марка': ['Brand', 'brand', 'Марка', 'марка', 'manufacturer', 'Make'],
            'Серия': ['Series', 'series', 'Серия', 'серия', 'ModelSeries'],
            
            # Все варианты для года
            'Модельный год': [
                'Year', 'year', 'ModelYear', 'model_year',
                'Год', 'год', 'Модельный год', 'модельный год'
            ],
            'Год выпуска': [
                'ProductionYear', 'production_year',
                'Год выпуска', 'год выпуска', 'YearOfManufacture'
            ],
            'Год производства': [
                'ManufactureYear', 'manufacture_year',
                'Год производства', 'год производства'
            ],
            
            # Остальные параметры
            'Регион': ['Region', 'region', 'Регион', 'регион', 'Market'],
            
            # Кузов и комплектация
            'Кузов': ['Body', 'body', 'Тип кузова', 'кузов', 'BodyType'],
            'Комплектация': ['Grade', 'grade', 'Trim', 'trim'],
            'Двери': ['Doors', 'doors', 'DoorCount'],
            
            # Двигатель
            'Двигатель': ['Engine', 'engine', 'EngineType'],
            'Объем': ['Displacement', 'displacement', 'EngineCapacity', 'engineCapacity'],
            'Мощность': ['Power', 'power', 'EnginePower', 'enginePower'],
            'Топливо': ['Fuel', 'fuel', 'FuelType'],
            
            # Трансмиссия
            'КПП': ['Transmission', 'transmission', 'GearBox'],
            'Привод': ['Drive', 'drive', 'DriveType', 'driveType'],
            
            # Рулевое управление
            'Руль': ['Steering', 'steering', 'SteeringType'],
            
            # Дополнительные параметры
            'Поколение': ['Generation', 'generation'],
            'Модификация': ['Modification', 'modification'],
            'Рынок': ['Market', 'market', 'destinationRegion'],
        }
        
        # Словарь соответствия ключей атрибутов и их отображаемых названий
        self.modification_attributes = {
            # Основные характеристики
            'grade': ('', ''),
            'transmission': ('КПП', ''),
            'engine': ('Двигатель', ''),
            'power': ('Мощность', 'л.с.'),
            'doors': ('', 'дв.'),
            
            # Тип и характеристики двигателя
            'engineType': ('Тип двигателя', ''),
            'engineCode': ('Код двигателя', ''),
            'engineCapacity': ('', 'л'),
            'enginePower': ('Мощность', 'л.с.'),
            'fuelType': ('Топливо', ''),
            'fuelSystem': ('Топливная система', ''),
            'cylinderCount': ('', 'цил.'),
            
            # Кузов и комплектация
            'bodyType': ('', ''),
            'bodyCode': ('Код кузова', ''),
            'steering': ('Руль', ''),
            'driveType': ('Привод', ''),
            'wheelBase': ('База', 'мм'),
            'seats': ('', 'мест'),
            
            # Идентификация модели
            'model': ('Модель', ''),
            'brand': ('Марка', ''),
            'modification': ('Модификация', ''),
            'series': ('Серия', ''),
            'generation': ('Поколение', ''),
            'chassis': ('Шасси', ''),
            'modelCode': ('Код модели', ''),
            
            # Региональные особенности
            'destinationRegion': ('Регион', ''),
            'market': ('Рынок', ''),
            'country': ('Страна', ''),
            
            # Временные характеристики
            'year': ('Год', ''),
            'productionStart': ('Начало выпуска', ''),
            'productionEnd': ('Конец выпуска', ''),
            'productionDate': ('Дата производства', ''),
            
            # Технические параметры
            'gearboxType': ('Тип КПП', ''),
            'gearCount': ('Передач', ''),
            'weight': ('Масса', 'кг'),
            'clearance': ('Клиренс', 'мм'),
            
            # Дополнительные характеристики
            'equipment': ('Оборудовние', ''),
            'options': ('Опции', ''),
            'trim': ('Отделка', ''),
            'color': ('Цвет', ''),
            
            # Технические идентификаторы (не отображаем)
            'Ssd': None,
            'carId': None,
            'id': None,
            'key': None,
            'value': None,
            'type': None,
            'code': None
        }
        
        # Приоритет отображения атрибутов
        self.attribute_priority = [
            'brand',
            'model',
            'series',
            'grade',
            'bodyType',
            'engineCapacity',
            'power',
            'transmission',
            'driveType',
            'doors',
            'steering',
            'year'
        ]
        
        # Настраиваем базовый logger
        self.logger = logging.getLogger('response_logger')
        self.logger.setLevel(logging.DEBUG)
        
        # Handler для файла
        fh = logging.FileHandler(os.path.join('logs', 'api_responses.log'), encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)

    def ensure_log_dirs(self):
        """Создание необходимых директорий для логов"""
        os.makedirs(self.log_dir, exist_ok=True)

    def save_response(self, response_type: str, data: Any, identifier: str = None):
        """Сохранение ответа API в JSON файл"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{response_type}_{identifier}_{timestamp}.json" if identifier else f"{response_type}_{timestamp}.json"
        filepath = os.path.join(self.log_dir, filename)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Saved {response_type} response to {filepath}")
        except Exception as e:
            self.logger.error(f"Error saving response: {e}")

    def format_modification_attribute(self, key: str, value: str) -> str:
        """Форматирование атрибута модификации"""
        if key not in self.modification_attributes or self.modification_attributes[key] is None:
            return None
            
        prefix, suffix = self.modification_attributes[key]
        if not value or value == 'Н/Д':
            return None
            
        formatted_value = value
        if prefix:
            formatted_value = f"{prefix}: {formatted_value}"
        if suffix:
            formatted_value = f"{formatted_value} {suffix}"
            
        return formatted_value

    def get_modification_info(self, attributes: Dict) -> list:
        """Получение отформатированной информации о модификации"""
        info_parts = []
        formatted_attrs = {}
        
        # Форматируем все доступные атрибуты
        for key, value in attributes.items():
            formatted_value = self.format_modification_attribute(key, value)
            if formatted_value:
                formatted_attrs[key] = formatted_value
        
        # Добавляем атрибуты в порядке приоритета
        for key in self.attribute_priority:
            if key in formatted_attrs:
                info_parts.append(formatted_attrs[key])
        
        # Добавляем оставшиеся атрибуты
        for key, value in formatted_attrs.items():
            if key not in self.attribute_priority:
                info_parts.append(value)
        
        return info_parts

    def log_modification_data(self, modifications: Dict):
        """Логирование данных �� модификациях"""
        self.logger.debug("=== Modification Data Analysis ===")
        
        if not modifications:
            self.logger.debug("Empty modifications data")
            return
            
        # Анализ общих атрибутов
        common_attrs = modifications.get('commonAttributes', [])
        self.logger.debug(f"Common attributes: {json.dumps(common_attrs, ensure_ascii=False, indent=2)}")
        
        # Анализ специфических атрибутов
        specific_attrs = modifications.get('specificAttributes', [])
        if specific_attrs:
            self.logger.debug(f"Total modifications: {len(specific_attrs)}")
            
            # Анализируем первую модификацию подробно
            first_mod = specific_attrs[0]
            self.logger.debug(f"First modification structure: {json.dumps(first_mod, ensure_ascii=False, indent=2)}")
            
            # Анализируем атрибуты первой модификации
            if 'attributes' in first_mod:
                attributes = {attr['key']: attr['value'] for attr in first_mod['attributes']}
                formatted_info = self.get_modification_info(attributes)
                self.logger.debug(f"Formatted modification info: {' | '.join(formatted_info)}")
            
            # Соираем все уникальные ключи атрибутов
            all_keys = set()
            for mod in specific_attrs:
                for attr in mod.get('attributes', []):
                    all_keys.add(attr['key'])
            self.logger.debug(f"All available attribute keys: {sorted(list(all_keys))}")
        
        # Сохраняем полный ответ
        self.save_response('modifications', modifications)

    def log_parts_data(self, parts_data: Dict):
        """Логирование данных о запчастях"""
        self.logger.debug("=== Parts Data Analysis ===")
        
        if not parts_data:
            self.logger.debug("Empty parts data")
            return
            
        # Анализ структуры данных
        if 'data' in parts_data:
            root_categories = parts_data['data']
            self.logger.debug(f"Root categories count: {len(root_categories)}")
            
            # Анализ первой категории
            if root_categories:
                first_category = root_categories[0]
                self.logger.debug(f"First category structure: {json.dumps(first_category, ensure_ascii=False, indent=2)}")
                
                # Анализ доступных полей
                fields = set()
                def extract_fields(item):
                    for key in item.keys():
                        fields.add(key)
                    if 'children' in item:
                        for child in item['children']:
                            extract_fields(child)
                
                extract_fields(first_category)
                self.logger.debug(f"Available fields in categories: {sorted(list(fields))}")
        
        # Сохраняем полный ответ
        self.save_response('parts_tree', parts_data)

    def log_spare_parts_data(self, parts_data: Dict):
        """Логирование данных о конкретных запчастях"""
        self.logger.debug("=== Spare Parts Data Analysis ===")
        
        if not parts_data:
            self.logger.debug("Empty spare parts data")
            return
            
        items = parts_data.get('items', [])
        self.logger.debug(f"Total spare parts: {len(items)}")
        
        if items:
            # Анализ первой запчасти
            first_item = items[0]
            self.logger.debug(f"First spare part structure: {json.dumps(first_item, ensure_ascii=False, indent=2)}")
            
            # Ан��лиз доступных полей
            fields = set()
            for item in items:
                fields.update(item.keys())
            self.logger.debug(f"Available fields in spare parts: {sorted(list(fields))}")
        
        # Сохраняем полный ответ
        self.save_response('spare_parts', parts_data)

    def get_parameter_key(self, param_name: str) -> str:
        """Получение стандартизированного ключа параметра по его названию"""
        param_name_lower = param_name.lower()
        for standard_key, aliases in self.input_aliases.items():
            if any(alias.lower() == param_name_lower for alias in aliases):
                self.logger.debug(f"[ПАРАМЕТРЫ] Найден алиас {param_name} -> {standard_key}")
                return standard_key
        return param_name

    def standardize_parameters(self, params: Dict) -> Dict:
        """Стандартизация параметров поиска"""
        standardized = {}
        for key, value in params.items():
            self.logger.debug(f"[ПАРАМЕТРЫ] Обработка параметра {key}={value}")
            
            # Проверяем все возможные варианты года
            if any(key.lower() in [alias.lower() for alias in aliases] 
                  for standard_key, aliases in self.input_aliases.items() 
                  if 'год' in standard_key.lower()):
                # Если это любой вариант года, добавляем его во все возможные поля года
                self.logger.debug(f"[ПАРАМЕТРЫ] Найден год: {value}")
                standardized['Модельный год'] = value
                standardized['Год выпуска'] = value
                standardized['Год производства'] = value
            else:
                # Для остальных параметров ищем соответствие в алиасах
                standard_key = self.get_parameter_key(key)
                standardized[standard_key] = value
            
            self.logger.debug(f"[ПАРАМЕТРЫ] Стандартизация {key} -> {standardized}")
        
        return standardized

# Создаем глобальный экземпляр логгера
response_logger = ResponseLogger() 