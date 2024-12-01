import asyncio
import logging
from typing import List, Dict
from .exist_parser import ExistParser
from .autodoc_parser import AutodocParser
from .avtoto_parser import AvtotoParser

class SearchAggregator:
    def __init__(self):
        self.exist_parser = ExistParser()
        self.autodoc_parser = AutodocParser()
        self.avtoto_parser = AvtotoParser()
        
    async def search_all(self, query: str) -> Dict[str, List[Dict]]:
        """
        Выполняет параллельный поиск по всем парсерам
        Args:
            query: Строка поиска (VIN или номер детали)
        Returns:
            Dict с ключами 'exist', 'autodoc', 'avtoto' и соответствующими результатами
        """
        try:
            # Для Autodoc используем универсальный поиск, для остальных - поиск по номеру детали
            tasks = [
                # asyncio.create_task(self.exist_parser.search_part(query)),
                asyncio.create_task(self.autodoc_parser.search(query)),  # Используем универсальный поиск
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
                    logging.error(f"Error in parser {i}: {result}")
                    continue
                    
                if i == 0:
                    aggregated_results['exist'] = result
                elif i == 1:
                    aggregated_results['autodoc'] = result
                elif i == 2:
                    aggregated_results['avtoto'] = result
            
            return aggregated_results
            
        except Exception as e:
            logging.error(f"Error in search aggregator: {e}", exc_info=True)
            return {
                'exist': [],
                'autodoc': [],
                'avtoto': []
            }
            
    def sort_results_by_price(self, results: Dict[str, List[Dict]]) -> List[Dict]:
        """
        Сортирует все результаты по цене (по возрастанию)
        """
        all_results = []
        for source, items in results.items():
            all_results.extend(items)
            
        return sorted(all_results, key=lambda x: x.get('price', float('inf')))
        
    def filter_results_by_price(self, results: Dict[str, List[Dict]], 
                              min_price: float = None, 
                              max_price: float = None) -> Dict[str, List[Dict]]:
        """
        Фильтрует результаты по диапазону цен
        """
        filtered_results = {}
        for source, items in results.items():
            filtered_items = items
            
            if min_price is not None:
                filtered_items = [item for item in filtered_items 
                                if item.get('price', 0) >= min_price]
                
            if max_price is not None:
                filtered_items = [item for item in filtered_items 
                                if item.get('price', float('inf')) <= max_price]
                
            filtered_results[source] = filtered_items
            
        return filtered_results
