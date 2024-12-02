import asyncio
from web_client import WebClient
import json
from pathlib import Path
import re
from typing import Dict, List, Optional

class AutodocCatalogParser:
    def __init__(self):
        self.web_client = WebClient()
        self.base_url = "https://catalogoriginal.autodoc.ru/api/catalogs/original"
        
    async def get_brand_code(self, brand: str) -> Optional[str]:
        """Get manufacturer code by brand name"""
        url = f"{self.base_url}/brands"
        response = await self.web_client.get_json(url)
        if not response:
            print("No response from API")
            return None
            
        try:
            # Debug print
            print("\nAPI Response type:", type(response))
            print("API Response content:", json.dumps(response, indent=2))
            
            # Find brand code
            brand_lower = brand.lower()
            if isinstance(response, list):
                items = response
            elif isinstance(response, dict):
                items = response.get("items", [])
            else:
                print(f"Unexpected response type: {type(response)}")
                return None
                
            print("\nSearching for brand:", brand_lower)
            for item in items:
                if not isinstance(item, dict):
                    continue
                    
                current_brand = item.get("brand", "")
                print(f"Checking brand: {current_brand}")
                
                if current_brand.lower() == brand_lower:
                    code = item.get("code")
                    print(f"Found brand code: {code}")
                    return code
            
            print(f"Brand {brand} not found in response")
            return None
            
        except Exception as e:
            print(f"Error processing API response: {e}")
            return None

    async def get_regions(self, brand_code: str, year: str) -> List[Dict]:
        """Get available regions for brand and year"""
        url = f"{self.base_url}/brands/{brand_code}/wizzard"
        print(f"Getting regions from URL: {url}")  # Debug print
        
        response = await self.web_client.get_json(url)
        if not response or "items" not in response:
            return []
            
        # Find region options
        for item in response["items"]:
            if item["name"] == "Регион":
                return item["options"]
        return []
        
    async def get_models(self, brand_code: str, year: str, region_key: str) -> List[Dict]:
        """Get models by brand, year and region"""
        url = f"{self.base_url}/brands/{brand_code}/wizzard?ssd={region_key}"
        print(f"Getting models from URL: {url}")  # Debug print
        
        response = await self.web_client.get_json(url)
        if not response or "items" not in response:
            return []
            
        # Find model options
        for item in response["items"]:
            if item["name"] == "Модель":
                return item["options"]
        return []
        
    async def get_year_options(self, brand_code: str, model_key: str) -> List[Dict]:
        """Get available years after selecting model"""
        url = f"{self.base_url}/brands/{brand_code}/wizzard?ssd={model_key}"
        print(f"Getting years from URL: {url}")  # Debug print
        
        response = await self.web_client.get_json(url)
        if not response or "items" not in response:
            return []
            
        # Find year options
        for item in response["items"]:
            if item["name"] == "Год":
                return item["options"]
        return []

    
    async def get_modifications(self, brand: str, model: str, year: str, region: str = None) -> List[Dict]:
        """Get car modifications by brand, model, year and region"""
        try:
            # 1. Get brand code once
            brand_code = await self.get_brand_code(brand)
            if not brand_code:
                print(f"Brand code not found for {brand}")
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
            print(f"Getting modifications from URL: {url}")  # Debug print
            
            response = await self.web_client.get_json(url)
            if not response:
                return []
            
            return response

        except Exception as e:
            print(f"Error getting modifications: {e}")
            return []

async def test_parser():
    parser = AutodocCatalogParser()
    
    # Test getting modifications
    modifications = await parser.get_modifications(
        brand="honda",
        model="civic",
        year="1996",
        region="General"
    )
    
    if modifications:
        print("\nОбщие характеристики:")
        common_attrs = modifications.get("commonAttributes", [])
        for attr in common_attrs:
            print(f"{attr.get('name')}: {attr.get('value')}")
            
        print(f"\nНайдено {len(modifications.get('specificAttributes', []))} модификаций:")
        for mod in modifications.get("specificAttributes", []):
            print("\n" + "="*50)
            print(f"Модификация ID: {mod.get('carId')}")
            
            attributes = mod.get('attributes', [])
            # Группируем основные характеристики
            doors = next((attr['value'] for attr in attributes if attr['key'] == 'doors'), 'Н/Д')
            transmission = next((attr['value'] for attr in attributes if attr['key'] == 'transmission'), 'Н/Д')
            grade = next((attr['value'] for attr in attributes if attr['key'] == 'grade'), 'Н/Д')
            region = next((attr['value'] for attr in attributes if attr['key'] == 'country'), 'Н/Д')
            dest_region = next((attr['value'] for attr in attributes if attr['key'] == 'destinationRegion'), 'Н/Д')
            
            print(f"Комплектация: {grade}")
            print(f"Количество дверей: {doors}")
            print(f"Коробка передач: {transmission}")
            print(f"Регион: {region}")
            print(f"Регион поставки: {dest_region}")
            print("="*50)
    else:
        print("Модификации не найдены")

if __name__ == "__main__":
    asyncio.run(test_parser())
