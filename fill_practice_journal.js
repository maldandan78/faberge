/**
 * Автозаполнение формы «Дневник прохождения практики»
 * Проект: ИИ-гид музея Фаберже — backend (FastAPI + PostgreSQL 17) + OpenAPI-контракт
 *
 * Как пользоваться:
 *   1. Откройте страницу с формой.
 *   2. Откройте DevTools → Console (F12).
 *   3. Вставьте содержимое этого файла целиком и нажмите Enter.
 *
 * Форма — React-управляемая (Radix UI), поэтому значения проставляются через
 * нативный сеттер value + события input/change, иначе React их «не увидит».
 */
(async () => {
  'use strict';

  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  // --- React-совместимая установка значения для input/textarea ---------------
  function setReactValue(el, value) {
    if (!el) return false;
    const proto =
      el instanceof window.HTMLTextAreaElement
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    return true;
  }

  function setByName(name, value) {
    const el = document.querySelector(`[name="${name}"]`);
    if (!el) {
      console.warn('⚠️ поле не найдено:', name);
      return false;
    }
    return setReactValue(el, value);
  }

  // --------------------------- КОНТЕНТ ----------------------------------------
  const data = {
    // Индивидуальное задание
    'journal.individualTask.ru':
      'Разработка серверной части (backend) и OpenAPI-контракта мобильного web-приложения (PWA) «ИИ-гид музея Фаберже»: проектирование REST API навигации по экспозиции (зал → витрина → экспонат), а также интеграция распознавания экспонатов (YOLO), генерации рассказов (YandexGPT) и озвучивания (SpeechKit) на стеке FastAPI + PostgreSQL 17 в Yandex Cloud.',
    'journal.individualTask.en':
      'Development of the backend and OpenAPI contract for the “Faberge Museum AI Guide” mobile web application (PWA): designing a REST API for exposition navigation (hall → showcase → exhibit) and integrating exhibit recognition (YOLO), story generation (YandexGPT) and speech synthesis (SpeechKit) on a FastAPI + PostgreSQL 17 stack in Yandex Cloud.',

    // Планируемые результаты
    'journal.expectedResults.ru':
      'Работающий backend с документированным REST API: навигация, каталог, поиск и карточки экспонатов на реальном PostgreSQL 17; эндпоинты ИИ-гида (распознавание, рассказ, озвучка) с детерминированными стабами и реальными вызовами Yandex Cloud; рукописный OpenAPI 3.0.3-контракт с примерами и Swagger UI; контейнеризация (Docker Compose) и готовность к развёртыванию в Yandex Cloud Functions.',
    'journal.expectedResults.en':
      'A working backend with a documented REST API: navigation, catalog, search and exhibit cards on a real PostgreSQL 17; AI-guide endpoints (recognition, story, speech) with deterministic stubs and real Yandex Cloud calls; a hand-written OpenAPI 3.0.3 contract with examples and Swagger UI; containerization (Docker Compose) and readiness for deployment to Yandex Cloud Functions.',

    // Краткое описание достигнутого результата
    'journal.achievedResults.ru':
      'Реализован backend на FastAPI + SQLAlchemy 2.0 (async) + asyncpg к PostgreSQL 17: полностью рабочие навигация, каталог, поиск и экспонаты. Эндпоинты ИИ-гида (POST /recognition, /guide/story, /speech) работают и через детерминированные стабы (без облака), и через реальные YOLO/YandexGPT/SpeechKit — реализация выбирается по наличию ключей в окружении. Подготовлены рукописный OpenAPI 3.0.3-контракт с примерами и offline Swagger UI, docker-compose (БД + API одной командой) и развёртывание в Yandex Cloud Functions.',
    'journal.achievedResults.en':
      'A FastAPI + SQLAlchemy 2.0 (async) + asyncpg backend over PostgreSQL 17 was implemented: fully working navigation, catalog, search and exhibits. The AI-guide endpoints (POST /recognition, /guide/story, /speech) run both via deterministic stubs (no cloud) and via real YOLO/YandexGPT/SpeechKit — the implementation is chosen automatically by the presence of keys. A hand-written OpenAPI 3.0.3 contract with examples and an offline Swagger UI, a docker-compose (DB + API in one command) and deployment to Yandex Cloud Functions were prepared.',

    // Саморефлексия
    'journal.selfReflection.ru':
      'Практика углубила навыки проектирования REST API «от контракта» (OpenAPI-first) и асинхронной работы с PostgreSQL через SQLAlchemy 2.0. Особенно ценным оказался приём с двумя реализациями внешних сервисов (детерминированный стаб + реальный вызов), выбираемыми по окружению: это позволило вести разработку и демонстрацию без облачных ключей. Освоил развёртывание FastAPI в Yandex Cloud Functions и подключение к Managed PostgreSQL 17 по TLS. В дальнейшем планирую усилить покрытие автотестами и наблюдаемость (логи и метрики).',
    'journal.selfReflection.en':
      'The internship deepened my skills in contract-first (OpenAPI-first) REST API design and asynchronous work with PostgreSQL via SQLAlchemy 2.0. The most valuable pattern was having two implementations of external services (a deterministic stub plus a real call) selected by environment: it allowed development and demos without cloud keys. I learned how to deploy FastAPI to Yandex Cloud Functions and connect to Managed PostgreSQL 17 over TLS. Next I plan to strengthen automated test coverage and observability (logs and metrics).',

    // ---- Этап 1: Анализ и проектирование контракта ----
    'journal.workScheduleItems.0.task.ru':
      'Анализ предметной области и материалов музея Фаберже (план экспозиции, путеводитель, шедевры коллекции). Формирование пользовательского сценария (QR → карта → экспонат → рассказ → озвучка) и проектирование REST API. Разработка рукописного OpenAPI 3.0.3-контракта с примерами запросов и ответов.',
    'journal.workScheduleItems.0.task.en':
      'Analysis of the domain and the Faberge Museum materials (exposition plan, guidebook, collection masterpieces). Defining the user scenario (QR → map → exhibit → story → speech) and designing the REST API. Writing a hand-crafted OpenAPI 3.0.3 contract with request/response examples.',
    'journal.workScheduleItems.0.result.ru':
      'Готов дизайн-контракт openapi.yaml (OpenAPI 3.0.3) с группами эндпоинтов: система, карта/навигация, экспонаты, поиск, распознавание, ИИ-гид, озвучивание. Определена иерархия данных зал → витрина → экспонат и ключевые поля (label_slug, raw_history). Развёрнут offline Swagger UI для согласования контракта с фронтендом.',
    'journal.workScheduleItems.0.result.en':
      'A design contract openapi.yaml (OpenAPI 3.0.3) was produced with endpoint groups: system, map/navigation, exhibits, search, recognition, AI-guide, speech. The data hierarchy hall → showcase → exhibit and key fields (label_slug, raw_history) were defined. An offline Swagger UI was deployed to align the contract with the frontend.',

    // ---- Этап 2: База данных и базовый API (навигация/каталог/поиск) ----
    'journal.workScheduleItems.1.task.ru':
      'Проектирование схемы PostgreSQL 17 (halls → showcases → exhibits, медиа, галерея) и демо-данных. Реализация на FastAPI слоёв db / models / schemas / crud и роутеров навигации, каталога экспонатов и поиска на SQLAlchemy 2.0 (async) + asyncpg.',
    'journal.workScheduleItems.1.task.en':
      'Designing the PostgreSQL 17 schema (halls → showcases → exhibits, media, gallery) and seed data. Implementing the FastAPI db / models / schemas / crud layers and the navigation, exhibit-catalog and search routers on SQLAlchemy 2.0 (async) + asyncpg.',
    'journal.workScheduleItems.1.result.ru':
      'Созданы db/schema.sql и db/seed.sql, а также скрипт init_db.py для локальной и Managed PostgreSQL. Полностью рабочие эндпоинты: GET /map, /halls, /showcases, /exhibits, /exhibits/{id}/related, /search — реальные запросы к PostgreSQL 17 с пагинацией и сериализацией ответов.',
    'journal.workScheduleItems.1.result.en':
      'Created db/schema.sql and db/seed.sql plus the init_db.py script for local and Managed PostgreSQL. Fully working endpoints: GET /map, /halls, /showcases, /exhibits, /exhibits/{id}/related, /search — real queries to PostgreSQL 17 with pagination and response serialization.',

    // ---- Этап 3: Сервисы ИИ-гида (распознавание/рассказ/озвучка) ----
    'journal.workScheduleItems.2.task.ru':
      'Реализация сервисного слоя ИИ-гида: распознавание экспоната (YOLO), генерация рассказа и вопросов-подсказок (YandexGPT), синтез речи (SpeechKit), хранение медиа (Object Storage). Для каждого сервиса — единый интерфейс с детерминированным стабом и реальным вызовом Yandex Cloud, выбор реализации по окружению.',
    'journal.workScheduleItems.2.task.en':
      'Implementing the AI-guide service layer: exhibit recognition (YOLO), story and follow-up question generation (YandexGPT), speech synthesis (SpeechKit), media storage (Object Storage). Each service exposes a single interface with a deterministic stub and a real Yandex Cloud call, selected by environment.',
    'journal.workScheduleItems.2.result.ru':
      'Заработали эндпоинты POST /recognition (фото → label_slug), POST /guide/story (label_slug → raw_history → рассказ + 3–4 вопроса), POST /guide/chat и POST /speech (озвучка). Без ключей сервис работает целиком на стабах; при наличии ключей — реальные YOLO/YandexGPT/SpeechKit. Флаги готовности видны в GET /health.',
    'journal.workScheduleItems.2.result.en':
      'The endpoints POST /recognition (photo → label_slug), POST /guide/story (label_slug → raw_history → story + 3–4 questions), POST /guide/chat and POST /speech (audio) became operational. Without keys the service runs entirely on stubs; with keys it calls real YOLO/YandexGPT/SpeechKit. Readiness flags are exposed in GET /health.',

    // ---- Этап 4: Контейнеризация, деплой, документация ----
    'journal.workScheduleItems.3.task.ru':
      'Контейнеризация приложения (Dockerfile, docker-compose с PostgreSQL 17), настройка CORS, раздачи /media и обработки ошибок. Подготовка к развёртыванию в Yandex Cloud Functions (index.py, API Gateway) и подключение к Managed PostgreSQL 17 по TLS. Финализация README и Swagger UI.',
    'journal.workScheduleItems.3.task.en':
      'Containerizing the application (Dockerfile, docker-compose with PostgreSQL 17), configuring CORS, /media serving and error handling. Preparing for deployment to Yandex Cloud Functions (index.py, API Gateway) and connecting to Managed PostgreSQL 17 over TLS. Finalizing the README and Swagger UI.',
    'journal.workScheduleItems.3.result.ru':
      'Команда docker compose up поднимает БД + API одной командой; приложение адаптировано под Yandex Cloud Functions и подключение к Managed PostgreSQL 17 по TLS (CA-сертификат). Оформлены два представления API (рукописный дизайн-контракт и автогенерация FastAPI), README с быстрым стартом и картой эндпоинтов. MVP-backend готов к интеграции с фронтендом.',
    'journal.workScheduleItems.3.result.en':
      'The command docker compose up brings up DB + API at once; the app was adapted for Yandex Cloud Functions and TLS connection to Managed PostgreSQL 17 (CA certificate). Two API views were prepared (the hand-written design contract and FastAPI auto-generation), plus a README with quick start and an endpoint map. The MVP backend is ready for frontend integration.',
  };

  // --------------------------- Заполнение текстов -----------------------------
  let ok = 0;
  for (const [name, value] of Object.entries(data)) {
    if (setByName(name, value)) ok++;
  }
  console.log(`✅ Текстовых полей заполнено: ${ok}/${Object.keys(data).length}`);

  // --------------------------- Даты этапов ------------------------------------
  // Этап 1 начинается 25.05.2026, этап 4 заканчивается 07.06.2026 (заданы и
  // заблокированы). Заполняем разблокированные «Даты окончания» этапов 1–3;
  // начала следующих этапов в форме обычно подтягиваются автоматически.
  const endDates = ['2026-05-28', '2026-06-01', '2026-06-04'];
  const editableDateInputs = [
    ...document.querySelectorAll('input[type="date"]:not([disabled])'),
  ];
  editableDateInputs.forEach((el, i) => {
    if (i < endDates.length) setReactValue(el, endDates[i]);
  });
  console.log(
    `📅 Дат окончания заполнено: ${Math.min(
      editableDateInputs.length,
      endDates.length
    )} (этапы 1–3)`
  );

  // --------------------------- Выпадающие списки (Radix) ----------------------
  // Два вопроса об удовлетворённости. Пытаемся выбрать максимально позитивный
  // вариант. Radix рендерит пункты в портал только после открытия списка.
  async function setRadixSelect(trigger) {
    const fire = (type) =>
      trigger.dispatchEvent(
        new PointerEvent(type, { bubbles: true, cancelable: true, pointerType: 'mouse', button: 0 })
      );
    fire('pointerdown');
    fire('pointerup');
    trigger.click();
    await delay(120);

    const options = [...document.querySelectorAll('[role="option"]')];
    if (!options.length) return false;

    const positive =
      options.find((o) => /полност/i.test(o.textContent)) ||
      options.find((o) => /(^|\s)да\b/i.test(o.textContent)) ||
      options.find((o) => /удовлетвор|скорее да|высок/i.test(o.textContent)) ||
      options[0];

    positive.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    positive.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
    positive.click();
    await delay(120);
    return positive.textContent.trim();
  }

  const combos = [...document.querySelectorAll('button[role="combobox"]')];
  for (const c of combos) {
    try {
      const picked = await setRadixSelect(c);
      console.log(picked ? `🔽 Выбрано: «${picked}»` : '⚠️ Список не открылся — выберите вручную');
    } catch (e) {
      console.warn('⚠️ Не удалось выбрать в списке, заполните вручную:', e.message);
    }
  }

  console.log('🎉 Готово. Проверьте поля и при необходимости поправьте даты/списки вручную.');
})();
