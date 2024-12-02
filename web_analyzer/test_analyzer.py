import asyncio
from web_client import WebClient

async def main():
    client = WebClient()
    url = "https://www.autodoc.ru/catalogs/original/list-nodes/quick-nodes?catalogCode=HONDA2017&carId=10161&quickGroupId=2&carSsd=JCpLd0dacmJ5VF9aUEJsTW56bmVhX3lNSFY5Zkxzbkp1ZG00eWprTmplN2ZubDRlUGdwYktlOU5yZTJ1djk1UFd6cnFTWmtPN2xfZVB1MFlDOGhkWGR4TWpybTUyZXhNMEFBQUFBX3lyQmFnPT0k&wizzardSsd=JCpLd0VjUmpsWFVCMW9IUnBSSEdwRlMxSUFBQUFBSDJyZDlRPT0k&t=1733133259608&name=Фильтр%20масляный"
    
    # Анализируем страницу и ждем загрузки основного контейнера
    result = await client.analyze_page(
        url=url,
        wait_for_selector=".original-catalog-page",  # Ждем загрузки основного контейнера
        timeout=60000  # Увеличиваем таймаут до 60 секунд
    )
    
    if result:
        print("Анализ страницы успешно завершен!")
        print(f"Заголовок страницы: {result['title']}")
        print(f"HTTP статус: {result['status']}")
        print(f"HTML сохранен в: {result['html_path']}")
        print(f"Скриншот сохранен в: {result['screenshot_path']}")
    else:
        print("Ошибка при анализе страницы")

if __name__ == "__main__":
    asyncio.run(main())
