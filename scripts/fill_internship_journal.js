/**
 * Автозаполнение журнала практики на my.innopolis.university
 * («Разработка чат-бота для Музея Фаберже», 25.05–07.06.2026).
 *
 * Как использовать:
 *   1. Откройте страницу практики → вкладка «Internship journal» (как на скриншоте/webarchive).
 *   2. Откройте DevTools → Console (Chrome: Cmd+Opt+J; Safari: включите меню Develop).
 *      В Chrome при первой вставке наберите `allow pasting` и нажмите Enter.
 *   3. Вставьте весь файл целиком и нажмите Enter.
 *   4. Проверьте поля глазами и нажмите «Save» вручную — скрипт сам ничего не отправляет.
 *
 * Скрипт совместим с React: значения ставятся через нативный сеттер + событие
 * `input` (иначе react-hook-form не увидит изменений), выпадающие списки Radix
 * открываются pointer-событиями.
 */
(async () => {
  // ───────────────────────────── CONFIG ─────────────────────────────
  const CONFIG = {
    SET_DATES: true,
    // Редактируемые поля «End date» этапов 1–4 (start-даты выводятся системой сами).
    STAGE_END_DATES: ['2026-05-28', '2026-06-01', '2026-06-04', '2026-06-07'],

    // Точный текст пункта выпадающего списка (подстрока, без учёта регистра).
    // Оставьте '' — скрипт выберет лучший вариант по эвристике и залогирует список.
    KNOWLEDGE_GAINED: '',
    ORG_QUALITY: '',

    FILL_ENGLISH: true, // поля "In English (for English-language programs)"
  };

  // ───────────────────────────── ТЕКСТЫ ─────────────────────────────
  const T = {
    'journal.individualTask.ru':
      'Спроектировать и реализовать backend мобильного web-приложения (PWA) «ИИ-гид музея Фаберже»: ' +
      'REST API на FastAPI с рукописным контрактом OpenAPI 3.0, базой данных PostgreSQL 17 ' +
      '(иерархия зал → витрина → экспонат) и интеграциями с сервисами Yandex Cloud — ' +
      'распознавание экспоната по фотографии (YOLO), генерация рассказа ИИ-гида (YandexGPT) ' +
      'и синтез речи (SpeechKit). Обеспечить полную работоспособность сервиса без облачных ' +
      'ключей за счёт детерминированных стабов и упаковать проект в Docker Compose.',
    'journal.individualTask.en':
      'Design and implement the backend of the “Fabergé Museum AI Guide” mobile web app (PWA): ' +
      'a FastAPI REST API with a hand-written OpenAPI 3.0 contract, a PostgreSQL 17 database ' +
      '(hall → showcase → exhibit hierarchy) and Yandex Cloud integrations — exhibit photo ' +
      'recognition (YOLO), AI-guide story generation (YandexGPT) and speech synthesis (SpeechKit). ' +
      'Keep the service fully functional without cloud keys via deterministic stubs and package ' +
      'the project with Docker Compose.',

    'journal.expectedResults.ru':
      'Работающий backend-сервис: согласованный OpenAPI-контракт (openapi.yaml) со Swagger UI; ' +
      'схема БД PostgreSQL 17 и демо-данные по коллекции музея; REST-эндпоинты карты и навигации, ' +
      'каталога экспонатов, поиска, распознавания фото, ИИ-гида с вопросами-подсказками, озвучивания, ' +
      'а также админ-CRUD и телеметрии; слой интеграций YOLO / YandexGPT / SpeechKit с автоматическим ' +
      'переключением «стаб ↔ реальный вызов»; запуск одной командой docker compose up; README с инструкциями.',
    'journal.expectedResults.en':
      'A working backend service: an agreed OpenAPI contract (openapi.yaml) with Swagger UI; ' +
      'a PostgreSQL 17 schema with museum-collection seed data; REST endpoints for the map and ' +
      'navigation, exhibit catalogue, search, photo recognition, the AI guide with follow-up ' +
      'questions, speech synthesis, plus admin CRUD and telemetry; a YOLO / YandexGPT / SpeechKit ' +
      'integration layer that switches automatically between stub and real cloud calls; one-command ' +
      'startup via docker compose up; a README with instructions.',

    'journal.achievedResults.ru':
      'Реализован backend на FastAPI: 9 роутеров (system, navigation, exhibits, search, recognition, ' +
      'guide, speech, admin, telemetry), асинхронный доступ к PostgreSQL 17 (SQLAlchemy 2.0 async + asyncpg), ' +
      'рукописный контракт OpenAPI 3.0.3 с примерами и два представления документации (Swagger UI и ReDoc). ' +
      'Сервисы YOLO / YandexGPT / SpeechKit / Object Storage работают и в стаб-режиме, и с реальными ' +
      'ключами Yandex Cloud (выбор автоматический, флаги готовности в GET /health). Подготовлены DDL-схема, ' +
      'сид-данные по шедеврам коллекции, скрипт инициализации БД, Dockerfile и docker-compose.',
    'journal.achievedResults.en':
      'Implemented the FastAPI backend: 9 routers (system, navigation, exhibits, search, recognition, ' +
      'guide, speech, admin, telemetry), async PostgreSQL 17 access (SQLAlchemy 2.0 async + asyncpg), ' +
      'a hand-written OpenAPI 3.0.3 contract with examples and two documentation views (Swagger UI and ReDoc). ' +
      'The YOLO / YandexGPT / SpeechKit / Object Storage services run both in stub mode and with real ' +
      'Yandex Cloud keys (auto-selected, readiness flags in GET /health). Delivered the DDL schema, ' +
      'seed data for collection masterpieces, a DB init script, Dockerfile and docker-compose.',

    'journal.selfReflection.ru':
      'Практика дала опыт полного цикла разработки backend: от анализа предметной области (экспозиция ' +
      'музея Фаберже) и проектирования контракта до реализации и контейнеризации. Освоил подход ' +
      'contract-first (OpenAPI до кода), асинхронный стек Python (FastAPI, SQLAlchemy 2.0 async, asyncpg) ' +
      'и паттерн взаимозаменяемых реализаций «стаб ↔ облачный API» для YOLO, YandexGPT и SpeechKit — ' +
      'он позволил разрабатывать и демонстрировать сервис без доступа к облаку. Сложнее всего было ' +
      'согласовать схему данных с потребностями всех эндпоинтов; помогло раннее проектирование DDL. ' +
      'В планах — автоматические тесты и CI/CD.',
    'journal.selfReflection.en':
      'The internship gave me end-to-end backend experience: from domain analysis (the Fabergé Museum ' +
      'exposition) and contract design to implementation and containerisation. I mastered the ' +
      'contract-first approach (OpenAPI before code), the async Python stack (FastAPI, SQLAlchemy 2.0 ' +
      'async, asyncpg) and the interchangeable “stub ↔ cloud API” pattern for YOLO, YandexGPT and ' +
      'SpeechKit — it allowed developing and demoing the service without cloud access. The hardest part ' +
      'was aligning the data schema with the needs of every endpoint; early DDL design helped. ' +
      'Next steps: automated tests and CI/CD.',

    // ── Этап 1: 25.05–28.05 — анализ и проектирование ──
    'journal.workScheduleItems.0.task.ru':
      'Анализ предметной области и проектирование: изучение плана экспозиции и путеводителя музея ' +
      'Фаберже, фиксация пользовательского сценария (QR-код → интерактивная карта → фото экспоната → ' +
      'рассказ ИИ-гида → озвучка), выбор технологического стека, проектирование схемы БД ' +
      '(залы → витрины → экспонаты) и черновика OpenAPI-контракта.',
    'journal.workScheduleItems.0.task.en':
      'Domain analysis and design: studying the Fabergé Museum exposition plan and guidebook, fixing ' +
      'the user scenario (QR code → interactive map → exhibit photo → AI-guide story → audio), choosing ' +
      'the tech stack, designing the DB schema (halls → showcases → exhibits) and a draft OpenAPI contract.',
    'journal.workScheduleItems.0.result.ru':
      'Зафиксированы сценарий MVP и стек (FastAPI, PostgreSQL 17, Yandex Cloud: YOLO, YandexGPT, ' +
      'SpeechKit); спроектирована схема данных с ключевыми полями label_slug (класс YOLO) и ' +
      'raw_history (факты для YandexGPT); подготовлен черновик openapi.yaml с основными группами эндпоинтов.',
    'journal.workScheduleItems.0.result.en':
      'Fixed the MVP scenario and the stack (FastAPI, PostgreSQL 17, Yandex Cloud: YOLO, YandexGPT, ' +
      'SpeechKit); designed the data schema with the key fields label_slug (YOLO class) and raw_history ' +
      '(facts for YandexGPT); prepared a draft openapi.yaml with the main endpoint groups.',

    // ── Этап 2: 29.05–01.06 — слой данных и базовое API ──
    'journal.workScheduleItems.1.task.ru':
      'Реализация слоя данных и базовых эндпоинтов: DDL-схема и сид-данные для PostgreSQL 17, ' +
      'ORM-модели SQLAlchemy 2.0 (async) и Pydantic-схемы, эндпоинты карты и навигации ' +
      '(/map, /halls, /showcases), каталога экспонатов (/exhibits, related) и поиска (/search), пагинация.',
    'journal.workScheduleItems.1.task.en':
      'Implementing the data layer and core endpoints: DDL schema and seed data for PostgreSQL 17, ' +
      'SQLAlchemy 2.0 (async) ORM models and Pydantic schemas, map and navigation endpoints ' +
      '(/map, /halls, /showcases), the exhibit catalogue (/exhibits, related) and search (/search), pagination.',
    'journal.workScheduleItems.1.result.ru':
      'Развёрнута БД со схемой и демо-данными по шедеврам коллекции; эндпоинты навигации, каталога и ' +
      'поиска выполняют реальные запросы к PostgreSQL 17; настроены async-движок и сессии SQLAlchemy, ' +
      'пагинация; скрипт scripts/init_db.py применяет схему к локальной и Yandex Managed БД.',
    'journal.workScheduleItems.1.result.en':
      'Deployed the database with the schema and seed data for collection masterpieces; navigation, ' +
      'catalogue and search endpoints run real queries against PostgreSQL 17; configured the async ' +
      'engine, SQLAlchemy sessions and pagination; scripts/init_db.py applies the schema to a local or ' +
      'Yandex Managed database.',

    // ── Этап 3: 02.06–04.06 — интеграции ИИ-сервисов ──
    'journal.workScheduleItems.2.task.ru':
      'Интеграция ИИ-сервисов: эндпоинт /recognition (фото → YOLO → label_slug), /guide/story и ' +
      '/guide/chat (YandexGPT: рассказ + вопросы-подсказки), /speech (SpeechKit), хранение медиа ' +
      '(Object Storage); реализация паттерна «стаб + реальный вызов» с автоматическим выбором по ' +
      'наличию ключей в окружении.',
    'journal.workScheduleItems.2.task.en':
      'Integrating the AI services: the /recognition endpoint (photo → YOLO → label_slug), /guide/story ' +
      'and /guide/chat (YandexGPT: story + follow-up questions), /speech (SpeechKit), media storage ' +
      '(Object Storage); implementing the “stub + real call” pattern with automatic selection based on ' +
      'the keys present in the environment.',
    'journal.workScheduleItems.2.result.ru':
      'Все ИИ-эндпоинты работают в двух режимах: детерминированный стаб без облака и реальные вызовы ' +
      'Yandex Cloud; рассказ собирается из полей экспоната и raw_history; озвучка возвращает WAV; ' +
      'флаги готовности сервисов отображаются в GET /health; история диалога сохраняется в БД ' +
      '(guide_sessions / guide_messages).',
    'journal.workScheduleItems.2.result.en':
      'All AI endpoints work in two modes: a deterministic stub without the cloud and real Yandex Cloud ' +
      'calls; the story is composed from exhibit fields and raw_history; speech synthesis returns WAV; ' +
      'service readiness flags are exposed in GET /health; dialogue history is persisted in the DB ' +
      '(guide_sessions / guide_messages).',

    // ── Этап 4: 05.06–07.06 — упаковка и завершение ──
    'journal.workScheduleItems.3.task.ru':
      'Завершение и упаковка проекта: админ-эндпоинты CRUD и аналитика, приём событий телеметрии, ' +
      'Bearer-авторизация, обработка ошибок и CORS, контейнеризация (Dockerfile, docker-compose), ' +
      'статический Swagger UI для контракта, сквозное тестирование пользовательского сценария, README.',
    'journal.workScheduleItems.3.task.en':
      'Finalising and packaging the project: admin CRUD endpoints and analytics, telemetry event ' +
      'ingestion, Bearer authorisation, error handling and CORS, containerisation (Dockerfile, ' +
      'docker-compose), a static Swagger UI for the contract, end-to-end testing of the user scenario, README.',
    'journal.workScheduleItems.3.result.ru':
      'Проект запускается одной командой docker compose up (API + PostgreSQL 17 + автоинициализация ' +
      'схемы и сид-данных); админ-CRUD и телеметрия защищены Bearer-токеном; контракт доступен в ' +
      'Swagger UI и ReDoc; ключевой сценарий «распознавание → рассказ → озвучка» проверен end-to-end; ' +
      'написан подробный README.',
    'journal.workScheduleItems.3.result.en':
      'The project starts with a single docker compose up command (API + PostgreSQL 17 + automatic ' +
      'schema and seed initialisation); admin CRUD and telemetry are protected by a Bearer token; the ' +
      'contract is available in Swagger UI and ReDoc; the key “recognition → story → speech” scenario ' +
      'was verified end-to-end; a detailed README was written.',
  };

  // ──────────────────────────── ХЕЛПЕРЫ ────────────────────────────
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /** Ставит value так, чтобы React/react-hook-form увидели изменение. */
  function setNativeValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  const pe = (type) => new PointerEvent(type, {
    bubbles: true, cancelable: true, composed: true,
    pointerId: 1, pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1,
  });

  /** Открывает Radix-select и выбирает пункт. Возвращает текст пункта или null. */
  async function pickRadixOption(trigger, exactText, preferPatterns) {
    trigger.scrollIntoView({ block: 'center' });
    trigger.dispatchEvent(pe('pointerdown'));
    trigger.dispatchEvent(pe('pointerup'));
    trigger.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await sleep(400);

    let options = [...document.querySelectorAll('[role="option"]')];
    if (!options.length) { // запасной путь — открыть с клавиатуры
      trigger.focus();
      trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      await sleep(400);
      options = [...document.querySelectorAll('[role="option"]')];
    }
    if (!options.length) return null;

    const texts = options.map((o) => o.textContent.trim());
    console.log('   варианты:', texts);

    let target = null;
    if (exactText) {
      target = options.find((o) => o.textContent.trim().toLowerCase().includes(exactText.toLowerCase()));
    }
    if (!target) {
      for (const p of preferPatterns) {
        target = options.find((o) => p.test(o.textContent.trim()));
        if (target) break;
      }
    }
    if (!target) target = options[0];

    target.scrollIntoView({ block: 'center' });
    target.dispatchEvent(pe('pointermove'));
    target.dispatchEvent(pe('pointerup'));
    target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await sleep(400);
    return target.textContent.trim();
  }

  // ──────────────────────────── ЗАПОЛНЕНИЕ ────────────────────────────
  console.log('▶ Заполняю журнал практики…');

  if (!document.querySelector('[name="journal.individualTask.ru"]')) {
    console.error('✗ Поля журнала не найдены. Откройте вкладку «Internship journal» и запустите скрипт ещё раз.');
    return;
  }

  // 1. Текстовые поля
  let filled = 0, skipped = 0;
  for (const [name, text] of Object.entries(T)) {
    if (!CONFIG.FILL_ENGLISH && name.endsWith('.en')) continue;
    const el = document.querySelector(`[name="${name}"]`);
    if (!el) { console.warn(`   ⚠ не найдено поле ${name}`); skipped++; continue; }
    setNativeValue(el, text);
    filled++;
  }
  console.log(`✓ Текстовые поля: заполнено ${filled}${skipped ? `, пропущено ${skipped}` : ''}`);

  // 2. Даты окончания этапов (start-даты система выводит сама из предыдущего end+1).
  if (CONFIG.SET_DATES) {
    for (let i = 0; i < CONFIG.STAGE_END_DATES.length; i++) {
      // после каждого ввода React может перерисовать форму — выбираем заново
      const editable = [...document.querySelectorAll('input[type="date"]:not([disabled])')];
      if (!editable[i]) { console.warn(`   ⚠ не найден date-input этапа ${i + 1}`); continue; }
      setNativeValue(editable[i], CONFIG.STAGE_END_DATES[i]);
      await sleep(250);
    }
    console.log('✓ Даты этапов:', CONFIG.STAGE_END_DATES.join(', '));
  }

  // 3. Выпадающие списки (Radix UI)
  const combos = [...document.querySelectorAll('button[role="combobox"]')];
  if (combos.length >= 2) {
    const POSITIVE = [/отличн|excellent/i, /значительн|significant/i, /^5\b/, /хорош|good|высок|high/i];
    console.log('▶ Knowledge gained…');
    const k = await pickRadixOption(combos[0], CONFIG.KNOWLEDGE_GAINED, POSITIVE);
    console.log(k ? `✓ Knowledge gained → «${k}»` : '⚠ не удалось открыть список — выберите вручную (2 клика)');
    console.log('▶ Internship organization quality…');
    const q = await pickRadixOption(combos[1], CONFIG.ORG_QUALITY, POSITIVE);
    console.log(q ? `✓ Organization quality → «${q}»` : '⚠ не удалось открыть список — выберите вручную (2 клика)');
  } else {
    console.warn('⚠ Выпадающие списки не найдены — выберите оценки вручную.');
  }

  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('Готово. Проверьте поля и нажмите «Save» (скрипт сам ничего не отправляет).');
})();
