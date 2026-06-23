#!/usr/bin/env python3
"""Загрузка экспонатов музея Фаберже в БД через админ-API.

Вход: items.json (см. scrape_faberge.py). Шаги:
  1) дедуп по сигнатуре (name, year, master, material) — оставляем версию с макс. числом фото;
  2) маппинг «Зал» -> hall_id (точное совпадение + алиасы), для зала-без-имени — фолбэк-зал;
  3) на каждый нужный зал — витрина «Коллекция (импорт)» (создаём, если нет);
  4) POST /admin/exhibits, затем загрузка фото POST /admin/exhibits/{id}/media (первое = primary).

Идемпотентность: при 409 (label_slug уже есть) экспонат пропускается.

Env: BASE_URL, ADMIN_TOKEN.
Использование:
  BASE_URL=... ADMIN_TOKEN=... python3 load_faberge.py items.json [--limit N] [--dry-run]
"""
from __future__ import annotations
import hashlib, json, os, re, subprocess, sys, tempfile, urllib.request, urllib.error

BASE = os.environ.get("BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("ADMIN_TOKEN", "")
UA = "Mozilla/5.0 (compatible; faberge-import/1.0)"

# Алиасы названий залов сайта -> названия залов в БД.
HALL_ALIASES = {
    "Голубая гостиная": "Белая и Голубая гостиные",
    "Белая гостиная": "Белая и Голубая гостиные",
}
FALLBACK_HALL_NAME = "Вне постоянной экспозиции"
FALLBACK_HALL_NUMBER = 99
IMPORT_SHOWCASE_NAME = "Коллекция (импорт)"


def api(method: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {TOKEN}",
                                          "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            txt = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(txt) if txt else {})
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, txt


def get_json(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def upload_image(exhibit_id: int, url: str, primary: bool) -> tuple[int, str]:
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
    try:
        out = subprocess.run(
            ["curl", "-sS", "--max-time", "120", "-o", "/dev/null", "-w", "%{http_code}",
             "-X", "POST", f"{BASE}/admin/exhibits/{exhibit_id}/media",
             "-H", f"Authorization: Bearer {TOKEN}",
             "-F", f"file=@{tmp};type={ct}", "-F", f"is_primary={'true' if primary else 'false'}"],
            capture_output=True, text=True)
        return (int(out.stdout) if out.stdout.strip().isdigit() else 0), out.stdout
    finally:
        os.unlink(tmp)


def dedup(items: list[dict]) -> tuple[list[dict], list[dict]]:
    best: dict[tuple, dict] = {}
    dups = []
    for it in items:
        sig = (it["name"].strip().lower(), it.get("year_created"),
               (it.get("master_name") or "").strip().lower(),
               (it.get("material") or "").strip().lower())
        if sig in best:
            keep, drop = (best[sig], it) if best[sig]["image_count"] >= it["image_count"] else (it, best[sig])
            best[sig] = keep; dups.append(drop)
        else:
            best[sig] = it
    return list(best.values()), dups


def clamp_slug(slug: str) -> str:
    """label_slug — VARCHAR(100). Длинные слаги обрезаем с хвостом-хэшем (уникальность)."""
    if len(slug) <= 100:
        return slug
    return slug[:91] + "-" + hashlib.sha1(slug.encode()).hexdigest()[:8]


def synth_short(it: dict) -> str | None:
    bits = []
    who = it.get("master_name") or it.get("firm")
    if who: bits.append(f"Фирма/мастер: {who}")
    if it.get("place"): bits.append(it["place"])
    if it.get("year_created"): bits.append(str(it["year_created"]))
    if it.get("material"): bits.append(it["material"])
    return ("«" + it["name"] + "». " + ", ".join(bits) + ".") if bits else None


def build_history(it: dict) -> str | None:
    body = (it.get("raw_history") or "").strip()
    footer = []
    if it.get("firm"): footer.append(f"Фирма: {it['firm']}")
    if it.get("place"): footer.append(f"Место создания: {it['place']}")
    if it.get("technique"): footer.append(f"Техника: {it['technique']}")
    footer.append(f"Источник: {it['source_url']}")
    foot = "Справочно — " + "; ".join(footer) + "."
    return (body + "\n\n" + foot) if body else foot


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    limit = None
    if "--limit" in args:
        i = args.index("--limit"); limit = int(args[i + 1]); del args[i:i + 2]
    path = args[0]
    if not BASE or not TOKEN:
        sys.exit("set BASE_URL and ADMIN_TOKEN")

    data = json.load(open(path))
    items = data["items"] if isinstance(data, dict) else data
    items, dups = dedup(items)
    print(f"items after dedup: {len(items)} (dropped {len(dups)} dups)", file=sys.stderr)
    if limit:
        items = items[:limit]

    # hall name -> id
    halls = get_json("/halls")["items"]
    name2id = {h["name"]: h["id"] for h in halls}

    def resolve_hall(name):
        if not name:
            return None
        if name in name2id:
            return name2id[name]
        if name in HALL_ALIASES and HALL_ALIASES[name] in name2id:
            return name2id[HALL_ALIASES[name]]
        for hn, hid in name2id.items():  # вхождение как запасной вариант
            if name in hn or hn in name:
                return hid
        return None

    showcase_cache: dict[int, int] = {}

    def showcase_for(hall_id: int) -> int:
        if hall_id in showcase_cache:
            return showcase_cache[hall_id]
        existing = get_json(f"/halls/{hall_id}/showcases")["items"]
        sc = next((s for s in existing if s["name"] == IMPORT_SHOWCASE_NAME), None)
        if sc is None:
            num = max([s["showcase_number"] for s in existing], default=0) + 1
            st, resp = api("POST", "/admin/showcases",
                           {"hall_id": hall_id, "showcase_number": num, "name": IMPORT_SHOWCASE_NAME})
            if st == 201:
                sc = resp
            else:  # коллизия/гонка — перечитаем и найдём по имени
                existing = get_json(f"/halls/{hall_id}/showcases")["items"]
                sc = next(s for s in existing if s["name"] == IMPORT_SHOWCASE_NAME)
        showcase_cache[hall_id] = sc["id"]
        return sc["id"]

    # фолбэк-зал для экспонатов без зала
    def fallback_hall_id():
        if FALLBACK_HALL_NAME in name2id:
            return name2id[FALLBACK_HALL_NAME]
        st, resp = api("POST", "/admin/halls",
                       {"hall_number": FALLBACK_HALL_NUMBER, "name": FALLBACK_HALL_NAME,
                        "description": "Экспонаты каталога, не привязанные к залу постоянной экспозиции.", "level": 0})
        if st != 201:  # уже существует — найдём по имени
            resp = next(h for h in get_json("/halls")["items"] if h["name"] == FALLBACK_HALL_NAME)
        name2id[FALLBACK_HALL_NAME] = resp["id"]
        return resp["id"]

    created = imgs_ok = imgs_fail = skipped = errors = 0
    for n, it in enumerate(items, 1):
        hall_id = resolve_hall(it.get("hall")) or fallback_hall_id()
        if dry:
            print(f"[{n}/{len(items)}] DRY «{it['name']}» hall={it.get('hall')}→{hall_id} imgs={it['image_count']}")
            continue
        sc_id = showcase_for(hall_id)
        payload = {
            "showcase_id": sc_id,
            "label_slug": clamp_slug(it["slug"]),
            "name": it["name"],
            "year_created": it.get("year_created"),
            "master_name": it.get("master_name") or it.get("firm"),
            "material": it.get("material"),
            "short_description": (it.get("short_description") or synth_short(it)),
            "raw_history": build_history(it),
        }
        st, resp = api("POST", "/admin/exhibits", payload)
        if st == 409:
            skipped += 1; print(f"[{n}/{len(items)}] ⤳ exists: {it['slug']}", file=sys.stderr); continue
        if st != 201:
            errors += 1; print(f"[{n}/{len(items)}] ✗ create {it['slug']} HTTP {st}: {resp}", file=sys.stderr); continue
        ex_id = resp["id"]; created += 1
        for k, url in enumerate(it["images"]):
            code, _ = upload_image(ex_id, url, primary=(k == 0))
            if code == 201: imgs_ok += 1
            else: imgs_fail += 1
        print(f"[{n}/{len(items)}] ✓ id={ex_id} «{it['name']}» hall={hall_id} sc={sc_id} imgs={it['image_count']}", file=sys.stderr)

    print("─" * 50, file=sys.stderr)
    print(f"created={created} skipped(409)={skipped} errors={errors} images_ok={imgs_ok} images_fail={imgs_fail}", file=sys.stderr)


if __name__ == "__main__":
    main()
