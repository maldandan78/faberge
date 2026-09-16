-- =============================================================================
-- Миграция: новая причина «вопрос без ответа» — 'blocked_topic'
-- (просьба музея 16.09.2026: запрещённые темы вопросов к ИИ-гиду)
--
-- Проблема
--   Музей назвал темы, на которые гид отвечать не должен: почему мастер выбрал
--   именно этот материал, для чего использовалась вещь, сколько времени заняло
--   изготовление, неподтверждённое «единственный». Для подсказок они уже
--   снимаются шаблонами (app/services/guide_style.py). Теперь и вопрос, который
--   посетитель ввёл сам, модель не получает: /guide/chat отвечает заглушкой
--   (guide_style.is_blocked_visitor_question, settings.guide_blocked_answer).
--
--   Такую реплику надо записать с признаком answered = FALSE — иначе музей не
--   увидит в отчёте /admin/analytics/unanswered, о чём посетители спрашивают и
--   получают отказ. Ни одна из пяти существующих причин не подходит:
--   'llm_refusal'/'no_context' означают отказ МОДЕЛИ и кормят глобальную память
--   отказов (решение Д8), 'llm_hedge' — содержательный ответ с оговоркой,
--   'not_found' и 'error' — провалы поиска и инфраструктуры.
--
-- Что делает
--   Расширяет CHECK-ограничение guide_messages.fail_reason шестым значением
--   'blocked_topic'. Данных не трогает.
--
-- Порядок применения
--   Строго ДО выкладки кода: код начинает писать 'blocked_topic' сразу, и на
--   старом ограничении INSERT упал бы на каждом заблокированном вопросе — то
--   есть посетитель получил бы 500 вместо заглушки.
--
--   psql "$DATABASE_URL" -f db/migrations/2026-09-16_guide_fail_reason_blocked.sql
--   (scripts/init_db.py применяет db/schema.sql целиком — на чистой базе
--    миграция не нужна.)
--
-- Идемпотентна (DROP IF EXISTS + ADD) и обратима — см. секцию «Откат».
-- =============================================================================

BEGIN;

ALTER TABLE guide_messages DROP CONSTRAINT IF EXISTS guide_messages_fail_reason_chk;
ALTER TABLE guide_messages ADD CONSTRAINT guide_messages_fail_reason_chk
    CHECK (fail_reason IS NULL OR fail_reason IN
           ('no_context', 'llm_refusal', 'llm_hedge', 'not_found', 'error', 'blocked_topic'));

COMMIT;

-- ── Проверка ─────────────────────────────────────────────────────────────────

-- Ожидаем определение ограничения с шестью значениями, включая blocked_topic.
SELECT pg_get_constraintdef(oid) AS definition
  FROM pg_constraint
 WHERE conname = 'guide_messages_fail_reason_chk';

-- ── Откат ────────────────────────────────────────────────────────────────────
-- Сузить ограничение обратно можно только после того, как в таблице не
-- останется строк с 'blocked_topic'. Откатывать вместе с кодом (или перед ним:
-- GUIDE_BLOCK_BANNED_QUESTIONS=false перестаёт писать эту причину).
--
-- BEGIN;
-- UPDATE guide_messages SET fail_reason = NULL WHERE fail_reason = 'blocked_topic';
-- ALTER TABLE guide_messages DROP CONSTRAINT IF EXISTS guide_messages_fail_reason_chk;
-- ALTER TABLE guide_messages ADD CONSTRAINT guide_messages_fail_reason_chk
--     CHECK (fail_reason IS NULL OR fail_reason IN
--            ('no_context', 'llm_refusal', 'llm_hedge', 'not_found', 'error'));
-- COMMIT;
