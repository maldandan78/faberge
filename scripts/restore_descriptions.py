#!/usr/bin/env python3
"""Восстановить обрезанные `short_description` экспонатов из `raw_history`.

Контекст проблемы
-----------------
Внешний импортёр, наполнявший прод, обрезал `short_description` до ~400 символов
и дописывал многоточие «…». Полный текст описания при этом сохранён в начале
`raw_history` — до служебного блока «\\n\\nСправочно — …; Источник: <url>».
Бэкенд ничего не режет: `short_description` — это `TEXT`, отдаётся как есть.

Что делает скрипт
-----------------
Для каждого экспоната сравнивает `short_description` и «прозу» из `raw_history`
(всё до «Справочно —») и восстанавливает полный текст ТОЛЬКО там, где описание
действительно обрезано и проза — его достоверное продолжение:

    * ``short_description`` заканчивается на «…» (маркер обрезки импортёром), И
    * проза длиннее обрезанного текста, И
    * проза начинается ровно с обрезанного текста (без «…») —
      защита от ложных срабатываний (мы никогда не перезапишем хорошее описание).

Категории (в отчёте dry-run):
    restore                 — будет восстановлено из raw_history
    truncated_no_prose      — обрезано, но в raw_history нет пригодной прозы (только «Справочно —»)
    truncated_mismatch      — обрезано, но проза не совпадает с началом (ручная проверка)
    stub                    — авто-заглушка «"Имя". Фирма/мастер: …» (реального описания нет нигде)
    ok                      — полное описание, трогать не нужно

Работа идёт ЧЕРЕЗ HTTP API (нужен только admin-токен, не доступ к БД).
Чтение `raw_history`: `GET /admin/exhibits/{id}` (если задеплоен) с откатом на
пустой `PATCH {}` (no-op: без изменённых полей SQLAlchemy не шлёт UPDATE — триггер
updated_at не срабатывает). Запись: `PATCH /admin/exhibits/{id}`.

Примеры
-------
    # только отчёт (ничего не меняет)
    python scripts/restore_descriptions.py --base <URL> --token <TOKEN>

    # применить + сохранить бэкап старых значений (обратимо)
    python scripts/restore_descriptions.py --base <URL> --token <TOKEN> --apply

    # откатить по бэкапу
    python scripts/restore_descriptions.py --base <URL> --token <TOKEN> --revert restore_backup.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

SPRAVOCHNO_RE = re.compile(r"\n\nСправочно —")
ELLIPSIS = "…"
PREFIX_MATCH_CHARS = 100  # сколько ведущих символов должно совпасть, чтобы признать прозу продолжением


# ── HTTP ─────────────────────────────────────────────────────────────────────
def _request(base: str, token: str, method: str, path: str, body: Optional[dict] = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base.rstrip("/") + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise  # 4xx/5xx — пробрасываем сразу (ретрай не поможет)
        except Exception as exc:  # noqa: BLE001 — сеть: короткий ретрай
            last_exc = exc
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"{method} {path} не удался после ретраев: {last_exc}")


def _read_exhibit(base: str, token: str, eid: int, mode: str) -> dict:
    """Прочитать полную карточку экспоната (с raw_history)."""
    if mode in ("auto", "get"):
        try:
            return _request(base, token, "GET", f"/admin/exhibits/{eid}")
        except urllib.error.HTTPError as exc:
            if mode == "get" or exc.code not in (404, 405):
                raise
            # 404/405 на GET → эндпоинт ещё не задеплоен, откатываемся на PATCH {}
    return _request(base, token, "PATCH", f"/admin/exhibits/{eid}", body={})


def _all_exhibit_ids(base: str, token: str) -> List[int]:
    ids: List[int] = []
    offset = 0
    while True:
        page = _request(base, token, "GET", f"/exhibits?limit=100&offset={offset}")
        items = page.get("items", [])
        ids += [it["id"] for it in items]
        total = page.get("total", len(ids))
        offset += 100
        if offset >= total or not items:
            break
    return ids


# ── Логика восстановления ────────────────────────────────────────────────────
def full_prose(raw_history: Optional[str]) -> Optional[str]:
    if not raw_history:
        return None
    # Весь raw_history — служебный блок «Справочно — …»: реальной прозы нет.
    if raw_history.lstrip().startswith("Справочно —"):
        return None
    prose = SPRAVOCHNO_RE.split(raw_history, maxsplit=1)[0].strip()
    return prose or None


def classify(short_description: Optional[str], raw_history: Optional[str]) -> Tuple[str, Optional[str]]:
    """Вернуть (категория, новый_short_description|None)."""
    sd = short_description or ""
    sd_stripped = sd.rstrip()
    prose = full_prose(raw_history)

    if sd_stripped.endswith(ELLIPSIS):
        if not prose or len(prose) <= len(sd):
            return "truncated_no_prose", None
        core = sd_stripped[:-1].rstrip()  # обрезанный текст без «…»
        k = min(PREFIX_MATCH_CHARS, len(core))
        if k > 0 and prose.startswith(core[:k]):
            return "restore", prose
        return "truncated_mismatch", None

    if "Фирма/мастер:" in sd:
        return "stub", None
    return "ok", None


# ── Команды ──────────────────────────────────────────────────────────────────
def run(base: str, token: str, apply: bool, read_mode: str, out: str, backup: str, limit: Optional[int]) -> int:
    ids = _all_exhibit_ids(base, token)
    if limit:
        ids = ids[:limit]
    print(f"Экспонатов к анализу: {len(ids)}", file=sys.stderr)

    buckets: Dict[str, List[dict]] = {k: [] for k in ("restore", "truncated_no_prose", "truncated_mismatch", "stub", "ok")}
    plan: List[dict] = []
    for i, eid in enumerate(ids, 1):
        try:
            ex = _read_exhibit(base, token, eid, read_mode)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! id={eid}: чтение не удалось: {exc}", file=sys.stderr)
            continue
        sd = ex.get("short_description")
        rh = ex.get("raw_history")
        cat, new_sd = classify(sd, rh)
        buckets[cat].append({"id": eid, "name": ex.get("name"), "old_len": len(sd or ""),
                             "new_len": len(new_sd or "") if new_sd else None})
        if cat == "restore":
            plan.append({"id": eid, "name": ex.get("name"), "old": sd, "new": new_sd})
        if i % 25 == 0:
            print(f"  …{i}/{len(ids)}", file=sys.stderr)

    # Отчёт
    print("\n=== Итог ===")
    for cat in ("restore", "truncated_no_prose", "truncated_mismatch", "stub", "ok"):
        print(f"  {cat:22} {len(buckets[cat])}")
    if plan:
        gained = sum((p["new"] and len(p["new"]) or 0) - len(p["old"] or "") for p in plan)
        print(f"\n  К восстановлению: {len(plan)} экспонатов, +{gained} символов суммарно")
        print("  Примеры:")
        for p in plan[:5]:
            print(f"    id={p['id']} {len(p['old'] or '')}→{len(p['new'])}  «{p['name']}»")

    with open(out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)
    print(f"\n  План сохранён: {out}", file=sys.stderr)

    if not apply:
        print("\n  DRY-RUN — ничего не изменено. Запустите с --apply для применения.")
        return 0

    if not plan:
        print("\n  Нечего применять.")
        return 0

    # Бэкап старых значений — для обратимости.
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump([{"id": p["id"], "short_description": p["old"]} for p in plan], fh, ensure_ascii=False, indent=2)
    print(f"  Бэкап старых значений: {backup}", file=sys.stderr)

    ok = 0
    for p in plan:
        try:
            _request(base, token, "PATCH", f"/admin/exhibits/{p['id']}", body={"short_description": p["new"]})
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ! id={p['id']}: PATCH не удался: {exc}", file=sys.stderr)
    print(f"\n  Применено: {ok}/{len(plan)}")
    return 0


def revert(base: str, token: str, backup_path: str) -> int:
    with open(backup_path, encoding="utf-8") as fh:
        rows = json.load(fh)
    ok = 0
    for r in rows:
        try:
            _request(base, token, "PATCH", f"/admin/exhibits/{r['id']}", body={"short_description": r["short_description"]})
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ! id={r['id']}: откат не удался: {exc}", file=sys.stderr)
    print(f"Откачено: {ok}/{len(rows)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Восстановить обрезанные short_description из raw_history.")
    ap.add_argument("--base", default=os.environ.get("FABERGE_API_BASE"), help="Базовый URL API.")
    ap.add_argument("--token", default=os.environ.get("FABERGE_ADMIN_TOKEN"), help="Admin Bearer-токен.")
    ap.add_argument("--apply", action="store_true", help="Применить изменения (по умолчанию dry-run).")
    ap.add_argument("--read-mode", choices=("auto", "get", "patch"), default="auto",
                    help="Как читать raw_history: auto (GET с откатом на PATCH), get, patch.")
    ap.add_argument("--out", default="restore_plan.json", help="Куда сохранить план восстановления.")
    ap.add_argument("--backup", default="restore_backup.json", help="Куда сохранить бэкап при --apply.")
    ap.add_argument("--limit", type=int, default=None, help="Ограничить число экспонатов (для проверки).")
    ap.add_argument("--revert", metavar="BACKUP", help="Откатить изменения по файлу бэкапа и выйти.")
    args = ap.parse_args()

    if not args.base or not args.token:
        ap.error("нужны --base и --token (или FABERGE_API_BASE / FABERGE_ADMIN_TOKEN).")

    if args.revert:
        return revert(args.base, args.token, args.revert)
    return run(args.base, args.token, args.apply, args.read_mode, args.out, args.backup, args.limit)


if __name__ == "__main__":
    sys.exit(main())
