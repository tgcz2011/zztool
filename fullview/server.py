#!/usr/bin/env python3
"""
简易本地HTTP服务器
解决浏览器安全限制问题
"""

import http.server
import socketserver
import os
import threading

# 配置参数
PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class MyHttpRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        # 允许跨域访问
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()


def start_server():
    with socketserver.TCPServer(("", PORT), MyHttpRequestHandler) as httpd:
        print(f"服务器启动在: http://localhost:{PORT}")
        print("按 Ctrl+C 停止服务器")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务器已停止")


if __name__ == "__main__":
    start_server()