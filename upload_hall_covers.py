#!/usr/bin/env python3
"""Обложки залов (cover_image_url) через админ-API.

Источник картинки на зал:
  - зал 1 «Парадная лестница» (экспонатов нет) — общий снимок дворца с сайта;
  - остальные залы — фото первого экспоната зала (уже лежит в Object Storage).
На сайте отдельных интерьерных фото по залам нет (галереи — только JS/виртуальный
тур), поэтому берём репрезентативное фото экспоната зала.

Загрузка идёт через POST /admin/halls/{id}/cover (заливает копию в бакет под
halls/<id>/ и проставляет cover_image_url). Требует развёрнутого нового эндпоинта.

Env: BASE_URL, ADMIN_TOKEN.
  BASE_URL=... ADMIN_TOKEN=... python3 upload_hall_covers.py [--dry-run]
"""
from __future__ import annotations
import os, re, shutil, subprocess, sys, tempfile, urllib.request

# Бэкенд режет загрузку по размеру (~3 МБ). Крупные оригиналы ужимаем sips (macOS).
MAX_BYTES = 2_500_000

BASE = os.environ.get("BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("ADMIN_TOKEN", "")
UA = "Mozilla/5.0 (compatible; faberge-import/1.0)"

# Реальные интерьерные фото залов со страницы «План экспозиции»
# (fabergemuseum.ru/posetitelyam/plan-ekspozitsii): полноразмерные оригиналы,
# путь /exposition/<N>/ соответствует номеру зала (= hall_id 1..11).
_PLAN = "https://fabergemuseum.ru/image/exhibitions/exposition"
HALL_INTERIOR = {
    1: f"{_PLAN}/1/grand_1.jpg",       # Парадная лестница
    2: f"{_PLAN}/2/knight_1.jpg",      # Рыцарский зал
    3: f"{_PLAN}/3/red_1.jpg",         # Красная гостиная
    4: f"{_PLAN}/4/blue_1.jpg",        # Синяя гостиная
    5: f"{_PLAN}/5/gold_7.jpg",        # Золотая гостиная
    6: f"{_PLAN}/6/avanzal_1.jpg",     # Аванзал
    7: f"{_PLAN}/7/white_blue_1.jpg",  # Белая и Голубая гостиные
    8: f"{_PLAN}/8/exhibition_1.jpg",  # Выставочный зал
    9: f"{_PLAN}/9/gothic_4.jpg",      # Готический зал
    10: f"{_PLAN}/10/scullery_1.jpg",  # Верхняя буфетная
    11: f"{_PLAN}/11/beige_1.jpg",     # Бежевый зал
}


def get_json(path: str):
    import json
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def first_exhibit_image(hall_id: int) -> str | None:
    data = get_json(f"/halls/{hall_id}/exhibits?limit=50")
    for e in data.get("items", []):
        u = e.get("thumbnail_url") or e.get("image_url")
        if u:
            return u
    return None


def upload_cover(hall_id: int, url: str) -> tuple[int, str]:
    ext = re.search(r"\.(jpg|jpeg|png|webp)", url, re.I)
    ext = ext.group(1).lower() if ext else "jpg"
    ct = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[ext]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except Exception as e:
        return 0, f"download failed: {e}"
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as fh:
        fh.write(data); tmp = fh.name
    # крупные фото ужимаем под лимит бэкенда (sips: ресайз по большей стороне)
    if len(data) > MAX_BYTES and ext != "webp" and shutil.which("sips"):
        for dim in (2000, 1600, 1280):
            subprocess.run(["sips", "-Z", str(dim), tmp], capture_output=True, text=True)
            if os.path.getsize(tmp) <= MAX_BYTES:
                break
    try:
        out = subprocess.run(
            ["curl", "-sS", "--max-time", "120", "-o", "/dev/null", "-w", "%{http_code}",
             "-X", "POST", f"{BASE}/admin/halls/{hall_id}/cover",
             "-H", f"Authorization: Bearer {TOKEN}",
             "-F", f"file=@{tmp};type={ct}"],
            capture_output=True, text=True)
        return (int(out.stdout) if out.stdout.strip().isdigit() else 0), out.stdout
    finally:
        os.unlink(tmp)


def main():
    dry = "--dry-run" in sys.argv
    only = None
    if "--halls" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--halls") + 1].split(",")}
    if not BASE or not TOKEN:
        sys.exit("set BASE_URL and ADMIN_TOKEN")
    halls = get_json("/halls")["items"]
    if only is not None:
        halls = [h for h in halls if h["id"] in only]
    ok = fail = skip = 0
    for h in halls:
        hid, name = h["id"], h.get("name")
        src = HALL_INTERIOR.get(hid) or first_exhibit_image(hid)
        if not src:
            skip += 1
            print(f"  ⤳ hall {hid} «{name}»: нет источника картинки — пропуск", file=sys.stderr)
            continue
        if dry:
            print(f"  DRY hall {hid} «{name}» <- {src[:80]}")
            continue
        code, _ = upload_cover(hid, src)
        if code == 201:
            ok += 1; print(f"  ✓ hall {hid} «{name}»", file=sys.stderr)
        else:
            fail += 1; print(f"  ✗ hall {hid} «{name}» HTTP {code}", file=sys.stderr)
    print("─" * 40, file=sys.stderr)
    print(f"covers set={ok} failed={fail} skipped={skip}", file=sys.stderr)


if __name__ == "__main__":
    main()
