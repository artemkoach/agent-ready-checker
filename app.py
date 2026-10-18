import os
import requests
import json
from datetime import datetime
from urllib.parse import urljoin
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

def build_readme(url, cms, existing_keys=None):
    if existing_keys is None:
        existing_keys = set()
    date_str = datetime.now().strftime("%d.%m.%Y")

    all_keys = ["llms_txt", "llms_full", "robots_ai", "sitemap", "agent_json",
                "ai_plugin", "jsonld", "meta_desc", "open_graph", "canonical", "faq_schema"]
    already = sum(1 for k in all_keys if k in existing_keys)
    to_install = 11 - already

    cms_blocks = {
        "WordPress": """  ФАЙЛЫ (Группа 1):
    Через FTP/SFTP (FileZilla) загрузите в папку, где лежит wp-config.php
    (обычно /public_html/).
    Или установите плагин "File Manager" и загрузите через админку.

  КОД (Группа 2):
    Проще всего — плагин WPCode или Insert Headers and Footers:
    установите, вставьте код в поле для header.
    Без плагина (для опытных): functions.php дочерней темы, хук wp_head.
    Правьте именно ДОЧЕРНЮЮ тему, чтобы не потерять при обновлении.
""",
        "Tilda": """  ВАЖНО: у Tilda нет прямого FTP-доступа к корню (кроме Business).

  ФАЙЛЫ (Группа 1):
    llms.txt и llms-full.txt — поддерживаются НАТИВНО с июля 2026.
      Настройки сайта -> SEO -> Дополнительно. Там два поля.
      Скопируйте содержимое из архива и вставьте. Файлы сразу
      будут доступны из корня домена.
    robots.txt и sitemap.xml — Tilda генерирует автоматически.
      Наши файлы — только для сверки, заменять не нужно.
    agent.json, ai-plugin.json, openapi.json, mcp.json — без доступа
      к корню их можно разместить только через Cloudflare Worker
      (если домен на DNS Cloudflare). Это техническая настройка.

  КОД (Группа 2):
    Настройки сайта -> Ещё -> HTML-код для вставки внутри HEAD
    (для всех страниц) ИЛИ Настройки страницы -> Дополнительно ->
    HTML-код для вставки внутри HEAD (для одной страницы).
    ВАЖНО: функция доступна только на платных тарифах (с Personal).
    На Free вставить код нельзя.
""",
        "1C-Bitrix": """  ФАЙЛЫ (Группа 1):
    Через FTP: в корень сайта (где лежит index.php и папка /bitrix/).
    Через админку: Контент -> Структура сайта -> корень -> Загрузить.

  КОД (Группа 2):
    Через FTP: /bitrix/templates/ВАШ_ШАБЛОН/header.php — вставьте
    перед </head>.
    Или через админку: Настройки -> Настройки продукта -> Сайты ->
    ваш шаблон -> Редактировать header.php.
""",
        "Shopify": """  ФАЙЛЫ (Группа 1):
    Shopify не позволяет загружать произвольные файлы в корень.
    Обходные пути:
      1) Для llms.txt: загрузите файл в Контент -> Файлы, затем
         создайте URL-редирект: Контент -> Меню -> URL-редиректы.
         "Откуда" = /llms.txt, "Куда" = ссылка на загруженный файл.
      2) Через SEO-приложение для Shopify (некоторые настраивают
         редирект автоматически).
      3) Через Cloudflare Worker (для технически подготовленных).

  КОД (Группа 2):
    Админка -> Интернет-магазин -> Темы -> Активная тема ->
    Действия -> Редактировать код -> theme.liquid.
    Вставьте код перед </head>. Работает для всех страниц.
""",
        "Wix": """  ФАЙЛЫ (Группа 1):
    llms.txt — поддерживается нативно:
      SEO и GEO в панели управления -> прокрутите до
      "Инструменты и настройки" -> "Перейти к llms.txt".
      Там можно просмотреть и отредактировать файл.
    Остальные файлы (agent.json и др.) — только через
      Cloudflare Worker или редирект (аналогично Shopify).

  КОД (Группа 2):
    Панель Wix -> Настройки сайта -> Свой код ->
    Добавить -> "Все страницы", размещение "В <head>".
""",
        "Joomla": """  ФАЙЛЫ (Группа 1):
    Через FTP или файловый менеджер хостинга — в корень, где лежит
    index.php.
    Или используйте расширения: JC AI Ready, WT LLMs — они
    автоматически генерируют llms.txt и другие файлы в корне.

  КОД (Группа 2):
    Админка -> Система -> Шаблоны -> Ваш шаблон -> index.php.
    Вставьте код перед </head>.
    Или через плагин для вставки пользовательского кода.
""",
        "Drupal": """  ФАЙЛЫ (Группа 1):
    Загрузите в docroot — папку, где лежат index.php и robots.txt.
    Для Composer-сайтов это web/.
    Или установите модуль llms_txt — он генерирует и управляет
    файлом через админку.

  КОД (Группа 2):
    Админка -> Структура -> Шаблоны -> Ваша тема -> html.html.twig.
    Вставьте код перед </head>.
    Или через модуль для вставки кода.
""",
        "OpenCart": """  ФАЙЛЫ (Группа 1):
    Через FTP или файловый менеджер хостинга — в корень, где лежит
    index.php (обычно public_html/).

  КОД (Группа 2):
    Админка -> Дизайн -> Шаблоны -> Ваш шаблон -> header.twig.
    Вставьте код перед </head>.
    Или через FTP откройте файл шаблона вручную.
""",
        "PrestaShop": """  ФАЙЛЫ (Группа 1):
    Через FTP — в корень магазина.
    Или модуль LLMs.txt Generator — автоматически создаёт и
    размещает файл в корне.

  КОД (Группа 2):
    Админка -> Дизайн -> Тема -> Ваша тема -> header.tpl.
    Вставьте код перед </head>.
    Или через модуль для вставки кода.
""",
        "Static": """  ФАЙЛЫ (Группа 1):
    Просто положите файлы в корень проекта (там, где index.html)
    или в папку public/ (для Vercel/Netlify). Они автоматически
    станут доступны по адресу вашсайт.ру/имя-файла.

  КОД (Группа 2):
    Вставьте код прямо в <head> вашего index.html
    (или в шаблон, если используете Jekyll/Hugo).
""",
        "Builder": """  Конструкторы с ограничениями (Craftum, uKit, Nethouse):

  ФАЙЛЫ (Группа 1):
    Прямого доступа к корню нет. Загрузить произвольные файлы
    нельзя. Варианты:
      1) Cloudflare Worker (если домен на DNS Cloudflare).
      2) Переезд на хостинг с доступом к файловой системе.

  КОД (Группа 2):
    Craftum — блок "Свой код" (для страницы), но для <head>
      может требоваться платный тариф — уточняйте в поддержке.
    uKit — виджет "Свой код" с выбором места (head или body).
    Nethouse — загрузка файлов в корень ограничена; для некоторых
      типов файлов обращайтесь в поддержку.
""",
    }

    cms_steps = cms_blocks.get(cms, """  Ваш движок не определён автоматически. Универсальные шаги:

  ФАЙЛЫ (Группа 1):
    Через FTP или файловый менеджер хостинга откройте корень сайта
    (обычно /public_html/, /www/, /htdocs/) и загрузите все файлы
    Группы 1. Проверьте: https://ваш-сайт/llms.txt.

  КОД (Группа 2):
    Откройте HTML-шаблон главной страницы (index.html, header.php,
    layout.html) и вставьте все фрагменты перед </head>.
    Если не уверены, где шаблон — спросите у разработчика или
    у поддержки хостинга.
""")

    return f"""=============================================================
  ПАКЕТ ДЛЯ AI-ПОИСКОВИКОВ — ПОДРОБНАЯ ИНСТРУКЦИЯ
=============================================================

Сайт:              {url}
Движок сайта:      {cms}
Дата генерации:    {date_str}

В этом архиве — 13 файлов, которые помогут ChatGPT, Perplexity,
Claude и другим нейросетям находить и правильно понимать ваш сайт.

ВАЖНО: из 11 рабочих файлов — {already} уже есть у вас на сайте,
а {to_install} нужно установить. Файлы, которые у вас уже есть,
помечены суффиксом "_УЖЕ_ЕСТЬ_НА_САЙТЕ" в имени. Они положены
для сверки — менять их не обязательно.

-------------------------------------------------------------
  1. ЧТО ВНУТРИ АРХИВА
-------------------------------------------------------------

Все файлы делятся на две группы.

ГРУППА 1 — ФАЙЛЫ (8 штук). Загрузить в корень сайта.

  llms.txt                 — главная карта сайта для нейросетей.
  llms-full.txt            — расширенная карта: больше ссылок.
  robots.txt               — разрешение для AI-ботов.
  sitemap.xml              — карта сайта для поисковиков.
  agent.json               — описание возможностей для AI-агентов.
  ai-plugin.json           — старый плагин для AI-ассистентов.
  mcp.json                 — протокол MCP (в разработке).
  openapi.json             — описание API (в разработке).

ГРУППА 2 — КОД (5 штук). Вставить в шапку (<head>) главной
страницы сайта.

  JSON-LD_ИНСТРУКЦИЯ.txt          — структурированные данные.
  FAQ_Schema_ИНСТРУКЦИЯ.txt        — разметка "вопрос-ответ".
  Meta_Description_ИНСТРУКЦИЯ.txt  — описание страницы для поиска.
  Open_Graph_ИНСТРУКЦИЯ.txt        — превью для соцсетей.
  Canonical_ИНСТРУКЦИЯ.txt         — главный адрес страницы.

-------------------------------------------------------------
  2. КАК УСТАНОВИТЬ ГРУППУ 1 (ФАЙЛЫ)
-------------------------------------------------------------

ЦЕЛЬ: файлы должны открываться в корне сайта.
      Например: https://ваш-сайт/llms.txt

ПОШАГОВО:
  1. Откройте FTP-клиент (FileZilla, Cyberduck) или файловый
     менеджер в панели хостинга.
  2. Подключитесь к серверу по данным из хостинга.
  3. Откройте КОРНЕВУЮ папку сайта. Обычно /public_html/, /www/,
     /htdocs/. Признак: в ней лежит index.html или index.php.
  4. Загрузите файлы Группы 1 (КРОМЕ тех, у кого в имени есть
     "_УЖЕ_ЕСТЬ_НА_САЙТЕ" — они у вас уже работают).
  5. Проверьте: https://ваш-сайт/llms.txt — видите текст, значит
     работает. 404 — вернитесь к шагу 3.

-------------------------------------------------------------
  3. КАК УСТАНОВИТЬ ГРУППУ 2 (КОД)
-------------------------------------------------------------

ЦЕЛЬ: фрагменты должны оказаться внутри тега <head> главной
      страницы, в её HTML-коде.

ПОШАГОВО:
  1. Откройте файл, например JSON-LD_ИНСТРУКЦИЯ.txt.
  2. Скопируйте только сам код (без первой служебной строки
     и без предупреждения "_УЖЕ_ЕСТЬ_НА_САЙТЕ", если оно есть).
  3. Откройте HTML-шаблон главной страницы (см. раздел 4).
  4. Найдите тег <head>.
  5. Вставьте код ПЕРЕД </head>.
  6. Сохраните, опубликуйте.
  7. Проверьте: Ctrl+U (исходный код страницы) -> Ctrl+F ->
     найдите "@context" или "og:title". Нашли — работает.

-------------------------------------------------------------
  4. УСТАНОВКА ДЛЯ ВАШЕГО ДВИЖКА: {cms}
-------------------------------------------------------------

{cms_steps}
-------------------------------------------------------------
  5. ЕСЛИ ЧТО-ТО НЕ РАБОТАЕТ
-------------------------------------------------------------

Файл открывается по /llms.txt, но показывает сайт, а не текст?
  -> Файл попал в подпапку, а не в корень. Путь должен быть
    ровно /имя-файла.

Файл отдаёт 404?
  -> Файла нет в корне. Проверьте через FTP.

Вставил мета-тег, но в коде страницы его нет?
  -> Вставили не в тот шаблон, не сохранили или не опубликовали.

Как проверить, что всё сработало?
  -> Через 2-3 дня откройте https://agent-ready-checker.onrender.com/
    и проверьте сайт снова. Балл должен вырасти.

-------------------------------------------------------------
  6. ВАЖНО ПРО AI-ФАЙЛЫ (честно)
-------------------------------------------------------------

Исследования 2026 года (Ahrefs, Search Engine Land) показывают:
97% файлов llms.txt не получают запросов от AI-ботов. Google
официально не использует llms.txt как сигнал. То есть эти файлы —
это НЕ "взлом AI-поиска", а гигиена сайта и задел на будущее.
Польза: стандартизация, закрытие базовых пробелов, экономия
времени на генерацию. Не ждите мгновенного роста трафика.

-------------------------------------------------------------
  7. ВОПРОСЫ
-------------------------------------------------------------

Исходный код и обсуждение:
https://github.com/artemkoach/agent-ready-checker
"""

# ⬇️ ВОТ ЭТА СТРОКА БЫЛА УДАЛЕНА У ТЕБЯ ⬇️
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


@app.route("/demo")
def demo():
    return render_template("demo.html")


@app.route("/download-files")
def download_files():
    url = request.args.get("url", "")
    cms = request.args.get("cms", "Unknown")
    if not url:
        return "URL is required", 400

    # Определяем, какие пункты у сайта уже есть — чтобы пометить файлы в архиве
    try:
        _check = check_url(url)
        existing_keys = {item["key"] for item in _check["results"] if item["exists"]}
    except Exception:
        existing_keys = set()

    home_html = _fetch(url)
    links = _extract_links(home_html, url) if home_html else []
    if not links:
        links = [f"- [Главная]({url}): Главная страница"]

    # --- ГЕНЕРАЦИЯ SITEMAP.XML ---
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

    meta_desc_code = f'<meta name="description" content="Описание сайта {url}">'
    og_code = f'<meta property="og:title" content="Заголовок">\n<meta property="og:description" content="Описание">'
    canonical_code = f'<link rel="canonical" href="{url}">'
    faq_code = '<script type="application/ld+json">\n{\n  "@context": "https://schema.org",\n  "@type": "FAQPage",\n  "mainEntity": []\n}\n</script>'

    # --- ГЕНЕРАЦИЯ ИИ ---
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
        # Хелпер: имя файла с суффиксом, если у сайта это уже есть
        def fn(name, key):
            return name.replace(".", "_УЖЕ_ЕСТЬ_НА_САЙТЕ.", 1) if key in existing_keys else name

        # Хелпер: шапка-предупреждение — разная для txt/xml/json
        def pre(key, text, ftype="txt"):
            if key not in existing_keys:
                return text
            if ftype == "xml":
                # XML-комментарий ПОСЛЕ <?xml ?>, иначе файл битый
                warn = "\n<!-- ВНИМАНИЕ: это у вас уже есть на сайте. Наша версия — для сверки, менять не обязательно. -->\n"
                if text.startswith("<?xml"):
                    end = text.find("?>") + 2
                    return text[:end] + warn + text[end:].lstrip("\n")
                return warn + text
            if ftype == "json":
                # В JSON нельзя текст/комментарии — только переименование
                return text
            # txt — обычный текстовый заголовок
            return "=== ВНИМАНИЕ: ЭТО У ВАС УЖЕ ЕСТЬ НА САЙТЕ ===\nНаша версия — для сверки. Менять не обязательно.\n=================================================\n\n" + text

        zf.writestr(fn("llms.txt", "llms_txt"), pre("llms_txt", llms_txt_content, "txt"))
        zf.writestr(fn("llms-full.txt", "llms_full"), pre("llms_full", llms_full_content, "txt"))

        robots_content = "User-agent: GPTBot\nAllow: /\n\nUser-agent: ClaudeBot\nAllow: /\n\nUser-agent: PerplexityBot\nAllow: /\n\nUser-agent: *\nAllow: /"
        zf.writestr(fn("robots.txt", "robots_ai"), pre("robots_ai", robots_content, "txt"))

        zf.writestr(fn("sitemap.xml", "sitemap"), pre("sitemap", sitemap_xml, "xml"))
        zf.writestr(fn("agent.json", "agent_json"), pre("agent_json", agent_json_content, "json"))
        zf.writestr(fn("ai-plugin.json", "ai_plugin"), pre("ai_plugin", ai_plugin_content, "json"))

        zf.writestr("mcp.json", '{\n  "mcpServers": {\n    "default": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-everything"]\n    }\n  }\n}')
        zf.writestr("openapi.json", '{\n  "openapi": "3.0.0",\n  "info": { "title": "API", "version": "1.0.0" },\n  "paths": {}\n}')

        zf.writestr(fn("JSON-LD_ИНСТРУКЦИЯ.txt", "jsonld"), pre("jsonld", f"Скопируйте этот код и вставьте его в тег <head>:\n\n{jsonld_content}", "txt"))
        zf.writestr(fn("Meta_Description_ИНСТРУКЦИЯ.txt", "meta_desc"), pre("meta_desc", f"Вставьте этот тег в <head>:\n\n{meta_desc_code}", "txt"))
        zf.writestr(fn("Open_Graph_ИНСТРУКЦИЯ.txt", "open_graph"), pre("open_graph", f"Вставьте эти теги в <head>:\n\n{og_code}", "txt"))
        zf.writestr(fn("Canonical_ИНСТРУКЦИЯ.txt", "canonical"), pre("canonical", f"Вставьте этот тег в <head>:\n\n{canonical_code}", "txt"))
        zf.writestr(fn("FAQ_Schema_ИНСТРУКЦИЯ.txt", "faq_schema"), pre("faq_schema", f"Вставьте этот код в <head>:\n\n{faq_code}", "txt"))

        zf.writestr("README_ИНСТРУКЦИЯ.txt", build_readme(url, cms, existing_keys))

    memory_file.seek(0)
    return send_file(memory_file, download_name="ai-ready-files.zip", as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)