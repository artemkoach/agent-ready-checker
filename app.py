import os
import requests
import json
from flask import Flask, render_template, request, send_file
from checker import check_url, _fetch, _extract_links
from openai import OpenAI
import io
import zipfile
from bs4 import BeautifulSoup
import re

app = Flask(__name__)

# --- НАСТРОЙКА DEEPSEEK ---
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY")
client = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")

# --- НАСТРОЙКА СЧЕТЧИКА ---
COUNTER_NAMESPACE = "agent-ready-checker-artem"
COUNTER_KEY = "total_checks"
COUNTER_HIT_URL = f"https://tallywire.cronpulse.workers.dev/hit/{COUNTER_NAMESPACE}/{COUNTER_KEY}"
COUNTER_GET_URL = f"https://tallywire.cronpulse.workers.dev/get/{COUNTER_NAMESPACE}/{COUNTER_KEY}"

def get_conversion_lift(score: int) -> float:
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
                
                try:
                    res = requests.get(COUNTER_HIT_URL, timeout=5)
                    if res.status_code == 200:
                        current_total = res.json().get("value", 0)
                except Exception:
                    pass
                
                # Теперь мы даем все файлы, кроме mcp и openapi
                target_keys = ["llms_txt", "robots_ai", "sitemap", "agent_json", "ai_plugin", "jsonld"]
                for item in result["results"]:
                    if item["key"] in target_keys and not item["exists"]:
                        potential_gain += item["weight"]
                
                new_score = result["score"] + potential_gain
                conversion_lift = get_conversion_lift(new_score)
                
            except Exception as e:
                error = f"Не удалось проверить сайт: {e}"
    
    if not current_total:
        try:
            res = requests.get(COUNTER_GET_URL, timeout=5)
            if res.status_code == 200:
                current_total = res.json().get("value", 0)
        except Exception:
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

    home_html = _fetch(url)
    links = _extract_links(home_html, url) if home_html else [f"- [Главная]({url}): Главная страница"]
    
    # --- ГЕНЕРАЦИЯ SITEMAP.XML ---
    sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for link in links:
        match = re.search(r'\((.*?)\)', link)
        if match:
            page_url = match.group(1)
            sitemap_xml += f"  <url>\n    <loc>{page_url}</loc>\n  </url>\n"
    sitemap_xml += '</urlset>'

    # Базовые заглушки
    agent_json_content = '{\n  "name": "Your Agent Name",\n  "url": "' + url + '",\n  "capabilities": []\n}'
    llms_txt_content = f"# LLMs.txt for {url}\n\n## Main Pages\n" + "\n".join(links)
    ai_plugin_content = '{\n  "schema_version": "v1",\n  "name_for_human": "Your Plugin",\n  "auth": { "type": "none" }\n}'
    jsonld_content = f'<script type="application/ld+json">\n{{\n  "@context": "https://schema.org",\n  "@type": "WebSite",\n  "name": "Your Site Name",\n  "url": "{url}"\n}}\n</script>'

    if home_html and DEEPSEEK_KEY:
        try:
            soup = BeautifulSoup(home_html, "html.parser")
            site_text = soup.get_text(separator=' ', strip=True)[:2000]
            
            # Умный фолбэк для сайтов на JavaScript
            if len(site_text) < 50:
                page_title = soup.title.string if soup.title else ""
                meta_desc = soup.find("meta", attrs={"name": "description"})
                desc_text = meta_desc["content"] if meta_desc else ""
                site_text = f"Название: {page_title}. Описание: {desc_text}"
            
            prompt = f"""
            Проанализируй текст сайта: "{site_text}" (URL: {url}).
            Сгенерируй 4 документа:
            1. agent.json: name, description, url, capabilities (массив из 3-5 функций).
            2. llms.txt: краткое описание и 5 ссылок на разделы.
            3. ai_plugin: schema_version (v1), name_for_human, description_for_human, auth (type: none).
            4. jsonld_script: готовый код <script type="application/ld+json"> с полями @context, @type, name, url, description.

            Верни ответ СТРОГО в формате JSON с ключами "agent_json", "llms_txt", "ai_plugin", "jsonld_script". Без markdown-разметки.
            """
            
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that only outputs valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={ "type": "json_object" },
                timeout=15
            )
            
            ai_data = json.loads(response.choices[0].message.content)
            
            if "agent_json" in ai_data:
                agent_json_content = json.dumps(ai_data["agent_json"], ensure_ascii=False, indent=2) if isinstance(ai_data["agent_json"], dict) else ai_data["agent_json"]
            if "llms_txt" in ai_data:
                llms_txt_content = ai_data["llms_txt"]
            if "ai_plugin" in ai_data:
                ai_plugin_content = json.dumps(ai_data["ai_plugin"], ensure_ascii=False, indent=2) if isinstance(ai_data["ai_plugin"], dict) else ai_data["ai_plugin"]
            if "jsonld_script" in ai_data:
                jsonld_content = ai_data["jsonld_script"]
                
        except Exception as e:
            print(f"AI Generation failed: {e}. Using fallback.")

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        zf.writestr("llms.txt", llms_txt_content)
        
        robots_content = "User-agent: GPTBot\nAllow: /\n\nUser-agent: ClaudeBot\nAllow: /\n\nUser-agent: PerplexityBot\nAllow: /\n\nUser-agent: *\nAllow: /"
        zf.writestr("robots.txt", robots_content)

        zf.writestr("sitemap.xml", sitemap_xml)
        zf.writestr("agent.json", agent_json_content)
        zf.writestr("ai-plugin.json", ai_plugin_content)
        
        # Заглушки (пока в разработке)
        zf.writestr("mcp.json", '{\n  "mcpServers": {\n    "default": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-everything"]\n    }\n  }\n}')
        zf.writestr("openapi.json", '{\n  "openapi": "3.0.0",\n  "info": { "title": "API", "version": "1.0.0" },\n  "paths": {}\n}')
        
        zf.writestr("JSON-LD_ИНСТРУКЦИЯ.txt", f"Скопируйте этот код и вставьте его в тег <head> на вашей главной странице:\n\n{jsonld_content}")
        
        if cms == "WordPress":
            instruction = f"1. Зайдите в админку WordPress.\n2. Установите плагин 'File Manager'.\n3. Загрузите все файлы (кроме JSON-LD_ИНСТРУКЦИЯ) в корневую папку сайта.\n4. Для JSON-LD: вставьте код из инструкции в header вашей темы."
        elif cms == "Tilda":
            instruction = f"1. Зайдите в настройки сайта на Tilda.\n2. Перейдите в раздел 'Ещё' -> 'Файлы'.\n3. Загрузите туда все файлы (кроме JSON-LD_ИНСТРУКЦИЯ).\n4. Для JSON-LD: вставьте код из файла в настройках страницы."
        elif cms == "1C-Bitrix":
            instruction = f"1. Зайдите в админку Битрикса.\n2. Перейдите в раздел 'Контент' -> 'Структура сайта'.\n3. Загрузите файлы в корневую директорию.\n4. Для JSON-LD: вставьте код из инструкции в header."
        elif cms == "Shopify":
            instruction = f"1. Зайдите в админку Shopify.\n2. Перейдите в раздел 'Интернет-магазин' -> 'Темы'.\n3. Нажмите 'Действия' -> 'Редактировать код' -> 'Добавить новый актив'.\n4. Загрузите файлы.\n5. Для JSON-LD: вставьте код из инструкции в theme.liquid перед </head>."
        else:
            instruction = f"1. Распакуйте архив.\n2. Загрузите все файлы (кроме JSON-LD_ИНСТРУКЦИЯ) в корень вашего сайта через FTP.\n3. Для JSON-LD: откройте файл с инструкцией и вставьте код в <head> главной страницы."
            
        zf.writestr("README_ИНСТРУКЦИЯ.txt", f"Инструкция для {url}:\n\n{instruction}")
    
    memory_file.seek(0)
    return send_file(memory_file, download_name="ai-ready-files.zip", as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)