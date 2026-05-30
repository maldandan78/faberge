#!/usr/bin/env python3
"""
Надёжный статический сервер для Swagger UI (для панели предпросмотра Claude).

В отличие от `python3 -m http.server`, этот скрипт не вычисляет `os.getcwd()`
на этапе импорта (что падает в песочнице предпросмотра с EPERM): он сразу
делает `os.chdir()` на абсолютный путь проекта и лишь затем импортирует
обработчик. Подходит и для обычного терминала.

Запуск:
  python3 serve_preview.py            # порт 8080
  python3 serve_preview.py 9000       # другой порт
"""
import os
import sys

# Корень проекта — каталог этого файла (портативно, без зависимости от CWD).
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

import http.server
import socketserver

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8080"))


class Handler(http.server.SimpleHTTPRequestHandler):
    # Отдаём YAML с корректным content-type (по умолчанию octet-stream).
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
    }


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    print(f"Serving {ROOT} at http://127.0.0.1:{PORT}/  (Swagger UI: /swagger/)")
    httpd.serve_forever()
