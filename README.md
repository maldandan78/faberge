# ИИ-гид музея Фаберже — backend

Backend мобильного web-приложения (PWA) **«ИИ-гид музея Фаберже»**: FastAPI +
PostgreSQL 17, развёрнутый как Yandex Cloud Function за API Gateway, плюс
рукописный OpenAPI-контракт для фронтенда.

Посетитель сканирует **QR-код** на входе, ходит по **интерактивной карте**
(зал → витрина → экспонат), может **сфотографировать экспонат**, получить о нём
рассказ ИИ-гида, **поговорить** с гидом и **прослушать** озвучку. Музей через
админку ведёт каталог и смотрит **аналитику посетителей**.

Этот README — точка входа для нового разработчика: что где лежит, как устроены
потоки данных, какие решения приняты и почему, и где разложены грабли.

> [!TIP]
> **Первые 15 минут.** Прочитайте [«Архитектура»](#архитектура),
> [«Карта кода»](#карта-кода) и [«Инварианты и подводные камни»](#инварианты-и-подводные-камни).
> Поднимите стенд через `docker compose up --build` и прогоните тесты
> (`python -m pytest tests -q`, ~2 с, без БД и сети). Всё остальное читайте по мере надобности.

## Содержание

1. [Продукт и основной сценарий](#продукт-и-основной-сценарий)
2. [Быстрый старт](#быстрый-старт)
3. [Архитектура](#архитектура)
4. [Карта кода](#карта-кода)
5. [Модель данных](#модель-данных)
6. [Карта эндпоинтов](#карта-эндпоинтов)
7. [Подсистемы](#подсистемы)
   - [Каталог и навигация](#каталог-и-навигация)
   - [Карточка экспоната](#карточка-экспоната)
   - [Распознавание по фото](#распознавание-по-фото)
   - [ИИ-гид: рассказ](#ии-гид-рассказ-post-guidestory)
   - [ИИ-гид: диалог](#ии-гид-диалог-post-guidechat)
   - [Вопросы-подсказки](#вопросы-подсказки)
   - [Фильтры стиля (guide_style)](#фильтры-стиля-guide_style)
   - [Озвучивание](#озвучивание)
   - [Хранилище медиа](#хранилище-медиа)
   - [Админка](#админка)
   - [Телеметрия и аналитика](#телеметрия-и-аналитика)
8. [Конфигурация](#конфигурация)
9. [Деплой и эксплуатация](#деплой-и-эксплуатация)
10. [База данных: схема, миграции, сиды](#база-данных-схема-миграции-сиды)
11. [Скрипты](#скрипты)
12. [Тесты](#тесты)
13. [Документация API: два представления](#документация-api-два-представления)
14. [Инварианты и подводные камни](#инварианты-и-подводные-камни)
15. [Процесс и история решений](#процесс-и-история-решений)
16. [Стек и источники данных](#стек-и-источники-данных)

---

## Продукт и основной сценарий

```
Клик «Распознать экспонат» → камера → снимок
   → POST /recognition          (фото → ML-поиск → label_slug → карточка + альтернативы)
   → POST /guide/story          (карточка → YandexGPT → рассказ + вопросы-подсказки)
   → POST /guide/chat           (вопрос посетителя → ответ + подсказки + «Упомянуто в ответе»)
   → POST /speech               («Прослушать» → SpeechKit → аудио)
   → GET  /exhibits/{id}/related («Другие экспонаты зала»)
   → POST /telemetry/events     (всё, что делал посетитель, → аналитика)
```

Ключевые сущности каталога: **зал** (`halls`) → **витрина** (`showcases`) →
**экспонат** (`exhibits`). Живой каталог — ~1250 карточек по путеводителю музея
2014 года. Каталог и ответы гида музей проверяет сам и присылает баг-репорты.
Большая часть нетривиальных решений в коде — ответы на конкретные пункты этих
баг-репортов (см. [«Процесс и история решений»](#процесс-и-история-решений)).

## Быстрый старт

### Вариант A — Docker Compose (PostgreSQL 17 + API одной командой)

```bash
docker compose up --build
```

- API + Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- PostgreSQL 17: `localhost:5432` (`faberge` / `faberge`)
- Админ-токен стенда: `dev-admin-token`

`db/schema.sql` и демо-данные `db/seed.sql` применяются автоматически, но
**только на пустом томе** (`/docker-entrypoint-initdb.d`). Сбросить БД:
`docker compose down -v`.

### Вариант B — локально (venv + своя БД)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt

export DATABASE_URL="postgresql+asyncpg://faberge:faberge@localhost:5432/faberge"
python scripts/init_db.py --seed          # применить схему + демо-данные
uvicorn app.main:app --reload --port 8000
```

### Вариант C — Yandex Managed PostgreSQL 17

TLS обязателен. CA-сертификат Yandex уже лежит в корне репозитория (`CA.pem`), либо
его можно скачать по [инструкции Yandex Cloud](https://yandex.cloud/docs/managed-postgresql/operations/connect):

```bash
export DATABASE_URL="postgresql+asyncpg://<user>:<pwd>@<fqdn>:6432/<db>"
export DB_SSL_ROOT_CERT="$PWD/CA.pem"
python scripts/init_db.py                 # только схема; --seed на живом каталоге НЕ запускать
uvicorn app.main:app --port 8000
```

### Без ключей Yandex всё работает

Без ключей Yandex Cloud (обычная локальная разработка) сервис работает целиком
на **стабах**:

- распознавание детерминированно выбирает экспонат по хэшу фото;
- рассказ собирается из полей карточки;
- «Прослушать» отдаёт настоящий, но тихий WAV;
- медиа пишутся в локальный `media/` и отдаются через `/media`.

Как только ключи появляются в окружении, те же эндпоинты начинают ходить в
облако (см. [«Стаб или облако»](#стаб-или-облако)). Какой режим включён, видно в
`GET /health`. Полный список переменных — в [`.env.example`](.env.example) и в
разделе [«Конфигурация»](#конфигурация).

## Архитектура

### Топология

```mermaid
flowchart LR
    pwa["PWA посетителя"] --> gw["Yandex API Gateway<br/>лимит запроса 3.5 МиБ"]
    adm["Админка музея"] --> gw
    gw --> fn["Cloud Function faberge-api<br/>index.handler → FastAPI"]
    cron["Cloud Function analytics_cron<br/>таймер 04:00"] -->|"POST /admin/analytics/rebuild"| gw
    fn --> pg[("Managed PostgreSQL 17")]
    fn --> gpt["YandexGPT<br/>Pro + Lite"]
    fn --> sk["SpeechKit v3"]
    fn --> ml["ML-сервис поиска по фото<br/>YOLO_ENDPOINT"]
    fn --> s3["Object Storage + CDN"]
```

Прод — **не контейнер**, а zip-архив Cloud Function. Из этого следует:

- `index.py` в корне — мост «событие API Gateway → ASGI-приложение». Он держит
  один event loop на «тёплый» экземпляр (чтобы пул asyncpg переживал вызовы),
  ставит `Cache-Control: no-store` на каждый ответ и пробрасывает `x-request-id`
  из запроса в ответ (по нему вызов ищется в логах).
- Файловая система функции read-only, писать можно только в `/tmp`
  (`MEDIA_DIR=/tmp/media`). Apt и системных шрифтов нет, поэтому всё, что нужно
  в рантайме, должно лежать в дереве репозитория (например, `assets/fonts/`, `CA.pem`).
- API Gateway режет запрос на 3 670 016 байт и отвечает **без CORS**. Отсюда
  лимит загрузки 2,5 МБ, см. [«Лимит загрузки»](#лимит-загрузки-25-мб-а-не-10).
- `Dockerfile` и `docker-compose.yml` нужны для локального стенда, прод они не
  описывают.

### Слои приложения

```mermaid
flowchart TD
    main["app/main.py<br/>FastAPI, CORS, /media, UpstreamError→502"] --> routers
    subgraph routers [routers]
        direction TB
        r1["system · navigation · exhibits · search"]
        r2["recognition · guide · speech"]
        r3["admin · telemetry"]
    end
    routers --> crud["app/crud.py<br/>запросы к БД, сериализация, аналитика"]
    routers --> services
    subgraph services [services]
        direction TB
        s1["recognizer · llm · tts · storage<br/>стаб + Yandex"]
        s2["guide_intel · guide_questions · guide_style<br/>guide_mentions · question_cluster"]
        s3["catalog_line · location · text_normalize<br/>visits · analytics_export"]
    end
    crud --> models["app/models.py ORM = db/schema.sql"]
    services --> crud
```

Правила слоёв:

- **Роутеры** тонкие: валидируют вход, выбирают ветку и зовут `crud` и `services`.
  Исключение — `routers/guide.py`, в нём живёт оркестрация диалога.
- **`crud.py`** — единственное место с SQL и ORM-запросами. Там же сериализаторы
  ORM → Pydantic (`to_exhibit`, `to_hall`…) и все аналитические отчёты.
- **`services/`** делятся на два вида:
  - **внешние сервисы** (`recognizer`, `llm`, `tts`, `storage`) — у каждого
    две реализации, стаб и Yandex;
  - **чистые модули** (`guide_style`, `guide_mentions`, `guide_intel`,
    `catalog_line`, `location`, `text_normalize`, `question_cluster`, `visits`) —
    без БД и сети, на них приходится основная масса юнит-тестов.

### Стаб или облако

Реализация выбирается флагами `settings.*_configured` (`app/config.py`):

| Сервис | Реальный режим включается, когда задано | Стаб |
|---|---|---|
| LLM (YandexGPT) | `YANDEX_API_KEY` **и** (`YANDEXGPT_MODEL_URI` или `YANDEX_FOLDER_ID`) | рассказ и ответ из полей карточки, `model="stub/heuristic"` |
| TTS (SpeechKit) | `SPEECHKIT_API_KEY` или `YANDEX_API_KEY` | тихий WAV длиной `chars/14` с (1–12 с) |
| Распознавание | `YOLO_ENDPOINT` | sha256(фото) → один из известных `label_slug` |
| Object Storage | `OBJECT_STORAGE_BUCKET` (+ `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` из окружения) | файлы в `MEDIA_DIR`, URL `{PUBLIC_BASE_URL}/media/…` |

Любой сбой внешнего сервиса выбрасывается как `services.UpstreamError`, и
глобальный обработчик в `main.py` превращает его в **502** с человеческим
текстом. Отсутствие ключей сбоем не считается: включается стаб.

## Карта кода

```
index.py                 Точка входа Cloud Function: событие API Gateway → ASGI (тесты: tests/test_bridge.py)
openapi.yaml             Дизайн-контракт API (OpenAPI 3.0.3, рукописный, ~220 КБ, с примерами)
requirements.txt         Зависимости для сборки функции (= app/requirements.txt без uvicorn; синхронить руками!)
CA.pem                   CA Yandex для TLS к Managed PG (кладётся в архив функции)
Dockerfile, docker-compose.yml   Локальный стенд (PG 17 + API)
.env.example             Все переменные окружения с комментариями

app/
  main.py                Сборка FastAPI: уровень логов, CORS, /media, UpstreamError→502, роутеры
  config.py              Settings (pydantic-settings, .env): все ручки + расчёт лимита загрузки + флаги *_configured
  db.py                  Async-движок SQLAlchemy (asyncpg, pool_pre_ping, TLS), get_session()
  models.py              ORM-модели — зеркало db/schema.sql (включая выражения search_vector!)
  schemas.py             Pydantic-схемы запросов/ответов; словарь событий телеметрии и белый список props
  crud.py                Весь доступ к БД (~2100 строк): навигация, поиск, админ-CRUD, кэш подсказок,
                         память отказов, телеметрия, аналитические отчёты и их кэш
  dependencies.py        Пагинация (limit/offset), Bearer-проверка админа
  routers/
    system.py            GET /health
    navigation.py        /map, /halls…, /showcases…
    exhibits.py          /exhibits, /exhibits/{id}, /by-slug/{slug}, /related
    search.py            /search (FTS + ILIKE по залам и экспонатам)
    recognition.py       POST /recognition: приём фото, лимиты, сшивка, добор кандидатов
    guide.py             POST /guide/story, /guide/chat — оркестрация ИИ-гида (самый сложный роутер)
    speech.py            POST /speech
    admin.py             /admin/**: вход, CRUD каталога, медиа, прогрев подсказок, аналитика, выгрузка
    telemetry.py         POST /telemetry/events
  services/
    __init__.py          UpstreamError
    recognizer.py        ML-поиск по фото + сшивка title_en → label_slug (канонический ключ, нечёткое сравнение)
    llm.py               YandexGPT: рассказ, ответ в диалоге, вопросы-подсказки, числа прописью; промпты; стабы
    tts.py               SpeechKit v1/v3, роли голосов, ключ аудио-кэша, стаб WAV
    storage.py           Object Storage (boto3) или локальный media/; безопасное удаление только «своих» URL
    guide_intel.py       Разбор реплики: «№12», «какие есть залы», навигационный вопрос, детектор отказа/оговорки
    guide_questions.py   Кэш подсказок в exhibit_questions, выбор среза (исключения, фолбэки, «не бывает пустым»)
    guide_style.py       Детерминированные фильтры: запрещённые темы, неподтверждённые вопросы, дубли, «вода»
    guide_mentions.py    «Упомянуто в ответе»: реально ли предмет назван в реплике
    question_cluster.py  Смысловая близость вопросов (леммы/стемы) — для аналитики и дедупликации
    location.py          ЕДИНАЯ формулировка расположения («Зал 4 «Синяя гостиная», витрина 5»)
    catalog_line.py      Разбор каталожной строки путеводителя (датировка/мастер/материал/техники/место)
    text_normalize.py    Числа прописью для TTS, типографика каталога, обрезка превью по предложению
    visits.py            Разбиение сессии на визиты (30 мин), база конверсий
    analytics_export.py  Выгрузка отчётов в .xlsx / .pdf (поиск TTF-шрифта с кириллицей)

db/
  schema.sql             Полный идемпотентный DDL (источник правды для структуры)
  seed.sql               Синтетические демо-данные (id совпадают с примерами openapi.yaml)
  seed_fabergemuseum.sql Реальные данные с сайта музея (TRUNCATE всего каталога! не путать с seed.sql)
  migrations/            Инкрементальные миграции живой БД (идемпотентные, с секцией отката)
  hall_descriptions.json Тексты залов по путеводителю 2014 (для scripts/apply_hall_descriptions.py)
  guide_fixes_20260812.json      Декларативные правки карточек с проверкой expect_current
  guide_showcases.example.json   Формат выписки путеводителя для import_guide_showcases.py

scripts/                 Эксплуатационные и разовые скрипты (см. «Скрипты»); analytics_cron/ — отдельная функция
tests/                   ~35 файлов, 700+ тестов; без БД и сети
docs/                    Решения, разборы баг-репортов, ответы музею
assets/fonts/            DejaVuSans.ttf для PDF-выгрузки — лежит в git НАМЕРЕННО
swagger/, serve.sh, serve_preview.py, index.html   Офлайн Swagger UI для openapi.yaml (порт 8080)
yaak/                    Рабочее пространство API-клиента Yaak (запросы к проду)

# Наследие первоначального наполнения (одноразовое, в рантайме не используется):
scrape_faberge.py, load_faberge.py, upload_media.sh, upload_hall_covers.py
# Не относится к продукту (формы учебной практики; кандидаты на удаление):
fill_practice_journal.js, fill_supervisor_feedback.js, scripts/fill_*.js
```

## Модель данных

```mermaid
erDiagram
    HALLS ||--o{ SHOWCASES : "hall_id CASCADE"
    SHOWCASES ||--o{ EXHIBITS : "showcase_id CASCADE"
    EXHIBITS ||--o{ EXHIBIT_IMAGES : "exhibit_id CASCADE"
    EXHIBITS ||--o{ EXHIBIT_QUESTIONS : "exhibit_id CASCADE"
    GUIDE_SESSIONS ||--o{ GUIDE_MESSAGES : "session_id CASCADE"
    HALLS {
        int id PK
        int hall_number UK "NULL = зал без номера"
        text name
        text description
        bool is_temporary
        bool is_service
        int sort_order
        tsvector search_vector
    }
    SHOWCASES {
        int id PK
        int hall_id FK
        int showcase_number "NULL = не в витринах"
    }
    EXHIBITS {
        int id PK
        int showcase_id FK
        varchar label_slug UK "класс распознавания"
        varchar exhibit_number "12, 12а"
        text name
        text year_created "строка датировки"
        text master_name
        text material
        text techniques
        text origin_place
        text short_description
        text short_description_spoken
        text raw_history "не публичное"
        tsvector search_vector
    }
    EXHIBIT_IMAGES {
        int id PK
        int exhibit_id FK
        bool is_primary
        int position
    }
    EXHIBIT_QUESTIONS {
        int exhibit_id PK
        varchar language PK
        jsonb questions
        char source_hash
    }
    GUIDE_SESSIONS {
        uuid id PK
        jsonb context
    }
    GUIDE_MESSAGES {
        bigint id PK
        uuid session_id FK
        varchar role
        bool answered
        varchar fail_reason
        int exhibit_id "без FK"
    }
    EVENTS {
        bigint id PK
        uuid session_id
        uuid device_id
        varchar type
        jsonb props
    }
```

Отдельно от графа лежат `analytics_daily` (PK `(date, metric, dimension_key)`,
суточный срез) и `analytics_reports` (PK `(report, period_key)`, кэш готовых
отчётов). У `events` и `guide_messages` внешних ключей на каталог **нет**
намеренно: удаление экспоната не должно стирать историю.

### Смысловые флаги каталога

| Признак | Что означает |
|---|---|
| `halls.hall_number = NULL` | Зал без номера («Вне постоянной экспозиции»). В подписях и ответах гида пишется только название, без «зал № …». В списке идёт последним и не входит в счётчик «В музее N залов». |
| `halls.is_service = true` | Служебная запись. Скрыта из `GET /map`, `GET /halls`, `/search` и из ответов гида (`crud._hall_visibility`), но **доступна по прямой ссылке** (`/halls/{id}`, `/exhibits`). Админке видна по `?include_service=true`. Сейчас таких залов нет: «Парадная лестница» была служебной с 29.07 по 31.08.2026, потом музей это решение отменил ([разбор](docs/staircase-hall-decision.md)). |
| `halls.is_temporary = true` | Временная выставка, отдельная ветка каталога (`?is_temporary=`). Экспонаты наследуют признак через витрину. |
| `halls.sort_order` | Порядок залов (drag-and-drop в админке). Сортировка: `sort_order`, затем `hall_number NULLS LAST`. |
| `showcases.showcase_number = NULL` | Группа «Не в витринах» (в путеводителе нарисована пустым квадратом). В зале такая группа одна (частичный уникальный индекс), выводится последней. |
| `exhibits.label_slug` | Класс распознавания. **Карточка без слага распознаванием не находится никогда.** |
| `exhibits.year_created` | **Строка** датировки, дословно как в путеводителе: «1899–1903», «1880-е», «конец XIX — начало XX века». До 17.08.2026 поле было INT. |
| `exhibits.master_name` | Источник правды для «Фирма К. Фаберже, мастер М. Перхин». `maker.firm`/`maker.master` в API — производный разбор, отдельных колонок нет и заводить их не нужно. |
| `exhibits.raw_history` | Внутренние факты для YandexGPT. В публичный API **не отдаётся**, только в `ExhibitAdmin`. |
| `exhibits.short_description_spoken` | Текст для озвучки (числа прописью). Генерируется LLM при правке `short_description` в админке. |

### Полнотекстовый поиск

`search_vector` — это `GENERATED ALWAYS … STORED` с конфигурацией `'russian'`:

- у зала: A = название, C = описание;
- у экспоната: A = название, B = мастер и номер, C = краткое описание, D = `raw_history`.

`material`, `techniques` и `year_created` в вектор **не входят** намеренно.
Запрос строится через `plainto_tsquery`, у которого `&` переписывается в `|`
(OR-семантика), и дополняется `ILIKE`. Сортировка — по `ts_rank`.

> [!WARNING]
> Выражение `search_vector` для экспонатов существует в **трёх копиях**:
> `CREATE` в `schema.sql`, `ALTER` в `schema.sql` и `_EXHIBIT_TSV` в `app/models.py`.
> Меняйте все три. `ADD COLUMN IF NOT EXISTS` не меняет уже существующую
> generated-колонку: нужен `ALTER … SET EXPRESSION` (PG 17) или DROP + ADD.

## Карта эндпоинтов

| Группа | Эндпоинты | Доступ |
|---|---|---|
| Система | `GET /health` | публично |
| Карта и навигация | `GET /map`, `/halls`, `/halls/{id}`, `/halls/{id}/showcases`, `/halls/{id}/exhibits`, `/showcases`, `/showcases/{id}`, `/showcases/{id}/exhibits` | публично |
| Экспонаты | `GET /exhibits`, `/exhibits/{id}`, `/exhibits/by-slug/{slug}`, `/exhibits/{id}/related` | публично |
| Поиск | `GET /search` | публично |
| Распознавание | `POST /recognition` (multipart) | публично |
| ИИ-гид | `POST /guide/story`, `POST /guide/chat` | публично |
| Озвучивание | `POST /speech` | публично |
| Телеметрия | `POST /telemetry/events` → 202 | публично |
| Админ · вход | `POST /admin/login` | публично |
| Админ · каталог | CRUD `/admin/halls` (+ `PUT /admin/halls/reorder`, `POST /admin/halls/{id}/cover`), `/admin/showcases`, `/admin/exhibits` (+ `POST …/spoken/regenerate`) | Bearer |
| Админ · медиа | `GET`/`POST /admin/exhibits/{id}/media`, `DELETE /admin/exhibits/{id}/media/{image_id}` | Bearer |
| Админ · подсказки | `GET /admin/guide/questions/status`, `POST /admin/guide/questions/warm` | Bearer |
| Админ · аналитика | `GET /admin/analytics/{overview,questions,unanswered,engagement,routes,exhibits,recognition,daily}`, `GET /admin/analytics/export`, `POST /admin/analytics/rebuild` | Bearer |

Общие соглашения:

- Пагинация — `limit` (по умолчанию 20, максимум 100) и `offset`. Списки
  отвечают `{items, total, limit, offset}`.
- Ошибки: `404` — нет сущности, `409` — нарушение уникальности (IntegrityError
  → rollback), `413`/`415` — загрузка, `502` — сбой внешнего сервиса, `503` —
  нет зависимости (например, шрифта для PDF или LLM для регенерации озвучки).
- `/health` реально проверяет **только PostgreSQL** (`SELECT 1`, при сбое отвечает
  503 `degraded`). Флаги `yandexgpt`/`speechkit`/`yolo`/`object_storage`
  показывают, **заданы ли ключи**, а не доступен ли сервис. `pdf_font` показывает,
  найден ли TTF.

## Подсистемы

### Каталог и навигация

`GET /halls/{id}/exhibits` отдаёт экспонаты зала, и у каждого есть `showcase_id` и
`showcase_number`. Группировку «витрина → экспонаты» фронт собирает из этого одного ответа.

Описание зала приходит сразу в двух видах:

- `description` — полный текст (в путеводителе это 1,8–4,1 тыс. знаков);
- `description_preview` — начало текста, обрезанное **по границе предложения** до
  `HALL_DESCRIPTION_PREVIEW_CHARS` (350), плюс флаг `description_has_more` для
  кнопки «Подробнее о зале».

Колонки под превью в БД нет: превью — способ показать `description`, а не
отдельный текст, который разъедется с описанием после первой правки
(баг-репорт 31.08.2026, п. I-3).

### Карточка экспоната

Музей просил карточку «понятную и **прогнозируемую**» (баг-репорт 31.08.2026, п. I-2):

- **Порядок и набор полей `Exhibit`/`ExhibitSummary` — контракт.** Pydantic переносит
  порядок объявления в JSON и OpenAPI, и он зафиксирован в `tests/test_exhibit_card.py`.
  В `openapi.yaml` в `required` перечислены **все** свойства: иначе генератор
  клиента делает поля опциональными. Пустое значение — `null`, а не пропавший ключ.
- `location` и `maker` присутствуют **всегда** в виде объектов, даже у экспоната без
  витрины и без мастера (тогда все поля внутри `null`).
- **Формулировка расположения одна на весь бэкенд** — `app/services/location.py`.
  Её печатают и карточка (`location.text`), и ответ гида (`location.text_in`).
  Своей склейки не пишите: тест сверяет обе фразы символ в символ.
- Легаси-дубли (`hall`, `showcase`, плоские `hall_id`/`showcase_id`) не удаляйте и
  не переименовывайте: ими пользуется фронт.
- `origin_place`, `techniques` и строковый `year_created` заполняются разбором
  каталожной строки путеводителя (см. [«Каталожная строка»](#каталожная-строка-путеводителя)).

Подробности — [`docs/task-2026-08-31-exhibit-card.md`](docs/task-2026-08-31-exhibit-card.md).

### Распознавание по фото

`POST /recognition` принимает multipart с полями `file`, `hall_id?`, `top_k=3`.

1. **Проверки.** Тип файла — только JPEG/PNG/WebP (иначе 415). Размер проверяется
   дважды: сначала по `file.size` до чтения, потом по `len(data)` (413 с
   фактическим размером в тексте). Пустой файл — 400.
2. **Внешний ML-сервис.** `POST {YOLO_ENDPOINT}` без авторизации, multipart
   `{file, limit}`, ответ `{"predictions":[{item_id,title_en,confidence}],"found"}`
   (Faberge Search API 1.0.0). `title_en` — slug страницы предмета на сайте
   музея, `item_id` — внутренний id сервиса, с нашими id не связан.
   `limit = max(top_k, 10)`: индекс ключуется по фото, и несколько ракурсов одного
   предмета нужно схлопнуть. Таймаут — `RECOGNITION_TIMEOUT_SEC` (25 с).
3. **Сшивка `title_en → label_slug`** (`recognizer.match_slug`). Slug музея и наш
   `label_slug` совпадают не всегда: у ключевых яиц префикс и подчёркивания
   (`faberge_paskhalnoye_yaytso_landyshi`), часть заведена другим транслитом
   (`pasxalnoe_yajczo` ↔ `paskhalnoe-yaytso`), длинные обрезаны до 100 знаков с
   хвостом-хэшем (`load_faberge.clamp_slug`). Поэтому сравнение идёт так:
   - сначала точно, в том числе после той же обрезки до 100 знаков;
   - затем по каноническому ключу (`normalize_slug`): регистр, `_`/`-`, префикс
     `faberge_`, варианты транслита (`kh/x`, `cz/tz/ts`, `j/y`, `-yi/-y`);
   - затем нечётко (`difflib`, порог `RECOGNITION_SLUG_MATCH_CUTOFF=0.9`), но
     только если совпадают первое слово (тип предмета) и числа: `blyudo-s-monogrammami-…`
     и `byuvar-s-monogrammami-…` — разные предметы, `chasy-2` и `chasy-3` тоже.

   Если сервис прислал `title` (контракт до 1.0.0), работает прежняя сшивка по
   названию (`recognizer.match_title`: NFKC, кавычки, ё→е, пробелы, casefold;
   нечётко — порог `RECOGNITION_NAME_MATCH_CUTOFF=0.86`). Несшитые предсказания
   пишутся в лог на уровне `WARNING` (с `title_en`, `title`, `item_id`), сырой
   ответ сервиса — на уровне `INFO`.
4. **Добор кандидатов.** Если не сшилось ничего и сервис прислал русские
   названия, они идут в полнотекстовый поиск, и фронт показывает «возможно,
   это» вместо ошибки. По контракту 1.0.0 названий нет — добора тоже нет.
5. **Ответ** `{recognized, label_slug, confidence, exhibit, candidates, request_id, processing_ms}`.
   `recognized = true`, только если уверенность ≥ `RECOGNITION_CONFIDENCE_THRESHOLD`
   (0.6) **и** экспонат нашёлся в БД.
   `candidates` заполнены всегда, и **первый элемент — сам распознанный
   экспонат**: фронт должен его пропустить.

Две ловушки сшивки:

- **Карточка без `label_slug` распознаванием не возвращается вообще.** Значит, доля
  карточек со слагом — верхняя граница покрытия.
- **Имена в каталоге не уникальны** (например, 12 «Портсигаров»). Для сшивки по
  `title` (старый контракт) побеждает наименьший id, так что вторая одноимённая
  карточка так не распознаётся никогда. Сшивку по `title_en` это не касается:
  slug уникален.

Оба эффекта меряет читающий скрипт, админ-токен ему не нужен:

```bash
BASE_URL=… python scripts/recognition_coverage.py --save recognition_<дата>.json
BASE_URL=… python scripts/recognition_coverage.py --hall-id 4    # кого не хватает поимённо
BASE_URL=… python scripts/recognition_coverage.py --collisions   # одноимённые карточки
python scripts/recognition_coverage.py --from-seed db/seed_fabergemuseum.sql  # без сети
```

Фактическую успешность модели показывает `GET /admin/analytics/recognition`, а не
этот скрипт. Сервер повторных попыток не делает: сбой ML-сервиса сразу даёт 502.
Разбор: [`docs/task-2026-08-31-recognition-coverage.md`](docs/task-2026-08-31-recognition-coverage.md).

### ИИ-гид: рассказ (`POST /guide/story`)

1. **Экспонат.** Ищется по `exhibit_id` или `label_slug`: 400, если не передано
   ни одно, 404, если не найден.
2. **Память сессии.** Если передан `session_id`, подгружаются уже заданные и
   «отказные» вопросы, чтобы подсказки под рассказом не противоречили диалогу.
3. **Промпт** (`llm._yandexgpt_story`) собирается так:
   - текст — `raw_history`, а если его нет, то `short_description`. Ссылки
     «Источник: URL» вырезаются: в промпт они не идут;
   - датировка и техники добавляются, только если заполнены;
   - объём задаётся **промптом**: `GUIDE_STORY_MAX_CHARS` (900 знаков),
     4–6 предложений (для `short` — 2–3). `maxTokens` — только страховка.
     Обрезка по токенам рвала бы фразу;
   - промпт заканчивается фразой «Чего не знаешь — не пиши».
4. **YandexGPT** — `foundationModels/v1/completion`, авторизация `Api-Key`.
   После ответа `guide_style.strip_filler` вырезает обороты-«воду» (до TTS,
   так что озвучка тоже чистая).
5. **Подсказки** (`max_questions`, по умолчанию 4) берутся из кэша, см. [ниже](#вопросы-подсказки).
6. **Озвучка.** При `include_audio=true` сразу синтезируется аудио.

Параметры вызовов LLM:

| operation | модель | temperature | maxTokens |
|---|---|---|---|
| `story` | основная | 0.6 | `GUIDE_STORY_MAX_TOKENS` (500) |
| `chat` | основная | 0.6 | 800 |
| `questions` | основная | 0.7 | 200 |
| `tts_spoken` | **lite** | 0.0 | 2000 |

URI основной модели — `YANDEXGPT_MODEL_URI`, а при его отсутствии
`gpt://{folder}/yandexgpt/latest`. Lite-модель берётся из
`YANDEXGPT_LITE_MODEL_URI` либо выводится из основной заменой `yandexgpt` →
`yandexgpt-lite`.

### ИИ-гид: диалог (`POST /guide/chat`)

Сессия хранится в `guide_sessions`, реплики — в `guide_messages`.

**Контекст.** Бэкенд различает «контекст не передавали» и «сбросьте контекст».
Без этого различия зал «залипал» в сессии, и общий вопрос получал отказ.

| Что прислал клиент | Что делает бэкенд |
|---|---|
| поля `context` нет | подставляет контекст, сохранённый в сессии |
| `"context": {}` или `null` | сбрасывает контекст, вопрос считается общим |
| `"reset_context": true` | то же, без передачи `context` |
| заполненный `context` | заменяет контекст сессии **целиком** (старый `hall_id` не «доклеивается») |

Сброс при наличии экспоната пишется в лог строкой `guide_context_reset`. Клиент,
который шлёт `"context": null` на каждой реплике, теряет предмет на каждом ходу:
это частая причина жалобы «подсказки пропали».

**Справка для модели.** Для экспоната это `short_description + raw_history`,
для зала — его описание. Справка обрезается по границе фразы до
`GUIDE_GROUNDING_MAX_CHARS` (700). История — последние `GUIDE_HISTORY_TURNS`
(3) **строк** сообщений: это не пары вопрос–ответ.

**Ветки обработки** (проверяются по порядку):

```mermaid
flowchart TD
    q["Реплика посетителя"] --> n{"Только номер?<br/>«12», «№ 12а»"}
    n -->|"1 совпадение"| one["Детерминированное описание<br/>+ переключение контекста"]
    n -->|"несколько"| many["«Уточните зал или витрину»<br/>подсказки = варианты расположения"]
    n -->|"0 или не номер"| h{"«Какие есть залы?»"}
    h -->|"да"| halls["Список залов без LLM"]
    h -->|"нет"| b{"Запрещённая тема?<br/>guide_style"}
    b -->|"да"| blk["GUIDE_BLOCKED_ANSWER без LLM<br/>fail_reason = blocked_topic"]
    b -->|"нет"| llm["YandexGPT"]
    llm --> ref["Детектор отказа или оговорки<br/>guide_intel"]
    ref --> save["Запись реплик: answered + fail_reason"]
```

- Номер, который не нашёлся, уходит в обычный чат: «1885» может быть годом.
- В ветке с неуникальным номером `suggested_questions` содержит **варианты
  расположения** («В зале 4 «Синяя гостиная», витрина 5»), а не вопросы. Это
  контракт B9.
- При сбое LLM реплика сохраняется с `fail_reason="error"`, и **после** этого
  клиент получает 502.

**Разметка ответа** (`answered`, `fail_reason` — для аналитики и памяти отказов):

| `fail_reason` | Когда | Прячет вопрос из подсказок? |
|---|---|---|
| `null` | ответил | — |
| `llm_refusal` | «жёсткий» отказ: ни одна клауза ответа не несёт содержания (`guide_intel.is_hard_refusal`) | да |
| `no_context` | жёсткий отказ при пустой справке | да |
| `llm_hedge` | ответ по существу с оговоркой «точно не знаю» | **нет** |
| `not_found` | навигационный вопрос, а цели нет | нет |
| `blocked_topic` | запрещённая тема, модель не вызывалась | нет |
| `error` | сбой LLM | нет |

Детекторы нарочно асимметричны: ложный «отказ» прячет вопрос от всех посетителей
на 90 дней, поэтому он должен случаться реже, чем ложный «ответил». В регулярках
длинные комментарии с проверенными контрпримерами — прочитайте их до правки.

**Промпт диалога запрещает выдумку по действию, а не по источнику.** Гиду
нельзя приписывать мастерам заслуги и качества, которых нет ни в справке, ни в
твёрдых знаниях (баг-репорт 31.08.2026, п. II-6). Но формулировка «отвечай только
по справке» запрещена: она вернула бы массовые отказы 28.07.2026. Это стережёт
`tests/test_guide_style.py`.

**«Упомянуто в ответе»** (`referenced_exhibits`):

- Кандидаты — полнотекстовый поиск по вопросу и ответу
  (`GUIDE_REFERENCED_CANDIDATES`, 20).
- В блок попадают только предметы, чьё название или номер («№12») **реально
  встречаются** в ответе (а если ответ никого не назвал — в вопросе). Проверка —
  `guide_mentions.py`: ядро названия, стемы, явный номер.
- Неоднозначные совпадения отбрасываются (162 карточки называются просто «Портсигар»).
- Экспонат из контекста стоит в блоке всегда и первым (`mentioned_in="context"`).
  Максимум — 4 плашки.
- Пустой массив — законное состояние, а не ошибка. `null` не бывает.

Откат к старому поведению — `GUIDE_REFERENCED_REQUIRE_MENTION=false`. Разбор:
[`docs/task-2026-08-31-referenced-exhibits.md`](docs/task-2026-08-31-referenced-exhibits.md).

**История чатов** пишется на сервер, но ручки чтения нет: переписку хранит фронт.
Решение и готовый контракт на будущее — [`docs/chat-history-decision.md`](docs/chat-history-decision.md).

### Вопросы-подсказки

Подсказки («Кому подарили это яйцо?») зависят **только от карточки**. Поэтому
они кэшируются в `exhibit_questions` с ключом `(exhibit_id, language)`:

- **Свежесть** определяется по `source_hash` = sha256(язык + `llm.questions_source(ex)`),
  а не по времени. Музей поправил описание — хэш разошёлся — запись
  перегенерируется при следующем обращении. TTL нет намеренно.
- **В таблице лежит сырой пул** (`GUIDE_QUESTIONS_CACHE_SIZE`, 8 вопросов).
  Фильтры, исключения и срез под `max_questions` применяются **при чтении**, так
  что смена фильтра не требует платной перегенерации.
- **Если LLM недоступен**, а запись есть, отдаётся прошлый набор, а не 502.

Как из пула получается блок (`guide_questions.select_questions`). Берётся первый
непустой уровень:

1. пул минус **уже заданные** в этой сессии у этого предмета (включая текущую
   реплику) и минус **отказные**;
2. детерминированные фолбэки по заполненным полям карточки минус те же исключения;
3. пул + фолбэки минус только отказные;
4. общие вопросы о музее.

**Отказные** — это отказы сессии плюс **глобальная память отказов**: вопрос,
на который гид отказал ≥ `GUIDE_REFUSAL_MEMORY_MIN_COUNT` (2) раз за
`GUIDE_REFUSAL_MEMORY_DAYS` (90) дней по этому предмету, прячется у всех. Отдельного
хранилища под память нет: она читается из `guide_messages`.

**Блок при `max_questions > 0` не бывает пустым.** Ветки без экспоната (поиск по
номеру, список залов, контекст только зала, общий чат, сбой генерации)
заполняются детерминированными наборами, которые не стоят ни токена.

Заданные вопросы сравниваются **по смыслу**, а не по буквам (`question_cluster.py`).

Прогрев всего каталога:

```bash
python scripts/warm_guide_questions.py            # сухой прогон: сколько карточек требует генерации
python scripts/warm_guide_questions.py --apply    # один вызов LLM на карточку; свежие пропускаются
```

Порциями без шелла — `POST /admin/guide/questions/warm?limit=25`, покрытие —
`GET /admin/guide/questions/status`.

> [!CAUTION]
> - Правка **промпта** вопросов кэш не инвалидирует: нужен `--force`
>   (~1250 вызовов LLM).
> - Без ключей Yandex прогрев запишет в кэш **стаб-вопросы**, и они будут
>   считаться свежими, пока их не перегенерировать с `--force`.

Подробно — [`docs/task-2026-08-26-questions-cache.md`](docs/task-2026-08-26-questions-cache.md),
[`docs/task-2026-08-31-guide-suggestions.md`](docs/task-2026-08-31-guide-suggestions.md).

### Фильтры стиля (`guide_style`)

Это чистый модуль на регулярках и лексиконах (lowercase, ё→е). Флаги передаёт
вызывающий код, так что любой фильтр откатывается переменной окружения без релиза.

| Фильтр | Что делает | Флаг |
|---|---|---|
| `is_meaningless_question` | Снимает запрещённые музеем темы: «почему выбрали этот материал» (разрешено, если карточка сама объясняет выбор), «сколько времени заняло создание», «уникальные особенности этой работы», бытовое назначение предмета | `GUIDE_QUESTIONS_FILTER` |
| `is_unsupported_question` | Снимает подсказку с именем, 4-значным годом, «единственный» или домыслом («мог», «вероятно»), которых нет в карточке | `GUIDE_QUESTIONS_GROUNDED` |
| `dedupe_questions` | Убирает перефразировки одного вопроса: сравнивает леммы, числа и теги действий (заказ ≠ подарок) | `GUIDE_QUESTIONS_DEDUPE` |
| `is_blocked_visitor_question` | Вопрос, который **посетитель ввёл сам**, на запрещённую тему не уходит в модель, ответ — `GUIDE_BLOCKED_ANSWER` | `GUIDE_BLOCK_BANNED_QUESTIONS` |
| `strip_filler` | Вырезает из рассказа предложения-«воду». Предложения с цифрами не трогает. Если после чистки осталось слишком мало текста, возвращает оригинал | `GUIDE_STORY_FILLER_FILTER` |

Все фильтры подсказок проходят через единую воронку `clean_questions`: пустые →
бессмысленные → неподтверждённые → дубли и исключения → срез (**последним**).

### Озвучивание

`POST /speech` принимает `text` или `exhibit_id`. Для экспоната текст берётся из
`short_description_spoken`, затем `short_description`, затем `name`.

- **Числа прописью.** В синтез уходит «Пётр Первый», «в девятнадцатом веке».
  Переписывает `llm.to_spoken_text` (lite-модель, `temperature=0`), и только если в
  тексте есть числа. Результат кэшируется в процессе. Фолбэк без LLM —
  детерминированный `text_normalize.normalize_for_tts`. Отключается через
  `TTS_SPOKEN_VIA_LLM=false`.
- **SpeechKit.** По умолчанию используется **API v3** (`/tts/v3/utteranceSynthesis`),
  он тарифицируется по запросам. v1 (тарификация по символам) — аварийный откат:
  `SPEECHKIT_API_VERSION=v1`. Голос по умолчанию — `alena`, роль `good` с цепочкой
  фолбэков `friendly` → `neutral`, формат `mp3`.
- **Предел v3 — 250 знаков и 24 секунды на запрос.** Замер 02.09.2026: 249 знаков
  синтезируются, 250 — отказ. Рассказ гида (300–600 знаков) поэтому режется
  `tts.split_for_v3` по предложениям (длинное предложение — по словам), куски
  синтезируются по очереди и склеиваются. На замедленной речи предел по знакам
  ужимается пропорционально. Настройка — `SPEECHKIT_V3_MAX_CHARS`.
- **Файл** — `tts/{voice}_{sha256(voice:role:speed:fmt:text)[:16]}.{fmt}` в Object
  Storage или `media/tts/`. В реальном режиме синтез идёт на каждый запрос (файл
  перезаписывается). Проверку «уже есть» делает только стаб.

### Хранилище медиа

`services/storage.py` — это boto3 S3-клиент к Object Storage (один на «тёплый»
экземпляр). Публичный доступ на чтение выдан на уровне бакета, а не объекта.
Публичный URL — `OBJECT_STORAGE_PUBLIC_BASE` (CDN) или `{endpoint}/{bucket}/{key}`.

Удаление best-effort и трогает **только «свои» URL** (наш бакет или локальный
`media/`): внешние ссылки молча пропускаются.

Картинки лежат по ключу `{prefix}/{uuid}/{filename}`. `thumbnail_url` совпадает с
`image_url`: отдельные миниатюры не генерируются.

#### Лимит загрузки: 2,5 МБ, а не 10

`MAX_UPLOAD_MB` по умолчанию **2.5**. Yandex API Gateway рубит запрос на 3 670 016 Б
и отвечает **без CORS-заголовков**, поэтому в браузере это «Failed to fetch», а не 413.
Наш лимит обязан быть ниже, чтобы 413 с CORS и внятным текстом отдал FastAPI.

| Стена | Сколько | Почему считаем по ней |
|---|---|---|
| API Gateway, весь запрос | 3 670 016 Б | `413 request entity is larger than limits` |
| Тело в Cloud Function | × 3/4 | тело уезжает в функцию как base64 (+33 %) |
| Запас на multipart | − 65 536 Б | boundary, имя файла, поля |

Итого 3 670 016 × 3/4 − 65 536 = 2 686 976 Б ≈ 2,5 МБ. Расчёт живёт в
`app/config.py` (`platform_max_upload_bytes`, `max_upload_bytes`, `max_upload_label`).
Значение `MAX_UPLOAD_MB` выше платформенного приложение **зажимает** и пишет
`WARNING`, но не падает. Поднять потолок можно только в конфигурации API Gateway,
кодом нельзя.

### Админка

- **Аутентификация.** `POST /admin/login` сверяет логин и пароль с
  `ADMIN_USERNAME`/`ADMIN_PASSWORD` и возвращает **статический общий токен**
  `ADMIN_API_TOKEN`. JWT, подписи и срока жизни нет. `require_admin` сравнивает
  строку из `Authorization: Bearer …`. Для прода все три значения обязательно
  переопределяются (умолчания — `admin`/`admin`/`dev-admin-token`).
- **Новые админские ручки** вешайте на `admin.router`: авторизация там уже
  подключена. `auth_router` нужен только для входа.
- **`PUT`/`PATCH /admin/exhibits/{id}` сливают тело с карточкой.** Непереданное
  поле не меняется, очищается поле только явным `null`
  (`model_dump(exclude_unset=True)`). Прежнее поведение «PUT затирает всё» стоило
  музею фото и описаний (п. IV-1 от 31.08.2026). Оно доступно только через
  `?full_replace=true`. Каждое очищение пишется в лог (`_warn_on_wipe`).
  [Разбор](docs/task-2026-08-31-admin-put-data-loss.md).
- **`image_url` зеркалит основное фото галереи** (`exhibit_images.is_primary`).
  Если оно пустое и не передано, восстанавливается из единственной основной картинки.
- **Правка `short_description`** без `short_description_spoken` запускает
  генерацию текста для озвучки через LLM.
- **Ограничения PATCH.** `HallPatch` не принимает `null` для `is_temporary`,
  `is_service` и `sort_order`, `ShowcasePatch` — для `hall_id` (422).
- **Каскадное удаление.** Зал и витрина с содержимым удаляются только с
  `?force=true`. Вместе с каскадом удаляются и файлы из хранилища.

> [!NOTE]
> Загрузка медиа с `is_primary=true` **не снимает** флаг с прежних основных фото.
> У карточки может оказаться несколько «основных», и тогда восстановление
> `image_url` откажется угадывать.

### Телеметрия и аналитика

**Приём событий** — `POST /telemetry/events`, батч из 1–50 событий, ответ `202
{accepted, rejected}`.

- Словарь типов закрытый (`schemas.EventType`): `app_open`, `hall_view`,
  `showcase_view`, `exhibit_view`, `recognition`, `chat_open`, `chat_message`,
  `tts_play`, `search_query`, `session_end`.
- Неизвестный тип не роняет батч: он отбрасывается поштучно и попадает в
  `rejected`. `audio_play` переименовывается в `tts_play`.
- `props` принимаются по **белому списку** ключей для каждого типа
  (`EVENT_PROPS_ALLOWED`). `text` обрезается до 500 знаков.
- IP и User-Agent не читаются и не логируются
  ([приватность](docs/analytics-privacy.md)). События по требованию заказчика
  **не удаляются никогда**.

**Отчёты** (`/admin/analytics/*`, построители в `crud.py`):

| Отчёт | Что показывает |
|---|---|
| `overview` | Сводка по плиткам дашборда |
| `questions` | Вопросы посетителей, сгруппированные **по смыслу** (`question_cluster.py`): частые и редкие (≤ `ANALYTICS_RARE_MAX_COUNT`) |
| `unanswered` | Вопросы без ответа по `fail_reason` |
| `engagement` | Длительность визита, конверсии, глубина ([формулировки метрик](docs/analytics-metrics.md)) |
| `routes` | Маршруты по залам, выходы, повторные визиты по `device_id` |
| `exhibits` | Просмотры и вопросы по экспонатам |
| `recognition` | Успешность распознавания, фолбэк на top-3, повтор или уход после неудачи |
| `daily` | Плоский суточный ряд из `analytics_daily` |

Соглашения отчётов:

- Период `from`/`to` включает **обе** границы.
- **Визит** — поток событий сессии, разрезанный по паузе дольше
  `SESSION_TIMEOUT_MINUTES` (30 мин).
- **База конверсий** отдаётся явно (`conversion_basis`: `app_open` или
  `all_visits`, плюс `conversion_denominator`). Числитель считается внутри базы,
  поэтому доля не превышает 100 %.

**Кэш.** Готовый отчёт хранится в `analytics_reports` под ключом `(report,
"<from>:<to>[:variant]")` с TTL `ANALYTICS_CACHE_TTL_MINUTES` (сутки); в ответе
есть `updated_at`. Пересчёт (`crud.rebuild_analytics`) — это суточный срез плюс
все отчёты. Запустить его можно тремя способами:

```bash
python scripts/rebuild_analytics.py --days 2             # напрямую в БД
curl -X POST -H "Authorization: Bearer $TOKEN" "$BASE_URL/admin/analytics/rebuild"
# и ночью — отдельная функция scripts/analytics_cron/index.py (таймер, cron 0 4 * * *)
```

Cron-функция намеренно вызывает rebuild **без** `from`/`to`: дашборд читает ключ
открытого периода `:`, а пересчёт с окном его не обновил бы. Подробности — в
docstring `scripts/analytics_cron/index.py`.

Старые диалоги (до 03.08.2026) размечает `python scripts/backfill_unanswered.py --apply`.

**Выгрузка** — `GET /admin/analytics/export?report=<имя>|all&format=xlsx|pdf`.

- `report=all` отдаёт все отчёты одним файлом: лист на отчёт в xlsx, раздел на
  отчёт в PDF. Упавший раздел остаётся с пометкой «Нет данных», а одиночный
  отчёт при ошибке честно отдаёт 500.
- Для PDF нужен **TTF с кириллицей**. Порядок поиска: `ANALYTICS_PDF_FONT_PATH`,
  затем `assets/fonts/DejaVuSans.ttf` (в том числе `/function/code/...`), затем
  системные пути. Битый файл и OTF/CFF отвергаются. Без шрифта — **503** с
  инструкцией. Наличие шрифта видно заранее в `/health` → `dependencies.pdf_font`.
- Шрифт **лежит в git намеренно**: в рантайме функции нет ни apt, ни системных
  шрифтов. Восстановить или обновить его можно через
  `python scripts/fetch_pdf_font.py [--force]`.

## Конфигурация

Все настройки — `app/config.py` (pydantic-settings). Имя переменной окружения —
это имя поля в верхнем регистре. Значения читаются из окружения и `.env` **один
раз при импорте** (`Settings` кэшируется), поэтому `index.py` выставляет свои
умолчания **до** `from app.main import app`.

| Область | Переменные (умолчание) |
|---|---|
| БД | `DATABASE_URL` (локальная faberge), `DB_SSL_ROOT_CERT` (None), `SQL_ECHO` (false) |
| Приложение | `PUBLIC_BASE_URL` (`http://localhost:8000`), `CORS_ORIGINS` (`*`, через запятую), `MEDIA_DIR` (`media`), `LOG_LEVEL` (`INFO` — **нужен** для строк расхода) |
| Админ | `ADMIN_API_TOKEN` (`dev-admin-token`), `ADMIN_USERNAME`/`ADMIN_PASSWORD` (`admin`/`admin`) |
| Загрузка | `MAX_UPLOAD_MB` (2.5), `GATEWAY_MAX_REQUEST_BYTES` (3670016), `UPLOAD_REQUEST_OVERHEAD_BYTES` (65536) |
| Залы | `HALL_DESCRIPTION_PREVIEW_CHARS` (350; ≤0 отключает превью) |
| Yandex | `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`, `YANDEXGPT_MODEL_URI`, `YANDEXGPT_LITE_MODEL_URI`, `SPEECHKIT_API_KEY`, `YOLO_ENDPOINT` |
| Object Storage | `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ENDPOINT` (`https://storage.yandexcloud.net`), `OBJECT_STORAGE_PUBLIC_BASE`; ключи — `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` (читаются напрямую из `os.environ`) |
| Распознавание | `RECOGNITION_CONFIDENCE_THRESHOLD` (0.6), `RECOGNITION_TIMEOUT_SEC` (25), `RECOGNITION_SLUG_MATCH_CUTOFF` (0.9), `RECOGNITION_NAME_MATCH_CUTOFF` (0.86, только для старого контракта с `title`); 0 отключает нечёткое сравнение; `RECOGNITION_SEARCH_LIMIT` (10) |
| TTS | `SPEECHKIT_API_VERSION` (`v3`), `SPEECHKIT_V3_MAX_CHARS` (249), `TTS_SPOKEN_VIA_LLM` (true) |
| Гид: расход | `GUIDE_HISTORY_TURNS` (3), `GUIDE_GROUNDING_MAX_CHARS` (700), `GUIDE_STORY_MAX_CHARS` (900), `GUIDE_STORY_MAX_TOKENS` (500), `LLM_LOG_USAGE` (true) |
| Гид: подсказки | `GUIDE_QUESTIONS_CACHE_ENABLED` (true), `GUIDE_QUESTIONS_CACHE_SIZE` (8), `GUIDE_QUESTIONS_FILTER`, `GUIDE_QUESTIONS_GROUNDED`, `GUIDE_QUESTIONS_DEDUPE` (все true) |
| Гид: память отказов | `GUIDE_REFUSAL_MEMORY_ENABLED` (true), `GUIDE_REFUSAL_MEMORY_MIN_COUNT` (2), `GUIDE_REFUSAL_MEMORY_DAYS` (90) |
| Гид: прочее | `GUIDE_STORY_FILLER_FILTER` (true), `GUIDE_BLOCK_BANNED_QUESTIONS` (true), `GUIDE_BLOCKED_ANSWER` (текст заглушки), `GUIDE_REFERENCED_REQUIRE_MENTION` (true), `GUIDE_REFERENCED_CANDIDATES` (20) |
| Аналитика | `SESSION_TIMEOUT_MINUTES` (30), `ANALYTICS_CACHE_TTL_MINUTES` (1440), `ANALYTICS_RARE_MAX_COUNT` (2), `ANALYTICS_PDF_FONT_PATH` |
| Cron-функция | `ANALYTICS_API_BASE`, `ADMIN_API_TOKEN` |

Почти каждый булев флаг `GUIDE_*` — это **рубильник отката без релиза**: если
новое поведение гида повело себя плохо на проде, переменная функции возвращает
прежнее.

### Расход LLM и SpeechKit

Каждый вызов оставляет в логе функции строку уровня `INFO`:

```
llm_usage operation=chat model=gpt://<folder>/yandexgpt/latest model_version=… input_tokens=412 output_tokens=180 total_tokens=592
tts_request api=v3 voice=alena role=good fmt=mp3 chars=284 duration_ms=19040 bytes=76032
```

`operation` принимает значения `story` | `chat` | `questions` | `tts_spoken`.

- У прогретого каталога ход диалога — **один** вызов LLM.
- Строка `questions` означает новую или отредактированную карточку (промах кэша).
- Логгер httpx понижен до `WARNING`, чтобы не дублировать эти строки.

Что уже урезано и чем откатывается — [`docs/task-2026-08-19-llm-cost.md`](docs/task-2026-08-19-llm-cost.md).

#### Замер: сколько стоит один посетитель

`scripts/measure_llm_usage.py` прогоняет сценарий посетителя целиком — рассказ
(`/guide/story`) + уточняющие вопросы (`/guide/chat`) + озвучка (`/speech`) — по
выборке карточек и печатает медианы input/output токенов по каждой операции,
медиану символов синтеза и медиану «на одного посетителя».

```bash
python scripts/measure_llm_usage.py                 # сухой прогон: выборка и план, в облако не ходим
python scripts/measure_llm_usage.py --apply --count 12 --turns 2 --csv usage.csv
# без БД и ключей на машине: прогон по стенду, токены — из Cloud Logging
python scripts/measure_llm_usage.py --source remote --apply \
    --base-url https://<gateway>.apigw.yandexcloud.net --log-group default
yc logging read --group-name default --since 24h | \
    python scripts/measure_llm_usage.py --source log -    # те же медианы по живому трафику
```

Три источника чисел: `live` — прогон в этом процессе через ASGI (нужны
`DATABASE_URL` и ключи, привязка вызова к экспонату точная); `remote` — прогон
по HTTP против развёрнутого стенда, строки расхода забираются после прогона
через `yc logging read` и привязываются к шагу по времени; `log` — готовая
выгрузка логов, медианы по живому трафику без прогона. Без `--apply` прогон не
тратит ни токена. Ноль вызовов `questions` в сводке означает прогретый кэш, а не
пропущенный замер. В режиме `remote` держите `--retries`: шлюз отдаёт 502 на
холодном инстансе. Арифметика закреплена тестом `tests/test_llm_usage_probe.py`.

## Деплой и эксплуатация

### Прод: Yandex Cloud Function

- **Функция** `faberge-api`, таймаут 30 с, точка входа `index.handler`.
- **Архив** собирается из дерева репозитория. В нём должны быть `index.py`,
  `app/`, корневой `requirements.txt` (Yandex делает `pip install` по файлу в
  корне архива), `CA.pem` и `assets/fonts/`. Артефакт `faberge-fn.zip` в `.gitignore`.
- **Порядок релиза**, если есть миграция:
  1. миграции применяются **до** деплоя нового кода, если в шапке миграции не
     сказано иное (например, `2026-08-17_year_created_text.sql` требует
     обратного порядка);
  2. затем деплой;
  3. затем проверки:

  ```bash
  curl -s "$BASE_URL/health"                                   # status=ok, dependencies.*
  curl -s "$BASE_URL/health" | grep -o '"pdf_font":"[a-z]*"'   # ожидаем "up"
  BASE_URL=$BASE_URL python scripts/smoke_bugreport_20260831.py  # приёмочный smoke (только чтение)
  ```
- **Поиск запроса в логах.** Клиенту достаточно приложить заголовок `x-request-id`
  из ответа: по нему вызов находится в логах функции.

> [!IMPORTANT]
> **Чего в репозитории нет** (и что стоит завести при случае): скрипта сборки и
> деплоя zip, спецификации API Gateway (лимит 3.5 МиБ и CORS на его собственных
> ответах лечатся только там), инструкции по созданию функции `analytics_cron` и
> её таймер-триггера. Адрес прод-API есть в `yaak/` (окружение «Global Variables»).

### Локальный стенд: Docker

`Dockerfile` (python 3.12-slim + `fonts-dejavu-core` + `uvicorn`) и
`docker-compose.yml` (PG 17 + API). См. [«Быстрый старт»](#быстрый-старт).

## База данных: схема, миграции, сиды

- **`db/schema.sql`** — полный идемпотентный DDL, источник правды. `app/models.py`
  его зеркалит, но частичные и триграммные индексы объявлены **только** в SQL.
- **`scripts/init_db.py [--seed]`** применяет `schema.sql` (и `seed.sql`).
  Миграции данных он **не** выполняет.
- **Сиды**:
  - `db/seed.sql` — синтетический демо-набор: 6 залов, 14 экспонатов, id совпадают
    с примерами в `openapi.yaml`, `ON CONFLICT DO NOTHING`;
  - `db/seed_fabergemuseum.sql` — реальные данные с сайта музея. Начинается с
    `TRUNCATE … CASCADE` всего каталога (а каскад задевает и `exhibit_questions`).

  **Не применяйте оба:** id и номера залов пересекаются. На проде не применяйте ни один.

### Миграции

`db/migrations/*.sql` — инкрементальные и идемпотентные. У каждой есть шапка
(проблема, что делает, как применять), блок `BEGIN…COMMIT` и закомментированная
секция отката. Структурные изменения продублированы в `schema.sql`, так что
чистой БД миграции не нужны.

**Миграции данных** (правка живого каталога) повторяются только через `psql`.
Они ищут залы по паре «номер + название», а не по id (id в окружениях разные), и
включают флаг в `WHERE`, чтобы повторный прогон обновил 0 строк.

```bash
psql "$DATABASE_URL" -f db/migrations/<файл>.sql
```

| Файл | Что делает |
|---|---|
| `2026-07-14_add_hall_is_temporary` | `halls.is_temporary` |
| `2026-07-15_analytics_reorder_tts` | `halls.sort_order`, `exhibits.short_description_spoken`, индекс событий |
| `2026-07-22_backend_tracker` | `exhibit_number`, `video_url`, `search_vector` + GIN-индексы |
| `2026-07-29_bugreport_catalog` | nullable `hall_number`/`showcase_number`, `is_service`, частичный уникальный индекс |
| `2026-08-03_analytics` | поля событий, `answered`/`fail_reason` у реплик, `analytics_daily`/`analytics_reports` |
| `2026-08-06_bugreport_iter2` | **данные:** снять `is_temporary` с «Выставочного зала». Аналог через API: `PATCH /admin/halls/{id} {"is_temporary": false}` |
| `2026-08-12_exhibit_dating_techniques` | `dating`, `techniques` (бэкфилл — `backfill_catalog_fields.py`) |
| `2026-08-17_year_created_text` | `year_created` INT → TEXT из `dating`, `dating` удаляется. **Порядок релиза — в шапке** |
| `2026-08-26_exhibit_questions_cache` | таблица `exhibit_questions`; затем прогрев `warm_guide_questions.py --apply` |
| `2026-08-31_exhibit_origin_place` | `exhibits.origin_place` (бэкфилл — `backfill_exhibit_origin_place.py`) |
| `2026-08-31_guide_fail_reason_hedge` | `llm_hedge` в CHECK `fail_reason` |
| `2026-08-31_guide_refusal_memory` | индекс под глобальную память отказов |
| `2026-08-31_staircase_public` | **данные:** «Парадная лестница» (зал №1) — публичный зал, первым по порядку |
| `2026-09-16_guide_fail_reason_blocked` | `blocked_topic` в CHECK `fail_reason` |

> [!WARNING]
> **Парадная лестница: сначала текст зала, потом флаг.** Иначе экспозиция
> откроется архитектурной справкой про перила. Скрипт `publish_staircase_hall.py`
> сам откажется снимать флаг раньше времени:
> ```bash
> BASE_URL=… ADMIN_TOKEN=… python scripts/apply_hall_descriptions.py --only "Парадная лестница" --apply
> psql "$DATABASE_URL" -f db/migrations/2026-08-31_staircase_public.sql
> # либо без psql: BASE_URL=… ADMIN_TOKEN=… python scripts/publish_staircase_hall.py --apply
> ```

При добавлении значения в `fail_reason` меняйте CHECK миграцией (drop-if-exists +
add), а также `schema.sql` и кортеж `_REFUSAL_REASONS` в `routers/guide.py`, если
новое значение должно прятать вопрос.

### Каталожная строка путеводителя

`app/services/catalog_line.py` разбирает строку вида

```
Санкт-Петербург, 1899–1903. Фирма К. Фаберже, мастер В. Аарне.
Золото, серебро, рубины, дерево; выпиловка, чеканка, гравировка, эмаль
```

на `origin_place` / `year_created` / `master_name` / `material` / `techniques`.
Здесь же `split_maker` делит мастера на фирму и мастера для карточки.

- **Материалы от техник отделяет позиция относительно `;`, а не словарь.**
  «Эмаль» в путеводителе бывает и материалом, и техникой, и словарь тут бессилен.
- **Разбор консервативен.** Неразобранная строка даёт `status='skipped'` и не
  трогает карточку. Связная проза отсеивается `looks_like_catalog_line`. На
  слепке прода разбирается 97,4 % карточек.
- **Бэкфилл-скрипты только дозаполняют пустые поля** и никогда не
  перезаписывают правку человека. Расхождения печатаются отдельной секцией отчёта.

## Скрипты

Скрипты ходят в систему одним из двух способов:

- **через админ-API** — `BASE_URL` + `ADMIN_TOKEN` (fallback — `ADMIN_API_TOKEN`).
  Исключение: `restore_descriptions.py` использует `--base`/`--token` или
  `FABERGE_API_BASE`/`FABERGE_ADMIN_TOKEN`;
- **напрямую в БД** — `DATABASE_URL`.

**Соглашение для скриптов, которые пишут:**

- по умолчанию **сухой прогон** с планом;
- `--apply` пишет изменения и сохраняет файл отката `<имя>_rollback_<ts>.json`;
- `--rollback <файл> --apply` откатывает. Откат идемпотентен и пропускает записи,
  которые с тех пор правили руками.

| Скрипт | Назначение | Доступ | Характер |
|---|---|---|---|
| `init_db.py` | схема (+ `--seed`) | БД | настройка |
| `rebuild_analytics.py` | пересчёт аналитики (`--days N`, `--from/--to`) | БД | **регулярный** (cron) |
| `analytics_cron/index.py` | отдельная Cloud Function под таймер: `POST /admin/analytics/rebuild` | API | **регулярный** |
| `warm_guide_questions.py` | прогрев кэша подсказок (`--apply`, `--force`, `--ids`, `--limit`) | БД + LLM | по необходимости |
| `recognition_coverage.py` | покрытие каталога классами распознавания, коллизии имён | API, только чтение | диагностика |
| `measure_llm_usage.py` | замер расхода: медианы токенов и символов синтеза на посетителя | БД + LLM / API / логи | диагностика, платный с `--apply` |
| `fetch_pdf_font.py` | DejaVuSans для PDF | сеть | по необходимости |
| `backfill_unanswered.py` | разметка `answered` у старых диалогов | БД | разовый |
| `apply_hall_descriptions.py` | тексты залов из `db/hall_descriptions.json` | API | разовый, повторяемый |
| `publish_staircase_hall.py` | «Парадная лестница» — публичный зал №1 | API | разовый |
| `cleanup_hall_catalog.py` | № 99 без номера, № 100 удалить (`--hide-staircase` — старое поведение) | БД | разовый |
| `import_guide_showcases.py` | витрины и экспонаты по выписке путеводителя (`--sweep-unmatched`) | API | разовый |
| `apply_guide_fixes_20260812.py` | 47 правок карточек с проверкой `expect_current` | API | разовый |
| `backfill_catalog_fields.py` | поля из каталожной строки (`--clean-material-techniques`) | API | разовый |
| `backfill_exhibit_origin_place.py` | место создания из каталожной строки | API | разовый |
| `fix_showcase_orphans.py` | записи без номера в пронумерованных витринах → «Не в витринах» | API | разовый |
| `fix_catalog_typography.py` | «ёлочки», `пресс- папье`, двойные пробелы (`--report-file` для музея) | API | разовый |
| `restore_descriptions.py` | обрезанные `short_description` из `raw_history` | API | разовый |
| `restore_wiped_cards_20260831.py` | карточки, затёртые старым PUT (`--stage image`/`description`) | API | разовый |
| `smoke_*.py` | интеграционные smoke-проверки по трекеру и баг-репортам | API | ручная проверка |

> [!CAUTION]
> Автоматическое удаление «дублей» по сходству названий **запрещено осознанно**:
> «Богоматерь Тихвинская» и «Богоматерь Иверская» похожи на 0.94, а это разные
> иконы. Скрипты только помечают пары, решение принимает музей. Удаление
> экспонатов идёт только по подтверждённому списку `--delete-ids`, и оно
> блокируется, если на карточке есть фото, описание, озвучка или `label_slug`.

## Тесты

```bash
python -m pytest tests -q          # все: ~725 тестов, ~2 с, без БД и сети
python tests/test_guide_style.py   # большинство файлов запускаются и без pytest
```

- **Без БД и сети.** Тесты проверяют чистые функции, скрипты с подменённым HTTP
  и ASGI-вызовы с `app.dependency_overrides`. `conftest.py` нет.
- **Запуск без pytest.** У 32 файлов из 35 есть свой `__main__`. Три файла
  работают **только под pytest**: `test_referenced_exhibits.py`,
  `test_recognition_coverage.py`, `test_smoke_bugreport_20260831.py`.
- **Тесты-стражи контрактов.** Часть тестов проверяет не поведение, а
  **договорённости**: порядок полей карточки, формулировки промптов, отпечаток
  кэша подсказок. Если такой тест упал после вашей правки, сначала выясните,
  зачем он был написан (обычно это есть в его docstring), и только потом решайте,
  менять ли тест.

Интеграционные проверки требуют запущенного API со схемой и сидом:

```bash
BASE_URL=http://localhost:8000 python scripts/smoke_backend_tasks.py
BASE_URL=http://localhost:8000 python scripts/smoke_bugreport_20260728.py
BASE_URL=http://localhost:8000 python scripts/smoke_analytics_20260803.py
BASE_URL=http://localhost:8000 python scripts/smoke_telemetry_20260804.py
# BASE_URL обязателен; --write проверяет п. IV-1 на временной карточке и откажется работать на проде
BASE_URL=http://localhost:8000 ADMIN_TOKEN=dev-admin-token python scripts/smoke_bugreport_20260831.py --write
```

## Документация API: два представления

| | Дизайн-контракт | Живая реализация |
|---|---|---|
| Источник | [`openapi.yaml`](openapi.yaml) (рукописный, OpenAPI 3.0.3, с примерами) | автогенерация FastAPI (OpenAPI 3.1) |
| Swagger UI | `./serve.sh` → <http://localhost:8080/swagger/> | <http://localhost:8000/docs> |
| Когда смотреть | согласование контракта, фронтенд, codegen | что сервер реально отдаёт сейчас |

Меняете форму ответа — меняйте **оба** представления: `openapi.yaml` правится
руками в том же PR.

## Инварианты и подводные камни

Короткий список того, что уже ломалось или сломается при невнимательной правке.

**Данные и контракт**

1. `raw_history` не публичен: он есть только в `ExhibitAdmin` (`to_exhibit(admin=True)`).
2. Порядок и полный набор полей карточки — контракт с музеем (`test_exhibit_card.py`).
3. Формулировка расположения берётся **только** из `services/location.py`.
4. `PUT` в админке — это слияние. Не возвращайте семантику «непереданное = null».
5. Правка данных живого каталога делается миграцией или скриптом с откатом, а не
   через `init_db.py`.
6. Бэкфиллы не перезаписывают непустые поля: правка человека важнее разбора.
7. Выражение `search_vector` живёт в трёх местах (см. [«Полнотекстовый поиск»](#полнотекстовый-поиск)).
8. `is_service` фильтруется только в `/map`, `/halls`, `/search` и гиде. По
   прямым ссылкам такие залы видны.
9. `requirements.txt` в корне и `app/requirements.txt` синхронизируются руками
   (в корневом нет uvicorn).

**ИИ-гид**

10. `"context": null` в `/guide/chat` означает **сброс**, а отсутствие поля —
    «продолжить». Это разные вещи.
11. Промпт запрещает выдумку по **действию**. Формулировка «только по справке»
    ломает гида (тест-страж).
12. Кэш подсказок не замечает правок промпта и кода (`--force`), зато фильтры
    применяются при чтении. `test_guide_style` фиксирует отпечаток
    `questions_source` намеренно.
13. Кортеж `_REFUSAL_REASONS` в `routers/guide.py` и литерал в
    `crud.exhibit_refused_questions` должны совпадать. Автоматически это не проверяется.
14. `_BANNED_QUESTION_PATTERNS[0]` обязан оставаться шаблоном «выбор материала»:
    два потребителя делают срез `[1:]`.
15. В `routers/guide.py` модуль `location` импортирован как `location_text`, потому
    что в `chat()` есть локальная переменная `location`. Прямой импорт даст
    `UnboundLocalError` на каждом запросе.
16. `save_exhibit_questions` делает commit посреди запроса, и вместе с ним
    коммитится всё, что висит в сессии.
17. `GUIDE_HISTORY_TURNS` считает строки сообщений, а не пары.
18. Модель может вернуть подсказки нумерованным списком («1. …»): парсер снимает
    только `-`, `•` и табы.

**Платформа**

19. Лимит загрузки ограничен API Gateway, а не нашим кодом (2,5 МБ).
20. Настройки читаются один раз при импорте. Окружение для функции задаётся
    **до** `import app.main`.
21. Шрифт для PDF и `CA.pem` обязаны быть в архиве функции.
22. `/health` не проверяет живость Yandex-сервисов, только наличие ключей.
23. Админ-токен статический и общий. Ротация — это смена `ADMIN_API_TOKEN` у
    функции и у cron-функции одновременно.

## Процесс и история решений

- **Как приходят задачи.** Задачи ставит заказчик (музей и продукт) в виде ТЗ и
  баг-репортов с пунктами (`п. II-3`, `B9`…). Ссылки на эти пункты стоят в коде,
  комментариях и тестах. Если непонятно, зачем написана строка, ищите по номеру
  пункта в `docs/`.
- **Что лежит в `docs/`:**

  | Документ | О чём |
  |---|---|
  | [`bugreport-2026-08-12-answers.md`](docs/bugreport-2026-08-12-answers.md), [`bugreport-2026-08-31-answers.md`](docs/bugreport-2026-08-31-answers.md) | Сводные ответы музею по баг-репортам |
  | [`analytics-metrics.md`](docs/analytics-metrics.md), [`analytics-privacy.md`](docs/analytics-privacy.md) | Метрики дашборда и состав данных |
  | [`chat-history-decision.md`](docs/chat-history-decision.md) | История чатов: решение и контракт на будущее |
  | [`staircase-hall-decision.md`](docs/staircase-hall-decision.md) | Зал №1: скрыт 29.07, открыт 31.08.2026 |
  | [`task-2026-08-17-year-created-string.md`](docs/task-2026-08-17-year-created-string.md) | `year_created` → строка |
  | [`task-2026-08-19-llm-cost.md`](docs/task-2026-08-19-llm-cost.md) | Расход LLM/SpeechKit |
  | [`task-2026-08-26-questions-cache.md`](docs/task-2026-08-26-questions-cache.md) | Кэш подсказок |
  | [`task-2026-08-31-exhibit-card.md`](docs/task-2026-08-31-exhibit-card.md) | Карточка предмета |
  | [`task-2026-08-31-guide-suggestions.md`](docs/task-2026-08-31-guide-suggestions.md) | Блок подсказок |
  | [`task-2026-08-31-referenced-exhibits.md`](docs/task-2026-08-31-referenced-exhibits.md) | «Упомянуто в ответе» |
  | [`task-2026-08-31-recognition-coverage.md`](docs/task-2026-08-31-recognition-coverage.md) | Покрытие распознавания |
  | [`task-2026-08-31-admin-put-data-loss.md`](docs/task-2026-08-31-admin-put-data-loss.md) | PUT затирал поля |

- **Стиль кода.** Комментарии и docstring пишутся по-русски и объясняют
  **почему**, часто со ссылкой на пункт баг-репорта и дату. Новое поведение гида
  выкатывается за флагом `GUIDE_*`, чтобы его можно было откатить без релиза.
  Скрипты правки данных по умолчанию делают сухой прогон и пишут файл отката.

## Стек и источники данных

**Стек:** Python 3.12+ · FastAPI · Pydantic 2 · SQLAlchemy 2.0 (async) + asyncpg ·
PostgreSQL 17 (Yandex Managed) · Yandex Cloud Functions + API Gateway · Object
Storage + CDN (boto3) · YandexGPT (Pro + Lite) · SpeechKit v3 · внешний ML-сервис
поиска по фото · openpyxl / ReportLab (выгрузки) · Koinovo (3D-модели, embed).

**Источники наполнения каталога:**

- Путеводитель 2014 (PDF) — главный источник правды для каталожных строк:
  <http://fabergemuseum.ru/image/pdf/faberge_expo.pdf>
- План экспозиции: <https://fabergemuseum.ru/posetitelyam/plan-ekspozitsii>
- Шедевры коллекции: <https://fabergemuseum.ru/kollekczii/shedevryi-kollekczii/>
  (первичное наполнение — `scrape_faberge.py` → `load_faberge.py`)
- 3D-модели (Koinovo): <https://koinovo.ru/fabergemuseum>
