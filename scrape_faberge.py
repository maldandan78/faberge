#!/usr/bin/env python3
"""Скрейпер каталога «Шедевры коллекции» музея Фаберже (fabergemuseum.ru).

Парсит карточку экспоната из server-rendered HTML (без браузера): поля
page__feature (Дата/Мастер/Материалы/Зал/Фирма/Техника/Место создания),
текстовое описание (text-content) и изображения (phpthumbof cache).

Использование:
  python3 scrape_faberge.py --dry-run slug1 slug2 ...   # печать JSON, без сети к API
  python3 scrape_faberge.py --all-from FILE --out items.json
"""
from __future__ import annotations
import argparse, json, re, sys, time, urllib.request

BASE = "https://fabergemuseum.ru/kollekczii/shedevryi-kollekczii"
UA = "Mozilla/5.0 (compatible; faberge-import/1.0)"

FEATURE_RE = re.compile(
    r'page__feature-title[^>]*>(?P<label>[^<]+)</div>\s*'
    r'<div class="page__feature-value[^>]*>(?P<value>.*?)</div>\s*<div class="clear"',
    re.S,
)
TAG_RE = re.compile(r"<[^>]+>")
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
DESC_RE = re.compile(r'<div class="text-content[^>]*>(.*?)</div>', re.S)
IMG_RE = re.compile(r'/assets/components/phpthumbof/cache/[^"\']+\.(?:jpg|jpeg|png|webp)', re.I)
LANG_RE = re.compile(r'<html[^>]*\blang="([^"]+)"', re.I)


def _clean(html_fragment: str) -> str:
    txt = TAG_RE.sub("", html_fragment)
    txt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", txt)  # control chars (напр. \x01-разделитель)
    txt = re.sub(r"&nbsp;", " ", txt)
    txt = re.sub(r"&laquo;", "«", txt)
    txt = re.sub(r"&raquo;", "»", txt)
    txt = re.sub(r"&mdash;", "—", txt)
    txt = re.sub(r"&amp;", "&", txt)
    txt = re.sub(r"&quot;", '"', txt)
    txt = re.sub(r"\s+", " ", txt).strip(" ,;")
    return txt.strip()


def _cyrillic_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    cyr = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    return cyr / len(letters)


def fetch(slug: str) -> str:
    url = f"{BASE}/{slug}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def parse(slug: str, html: str) -> dict:
    feats = {}
    for m in FEATURE_RE.finditer(html):
        feats[_clean(m.group("label"))] = _clean(m.group("value"))

    h1 = H1_RE.search(html)
    name = _clean(h1.group(1)) if h1 else ""

    desc_m = DESC_RE.search(html)
    desc = ""
    if desc_m:
        # сохранить разбиение на абзацы как переводы строк
        frag = re.sub(r"</p>\s*<p>", "\n\n", desc_m.group(1))
        desc = _clean(frag.replace("\n\n", "  ")).replace("  ", "\n\n")

    # год: первое 4-значное число в поле «Дата»
    year = None
    if feats.get("Дата"):
        ym = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", feats["Дата"])
        year = int(ym.group(1)) if ym else None

    images = []
    for u in IMG_RE.findall(html):
        full = "https://fabergemuseum.ru" + u
        if full not in images:
            images.append(full)

    lang_m = LANG_RE.search(html)
    lang = (lang_m.group(1) if lang_m else "").lower()

    short = desc.split("\n\n")[0] if desc else None
    if short and len(short) > 400:
        short = short[:397].rstrip() + "…"

    return {
        "slug": slug,
        "name": name,
        "lang": lang,
        "cyr_ratio": round(_cyrillic_ratio(name), 2),
        "year_created": year,
        "date_raw": feats.get("Дата"),
        "master_name": feats.get("Мастер"),
        "firm": feats.get("Фирма"),
        "place": feats.get("Место создания"),
        "material": feats.get("Материалы"),
        "technique": feats.get("Техника"),
        "hall": feats.get("Зал"),
        "short_description": short,
        "raw_history": desc or None,
        "images": images,
        "image_count": len(images),
        "source_url": f"{BASE}/{slug}",
    }


def is_usable(item: dict) -> bool:
    """Берём всё с непустым русским названием. Англослаговые страницы (brooch,
    desk-clock) отдают РУССКИЙ контент и являются отдельными объектами, поэтому
    по языку не отсекаем. Реально английские страницы редки: их ловим по очень
    низкой доле кириллицы в названии."""
    if not item["name"]:
        return False
    if item["cyr_ratio"] < 0.2:  # настоящий английский заголовок
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all-from")
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.3)
    a = ap.parse_args()

    slugs = list(a.slugs)
    if a.all_from:
        slugs += [s.strip() for s in open(a.all_from) if s.strip()]

    items, skipped = [], []
    for i, slug in enumerate(slugs, 1):
        try:
            it = parse(slug, fetch(slug))
        except Exception as e:
            skipped.append({"slug": slug, "reason": f"fetch/parse error: {e}"})
            print(f"[{i}/{len(slugs)}] ✗ {slug}: {e}", file=sys.stderr)
            continue
        if not is_usable(it):
            skipped.append({"slug": slug, "reason": f"unusable (lang={it['lang']},cyr={it['cyr_ratio']},name='{it['name']}')"})
            print(f"[{i}/{len(slugs)}] ⤳ skip {slug} (unusable)", file=sys.stderr)
        else:
            items.append(it)
            print(f"[{i}/{len(slugs)}] ✓ {slug}: «{it['name']}» hall={it['hall']} imgs={it['image_count']}", file=sys.stderr)
        time.sleep(a.sleep)

    if a.dry_run:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    if a.out:
        json.dump({"items": items, "skipped": skipped}, open(a.out, "w"), ensure_ascii=False, indent=2)
        print(f"\nwrote {len(items)} items, {len(skipped)} skipped -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
