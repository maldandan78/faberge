"""Заглушка на введённые посетителем вопросы из запрещённых музеем тем (16.09.2026).

Вслед за подсказками музей попросил закрыть те же темы и для вопроса, который
посетитель набрал сам: модель не вызывается, в ответ — «ответа на этот вопрос у
меня нет, попробуйте задать другой вопрос», и сразу блок подсказок.

Что здесь проверяется и почему именно так:

  1. Примеры музея — дословно: в модель не уходят, в `answer` заглушка, реплика
     записана с причиной `blocked_topic`, блок подсказок не пустой.
  2. Вопросы, которые НЕ должны блокироваться. Этот блок важнее первого: отказ
     на законный вопрос — это «не знаю» живому человеку. Особенно — вопрос об
     имени вне карточки: отказ на него повторил бы баг 28.07.2026, п.3.
  3. Оговорка музея про источник и флаг отката.
  4. Причина `blocked_topic` согласована во всех местах, где перечислены
     причины: модель, schema.sql, миграция, подпись в выгрузке аналитики. На
     рассинхроне CHECK посетитель получил бы 500 вместо заглушки.

Сеть и БД не нужны — обвязка роутера из tests/test_guide_suggestions.py. Запуск:
    python -m pytest tests/test_guide_blocked_questions.py
    python tests/test_guide_blocked_questions.py        # standalone
"""
from __future__ import annotations

import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import models as m  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import guide  # noqa: E402
from app.services import analytics_export, llm  # noqa: E402
from tests.test_guide_suggestions import (  # noqa: E402
    EXHIBIT, POOL, FakeRow, FakeSession, StubExhibit, ask, wired,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_ANSWER = "Ответ модели."


def chat(message, *, exhibit_data=None, context=True, **overrides):
    """Прогнать реплику через роутер. Возвращает (ответ, сессия, сколько раз звали модель)."""
    data = exhibit_data or EXHIBIT
    session = FakeSession()
    body = {"context": {"exhibit_id": data["id"]}} if context else {}
    model_calls = []
    with wired(exhibit=StubExhibit(data), row=FakeRow(POOL, exhibit=data), answer=MODEL_ANSWER, **overrides):
        original = llm.chat

        async def counting_chat(*args, **kwargs):
            model_calls.append(args)
            return await original(*args, **kwargs)

        llm.chat = counting_chat
        try:
            response = asyncio.run(guide.chat(ask(message, **body), session))
        finally:
            llm.chat = original
    return response, session, len(model_calls)


def _written(session):
    """(answered, fail_reason) пары строк, записанных роутером."""
    pairs = {(msg.answered, msg.fail_reason) for msg in session.added if isinstance(msg, m.GuideMessage)}
    assert len(pairs) == 1, f"на паре строк разъехался признак: {pairs}"
    return pairs.pop()


def assert_blocked(response, session, model_calls, question):
    assert model_calls == 0, f"вопрос ушёл в модель: {question}"
    assert response.answer == settings.guide_blocked_answer, question
    assert _written(session) == (False, "blocked_topic"), question
    assert response.suggested_questions, "«попробуйте другой вопрос» — должно быть из чего выбрать"


def assert_answered_by_model(response, model_calls, question):
    assert model_calls == 1, f"вопрос заблокирован, а не должен: {question}"
    assert response.answer == MODEL_ANSWER, question


# ═════════════════════════════════════════════════════════════════════════════
# 1. Примеры музея
# ═════════════════════════════════════════════════════════════════════════════
MUSEUM_EXAMPLES = [
    "Почему мастер выбрал именно жёлтую эмаль?",           # категория 2
    "Почему использованы именно алмазы?",                    # категория 2
    "Почему мастер выбрал именно этот материал?",            # категория 2, родовое слово
    "Для чего использовалась бонбоньерка?",                  # категория 3
    "Сколько времени заняло его создание?",                  # категория 1
    "Почему это яйцо стало единственным заказом герцогини?",  # категория 1: в карточке нет
]


def test_museum_examples_get_the_stub_without_calling_the_model():
    for question in MUSEUM_EXAMPLES:
        assert_blocked(*chat(question), question)


def test_pattern_topics_are_blocked_in_the_general_chat_too():
    """Выбор материала, быт и сроки не зависят от карточки — и без контекста тоже."""
    for question in MUSEUM_EXAMPLES[:5]:
        assert_blocked(*chat(question, context=False), question)


def test_the_plaque_of_the_exhibit_the_visitor_stands_at_stays():
    """Посетитель стоит у предмета — плашка не должна пропадать из-за заглушки."""
    response, _session, _calls = chat(MUSEUM_EXAMPLES[0])
    assert [e.id for e in response.referenced_exhibits] == [EXHIBIT["id"]]


def test_blocked_topic_does_not_feed_the_refusal_memory():
    """Отказала не модель, а мы: память отказов (решение Д8) — про поведение модели."""
    assert "blocked_topic" not in guide._REFUSAL_REASONS


# ═════════════════════════════════════════════════════════════════════════════
# 2. Что НЕ блокируется
# ═════════════════════════════════════════════════════════════════════════════
def test_names_outside_the_card_are_still_answered():
    """Сторож бага 28.07.2026, п.3: гид отвечает по общим знаниям, а не «нет в материалах».

    Для подсказок имя вне карточки — повод снять вопрос (мы его сами предложили
    бы, не зная ответа). Для живого посетителя — законный вопрос.
    """
    for question in ("Кто такой Николай II?", "Что происходило в России в 1917 году?"):
        assert_answered_by_model(*chat(question)[::2], question)


def test_ordinary_visitor_questions_are_answered():
    for question in (
        "Из чего сделано это яйцо?",
        "Кому подарили это яйцо?",
        "Чем уникален этот предмет?",             # «уникальность» запрещена только в подсказках
        "Сколько могло стоить это яйцо?",          # догадка — только в подсказках
        "Какие именно скифские мотивы использовал мастер?",  # повтор — не повод отказывать
        "Почему мастер выбрал сюжет коронации?",
        "Зачем в яйце использован механизм, который поднимает золотую птицу?",
    ):
        assert_answered_by_model(*chat(question)[::2], question)


def test_exclusivity_without_a_card_is_not_blocked():
    """Нет карточки — нечем проверить «единственный», и отказывать не за что."""
    question = "Почему это яйцо стало единственным заказом герцогини?"
    assert_answered_by_model(*chat(question, context=False)[::2], question)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Оговорка про источник и откат
# ═════════════════════════════════════════════════════════════════════════════
def test_choice_explained_by_the_card_goes_to_the_model():
    """«Если источник прямо говорит, почему выбран цвет, — вопрос можно разрешить»."""
    explained = dict(EXHIBIT, raw_history="Розовый цвет был выбран как любимый цвет императрицы.")
    question = "Почему был выбран именно розовый цвет?"
    assert_blocked(*chat(question), question)
    assert_answered_by_model(*chat(question, exhibit_data=explained)[::2], question)


def test_exclusivity_confirmed_by_the_card_goes_to_the_model():
    confirmed = dict(EXHIBIT, raw_history="Единственное яйцо, заказанное герцогиней Мальборо.")
    question = "Почему это яйцо стало единственным заказом герцогини?"
    assert_answered_by_model(*chat(question, exhibit_data=confirmed)[::2], question)


def test_blocking_can_be_switched_off():
    response, session, calls = chat(MUSEUM_EXAMPLES[0], guide_block_banned_questions=False)
    assert_answered_by_model(response, calls, MUSEUM_EXAMPLES[0])
    assert _written(session) == (True, None)


def test_stub_text_comes_from_settings():
    """Формулировку согласует музей — правка слова не должна требовать релиза."""
    text = "Об этом лучше спросить экскурсовода."
    response, _session, calls = chat(MUSEUM_EXAMPLES[0], guide_blocked_answer=text)
    assert calls == 0 and response.answer == text


# ═════════════════════════════════════════════════════════════════════════════
# 4. Причина `blocked_topic` согласована везде
# ═════════════════════════════════════════════════════════════════════════════
_REASON_SET_RE = re.compile(r"fail_reason IN\s*\(([^)]*)\)")


def _reason_sets(text):
    return [frozenset(re.findall(r"'(\w+)'", group)) for group in _REASON_SET_RE.findall(text)]


def _model_reasons():
    """Причины из CHECK модели — из метаданных SQLAlchemy, а не из текста файла."""
    (constraint,) = [
        c for c in m.GuideMessage.__table__.constraints if c.name == "guide_messages_fail_reason_chk"
    ]
    return _reason_sets(str(constraint.sqltext))[0]


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_check_constraint_is_the_same_in_model_schema_and_migration():
    """Рассинхрон CHECK = 500 на каждом заблокированном вопросе вместо заглушки."""
    model_set = _model_reasons()
    schema_sets = _reason_sets(_read("db", "schema.sql"))
    migration = _read("db", "migrations", "2026-09-16_guide_fail_reason_blocked.sql")
    # В миграции первое определение — рабочее, второе — в закомментированном откате.
    migration_set = _reason_sets(migration)[0]
    assert "blocked_topic" in migration_set
    assert len(schema_sets) == 2
    assert model_set == schema_sets[0] == schema_sets[1] == migration_set


def test_every_reason_has_a_label_in_the_analytics_export():
    reasons = _model_reasons()
    assert reasons <= set(analytics_export._FAIL_REASON_LABELS), reasons - set(analytics_export._FAIL_REASON_LABELS)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc!r}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
