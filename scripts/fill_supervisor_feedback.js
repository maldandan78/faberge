/**
 * Автозаполнение вкладки «Supervisor feedback (organization)» на my.innopolis.university
 * (практика «Разработка чат-бота для Музея Фаберже», 25.05–07.06.2026).
 *
 * Тексты написаны от лица руководителя практики со стороны организации.
 *
 * Как использовать:
 *   1. Откройте вкладку «Supervisor feedback (organization)».
 *   2. DevTools → Console → вставьте весь файл → Enter.
 *   3. Проверьте поля и нажмите «Save» вручную — скрипт сам ничего не отправляет.
 */
(async () => {
  const FILL_ENGLISH = true; // поля "In English (for English-language programs)"

  const T = {
    'organizationFeedback.qualityFeedback.ru':
      'Качество работы высокое, результатом удовлетворены полностью. Максим в установленный срок ' +
      'разработал backend MVP «ИИ-гид музея Фаберже»: REST API на FastAPI с проработанным ' +
      'OpenAPI-контрактом, базу данных PostgreSQL 17 со схемой и демо-данными по коллекции музея, ' +
      'интеграции с сервисами Yandex Cloud (распознавание экспонатов, генерация рассказов, синтез речи). ' +
      'Отдельно отмечаем продуманную архитектуру: сервис полностью работоспособен без облачных ключей ' +
      'за счёт детерминированных стабов, разворачивается одной командой через Docker Compose и ' +
      'сопровождён качественной документацией.',
    'organizationFeedback.qualityFeedback.en':
      'The quality of work is high and we are fully satisfied with the result. Maksim delivered the ' +
      'backend MVP of the “Fabergé Museum AI Guide” on schedule: a FastAPI REST API with a well-designed ' +
      'OpenAPI contract, a PostgreSQL 17 database with the schema and seed data for the museum ' +
      'collection, and integrations with Yandex Cloud services (exhibit recognition, story generation, ' +
      'speech synthesis). We especially note the thoughtful architecture: the service is fully ' +
      'functional without cloud keys thanks to deterministic stubs, deploys with a single Docker ' +
      'Compose command and is accompanied by quality documentation.',

    'organizationFeedback.wellDevelopedCompetencies.ru':
      'Проектирование REST API по подходу contract-first (OpenAPI 3.0); разработка на асинхронном ' +
      'стеке Python (FastAPI, SQLAlchemy 2.0 async, asyncpg); проектирование реляционных схем данных ' +
      '(PostgreSQL 17); интеграция внешних ИИ-сервисов (YOLO, YandexGPT, SpeechKit) с паттерном ' +
      'взаимозаменяемых реализаций «стаб ↔ реальный вызов»; контейнеризация (Docker, Docker Compose); ' +
      'самостоятельность, умение декомпозировать задачу и работать по дорожной карте; ведение ' +
      'технической документации.',
    'organizationFeedback.wellDevelopedCompetencies.en':
      'REST API design with the contract-first approach (OpenAPI 3.0); development on the async Python ' +
      'stack (FastAPI, SQLAlchemy 2.0 async, asyncpg); relational data schema design (PostgreSQL 17); ' +
      'integration of external AI services (YOLO, YandexGPT, SpeechKit) using the interchangeable ' +
      '“stub ↔ real call” pattern; containerisation (Docker, Docker Compose); independence, the ability ' +
      'to decompose a task and follow a roadmap; maintaining technical documentation.',

    'organizationFeedback.toBeDevelopedCompetencies.ru':
      'Рекомендуем развивать практики автоматизированного тестирования (unit- и интеграционные тесты, ' +
      'покрытие ключевых сценариев) и настройку CI/CD-конвейеров; углубить навыки наблюдаемости ' +
      'сервисов (структурированное логирование, метрики, трассировка) и нагрузочного тестирования; ' +
      'продолжить развивать навыки оценки сроков и презентации технических решений заказчику.',
    'organizationFeedback.toBeDevelopedCompetencies.en':
      'We recommend developing automated testing practices (unit and integration tests, coverage of key ' +
      'scenarios) and CI/CD pipeline setup; deepening service observability skills (structured logging, ' +
      'metrics, tracing) and load testing; continuing to develop estimation skills and the presentation ' +
      'of technical solutions to the customer.',

    'organizationFeedback.generalRecommendations.ru':
      'Максим показал себя ответственным и технически сильным разработчиком: задачи практики выполнены ' +
      'в полном объёме и в срок, код структурирован и сопровождён документацией. Рекомендуем продолжить ' +
      'развитие проекта (автоматические тесты, CI/CD, мониторинг) и в дальнейшем привлекать Максима к ' +
      'промышленным backend-проектам. Оценка за практику — «отлично»; готовы рекомендовать его как ' +
      'стажёра и младшего разработчика.',
    'organizationFeedback.generalRecommendations.en':
      'Maksim proved to be a responsible and technically strong developer: the internship tasks were ' +
      'completed in full and on time, the code is well structured and documented. We recommend ' +
      'continuing the project development (automated tests, CI/CD, monitoring) and involving Maksim in ' +
      'production backend projects in the future. The internship grade is “excellent”; we are ready to ' +
      'recommend him as an intern and junior developer.',
  };

  /** Ставит value так, чтобы React/react-hook-form увидели изменение. */
  function setNativeValue(el, value) {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  console.log('▶ Заполняю отзыв руководителя…');

  if (!document.querySelector('[name="organizationFeedback.qualityFeedback.ru"]')) {
    console.error('✗ Поля не найдены. Откройте вкладку «Supervisor feedback (organization)» и запустите скрипт ещё раз.');
    return;
  }

  let filled = 0, skipped = 0;
  for (const [name, text] of Object.entries(T)) {
    if (!FILL_ENGLISH && name.endsWith('.en')) continue;
    const el = document.querySelector(`[name="${name}"]`);
    if (!el) { console.warn(`   ⚠ не найдено поле ${name}`); skipped++; continue; }
    setNativeValue(el, text);
    filled++;
  }

  console.log(`✓ Заполнено полей: ${filled}${skipped ? `, пропущено ${skipped}` : ''}`);
  console.log('Готово. Проверьте текст (он от лица руководителя!) и нажмите «Save».');
})();
