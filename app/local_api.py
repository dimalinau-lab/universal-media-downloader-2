import threading
import logging
from flask import Flask, request, jsonify
from PyQt6.QtCore import QObject, pyqtSignal


# Создаем сигналы для общения между Flask и PyQt6
class ApiSignals(QObject):
    url_received = pyqtSignal(str)


signals = ApiSignals()
app = Flask(__name__)

# Отключаем лишний спам от Flask в консоли
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


# Разрешаем браузеру отправлять запросы (обходим защиту CORS)
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


# Главный "приемник" ссылок
@app.route('/download', methods=['POST', 'OPTIONS'])
def download():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    data = request.json
    url = data.get('url')
    if url:
        signals.url_received.emit(url)  # Отправляем ссылку в интерфейс UMD!
        return jsonify({"status": "success", "message": "URL sent to UMD"}), 200
    return jsonify({"status": "error", "message": "No URL provided"}), 400


def start_server():
    # Сервер будет висеть на порту 65432
    app.run(host='127.0.0.1', port=65432, debug=False, use_reloader=False)


class LocalApiManager:
    def __init__(self):
        self.signals = signals
        # Запускаем сервер в фоновом потоке (daemon=True), чтобы он закрывался вместе с программой
        self.thread = threading.Thread(target=start_server, daemon=True)

    def start(self):
        self.thread.start()