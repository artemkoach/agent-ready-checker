import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import sys

# Список проверок: (ключ, путь, описание, вес в баллах, категория)
# Всего 16 пунктов, сумма весов = 100 баллов
CHECKS = [
    # --- ФАЙЛЫ (8 штук) ---
    ("llms_txt", "/llms.txt", "llms.txt (карта для AI)", 15, "GEO"),
    ("robots_ai", "/robots.txt", "robots.txt (правила для AI-ботов)", 10, "GEO"),
    ("sitemap", "/sitemap.xml", "sitemap.xml (карта сайта)", 5, "GEO"),
    ("llms_full", "/llms-full.txt", "llms-full.txt (расширенная карта)", 5, "GEO"),
    ("agent_json", "/.well-known/agent.json", "agent.json (описание возможностей)", 10, "Агенты"),
    ("mcp_json", "/.well-known/mcp.json", "mcp.json (MCP-эндпоинт)", 5, "Агенты"),
    ("ai_plugin", "/.well-known/ai-plugin.json", "ai-plugin.json (старый стандарт)", 5, "Агенты"),
    ("openapi", "/openapi.json", "openapi.json (API для агентов)", 5, "Агенты"),
]

AI_BOT_KEYWORDS = [
    "gptbot", "chatgpt-user", "claudebot", "anthropic-ai", 
    "perplexitybot", "ccbot", "google-extended", 
    "bytespider", "amazonbot", "applebot", "cohere-ai"
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

def _fetch(url: str, timeout: int = 5): 
    """Пробует скачать URL. Возвращает текст или None."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and len(resp.text.strip()) > 20:
            return resp.text
    except requests.RequestException:
        pass
    return None

def _check_robots_ai(base_url: str) -> bool:
    """Проверяет, есть ли в robots.txt упоминания AI-ботов."""
    text = _fetch(urljoin(base_url, "/robots.txt"))
    if not text:
        return False
    lower = text.lower()
    return any(bot in lower for bot in AI_BOT_KEYWORDS)

def _extract_links(html: str, base_url: str) -> list:
    """Собирает внутренние ссылки с главной страницы для умного llms.txt"""
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(base_url).netloc
    links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        
        if parsed.netloc == domain and full_url not in seen:
            seen.add(full_url)
            if len(links) < 50:
                text = a.get_text(strip=True) or "Страница"
                text = " ".join(text.split())[:50] 
                links.append(f"- [{text}]({full_url})")

    return links

def check_url(base_url: str) -> dict:
    """Проверяет сайт по чек-листу и собирает данные для llms.txt."""
    results = []
    score = 0
    extracted_links = []

    # 1. Проверка файлов (8 штук)
    for key, path, label, weight, category in CHECKS:
        full_url = urljoin(base_url, path)
        if key == "robots_ai":
            exists = _check_robots_ai(base_url)
        else:
            exists = _fetch(full_url) is not None

        if exists:
            score += weight

        results.append({
            "key": key, "label": label, "exists": exists,
            "url": full_url, "weight": weight, "category": category,
        })

    # 2. Проверка HTML-тегов (8 штук)
    home_html = _fetch(base_url)
    
    # Инициализируем переменные для HTML-проверок
    has_jsonld = False
    has_meta_desc = False
    has_og = False
    has_faq = False
    has_canonical = False
    has_h1 = False
    has_dates = False
    has_alt = False
    cms = "Unknown"
    
    if home_html:
        soup = BeautifulSoup(home_html, "html.parser")
        
        # 1. JSON-LD (5 баллов)
        has_jsonld = soup.find("script", type="application/ld+json") is not None
        if has_jsonld:
            score += 5
            
        # 2. Meta Description (5 баллов)
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and len(meta_desc.get("content", "")) > 20:
            has_meta_desc = True
            score += 5
            
        # 3. Open Graph (5 баллов)
        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        if og_title and og_desc:
            has_og = True
            score += 5
            
        # 4. FAQ Schema (10 баллов)
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            if script.string and ('"FAQPage"' in script.string or '"Question"' in script.string):
                has_faq = True
                score += 10
                break

        # 5. Canonical (5 баллов)
        if soup.find("link", rel="canonical") is not None:
            has_canonical = True
            score += 5

        # 6. H1 (5 баллов)
        if len(soup.find_all("h1")) == 1:
            has_h1 = True
            score += 5

        # 7. Даты публикации (3 балла)
        if soup.find("meta", property="article:published_time") or soup.find("time"):
            has_dates = True
            score += 3

        # 8. Alt-текст (2 балла)
        imgs = soup.find_all("img")
        if len(imgs) > 0 and all(img.get("alt") for img in imgs):
            has_alt = True
            score += 2

        # Определение CMS
        html_lower = home_html.lower()
        if "wp-content" in html_lower or "wordpress" in html_lower:
            cms = "WordPress"
        elif "tilda" in html_lower:
            cms = "Tilda"
        elif "bitrix" in html_lower:
            cms = "1C-Bitrix"
        elif "shopify" in html_lower:
            cms = "Shopify"
        elif "wix.com" in html_lower:
            cms = "Wix"
            
        extracted_links = _extract_links(home_html, base_url)

    # Добавляем результаты HTML-проверок в общий список
    results.append({"key": "jsonld", "label": "JSON-LD (структурированные данные)", "exists": has_jsonld, "url": base_url, "weight": 5, "category": "GEO"})
    results.append({"key": "faq_schema", "label": "FAQ Schema (ответы на вопросы)", "exists": has_faq, "url": base_url, "weight": 10, "category": "Контент"})
    results.append({"key": "meta_desc", "label": "Meta Description (описание для AI)", "exists": has_meta_desc, "url": base_url, "weight": 5, "category": "Контент"})
    results.append({"key": "open_graph", "label": "Open Graph (превью для соцсетей)", "exists": has_og, "url": base_url, "weight": 5, "category": "Контент"})
    results.append({"key": "canonical", "label": "Canonical (защита от дублей)", "exists": has_canonical, "url": base_url, "weight": 5, "category": "Контент"})
    results.append({"key": "h1", "label": "H1 (правильный главный заголовок)", "exists": has_h1, "url": base_url, "weight": 5, "category": "Контент"})
    results.append({"key": "dates", "label": "Даты публикации (свежесть)", "exists": has_dates, "url": base_url, "weight": 3, "category": "Контент"})
    results.append({"key": "alt_text", "label": "Alt-текст изображений", "exists": has_alt, "url": base_url, "weight": 2, "category": "Контент"})

    # ФОЛБЭК: Если ссылок не найдено, добавляем главную, чтобы sitemap не был пустым
    if not extracted_links:
        extracted_links = [f"- [Главная]({base_url}): Главная страница"]

    return {
        "url": base_url,
        "score": score,
        "cms": cms,
        "links": extracted_links,
        "results": results,
    }


# Этот блок нужен для проверки через терминал (python checker.py site.com)
if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://openai.com"
    if not target.startswith(("http://", "https://")):
        target = "https://" + target

    result = check_url(target)

    print(f"\nПроверка: {result['url']}")
    print(f"Оценка:   {result['score']} / 100")
    print(f"Движок:   {result['cms']}")
    print(f"Найдено ссылок для llms.txt: {len(result['links'])}\n")
    
    for item in result["results"]:
        mark = "✅" if item["exists"] else "❌"
        print(f"  {mark} [{item['category']}] {item['label']}  (+{item['weight']})")
    print()