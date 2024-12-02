import asyncio
import logging
import json
import shutil
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from typing import Dict, List

class WebClient:
    """Клиент для анализа веб-страниц с поддержкой JavaScript"""
    
    def __init__(self, output_dir: str = "web_analyzer/output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Создаем поддиректории для разных типов данных
        self.requests_dir = self.output_dir / "requests"
        self.responses_dir = self.output_dir / "responses"
        self.js_dir = self.output_dir / "javascript"
        
        for directory in [self.requests_dir, self.responses_dir, self.js_dir]:
            directory.mkdir(exist_ok=True)
        
        # Настройка логирования
        self.logger = logging.getLogger("web_analyzer")
        self.logger.setLevel(logging.INFO)
        
        # Создаем директорию для логов
        log_dir = Path("web_analyzer/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Добавляем файловый handler
        fh = logging.FileHandler(log_dir / "web_analyzer.log", encoding='utf-8')
        fh.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)

    def _clear_directories(self):
        """Очищает директории с запросами и ответами"""
        for directory in [self.requests_dir, self.responses_dir]:
            try:
                shutil.rmtree(directory)
                directory.mkdir(exist_ok=True)
            except Exception as e:
                self.logger.error(f"Error clearing directory {directory}: {str(e)}")

    async def _save_request_data(self, request, timestamp: str):
        """Сохраняет данные запроса"""
        try:
            # Проверяем content-type ответа перед сохранением запроса
            response = await request.response()
            if response:
                content_type = response.headers.get('content-type', '').lower()
                if 'application/json' not in content_type:
                    return None
            
            # Безопасное получение post_data
            try:
                post_data = request.post_data
            except Exception as e:
                self.logger.warning(f"Could not decode post_data: {str(e)}")
                post_data = None

            request_data = {
                "url": request.url,
                "method": request.method,
                "headers": dict(request.headers),
                "post_data": post_data
            }
            
            filename = f"{timestamp}_json_{hash(request.url)}.json"
            filepath = self.requests_dir / filename
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(request_data, f, ensure_ascii=False, indent=2)
                
            return filepath
        except Exception as e:
            self.logger.error(f"Error saving request data: {str(e)}")
            return None

    async def _save_response_data(self, response, timestamp: str):
        """Сохраняет данные ответа"""
        try:
            content_type = response.headers.get('content-type', '').lower()
            
            # Сохраняем только JSON ответы
            if 'application/json' not in content_type:
                return None
                
            try:
                body = await response.json()
            except Exception as e:
                self.logger.warning(f"Could not parse JSON response: {str(e)}")
                return None
                
            response_data = {
                "url": response.url,
                "status": response.status,
                "status_text": response.status_text,
                "headers": dict(response.headers),
                "body": body
            }
            
            filename = f"{timestamp}_json_{hash(response.url)}.json"
            filepath = self.responses_dir / filename
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(response_data, f, ensure_ascii=False, indent=2)
                
            return filepath
            
        except Exception as e:
            self.logger.error(f"Error saving response data: {str(e)}")
            return None

    async def _extract_javascript(self, page, timestamp: str):
        """Извлекает и сохраняет весь JavaScript со страницы"""
        try:
            # Получаем все скрипты со страницы
            scripts = await page.evaluate("""
                Array.from(document.getElementsByTagName('script')).map(script => ({
                    src: script.src,
                    content: script.innerHTML,
                    type: script.type,
                    async: script.async,
                    defer: script.defer
                }))
            """)
            
            # Сохраняем информацию о скриптах
            scripts_info = []
            
            for i, script in enumerate(scripts):
                if script['src']:
                    # Для внешних скриптов сохраняем URL и пытаемся загрузить содержимое
                    try:
                        async with page.context.request.get(script['src']) as response:
                            content = await response.text()
                    except:
                        content = None
                else:
                    # Для встроенных скриптов берем содержимое напрямую
                    content = script['content']
                
                if content:
                    script_filename = f"{timestamp}_script_{i}.js"
                    script_path = self.js_dir / script_filename
                    script_path.write_text(content, encoding='utf-8')
                    
                    scripts_info.append({
                        "filename": script_filename,
                        "src": script['src'],
                        "type": script['type'],
                        "async": script['async'],
                        "defer": script['defer']
                    })
            
            # Сохраняем индекс скриптов
            index_path = self.js_dir / f"{timestamp}_scripts_index.json"
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(scripts_info, f, ensure_ascii=False, indent=2)
                
            return scripts_info
            
        except Exception as e:
            self.logger.error(f"Error extracting JavaScript: {str(e)}")
            return None

    async def analyze_page(self, url: str, wait_for_selector: str = None, timeout: int = 30000) -> dict:
        """
        Анализирует веб-страницу с выполнением JavaScript
        
        Args:
            url: URL страницы для анализа
            wait_for_selector: CSS селектор, ожидание которого гарантирует загрузку нужного контента
            timeout: Таймаут в миллисекундах
            
        Returns:
            dict: Результаты анализа страницы
        """
        self.logger.info(f"Starting analysis of {url}")
        
        # Очищаем директории перед началом анализа
        self._clear_directories()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        browser = None
        context = None
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                context = await browser.new_context()
                page = await context.new_page()
                
                # Список для хранения информации о запросах/ответах
                requests_data = []
                pending_requests = set()
                request_events = []
                
                # Отслеживаем запросы
                async def handle_request(request):
                    event = asyncio.create_task(self._handle_request(request, timestamp, requests_data, pending_requests))
                    request_events.append(event)
                    
                # Отслеживаем ответы
                async def handle_response(response):
                    event = asyncio.create_task(self._handle_response(response, timestamp, requests_data, pending_requests))
                    request_events.append(event)
                
                # Устанавливаем обработчики событий
                page.on("request", handle_request)
                page.on("response", handle_response)
                
                # Устанавливаем User-Agent
                await page.set_extra_http_headers({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/119.0.0.0 Safari/537.36"
                })
                
                # Загружаем страницу
                response = await page.goto(url, wait_until="networkidle")
                
                if not response:
                    self.logger.error(f"Failed to load {url}")
                    return None
                    
                # Ждем определенный селектор если указан
                if wait_for_selector:
                    try:
                        await page.wait_for_selector(wait_for_selector, timeout=timeout)
                    except PlaywrightTimeoutError:
                        self.logger.warning(f"Timeout waiting for selector {wait_for_selector}")
                
                # Ждем завершения всех запросов с таймаутом в 10 секунд
                try:
                    async def wait_for_requests():
                        await page.wait_for_load_state("networkidle")
                        await asyncio.sleep(2)  # Даем небольшую паузу для завершения последних запросов
                        if request_events:
                            await asyncio.gather(*request_events, return_exceptions=True)
                    
                    await asyncio.wait_for(wait_for_requests(), timeout=10)
                except asyncio.TimeoutError:
                    self.logger.warning("Reached 10 second timeout waiting for requests to complete")
                except Exception as e:
                    self.logger.error(f"Error waiting for requests: {str(e)}")
                
                # Получаем HTML после выполнения JavaScript
                html = await page.content()
                
                # Сохраняем HTML
                html_path = self.output_dir / f"{timestamp}_{url.split('/')[-1]}.html"
                html_path.write_text(html, encoding='utf-8')
                self.logger.info(f"Saved HTML to {html_path}")
                
                # Делаем скриншот всей страницы
                screenshot_path = self.output_dir / f"{timestamp}_{url.split('/')[-1]}.png"
                await page.screenshot(
                    path=str(screenshot_path),
                    full_page=True
                )
                self.logger.info(f"Saved full page screenshot to {screenshot_path}")
                
                # Извлекаем JavaScript
                scripts_info = await self._extract_javascript(page, timestamp)
                
                # Собираем информацию о странице
                title = await page.title()
                
                result = {
                    "url": url,
                    "title": title,
                    "status": response.status,
                    "html_path": str(html_path),
                    "screenshot_path": str(screenshot_path),
                    "headers": dict(response.headers),
                    "requests_data": requests_data,
                    "scripts_info": scripts_info,
                    "pending_requests": list(pending_requests)
                }
                
                return result
                
        except Exception as e:
            self.logger.error(f"Error analyzing {url}: {str(e)}", exc_info=True)
            return None
        finally:
            # Закрываем браузер в блоке finally
            if context:
                try:
                    await context.close()
                except Exception as e:
                    self.logger.error(f"Error closing context: {str(e)}")
            if browser:
                try:
                    await browser.close()
                except Exception as e:
                    self.logger.error(f"Error closing browser: {str(e)}")

    async def _handle_request(self, request, timestamp: str, requests_data: list, pending_requests: set):
        """Обработчик запроса"""
        try:
            request_path = await self._save_request_data(request, timestamp)
            request_info = {"request": str(request_path)}
            requests_data.append(request_info)
            pending_requests.add(request.url)
        except Exception as e:
            self.logger.error(f"Error handling request: {str(e)}")

    async def _handle_response(self, response, timestamp: str, requests_data: list, pending_requests: set):
        """Обработчик ответа"""
        try:
            response_path = await self._save_response_data(response, timestamp)
            request_url = response.request.url
            pending_requests.discard(request_url)
            
            # Находим соответствующий запрос и добавляем к нему ответ
            for req_data in requests_data:
                if req_data["request"] == str(self.requests_dir / f"{timestamp}_json_{hash(request_url)}.json"):
                    req_data["response"] = str(response_path)
                    break
        except Exception as e:
            self.logger.error(f"Error handling response: {str(e)}")

    async def get_page_content(self, url: str, wait_for_selector: str = None) -> str:
        """
        Получает содержимое страницы с выполненным JavaScript
        
        Args:
            url: URL страницы
            wait_for_selector: CSS селектор для ожидания
            
        Returns:
            str: HTML содержимое страницы
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                
                await page.set_extra_http_headers({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/119.0.0.0 Safari/537.36"
                })
                
                await page.goto(url, wait_until="networkidle")
                
                if wait_for_selector:
                    await page.wait_for_selector(wait_for_selector)
                    
                html = await page.content()
                await browser.close()
                return html
                
        except Exception as e:
            self.logger.error(f"Error getting content from {url}: {str(e)}", exc_info=True)
            return None

    async def get_json(self, url: str) -> Dict:
        """Get JSON data from URL"""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                context = await browser.new_context()
                page = await context.new_page()
                
                response = await page.goto(url)
                if not response:
                    return None
                    
                try:
                    data = await response.json()
                    return data
                except:
                    return None
                    
        except Exception as e:
            self.logger.error(f"Error getting JSON from {url}: {str(e)}")
            return None
