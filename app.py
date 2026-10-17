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
                
                # ДОБАВЛЕНО: Новые ключи, так как мы теперь даем код для них
                target_keys = [
                    "llms_txt", "robots_ai", "sitemap", "agent_json", 
                    "ai_plugin", "jsonld", "llms_full", 
                    "meta_desc", "open_graph", "canonical", "faq_schema"
                ]
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
    
    # --- ГЕНЕРАЦИЯ SITEMAP.XML (С ОЧИСТКОЙ ОТ UTM) ---
    sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for link in links:
        match = re.search(r'\((.*?)\)', link)
        if match:
            page_url = match.group(1)
            clean_url = page_url.split('?')[0]
            sitemap_xml += f"  <url>\n    <loc>{clean_url}</loc>\n  </url>\n"
    sitemap_xml += '</urlset>'

    # Базовые заглушки (на случай полного отказа ИИ)
    agent_json_content = '{\n  "name": "Your Agent Name",\n  "url": "' + url + '",\n  "capabilities": []\n}'
    llms_txt_content = f"# LLMs.txt for {url}\n\n## Main Pages\n" + "\n".join(links)
    llms_full_content = f"# LLMs Full.txt for {url}\n\n## Extended Data\n" + "\n".join(links)
    ai_plugin_content = '{\n  "schema_version": "v1",\n  "name_for_human": "Your Plugin",\n  "auth": { "type": "none" }\n}'
    jsonld_content = f'<script type="application/ld+json">\n{{\n  "@context": "https://schema.org",\n  "@type": "WebSite",\n  "name": "Your Site Name",\n  "url": "{url}"\n}}\n</script>'
    
    # ДОБАВЛЕНО: Заглушки для новых кодов
    meta_desc_code = f'<meta name="description" content="Описание сайта {url}">'
    og_code = f'<meta property="og:title" content="Заголовок">\n<meta property="og:description" content="Описание">'
    canonical_code = f'<link rel="canonical" href="{url}">'
    faq_code = '<script type="application/ld+json">\n{\n  "@context": "https://schema.org",\n  "@type": "FAQPage",\n  "mainEntity": []\n}\n</script>'

    # --- ГЛАВНЫЙ ФИКС: ИИ ЗАПУСКАЕТСЯ ВСЕГДА ---
    if DEEPSEEK_KEY:
        try:
            site_text = ""
            
            if home_html:
                soup = BeautifulSoup(home_html, "html.parser")
                site_text = soup.get_text(separator=' ', strip=True)[:2000]
                
                if len(site_text) < 50:
                    page_title = soup.title.string if soup.title else ""
                    meta_desc = soup.find("meta", attrs={"name": "description"})
                    desc_text = meta_desc["content"] if meta_desc else ""
                    site_text = f"Название: {page_title}. Описание: {desc_text}"
            
            if len(site_text.strip()) < 50:
                domain_name = url.split('//')[-1].split('/')[0].replace('www.', '')
                site_text = f"Сайт {domain_name}. Сгенерируй логичное описание и функции на основе названия домена."

            # ИЗМЕНЕНО: Просим 8 документов, включая новые коды
            prompt = f"""
            Проанализируй текст сайта: "{site_text}" (URL: {url}).
            Сгенерируй 8 документов:
            1. agent_json: name, description, url, capabilities (массив из 3-5 функций).
            2. llms_txt: краткое описание и 5 ссылок на разделы.
            3. llms_full: расширенное описание и 10-15 ссылок на разделы.
            4. ai_plugin: schema_version (v1), name_for_human, description_for_human, auth (type: none).
            5. jsonld_script: готовый код <script type="application/ld+json"> с полями @context, @type, name, url, description.
            6. meta_description: готовый тег <meta name="description" content="..."> (до 160 символов).
            7. open_graph: готовые теги <meta property="og:title" content="..."> и <meta property="og:description" content="...">.
            8. faq_schema: готовый код <script type="application/ld+json"> с типом FAQPage, содержащий 3 вопроса и ответа на основе бизнеса.

            Верни ответ СТРОГО в формате JSON с ключами "agent_json", "llms_txt", "llms_full", "ai_plugin", "jsonld_script", "meta_description", "open_graph", "faq_schema". Без markdown-разметки.
            """
            
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that only outputs valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={ "type": "json_object" },
                timeout=25
            )
            
            ai_data = json.loads(response.choices[0].message.content)
            
            if "agent_json" in ai_data:
                agent_json_content = json.dumps(ai_data["agent_json"], ensure_ascii=False, indent=2) if isinstance(ai_data["agent_json"], dict) else ai_data["agent_json"]
            if "llms_txt" in ai_data:
                llms_txt_content = ai_data["llms_txt"]
            if "llms_full" in ai_data:
                llms_full_content = ai_data["llms_full"]
            if "ai_plugin" in ai_data:
                ai_plugin_content = json.dumps(ai_data["ai_plugin"], ensure_ascii=False, indent=2) if isinstance(ai_data["ai_plugin"], dict) else ai_data["ai_plugin"]
            if "jsonld_script" in ai_data:
                jsonld_content = ai_data["jsonld_script"]
                
            # ДОБАВЛЕНО: Извлекаем новые коды
            if "meta_description" in ai_data:
                meta_desc_code = ai_data["meta_description"]
            if "open_graph" in ai_data:
                og_code = ai_data["open_graph"]
            if "faq_schema" in ai_data:
                faq_code = ai_data["faq_schema"]
                
        except Exception as e:
            print(f"AI Generation failed: {e}. Using fallback.")

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        zf.writestr("llms.txt", llms_txt_content)
        zf.writestr("llms-full.txt", llms_full_content)
        
        robots_content = "User-agent: GPTBot\nAllow: /\n\nUser-agent: ClaudeBot\nAllow: /\n\nUser-agent: PerplexityBot\nAllow: /\n\nUser-agent: *\nAllow: /"
        zf.writestr("robots.txt", robots_content)

        zf.writestr("sitemap.xml", sitemap_xml)
        zf.writestr("agent.json", agent_json_content)
        zf.writestr("ai-plugin.json", ai_plugin_content)
        
        zf.writestr("mcp.json", '{\n  "mcpServers": {\n    "default": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-everything"]\n    }\n  }\n}')
        zf.writestr("openapi.json", '{\n  "openapi": "3.0.0",\n  "info": { "title": "API", "version": "1.0.0" },\n  "paths": {}\n}')
        
        # ДОБАВЛЕНО: Записываем новые файлы с инструкциями
        zf.writestr("JSON-LD_ИНСТРУКЦИЯ.txt", f"Скопируйте этот код и вставьте его в тег <head>:\n\n{jsonld_content}")
        zf.writestr("Meta_Description_ИНСТРУКЦИЯ.txt", f"Вставьте этот тег в <head>:\n\n{meta_desc_code}")
        zf.writestr("Open_Graph_ИНСТРУКЦИЯ.txt", f"Вставьте эти теги в <head>:\n\n{og_code}")
        zf.writestr("Canonical_ИНСТРУКЦИЯ.txt", f"Вставьте этот тег в <head>:\n\n{canonical_code}")
        zf.writestr("FAQ_Schema_ИНСТРУКЦИЯ.txt", f"Вставьте этот код в <head>:\n\n{faq_code}")
        
        if cms == "WordPress":
            instruction = f"1. Зайдите в админку WordPress.\n2. Установите плагин 'File Manager'.\n3. Загрузите файлы (кроме тех, что с _ИНСТРУКЦИЯ) в корневую папку.\n4. Все файлы с _ИНСТРУКЦИЯ содержат код, который нужно вставить в <head> вашей темы."
        elif cms == "Tilda":
            instruction = f"1. Зайдите в настройки сайта на Tilda.\n2. Перейдите в раздел 'Ещё' -> 'Файлы'.\n3. Загрузите файлы (кроме тех, что с _ИНСТРУКЦИЯ).\n4. Код из файлов _ИНСТРУКЦИЯ вставьте в настройках страницы (раздел HTML-код для head)."
        elif cms == "1C-Bitrix":
            instruction = f"1. Зайдите в админку Битрикса.\n2. Перейдите в раздел 'Контент' -> 'Структура сайта'.\n3. Загрузите файлы в корневую директорию.\n4. Код из файлов _ИНСТРУКЦИЯ вставьте в header."
        elif cms == "Shopify":
            instruction = f"1. Зайдите в админку Shopify.\n2. Перейдите в раздел 'Интернет-магазин' -> 'Темы'.\n3. Нажмите 'Действия' -> 'Редактировать код' -> 'Добавить новый актив'.\n4. Загрузите файлы (кроме _ИНСТРУКЦИЯ).\n5. Код из файлов _ИНСТРУКЦИЯ вставьте в theme.liquid перед </head>."
        else:
            instruction = f"1. Распакуйте архив.\n2. Загрузите файлы (кроме _ИНСТРУКЦИЯ) в корень вашего сайта через FTP.\n3. Код из файлов _ИНСТРУКЦИЯ вставьте в <head> главной страницы."
            
        zf.writestr("README_ИНСТРУКЦИЯ.txt", f"Инструкция для {url}:\n\n{instruction}")
    
    memory_file.seek(0)
    return send_file(memory_file, download_name="ai-ready-files.zip", as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)