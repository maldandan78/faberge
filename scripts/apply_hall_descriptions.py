#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Заливает длинные описания залов (из db/hall_descriptions.json) через API.

Используется после деплоя эндпоинта PATCH /admin/halls/{hall_id}.

    BASE_URL=https://api.example.ru \
    ADMIN_API_TOKEN=secret \
    python scripts/apply_hall_descriptions.py [--dry-run]

Сопоставление идёт по hall_number (а не по id), поэтому не зависит от того,
какие id выдала база. Только stdlib — никаких зависимостей.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("ADMIN_API_TOKEN", "dev-admin-token")
DRY_RUN = "--dry-run" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
DESC_FILE = os.path.join(HERE, "..", "db", "hall_descriptions.json")


def _req(method, path, payload=None):
    url = BASE_URL + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if method != "GET":
        req.add_header("Authorization", "Bearer " + TOKEN)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def main():
    descs = json.load(open(DESC_FILE, encoding="utf-8"))
    by_number = {v["hall_number"]: v for v in descs.values()}

    # карта hall_number -> id из живой базы
    try:
        _, halls = _req("GET", "/halls?limit=100")
    except urllib.error.URLError as e:
        print(f"❌ Не достучался до {BASE_URL}/halls: {e}")
        sys.exit(1)
    live = {h["hall_number"]: h for h in halls["items"]}
    print(f"В базе залов: {len(live)} | описаний в файле: {len(by_number)}")
    print(f"Цель: {BASE_URL}  | режим: {'DRY-RUN' if DRY_RUN else 'ЗАПИСЬ'}\n")

    ok = miss = err = 0
    for num in sorted(by_number):
        d = by_number[num]
        h = live.get(num)
        if not h:
            print(f"⚠️  зал #{num} ({d['name']}) — нет в базе, пропуск")
            miss += 1
            continue
        n = len(d["description"])
        if DRY_RUN:
            print(f"• #{num} id={h['id']} {d['name']}: PATCH description ({n} симв.) [dry-run]")
            ok += 1
            continue
        try:
            status, _ = _req("PATCH", f"/admin/halls/{h['id']}", {"description": d["description"]})
            print(f"✅ #{num} id={h['id']} {d['name']}: {status} ({n} симв.)")
            ok += 1
        except urllib.error.HTTPError as e:
            print(f"❌ #{num} id={h['id']} {d['name']}: HTTP {e.code} {e.read().decode('utf-8')[:200]}")
            err += 1

    print(f"\nИтог: обновлено {ok}, пропущено {miss}, ошибок {err}")
    sys.exit(1 if err else 0)


if __name__ == "__main__":
    main()
