import asyncio
import logging
from utils.logger import logger
from typing import List, Dict
from .exist_parser import ExistParser
from .autodoc_factory import AutodocParserFactory
from .avtoto_parser import AvtotoParser

class SearchAggregator:
    def __init__(self):
        self.exist_parser = ExistParser()
        self.autodoc_factory = AutodocParserFactory()
        self.avtoto_parser = AvtotoParser()
        
    async def search_all(self, query: str) -> Dict[str, List[Dict]]:
        """
        Выполняет параллельный поиск по всем парсерам
        Args:
            query: Строка поиска (артикул, VIN или название бренда)
        Returns:
            Dict с ключами 'exist', 'autodoc', 'avtoto' и соответствующими результатами
        """
        try:
            # Создаем парсер через фабрику
            autodoc_parser = await self.autodoc_factory.create_parser(query)
            
            tasks = [
                # asyncio.create_task(self.exist_parser.search_part(query)),
                asyncio.create_task(autodoc_parser.search(query)),
                asyncio.create_task(self.avtoto_parser.search_part(query))
            ]
            
            # Ждем выполнения всех задач
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Обрабатываем результаты
            aggregated_results = {
                'exist': [],
                'autodoc': [],
                'avtoto': []
            }
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Error in parser {i}: {result}")
                    continue
                    
                if i == 0:
                    aggregated_results['autodoc'] = result if result else []
                elif i == 1:
                    aggregated_results['avtoto'] = result if result else []
            
            return aggregated_results
            
        except Exception as e:
            logger.error(f"Error in search aggregator: {e}", exc_info=True)
            return {
                'exist': [],
                'autodoc': [],
                'avtoto': []
            }
            
    def sort_results_by_price(self, results: Dict[str, List[Dict]]) -> List[Dict]:
        """
        Сортирует все результаты по цене (по возрастанию)
        Пропускает результаты поиска по марке автомобиля
        """
        all_results = []
        for source, items in results.items():
            for item in items:
                # Пропускаем результаты поиска по марке
                if item.get('type') == 'car_model':
                    continue
                item['source'] = source
                all_results.append(item)
            
        return sorted(all_results, key=lambda x: x.get('price', float('inf')))
        
    def filter_results_by_price(self, results: Dict[str, List[Dict]], 
                              min_price: float = None, 
                              max_price: float = None) -> Dict[str, List[Dict]]:
        """
        Фильтрует результаты по диапазону цен
        Пропускает результаты поиска по марке автомобиля
        """
        filtered_results = {}
        for source, items in results.items():
            filtered_items = []
            for item in items:
                # Пропускаем результаты поиска по марке
                if item.get('type') == 'car_model':
                    filtered_items.append(item)
                    continue
                    
                price = item.get('price', 0)
                if min_price is not None and price < min_price:
                    continue
                if max_price is not None and price > max_price:
                    continue
                filtered_items.append(item)
                
            filtered_results[source] = filtered_items
            
        return filtered_results
