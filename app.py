from flask import Flask, render_template, request
from checker import check_url

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    
    if request.method == "POST":
        url = request.form.get("url", "").strip()
        if not url:
            error = "Введите URL сайта"
        else:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            try:
                result = check_url(url)
            except Exception as e:
                error = f"Не удалось проверить сайт: {e}"
                
    return render_template("index.html", result=result, error=error)

if __name__ == "__main__":
    app.run(debug=True)