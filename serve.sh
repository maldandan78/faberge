#!/usr/bin/env bash
# Локальный запуск Swagger UI для контракта API ИИ-гида музея Фаберже.
#
#   ./serve.sh           # порт 8080
#   ./serve.sh 9000      # другой порт
#
# Затем откройте:
#   http://localhost:<port>/         -> Swagger UI (редирект на /swagger/)
#   http://localhost:<port>/openapi.yaml
set -euo pipefail

PORT="${1:-8080}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Swagger UI:   http://localhost:${PORT}/swagger/"
echo "Спека YAML:   http://localhost:${PORT}/openapi.yaml"
echo "Ctrl+C — остановить."
exec python3 -m http.server "${PORT}" --bind 127.0.0.1 --directory "${ROOT}"
