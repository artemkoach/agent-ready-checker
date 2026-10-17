import requests
from flask import Flask, render_template, request, send_file
from checker import check_url, _fetch, _extract_links
import io
import zipfile

app = Flask(__name__)

# --- НАСТРОЙКА РАБОЧЕГО СЧЕТЧИКА TALLYWIRE ---
COUNTER_NAMESPACE = "agent-ready-checker-artem"
COUNTER_KEY = "total_checks"
COUNTER_HIT_URL = f"https://tallywire.cronpulse.workers.dev/hit/{COUNTER_NAMESPACE}/{COUNTER_KEY}"
COUNTER_GET_URL = f"https://tallywire.cronpulse.workers.dev/get/{COUNTER_NAMESPACE}/{COUNTER_KEY}"

# --- ФУНКЦИЯ ПЛАВНОЙ МАТЕМАТИКИ ---
def get_conversion_lift(score: int) -> float:
    """Плавная оценка роста конверсии в зависимости от балла."""
    return round(1.0 + (score / 100.0) * 3.0, 1)

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    potential_gain = 0
    current_total = 0 
    conversion_lift = 1.0
    
    if request.method == "POST":
        url = request.form.get("url", "").strip()
        if not url:
            error = "Введите URL сайта"
        else:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            try:
                result = check_url(url)
                
                # Увеличиваем счетчик
                try:
                    res = requests.get(COUNTER_HIT_URL, timeout=5)
                    if res.status_code == 200:
                        current_total = res.json().get("value", 0)
                except Exception as e:
                    print(f"Counter hit error: {e}")
                
                # Считаем баллы за ВСЕ файлы, которые мы можем дать в архиве
                target_keys = ["llms_txt", "robots_ai", "agent_json", "mcp_json", "ai_plugin", "openapi", "jsonld"]
                for item in result["results"]:
                    if item["key"] in target_keys and not item["exists"]:
                        potential_gain += item["weight"]
                
                # Считаем прогноз конверсии
                new_score = result["score"] + potential_gain
                conversion_lift = get_conversion_lift(new_score)
                
            except Exception as e:
                error = f"Не удалось проверить сайт: {e}"
    
    # Читаем текущее значение
    if not current_total:
        try:
            res = requests.get(COUNTER_GET_URL, timeout=5)
            if res.status_code == 200:
                current_total = res.json().get("value", 0)
        except Exception as e:
            print(f"Counter read error: {e}")
            current_total = 0
            
    return render_template("index.html", result=result, error=error, 
                           total_checks=current_total, potential_gain=potential_gain,
                           conversion_lift=conversion_lift)

@app.route("/download-files")
def download_files():
    url = request.args.get("url", "")
    cms = request.args.get("cms", "Unknown")
    if not url:
        return "URL is required", 400

    # --- УМНЫЙ ПАРСИНГ ССЫЛОК ДЛЯ llms.txt ---
    # Делаем повторный запрос к сайту, чтобы собрать реальные ссылки
    home_html = _fetch(url)
    links = _extract_links(home_html, url) if home_html else [f"- [Главная]({url}): Главная страница"]

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        # 1. УМНЫЙ llms.txt (с реальными ссылками из меню)
        llms_content = f"# LLMs.txt for {url}\n> This file helps AI models understand your site structure.\n\n## Main Pages\n"
        llms_content += "\n".join(links)
        zf.writestr("llms.txt", llms_content)
        
        # 2. robots.txt
        robots_content = "User-agent: GPTBot\nAllow: /\n\nUser-agent: ClaudeBot\nAllow: /\n\nUser-agent: PerplexityBot\nAllow: /\n\nUser-agent: *\nAllow: /"
        zf.writestr("robots.txt", robots_content)

        # 3. agent.json (Пока шаблон, заменим на ИИ на следующем этапе)
        agent_json = '{\n  "name": "Your Agent Name",\n  "description": "Description of your agent",\n  "url": "' + url + '",\n  "capabilities": ["read", "search"]\n}'
        zf.writestr("agent.json", agent_json)

        # 4. mcp.json
        mcp_json = '{\n  "mcpServers": {\n    "default": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-everything"]\n    }\n  }\n}'
        zf.writestr("mcp.json", mcp_json)

        # 5. ai-plugin.json
        ai_plugin = '{\n  "schema_version": "v1",\n  "name_for_human": "Your Plugin",\n  "description_for_human": "Description",\n  "auth": { "type": "none" }\n}'
        zf.writestr("ai-plugin.json", ai_plugin)

        # 6. openapi.json
        openapi = '{\n  "openapi": "3.0.0",\n  "info": { "title": "API", "version": "1.0.0" },\n  "paths": {}\n}'
        zf.writestr("openapi.json", openapi)

        # 7. JSON-LD инструкция
        jsonld_instruction = 'Для получения баллов за JSON-LD, скопируйте этот код и вставьте его в тег <head> на вашей главной странице:\n\n<script type="application/ld+json">\n{\n  "@context": "https://schema.org",\n  "@type": "WebSite",\n  "name": "Your Site Name",\n  "url": "' + url + '"\n}\n</script>'
        zf.writestr("JSON-LD_ИНСТРУКЦИЯ.txt", jsonld_instruction)
        
        # 8. README (Инструкция под CMS)
        if cms == "WordPress":
            instruction = f"Мы определили, что ваш сайт работает на WordPress.\n\n1. Зайдите в админку WordPress.\n2. Установите плагин 'File Manager'.\n3. Загрузите все файлы (кроме JSON-LD_ИНСТРУКЦИЯ) в корневую папку сайта.\n4. Для JSON-LD: вставьте код из инструкции в header вашей темы."
        elif cms == "Tilda":
            instruction = f"Мы определили, что ваш сайт работает на Tilda.\n\n1. Зайдите в настройки сайта на Tilda.\n2. Перейдите в раздел 'Ещё' -> 'Файлы'.\n3. Загрузите туда все файлы (кроме JSON-LD_ИНСТРУКЦИЯ).\n4. Для JSON-LD: вставьте код из файла в настройках страницы."
        elif cms == "1C-Bitrix":
            instruction = f"Мы определили, что ваш сайт работает на 1С-Битрикс.\n\n1. Зайдите в админку Битрикса.\n2. Перейдите в раздел 'Контент' -> 'Структура сайта'.\n3. Загрузите файлы в корневую директорию.\n4. Для JSON-LD: вставьте код из инструкции в header."
        elif cms == "Shopify":
            instruction = f"Мы определили, что ваш сайт работает на Shopify.\n\n1. Зайдите в админку Shopify.\n2. Перейдите в раздел 'Интернет-магазин' -> 'Темы'.\n3. Нажмите 'Действия' -> 'Редактировать код' -> 'Добавить новый актив'.\n4. Загрузите файлы.\n5. Для JSON-LD: вставьте код из инструкции в theme.liquid перед </head>."
        else:
            instruction = f"Инструкция для {url}:\n1. Распакуйте архив.\n2. Загрузите все файлы (кроме JSON-LD_ИНСТРУКЦИЯ) в корень вашего сайта через FTP.\n3. Для JSON-LD: откройте файл с инструкцией и вставьте код в <head> главной страницы."
        
        zf.writestr("README_ИНСТРУКЦИЯ.txt", instruction)
    
    memory_file.seek(0)
    return send_file(memory_file, download_name="ai-ready-files.zip", as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)