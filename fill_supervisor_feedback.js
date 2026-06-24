/**
 * Автозаполнение формы «Отзыв руководителя практики от профильной организации»
 * Проект: ИИ-гид музея Фаберже — backend (FastAPI + PostgreSQL 17) + OpenAPI-контракт
 *
 * Текст написан от лица руководителя практики от организации (оценка студента).
 *
 * Как пользоваться:
 *   1. Откройте вкладку «Отзыв руководителя (организация)».
 *   2. DevTools → Console (F12), вставьте этот файл целиком, Enter.
 *
 * Форма React-управляемая (Radix UI): значения ставятся через нативный сеттер
 * value + события input/change, иначе React изменения «не увидит».
 */
(() => {
  'use strict';

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

  const data = {
    // Качество выполненной работы и удовлетворённость полученным результатом
    'organizationFeedback.qualityFeedback.ru':
      'Работа выполнена на высоком профессиональном уровне; полученным результатом полностью удовлетворены. В срок реализована серверная часть (backend) MVP мобильного приложения «ИИ-гид музея Фаберже» на FastAPI + PostgreSQL 17 и рукописный OpenAPI 3.0.3-контракт. Навигация по экспозиции (зал → витрина → экспонат), каталог, поиск и карточки экспонатов работают на реальной базе данных; эндпоинты ИИ-гида (распознавание, рассказ, озвучивание) реализованы и через детерминированные стабы, и через реальные сервисы Yandex Cloud. Код структурирован, документирован и пригоден к интеграции с фронтендом.',
    'organizationFeedback.qualityFeedback.en':
      'The work was performed at a high professional level; we are fully satisfied with the result. The backend of the “Faberge Museum AI Guide” MVP on FastAPI + PostgreSQL 17 and a hand-written OpenAPI 3.0.3 contract were delivered on time. Exposition navigation (hall → showcase → exhibit), catalog, search and exhibit cards run on a real database; the AI-guide endpoints (recognition, story, speech) are implemented both via deterministic stubs and via real Yandex Cloud services. The code is well structured, documented and ready for frontend integration.',

    // Сильные компетенции
    'organizationFeedback.wellDevelopedCompetencies.ru':
      'Уверенное проектирование REST API «от контракта» (OpenAPI-first) и асинхронная работа с PostgreSQL через SQLAlchemy 2.0 (async) + asyncpg. Грамотная интеграция облачных сервисов (YOLO, YandexGPT, SpeechKit, Object Storage) с разделением на интерфейс, стаб и реальный вызов. Навыки контейнеризации (Docker, docker-compose) и развёртывания в Yandex Cloud Functions, подключения к Managed PostgreSQL по TLS. Самостоятельность, аккуратность, качественная техническая документация и ответственное отношение к срокам.',
    'organizationFeedback.wellDevelopedCompetencies.en':
      'Confident contract-first (OpenAPI-first) REST API design and asynchronous work with PostgreSQL via SQLAlchemy 2.0 (async) + asyncpg. Sound integration of cloud services (YOLO, YandexGPT, SpeechKit, Object Storage) with a clear split into interface, stub and real call. Skills in containerization (Docker, docker-compose) and deployment to Yandex Cloud Functions, connecting to Managed PostgreSQL over TLS. Independence, accuracy, high-quality technical documentation and a responsible attitude to deadlines.',

    // Компетенции, нуждающиеся в развитии
    'organizationFeedback.toBeDevelopedCompetencies.ru':
      'Рекомендуется усилить покрытие автоматизированными тестами (unit/integration) и практики CI/CD. Стоит развивать наблюдаемость сервиса — структурированное логирование, метрики и трассировку, а также нагрузочное тестирование и оптимизацию запросов под рост данных. Полезно углубить навыки обеспечения безопасности API (rate limiting, валидация ввода, управление секретами) и проектирования отказоустойчивой облачной архитектуры.',
    'organizationFeedback.toBeDevelopedCompetencies.en':
      'It is recommended to strengthen automated test coverage (unit/integration) and CI/CD practices. The service’s observability should be developed — structured logging, metrics and tracing, as well as load testing and query optimization for data growth. It would be useful to deepen API security skills (rate limiting, input validation, secret management) and the design of fault-tolerant cloud architecture.',

    // Общие рекомендации студенту
    'organizationFeedback.generalRecommendations.ru':
      'Студент проявил себя как мотивированный и технически грамотный разработчик, способный самостоятельно довести задачу от проектирования контракта до рабочего сервиса. Рекомендуем продолжать развитие в области backend- и облачной разработки, системно внедрять автотесты и CI/CD, изучать паттерны проектирования распределённых систем. Считаем возможным рекомендовать студента к дальнейшему сотрудничеству и работе над развитием проекта до полноценного релиза.',
    'organizationFeedback.generalRecommendations.en':
      'The student proved to be a motivated and technically competent developer, able to independently take a task from contract design to a working service. We recommend continuing development in backend and cloud engineering, systematically adopting automated tests and CI/CD, and studying distributed-system design patterns. We consider it possible to recommend the student for further cooperation and for developing the project toward a full release.',
  };

  let ok = 0;
  for (const [name, value] of Object.entries(data)) {
    if (setByName(name, value)) ok++;
  }
  console.log(`✅ Полей заполнено: ${ok}/${Object.keys(data).length}`);
  console.log('🎉 Готово. Проверьте текст и нажмите «Сохранить».');
})();
