import asyncio
import json
from pathlib import Path
import re
from typing import Dict, List, Optional
import logging
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

class AutodocCarParser(BaseParser):
    """Парсер для поиска модификаций автомобилей и запчастей"""
    
    def __init__(self):
        super().__init__()
        self.base_url = "https://catalogoriginal.autodoc.ru/api/catalogs/original"
        self.available_regions = ["General", "America", "Europe", "Japan"]

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

    async def get_regions(self, brand_code: str, year: str) -> List[Dict]:
        """Get available regions for brand and year"""
        url = f"{self.base_url}/brands/{brand_code}/wizzard"
        logger.info(f"[REQUEST] GET {url}")
        
        try:
            response = await self._make_request(url)
            if not response or "items" not in response:
                return []
                
            for item in response["items"]:
                if item["name"] == "Регион":
                    return item["options"]
            return []
            
        except Exception as e:
            logger.error(f"Error getting regions: {e}")
            return []

    async def get_models(self, brand_code: str, year: str, region_key: str) -> List[Dict]:
        """Get models by brand, year and region"""
        url = f"{self.base_url}/brands/{brand_code}/wizzard?ssd={region_key}"
        logger.info(f"[REQUEST] GET {url}")
        
        try:
            response = await self._make_request(url)
            if not response or "items" not in response:
                return []
                
            for item in response["items"]:
                if item["name"] == "Модель":
                    return item["options"]
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

            # 2. Get regions
            regions = await self.get_regions(brand_code, year)
            if not regions:
                return []

            # 3. Find region key
            region_key = None
            for r in regions:
                if r["value"].lower() == region.lower():
                    region_key = r["key"]
                    break

            if not region_key:
                return []

            # 4. Get models with region key
            models = await self.get_models(brand_code, year, region_key)
            if not models:
                return []

            # 5. Filter and find matching model
            model_key = None
            for m in models:
                if model.lower() in m["value"].lower():
                    model_key = m["key"]
                    break

            if not model_key:
                return []

            # 6. Get years with model key
            years = await self.get_year_options(brand_code, model_key)
            if not years:
                return []

            # 7. Find matching year key
            year_key = None
            for y in years:
                if y["value"] == year:
                    year_key = y["key"]
                    break

            if not year_key:
                return []

            # 8. Get modifications using year key
            url = f"{self.base_url}/brands/{brand_code}/wizzard/0/modifications?ssd={year_key}"
            logger.info(f"[REQUEST] GET {url}")
            
            try:
                response = await self._make_request(url)
                if not response:
                    return []
                
                return response
                
            except Exception as e:
                logger.error(f"Error getting modifications: {e}")
                return []

        except Exception as e:
            logger.error(f"Error getting modifications: {e}")
            return []

    def format_modification(self, mod: Dict) -> Dict:
        """Format a single modification for display"""
        attributes = mod.get('attributes', [])
        return {
            'id': mod.get('carId'),
            'grade': next((attr['value'] for attr in attributes if attr['key'] == 'grade'), 'Н/Д'),
            'doors': next((attr['value'] for attr in attributes if attr['key'] == 'doors'), 'Н/Д'),
            'transmission': next((attr['value'] for attr in attributes if attr['key'] == 'transmission'), 'Н/Д'),
            'country': next((attr['value'] for attr in attributes if attr['key'] == 'country'), 'Н/Д'),
            'dest_region': next((attr['value'] for attr in attributes if attr['key'] == 'destinationRegion'), 'Н/Д'),
            'ssd': next((attr['value'] for attr in attributes if attr['key'] == 'ssd'), 'Н/Д')
        }

    def format_common_info(self, common_attrs: List[Dict]) -> Dict:
        """Format common attributes for display"""
        result = {}
        for attr in common_attrs:
            if attr['value']:
                result[attr['key']] = attr['value']
        return result

    async def search_modifications(self, brand: str, model: str, year: str, region: str) -> Optional[Dict]:
        """Search modifications with region selection"""
        try:
            modifications = await self.get_modifications(
                brand=brand,
                model=model,
                year=year,
                region=region
            )
            
            if not modifications:
                logger.info(f"No modifications found for {brand} {model} {year} in {region}")
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

async def test_parser():
    parser = AutodocCarParser()
    
    # Test getting modifications
    modifications = await parser.get_modifications(
        brand="honda",
        model="civic",
        year="1996",
        region="General"
    )
    
    if modifications:
        print(modifications)
    else:
        print("Модификации не найдены")

    # Test search by name
    print("\nTesting search by name...")
    results = await parser.search_modifications("honda", "civic", "1996", "General")
    
    if results:
        print("\nSearch Results:")
        print(results)
    else:
        print("No parts found")

if __name__ == "__main__":
    asyncio.run(test_parser())
