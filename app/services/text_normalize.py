"""Нормализация текста перед отправкой в синтез речи.

Главная задача — римские цифры. SpeechKit (и любой TTS) читает «XIX век» как
буквы («икс-и-икс»), а «Александр III» — как «Александр Ай-Ай-Ай». Поэтому перед
озвучкой заменяем римские числа на арабские: «XIX» → «19», «Александр III» →
«Александр 3».
"""
from __future__ import annotations

import re

# Канонический римский numeral (1..3999), только заглавные латинские буквы —
# именно так в текстах пишут века и порядковые имена монархов. Соседи слева и
# справа не должны быть буквами (ни латиница, ни кириллица), иначе зацепим часть
# слова вроде «VIVA» или «MIX». Lookahead [IVXLCDM] отсекает пустые совпадения.
_ROMAN_RE = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])"
    r"(?=[IVXLCDM])"
    r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"
    r"(?![A-Za-zА-Яа-яЁё])"
)

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_to_int(roman: str) -> int:
    total = 0
    prev = 0
    for ch in reversed(roman):
        value = _ROMAN_VALUES[ch]
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total


def roman_to_arabic(text: str) -> str:
    """Заменяет отдельные римские числа в тексте на арабские.

    Затрагивает только самостоятельные токены из заглавных латинских I/V/X/L/C/D/M,
    являющиеся корректным римским числом. Кириллический текст и обычные слова не
    трогает.
    """
    if not text:
        return text
    return _ROMAN_RE.sub(lambda m: str(_roman_to_int(m.group(0))), text)


def normalize_for_tts(text: str) -> str:
    """Полная подготовка текста к озвучке (сейчас — только римские цифры)."""
    return roman_to_arabic(text)
