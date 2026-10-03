"""A small local server for the film page: serves this folder and saves what the page hands back into out/."""
import http.server
import os
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        name = os.path.normpath(urllib.parse.parse_qs(url.query).get("name", [""])[0])
        if url.path != "/save" or not name or name.startswith(("..", "/")):
            self.send_error(400)
            return
        path = os.path.join(ROOT, "out", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        left = int(self.headers.get("Content-Length", 0))
        with open(path, "wb") as f:
            while left > 0:
                piece = self.rfile.read(min(left, 1 << 20))
                if not piece:
                    break
                f.write(piece)
                left -= len(piece)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"saved")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
