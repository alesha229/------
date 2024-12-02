import asyncio
from autodoc_catalog_parser import AutodocCatalogParser
import json
from pathlib import Path

async def test_different_searches():
    parser = AutodocCatalogParser()
    
    # Список тестовых параметров
    test_cases = [
        {
            "brand": "honda",
            "model": "civic",
            "region": "EUROPE",
            "year": "2017",
            "description": "Honda Civic 2017 (Europe)"
        },
        {
            "brand": "toyota",
            "model": "camry",
            "region": "JAPAN",
            "year": "2018",
            "description": "Toyota Camry 2018 (Japan)"
        },
        {
            "brand": "nissan",
            "model": "x-trail",
            "region": "EUROPE",
            "year": "2016",
            "description": "Nissan X-Trail 2016 (Europe)"
        }
    ]
    
    # Проходим по всем тестовым случаям
    for test_case in test_cases:
        print(f"\n{'='*50}")
        print(f"Testing: {test_case['description']}")
        print(f"{'='*50}")
        
        try:
            # Получаем wizard_ssd
            print(f"\nGetting wizard_ssd for {test_case['brand']}...")
            wizard_ssd = await parser.get_wizard_ssd(test_case['brand'])
            print(f"Wizard SSD: {wizard_ssd}")
            
            # Получаем код каталога
            catalog_code = await parser.get_catalog_code(test_case['brand'], test_case['year'])
            print(f"Catalog code: {catalog_code}")
            
            # Ищем модификации
            print(f"\nSearching modifications...")
            modifications = await parser.search_modifications(
                test_case['brand'],
                test_case['model'],
                test_case['region'],
                test_case['year']
            )
            
            # Выводим результаты
            print(f"\nFound {len(modifications)} modifications:")
            for i, mod in enumerate(modifications, 1):
                print(f"\n{i}. Modification:")
                print(f"   Name: {mod.get('name', 'N/A')}")
                print(f"   Code: {mod.get('code', 'N/A')}")
                print(f"   Manufacturer ID: {mod.get('manufacturerId', 'N/A')}")
                
                # Выводим дополнительные параметры, если есть
                for key, value in mod.items():
                    if key not in ['name', 'code', 'manufacturerId']:
                        print(f"   {key}: {value}")
                        
            # Сохраняем результаты в JSON
            results_dir = Path("web_analyzer/output/test_results")
            results_dir.mkdir(parents=True, exist_ok=True)
            
            result_file = results_dir / f"{test_case['brand']}_{test_case['year']}_results.json"
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "test_case": test_case,
                    "wizard_ssd": wizard_ssd,
                    "catalog_code": catalog_code,
                    "modifications": modifications
                }, f, ensure_ascii=False, indent=2)
                
            print(f"\nResults saved to: {result_file}")
            
        except Exception as e:
            print(f"\nError testing {test_case['description']}: {str(e)}")
            continue
            
        print(f"\nTest case completed: {test_case['description']}")
        print(f"{'='*50}")
        
        # Небольшая пауза между тестами
        await asyncio.sleep(2)

if __name__ == "__main__":
    # Запускаем тесты
    print("Starting Autodoc Catalog Parser Tests...")
    asyncio.run(test_different_searches())
    print("\nAll tests completed!")
