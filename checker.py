import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import sys

# Список проверок: (ключ, путь, описание, вес в баллах, категория)
CHECKS = [
    ("llms_txt", "/llms.txt", "llms.txt (карта для AI)", 20, "GEO"),
    ("robots_ai", "/robots.txt", "robots.txt (правила для AI-ботов)", 15, "GEO"),
    ("sitemap", "/sitemap.xml", "sitemap.xml (карта сайта)", 10, "GEO"),
    ("agent_json", "/.well-known/agent.json", "agent.json (описание возможностей)", 15, "Агенты"),
    ("mcp_json", "/.well-known/mcp.json", "mcp.json (MCP-эндпоинт)", 15, "Агенты"),
    ("ai_plugin", "/.well-known/ai-plugin.json", "ai-plugin.json (старый стандарт)", 10, "Агенты"),
    ("openapi", "/openapi.json", "openapi.json (API для агентов)", 5, "Агенты"),
]

AI_BOT_KEYWORDS = [
    "gptbot", "chatgpt-user", "claudebot", "anthropic-ai", 
    "perplexitybot", "ccbot", "google-extended", 
    "bytespider", "amazonbot", "applebot", "cohere-ai"
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

def _fetch(url: str, timeout: int = 3): 
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

    home_html = _fetch(base_url)
    has_jsonld = False
    cms = "Unknown"
    
    if home_html:
        soup = BeautifulSoup(home_html, "html.parser")
        has_jsonld = soup.find("script", type="application/ld+json") is not None
        
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

    if has_jsonld:
        score += 10

    results.append({
        "key": "jsonld", "label": "JSON-LD (структурированные данные)",
        "exists": has_jsonld, "url": base_url, "weight": 10, "category": "GEO",
    })

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