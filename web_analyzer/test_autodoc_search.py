import asyncio
from web_client import WebClient
import json
from pathlib import Path

async def analyze_autodoc_search():
    client = WebClient()
    
    # URL для анализа формы поиска
    url = "https://www.autodoc.ru/catalogs/original/honda/all"
    
    # Анализируем страницу с формой поиска
    print("Analyzing search form...")
    result = await client.analyze_page(url, wait_for_selector="form")
    
    if not result:
        print("Failed to analyze search form")
        return
        
    # Анализируем POST запрос для поиска
    search_params = {
        "brand": "HONDA",
        "region": "EUROPE", 
        "model": "CIVIC",
        "year": "2017"
    }
    
    search_url = "https://www.autodoc.ru/catalogs/original/search"
    print(f"\nAnalyzing search with parameters: {search_params}")
    
    result = await client.analyze_page(
        search_url,
        wait_for_selector=".catalog-modifications"
    )
    
    if not result:
        print("Failed to analyze search results")
        return
        
    # Выводим сохраненные запросы и ответы
    requests_dir = Path("web_analyzer/output/requests")
    responses_dir = Path("web_analyzer/output/responses")
    
    print("\nSaved Requests:")
    for req_file in requests_dir.glob("*.json"):
        with open(req_file) as f:
            req_data = json.load(f)
            print(f"\nRequest: {req_file.name}")
            print(f"URL: {req_data['url']}")
            print(f"Method: {req_data['method']}")
            if req_data['post_data']:
                print(f"Post data: {req_data['post_data']}")
                
    print("\nSaved Responses:")
    for resp_file in responses_dir.glob("*.json"):
        with open(resp_file) as f:
            resp_data = json.load(f)
            print(f"\nResponse: {resp_file.name}")
            print(f"URL: {resp_data['url']}")
            print(f"Status: {resp_data['status']}")
            if 'body' in resp_data:
                print("Response has body data")

if __name__ == "__main__":
    asyncio.run(analyze_autodoc_search())
