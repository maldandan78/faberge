#!/usr/bin/env bash
# Загрузка фотографий экспонатов в Object Storage через админ-эндпоинт.
#
# Использование:
#   BASE_URL=https://<host> ADMIN_TOKEN=<token> ./upload_media.sh [media/faberge]
#
# Для каждой папки media/faberge/<folder>:
#   slug = "faberge_" + <folder с '-' заменёнными на '_'>
#   GET  /exhibits/by-slug/{slug}            -> exhibit_id
#   POST /admin/exhibits/{id}/media          для каждого файла (по одному)
# Первый файл в папке (01.*) загружается как is_primary=true (становится image_url
# карточки), остальные — как галерея. Эндпоинт сам кладёт объект в бакет и создаёт
# строку exhibit_images.
#
# ВНИМАНИЕ: запускать ОДИН раз. Эндпоинт всегда вставляет новую строку галереи,
# поэтому повторный прогон создаст дубликаты. Перед повторным запуском пересидируйте
# базу (db/seed_fabergemuseum.sql теперь идемпотентен).
set -euo pipefail

BASE_URL="${BASE_URL:?Задайте BASE_URL, напр. https://host}"
ADMIN_TOKEN="${ADMIN_TOKEN:?Задайте ADMIN_TOKEN}"
ROOT="${1:-media/faberge}"
BASE_URL="${BASE_URL%/}"

ok=0; fail=0
for dir in "$ROOT"/*/; do
  [ -d "$dir" ] || continue
  folder="$(basename "$dir")"
  slug="faberge_${folder//-/_}"

  resp="$(curl -sS --max-time 30 "$BASE_URL/exhibits/by-slug/$slug")" \
    || { echo "‼  $folder: запрос by-slug не прошёл"; fail=$((fail + 1)); continue; }
  id="$(printf '%s' "$resp" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("id",""))
except Exception: pass' 2>/dev/null || true)"
  if [ -z "$id" ]; then
    echo "‼  $folder: нет экспоната slug=$slug (ответ: ${resp:0:140})"
    fail=$((fail + 1)); continue
  fi
  echo "▶  $folder → exhibit $id"

  primary=true
  for f in "$dir"*; do
    [ -f "$f" ] || continue
    case "$f" in
      *.png)  ct=image/png ;;
      *.webp) ct=image/webp ;;
      *)      ct=image/jpeg ;;
    esac
    code="$(curl -sS --max-time 120 -o /tmp/upload_media_resp.json -w '%{http_code}' \
        -X POST "$BASE_URL/admin/exhibits/$id/media" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -F "file=@${f};type=${ct}" \
        -F "is_primary=${primary}")" || code=000
    if [ "$code" = "201" ]; then
      url="$(python3 -c 'import json;print(json.load(open("/tmp/upload_media_resp.json")).get("image_url",""))' 2>/dev/null || true)"
      echo "   ✓ $(basename "$f")  primary=${primary}  → ${url}"
      ok=$((ok + 1))
    else
      echo "   ✗ $(basename "$f")  HTTP ${code}: $(head -c 200 /tmp/upload_media_resp.json 2>/dev/null)"
      fail=$((fail + 1))
    fi
    primary=false
  done
done

echo "──────────────────────────────────────"
echo "Готово: загружено ${ok}, ошибок ${fail}"
