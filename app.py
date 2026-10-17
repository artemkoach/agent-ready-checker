import requests
from flask import Flask, render_template, request, send_file
from checker import check_url
import io
import zipfile

app = Flask(__name__)

# Используем сервис Abacus для вечного счетчика
COUNTER_NAME = "agentreadychecker"
COUNTER_HIT_URL = f"https://abacus.jamesm.dev/hit/{COUNTER_NAME}"
COUNTER_GET_URL = f"https://abacus.jamesm.dev/get/{COUNTER_NAME}"

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    potential_gain = 0
    current_total = 0 
    
    if request.method == "POST":
        url = request.form.get("url", "").strip()
        if not url:
            error = "Введите URL сайта"
        else:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            try:
                result = check_url(url)
                
                # Увеличиваем счетчик (hit)
                try:
                    res = requests.get(COUNTER_HIT_URL, timeout=5)
                    if res.status_code == 200:
                        current_total = res.json().get("value", 0)
                except Exception as e:
                    print(f"Counter error: {e}")
                
                for item in result["results"]:
                    if item["key"] == "llms_txt" and not item["exists"]:
                        potential_gain += 20
                    if item["key"] == "robots_ai" and not item["exists"]:
                        potential_gain += 15
            except Exception as e:
                error = f"Не удалось проверить сайт: {e}"
    
    # Читаем текущее значение (если это просто заход на сайт)
    if not current_total:
        try:
            res = requests.get(COUNTER_GET_URL, timeout=5)
            if res.status_code == 200:
                current_total = res.json().get("value", 0)
        except Exception as e:
            print(f"Counter read error: {e}")
            current_total = 0
            
    return render_template("index.html", result=result, error=error, total_checks=current_total, potential_gain=potential_gain)

@app.route("/download-files")
def download_files():
    url = request.args.get("url", "")
    cms = request.args.get("cms", "Unknown")
    if not url:
        return "URL is required", 400

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        llms_content = f"# LLMs.txt for {url}\n> This file helps AI models understand your site.\n\n## Main Pages\n- [Home]({url}): Main page"
        zf.writestr("llms.txt", llms_content)
        
        robots_content = "User-agent: GPTBot\nAllow: /\n\nUser-agent: ClaudeBot\nAllow: /\n\nUser-agent: PerplexityBot\nAllow: /\n\nUser-agent: *\nAllow: /"
        zf.writestr("robots.txt", robots_content)
        
        if cms == "WordPress":
            instruction = f"Мы определили, что ваш сайт работает на WordPress.\n\n1. Зайдите в админку WordPress.\n2. Установите плагин 'File Manager'.\n3. Загрузите llms.txt и robots.txt в корневую папку сайта (туда, где лежит wp-config.php).\n4. Либо загрузите файлы через FTP (FileZilla) в ту же папку."
        elif cms == "Tilda":
            instruction = f"Мы определили, что ваш сайт работает на Tilda.\n\n1. Зайдите в настройки вашего сайта на Tilda.\n2. Перейдите в раздел 'Ещё' -> 'Файлы'.\n3. Загрузите туда llms.txt и robots.txt."
        elif cms == "1C-Bitrix":
            instruction = f"Мы определили, что ваш сайт работает на 1С-Битрикс.\n\n1. Зайдите в админку Битрикса.\n2. Перейдите в раздел 'Контент' -> 'Структура сайта'.\n3. Загрузите файлы в корневую директорию через файловый менеджер."
        elif cms == "Shopify":
            instruction = f"Мы определили, что ваш сайт работает на Shopify.\n\n1. Зайдите в админку Shopify.\n2. Перейдите в раздел 'Интернет-магазин' -> 'Темы'.\n3. Нажмите 'Действия' -> 'Редактировать код' -> 'Добавить новый актив'.\n4. Загрузите файлы."
        else:
            instruction = f"Инструкция для {url}:\n1. Распакуйте архив.\n2. Загрузите llms.txt и robots.txt в корень вашего сайта (туда, где лежит index.html) через FTP или хостинг-панель.\n3. Вернитесь на наш сайт и проверьте результат!"
        
        zf.writestr("README_ИНСТРУКЦИЯ.txt", instruction)
    
    memory_file.seek(0)
    return send_file(memory_file, download_name="ai-ready-files.zip", as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)