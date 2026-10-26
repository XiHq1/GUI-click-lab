"""本地假 API：只有带正确 Bearer 才返回 200，用来验证客户端的认证头。"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

KEY = "test123"


class H(BaseHTTPRequestHandler):
    def _auth_ok(self):
        return self.headers.get("Authorization") == f"Bearer {KEY}"

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.path.endswith("/models"):
            return self._json(404, {"message": "not found"})
        if not self._auth_ok():
            return self._json(401, {"message": "Invalid token"})
        return self._json(200, {"data": [{"id": "mock-vl-8b"}]})

    def do_POST(self):
        if not self._auth_ok():
            return self._json(401, {"message": "Invalid token"})
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n).decode() or "{}")
        return self._json(200, {
            "choices": [{"message": {"content": "<point>137,158</point>"}}],
            "usage": {"prompt_tokens": 1234, "completion_tokens": 12},
            "echo_model": body.get("model"),
        })

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("mock api on 8799, key=test123", flush=True)
    HTTPServer(("127.0.0.1", 8799), H).serve_forever()
