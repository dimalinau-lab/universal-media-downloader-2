import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class ApiSignals(QObject):
    url_received = pyqtSignal(str)


signals = ApiSignals()


class LocalApiRequestHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        self.send_header('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self):
        if self.path == '/download':
            origin = self.headers.get('Origin', '')
            if origin and not (
                origin.startswith('chrome-extension://') or
                origin.startswith('moz-extension://') or
                origin.startswith('extension://') or
                'localhost' in origin or
                '127.0.0.1' in origin
            ):
                logger.warning(f"Заблокирован подозрительный внешний запрос к Local API от Origin: {origin}")
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b'{"status":"forbidden","message":"External cross-origin requests are blocked"}')
                return

            try:
                content_len = int(self.headers.get('Content-Length', 0))
                if content_len > 64 * 1024:  # Лимит 64 КБ на JSON с URL
                    self.send_response(413)
                    self.end_headers()
                    return

                post_body = self.rfile.read(content_len)
                data = json.loads(post_body.decode('utf-8'))
                url = data.get('url')
                if url and isinstance(url, str):
                    clean_url = url.strip()
                    if clean_url.startswith('http://') or clean_url.startswith('https://'):
                        signals.url_received.emit(clean_url)
                        response_data = json.dumps({"status": "success", "message": "URL sent to UMD"}).encode('utf-8')
                        self.send_response(200)
                        self._send_cors_headers()
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(response_data)
                        return
            except Exception as e:
                logger.error(f"Error processing /download request: {e}")

            response_data = json.dumps({"status": "error", "message": "No valid URL provided"}).encode('utf-8')
            self.send_response(400)
            self._send_cors_headers()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(response_data)
        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()

    def log_message(self, format, *args):
        # Отключаем спам в консоль
        pass


class LocalApiManager:
    def __init__(self, host='127.0.0.1', port=65432):
        self.signals = signals
        self.host = host
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        try:
            self.server = HTTPServer((self.host, self.port), LocalApiRequestHandler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            logger.info(f"Local API server started on http://{self.host}:{self.port}")
        except OSError as e:
            logger.warning(f"Could not start Local API server on port {self.port}: {e}")

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception as e:
                logger.debug(f"Error stopping Local API server: {e}")
            self.server = None