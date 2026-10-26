#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cdp_min.py —— 极简 Chrome 控制层（只用 Python 标准库，不需要 pip install 任何东西）

它只做四件事，够我们做 GUI 实验：
    Browser.goto(url)            打开网页
    Browser.eval(js)             在页面里执行 JS，拿回结果
    Browser.screenshot(scale)    截图，返回 PNG 字节
    Browser.click(x, y)          在 (x, y) 处点一下

实现方式：启动 Chrome 的无头模式，通过 DevTools 协议（CDP）通信。
这一层你**不需要看懂**，把它当黑盒；要改的是 run_test.py。
"""

import base64
import json
import os
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.isfile(p):
            return p
    raise RuntimeError("找不到 Chrome/Edge，请手动把路径填进 CHROME_CANDIDATES")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _WS:
    """最小 WebSocket 客户端：只处理文本帧，够 CDP 用。"""

    def __init__(self, url, timeout=30):
        # ws://127.0.0.1:9222/devtools/page/xxxx
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket 握手失败：连接被关闭")
            buf += chunk
        if b"101" not in buf.split(b"\r\n")[0]:
            raise RuntimeError("WebSocket 握手失败：" + buf.split(b"\r\n")[0].decode(errors="ignore"))
        self._buf = buf.split(b"\r\n\r\n", 1)[1]

    # ---- 发送 ----
    def send(self, text):
        data = text.encode()
        header = bytearray([0x81])  # FIN + text
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    # ---- 接收 ----
    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("WebSocket 连接已断开")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv(self):
        while True:
            b1, b2 = self._recv_exact(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv_exact(8))[0]
            masked = b2 & 0x80
            mask = self._recv_exact(4) if masked else None
            payload = self._recv_exact(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:  # ping
                self._pong(payload)
                continue
            if opcode == 0x8:  # close
                raise RuntimeError("WebSocket 被关闭")
            if opcode in (0x1, 0x2):
                if not fin:
                    raise RuntimeError("收到分片帧，本客户端不支持")
                return payload.decode()

    def _pong(self, data):
        header = bytearray([0x8A])
        n = len(data)
        header.append(0x80 | n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class Browser:
    def __init__(self, width=1920, height=1080, headless=True, chrome=None, verbose=False):
        self.width, self.height = width, height
        self.verbose = verbose
        self.proc = None
        self.ws = None
        self._id = 0

        chrome = chrome or find_chrome()
        port = _free_port()
        self.user_dir = tempfile.mkdtemp(prefix="cdp-profile-")
        args = [
            chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self.user_dir}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={width},{height}",
            "about:blank",
        ]
        if headless:
            args.insert(1, "--headless=new")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        ws_url = self._wait_for_page(port)
        self.ws = _WS(ws_url)
        self.call("Page.enable")
        self.call("Runtime.enable")
        # 精确锁定视口大小，避免受窗口/DPI 影响
        self.call(
            "Emulation.setDeviceMetricsOverride",
            width=width, height=height, deviceScaleFactor=1, mobile=False,
        )

    def _wait_for_page(self, port, timeout=30):
        deadline = time.time() + timeout
        last_err = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    targets = json.loads(r.read().decode())
                for t in targets:
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
            except Exception as e:  # Chrome 还没起来
                last_err = e
            time.sleep(0.3)
        raise RuntimeError(f"等待 Chrome 调试端口超时：{last_err}")

    # ---- CDP 调用 ----
    def call(self, method, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} 失败：{msg['error']}")
                return msg.get("result", {})
            # 其它是事件，忽略

    # ---- 对外接口 ----
    def goto(self, url, wait_ui=True, timeout=20):
        self.call("Page.navigate", url=url)
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.2)
            state = self.eval("document.readyState")
            if state == "complete":
                if not wait_ui:
                    return
                boxes = self.eval("(window.__ui && window.__ui.boxes.length) || 0")
                if boxes:
                    return
        raise RuntimeError(f"页面加载超时：{url}")

    def eval(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        res = r.get("result", {})
        if r.get("exceptionDetails"):
            raise RuntimeError(f"JS 出错：{r['exceptionDetails'].get('text')}")
        return res.get("value")

    def screenshot(self, scale=1.0):
        params = {"format": "png"}
        if scale != 1.0:
            params["clip"] = {"x": 0, "y": 0, "width": self.width, "height": self.height, "scale": scale}
        r = self.call("Page.captureScreenshot", **params)
        return base64.b64decode(r["data"])

    def click(self, x, y):
        for t in ("mousePressed", "mouseReleased"):
            self.call(
                "Input.dispatchMouseEvent",
                type=t, x=float(x), y=float(y), button="left", clickCount=1,
            )

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        finally:
            if self.proc:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except Exception:
                    self.proc.kill()
            import shutil
            shutil.rmtree(self.user_dir, ignore_errors=True)
