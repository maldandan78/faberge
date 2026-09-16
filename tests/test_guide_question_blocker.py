"""Четыре категории ненужных вопросов (просьба музея 16.09.2026).

Музей прислал список того, что всё ещё попадает в подсказки, с примерами по
каждой категории. Здесь эти примеры закреплены дословно — это приёмка, — а
рядом лежат вопросы, которые обязаны ВЫЖИТЬ. Второй блок в каждой категории
важнее первого: запрещённый вопрос посетитель просто не увидит и всегда может
задать его сам, а хороший вопрос исчезает МОЛЧА (фильтр стоит на чтении и
ничего не логирует), и узнать о потере неоткуда.

  1. Неподтверждённые вопросы — решаются сверкой с карточкой
     (`guide_style.is_unsupported_question`), а не шаблоном.
  2. Предположения о решениях мастера — старый п. II-4, у которого список
     материалов оказался узок: «этот материал», «этот камень», «эта техника».
     С оговоркой музея: подтверждённый источником выбор разрешён.
  3. Бытовые вопросы — «Для чего использовалась бонбоньерка?».
  4. Повторы — пара, которую дедупликация не склеивала.

Тесты старых запретов (пп. II-2/II-4/II-5/II-8 баг-репорта 31.08.2026) лежат в
tests/test_guide_style.py и здесь не дублируются. Сеть и БД не нужны. Запуск:
    python -m pytest tests/test_guide_question_blocker.py
    python tests/test_guide_question_blocker.py     # standalone
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import guide_questions, guide_style  # noqa: E402
from tests.test_guide_questions_cache import EXHIBIT, FakeExhibit, FakeRow, wired  # noqa: E402


# Справка карточки, на которой проверяется сверка с источником. Написана как
# настоящая: имя мастера, год, заказчик и — в последнем предложении — прямое
# объяснение выбора цвета, ради оговорки музея из категории 2.
CARD = (
    "Пасхальное яйцо «Ландыши» изготовлено фирмой Карла Фаберже в 1898 году "
    "по заказу императора Николая II для императрицы Александры Фёдоровны. "
    "Мастер Михаил Перхин покрыл корпус розовой гильошированной эмалью. "
    "Розовый цвет был выбран как любимый цвет императрицы."
)


# ═════════════════════════════════════════════════════════════════════════════
# Категория 1. Неподтверждённые вопросы
# ═════════════════════════════════════════════════════════════════════════════
def test_museum_examples_of_unverified_questions_are_dropped():
    """Оба примера музея. Второй — шаблоном, первый — сверкой с карточкой."""
    assert guide_style.is_meaningless_question("Сколько времени заняло его создание?")
    assert guide_style.is_unsupported_question(
        "Почему это яйцо стало единственным заказом герцогини?", CARD
    )


def test_unverified_name_year_and_exclusivity_are_dropped():
    """Три вида утверждений, которые вопрос вносит от себя и не подтверждает."""
    for question in (
        "Что связывает это яйцо с герцогиней Мальборо?",   # имени в карточке нет
        "Что случилось с яйцом в 1917 году?",              # года в карточке нет
        "Почему яйцо стало единственным в своём роде?",     # исключительность
    ):
        assert guide_style.is_unsupported_question(question, CARD), question


def test_questions_backed_by_the_card_survive():
    """Всё названное есть в справке — вопрос остаётся."""
    for question in (
        "Кому Николай II подарил это яйцо?",
        "Что известно о мастере Михаиле Перхине?",
        "Что произошло в 1898 году?",
        "Кому принадлежало это яйцо?",
        "Из чего сделан корпус?",
    ):
        assert not guide_style.is_unsupported_question(question, CARD), question


def test_faberge_is_answerable_even_without_the_card():
    """«Чем знаменит Карл Фаберже?» музей согласовал как подсказку БЕЗ экспоната.

    Этот вопрос лежит в `guide_questions.MUSEUM_QUESTIONS`, то есть отвечается и
    там, где карточки нет вовсе. Вырезать его у предмета, в описании которого
    фирма не названа, было бы запретом на согласованный музеем вопрос.
    """
    assert not guide_style.is_unsupported_question(
        "Чем знаменит Карл Фаберже?", "Портсигар. Подарен Николаем II."
    )


def test_without_the_card_nothing_is_dropped():
    """Пустая справка выключает сверку, а не вырезает всё подряд.

    Иначе карточка без описания осталась бы вообще без подсказок — это жалоба
    п. II-7 баг-репорта 31.08.2026 («варианты вопросов уже не предлагаются»),
    только устроенная нами самими.
    """
    question = "Что связывает это яйцо с герцогиней Мальборо?"
    assert not guide_style.is_unsupported_question(question, "")
    assert guide_style.drop_unsupported_questions([question], "") == [question]


def test_the_masters_name_comes_from_the_card_fields_not_only_the_story():
    """`card_source` шире, чем `llm.questions_source`, и это не косметика.

    «Что ещё создал мастер Михаил Перхин?» — вопрос из `llm._questions_stub`. В
    тексте истории мастера может не быть ни разу: он лежит отдельным полем
    карточки. Сверяйся мы только с текстом генерации — вопрос вырезался бы как
    неподтверждённый, хотя ответ на него в карточке есть.
    """
    exhibit = dict(EXHIBIT, master_name="Михаил Перхин")
    question = "Что ещё создал мастер Михаил Перхин?"
    assert guide_style.is_unsupported_question(question, guide_questions.card_source(EXHIBIT))
    assert not guide_style.is_unsupported_question(question, guide_questions.card_source(exhibit))


# ═════════════════════════════════════════════════════════════════════════════
# Категория 2. Предположения о решениях мастера
# ═════════════════════════════════════════════════════════════════════════════
# Формулировки, которые музей прислал 16.09.2026 как всё ещё проходящие. Общее у
# них одно: материал назван РОДОВЫМ словом, а пословный список запрета его не
# знал.
GENERIC_MATERIAL_CHOICE = [
    "Почему мастер выбрал именно этот материал?",
    "Почему выбран именно этот камень?",
    "Почему мастер использовал именно такой металл?",
    "Почему выбрана именно эта техника?",
    "Почему для отделки выбран именно этот сплав?",
    "Почему мастер выбрал именно этот оттенок?",
]


def test_generic_material_choice_questions_are_dropped():
    for question in GENERIC_MATERIAL_CHOICE:
        assert guide_style.is_meaningless_question(question), question


def test_technique_choice_is_the_same_ban_as_material_choice():
    """«Для чего использовали технику гильоше?» запрещён, и это не бытовой вопрос.

    Промпт генерации с 31.08.2026 говорит «материал ИЛИ технику» — то есть
    техника всегда была частью той же претензии п. II-4, просто в списке
    запрета её не было. Здесь она названа отдельным тестом, чтобы запрет не
    выглядел случайным следствием правки списка материалов.
    """
    assert guide_style.is_meaningless_question("Для чего использовали технику гильоше?")
    assert guide_style.is_meaningless_question("Почему мастер применил именно эту технику?")
    # А вопрос о самой технике, без «почему выбрали», остаётся.
    assert not guide_style.is_meaningless_question("В какой технике выполнен корпус?")


def test_the_museums_two_examples_are_still_dropped():
    """Дословно из просьбы 16.09.2026, категория 2."""
    assert guide_style.is_meaningless_question("Почему мастер выбрал именно жёлтую эмаль?")
    assert guide_style.is_meaningless_question("Почему использованы именно алмазы?")


def test_explained_choice_is_allowed_by_the_museum():
    """Оговорка музея: «появляется подтверждённый ответ» — вопрос разрешён.

    Запрет держится не на теме, а на отсутствии ответа. Один и тот же вопрос
    запрещён у карточки, которая о цвете молчит, и разрешён у той, которая
    объясняет выбор.
    """
    question = "Почему был выбран именно розовый цвет?"
    assert guide_style.is_meaningless_question(question)
    assert not guide_style.is_meaningless_question(question, CARD)


def test_the_exception_does_not_cover_other_materials_of_the_same_card():
    """Послабление даётся ТОМУ материалу, который карточка объясняет, а не всем.

    В справке объяснён цвет; про выбор эмали там не сказано ничего, и вопрос о
    ней остаётся догадкой о решении мастера.
    """
    assert guide_style.is_meaningless_question("Почему мастер выбрал именно эту эмаль?", CARD)


def test_the_exception_does_not_reopen_the_other_two_bans():
    """Сроки изготовления и «уникальные особенности» музей разрешать не просил."""
    explained = CARD + " Работа заняла два года, и это уникальная особенность заказа."
    assert guide_style.is_meaningless_question("Сколько времени заняло создание этого предмета?", explained)
    assert guide_style.is_meaningless_question(
        "Какие уникальные особенности есть у этой работы Михаила Перхина?", explained
    )


def test_material_questions_about_facts_still_survive():
    """Музей возражает против «почему выбрали именно X», а не против материалов."""
    for question in (
        "Из чего сделан этот предмет?",
        "Из каких материалов он сделан?",
        "В какой технике он выполнен?",
        "Какие камни украшают корпус?",
        "Почему мастер выбрал сюжет коронации?",
        "Почему яйцо назвали «Ландыши»?",
        "Что символизируют цветы на крышке?",
    ):
        assert not guide_style.is_meaningless_question(question), question


# ═════════════════════════════════════════════════════════════════════════════
# Категория 3. Бытовые вопросы
# ═════════════════════════════════════════════════════════════════════════════
def test_everyday_use_questions_are_dropped():
    """Пример музея — первым; остальные его живые формы."""
    for question in (
        "Для чего использовалась бонбоньерка?",
        "Зачем нужна была такая шкатулка?",
        # «нужЕн» вместо «нужна»: беглая гласная — обычный способ пройти мимо
        # списка форм, и на ней шаблон уже один раз промахнулся.
        "Зачем нужен был такой портсигар?",
        "Как использовали эту вещь в быту?",
        "Для чего служил этот портсигар?",
        "Каково было назначение этого ковша?",
    ):
        assert guide_style.is_meaningless_question(question), question


def test_everyday_pattern_is_bound_to_the_thing():
    """Запрет привязан к ТИПУ ВЕЩИ, иначе он выкашивает нормальные вопросы.

    «Зачем в яйце использован механизм…» — вопрос об устройстве сюрприза, и
    слово «яйцо» стоит в нём рядом с глаголом случайно. Ровно на нём первая
    редакция шаблона и сорвалась.
    """
    for question in (
        "Зачем в яйце использован механизм, который поднимает золотую птицу?",
        "Зачем нужен был этот зал?",
        "Для чего служил Шуваловский дворец?",
        "Где хранили это яйцо?",
        "Кто носил эту брошь?",
    ):
        assert not guide_style.is_meaningless_question(question), question


# ═════════════════════════════════════════════════════════════════════════════
# Категория 4. Повторы
# ═════════════════════════════════════════════════════════════════════════════
def test_the_museums_repeat_pair_collapses():
    """Пара из просьбы 16.09.2026 — дословно.

    Расходилась на трёх мелочах сразу: слово-паразит «именно», формы
    «использованы/использовал», которые грубый стеммер разводит, и названный
    мастер как лишняя лемма.
    """
    pair = [
        "Какие скифские мотивы использованы?",
        "Какие именно скифские мотивы использовал мастер?",
    ]
    assert guide_style.dedupe_questions(pair) == pair[:1]


def test_naming_the_author_does_not_make_it_a_new_question():
    """Имя автора в вопросе — признак перефразировки, а не новой темы."""
    pair = [
        "Какие скифские мотивы использованы в браслете?",
        "Какие скифские мотивы Эрик Коллин использовал в дизайне браслета?",
    ]
    assert guide_style.dedupe_questions(pair) == pair[:1]


def test_different_questions_still_stay_apart():
    """Склейка разных вопросов дороже повтора: тема исчезает у всех посетителей."""
    for pool in (
        ["Кто заказал это яйцо?", "Кто подарил это яйцо?"],
        ["Что стоит в витрине 5?", "Что стоит в витрине 12?"],
        ["Из чего сделано яйцо?", "Из чего сделана подставка яйца?"],
    ):
        assert guide_style.dedupe_questions(pool) == pool, pool


# ═════════════════════════════════════════════════════════════════════════════
# Утечки, найденные на проде сразу после релиза 16.09.2026
# ═════════════════════════════════════════════════════════════════════════════
# Дословно из ответов `POST /guide/story` по экспонатам 9 и 30 (прогретый кэш,
# версия функции d4eej45o0uv1cuekbuja). Каждый — формулировка уже запрещённого
# класса, которую шаблон не узнал.
PROD_LEAKS = [
    # сроки изготовления: настоящее время «занимает»
    "Сколько времени обычно занимает создание подобных изделий?",
    # «уникальные особенности этой работы» (п. II-8) другим словом
    "Какие уникальные техники использованы Михаилом Перхиным при создании этого изделия?",
]
PROD_SPECULATION = [
    "Сколько времени могло занять создание такой миниатюры в то время?",
    "Какие символические значения могут нести ландыши в этом произведении?",
]


def test_prod_leaks_are_dropped():
    for question in PROD_LEAKS:
        assert guide_style.is_meaningless_question(question), question


def test_speculative_questions_are_unsupported():
    """Вопрос просит предположение — карточка его не подтверждает по определению."""
    for question in PROD_SPECULATION:
        assert guide_style.is_unsupported_question(question, CARD), question


def test_modal_words_that_are_not_speculation_survive():
    """«Можно ли», «Могут ли» в начале и «обычно» — не догадки о предмете."""
    for question in (
        "Можно ли увидеть другие экспонаты, созданные в той же технике?",
        "Могут ли посетители фотографировать экспонаты?",
        "Что обычно дарили на Пасху при дворе?",
        "Были ли у Карла Фаберже уникальные приёмы в работе, отличающие его от других мастеров?",
    ):
        assert not guide_style.is_meaningless_question(question, CARD), question
        assert not guide_style.is_unsupported_question(question, CARD), question


# ═════════════════════════════════════════════════════════════════════════════
# Выдача: запреты работают на ЧТЕНИИ прогретого кэша
# ═════════════════════════════════════════════════════════════════════════════
# `source_hash` считается по тексту карточки, а не по версии кода: релиз не
# делает несвежей ни одну из 1200+ записей. Без фильтра на выдаче музей увидел
# бы после релиза ровно те же подсказки.
POOL_WITH_LEAKS = [
    "Почему мастер выбрал именно этот материал?",   # категория 2
    "Для чего использовался этот портсигар?",       # категория 3
    "Что связывает портсигар с герцогиней Мальборо?",  # категория 1
    "Кому подарили этот портсигар?",                # годный вопрос
    "Что изображено на крышке?",                    # годный вопрос
]


def _fresh(pool):
    return FakeRow(pool, guide_questions.fingerprint(EXHIBIT))


def test_warmed_pool_is_cleaned_on_read_without_calling_the_model():
    with wired(row=_fresh(POOL_WITH_LEAKS)) as calls:
        questions = asyncio.run(guide_questions.for_exhibit(None, EXHIBIT, 4))
    assert calls["llm"] == [], "чистка на чтении не должна стоить ни одного вызова LLM"
    assert questions == POOL_WITH_LEAKS[3:]


def test_grounding_can_be_switched_off_without_regeneration():
    """`GUIDE_QUESTIONS_GROUNDED=false` снимает только сверку с карточкой.

    Запреты по формулировкам (категории 2 и 3) при этом остаются: у них свой
    флаг, своя цена ошибки и своя история — они пришли из баг-репорта
    31.08.2026.
    """
    with wired(row=_fresh(POOL_WITH_LEAKS), guide_questions_grounded=False) as calls:
        questions = asyncio.run(guide_questions.for_exhibit(None, EXHIBIT, 4))
    assert calls["llm"] == []
    assert questions == POOL_WITH_LEAKS[2:]


def test_generated_pool_is_stored_raw():
    """Отмена запрета не должна требовать перегенерации каталога."""
    with wired(row=None, generated=POOL_WITH_LEAKS, guide_questions_cache_size=8) as calls:
        questions = asyncio.run(guide_questions.for_exhibit(None, EXHIBIT, 4))
    assert calls["saved"][0]["questions"] == POOL_WITH_LEAKS, "в БД пул кладём сырым"
    assert questions == POOL_WITH_LEAKS[3:]


def test_warm_report_shows_what_the_visitor_will_see():
    with wired(row=None) as calls:
        outcome, questions = asyncio.run(
            guide_questions.warm_exhibit(None, FakeExhibit(EXHIBIT), _fresh(POOL_WITH_LEAKS))
        )
    assert outcome == "cached" and calls["llm"] == []
    assert questions == POOL_WITH_LEAKS[3:]


def test_hall_and_museum_sets_are_not_grounded_away():
    """Наборы без экспоната сверять не с чем — они обязаны проходить целиком.

    `MUSEUM_QUESTIONS` называет Карла Фаберже и сам музей: попади они под сверку
    с карточкой портсигара, последняя страховка от пустого блока (п. II-7)
    вырезала бы сама себя.
    """
    assert guide_questions.museum_questions(4) == list(guide_questions.MUSEUM_QUESTIONS)
    assert guide_questions.hall_questions(3) == list(guide_questions.HALL_QUESTIONS)
    # Ярус 4 `select_questions`: ни пула, ни карточки — общий набор про музей.
    assert guide_questions.select_questions([], 4, exhibit=None) == list(
        guide_questions.MUSEUM_QUESTIONS
    )[:4]


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
