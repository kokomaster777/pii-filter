"""
Слой 1: детерминированные паттерны (regex). Жёсткие форматы — точность ~100%, мгновенно.
Каждый детектор возвращает спаны: (start, end, type, value).

Контекстные даты решаются так: дата рождения почти всегда подписана в документе
("дата рождения", "родился", "г.р.") — это ловит regex. Даты БЕЗ таких маркеров
(дата договора, срок исполнения) по умолчанию НЕ трогаем; спорные уходят в LLM-слой.
"""
import re

Span = tuple[int, int, str, str]  # start, end, type, value

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")),
    # Телефон: +7/8 + ровно 10 цифр с любыми разделителями. Покрывает мобильные
    # (+7 912 345-67-89) и городские с 4-значным кодом (+7 (3463) 45-50-17) —
    # второй формат был пропуском, найденным на реальном договоре с госзакупок.
    # Lookaround'ы не дают цепляться за цифры внутри счетов и реестровых номеров.
    ("PHONE", re.compile(r"(?<!\d)(?:\+7|8)(?:[\s()-]*\d){10}(?!\d)")),
    # Городской номер БЕЗ +7/8 — класс утечки, найденный на реальном документе
    # с zakupki.gov.ru: "Факс (423) 241-21-43" уходил в чистом виде.
    # Ловим по контекстному маркеру (тел/факс) либо по строгому формату (XXX[X]) NN-NN-NN.
    ("PHONE_LANDLINE", re.compile(
        r"(?:тел(?:ефон)?|факс)\s*[.:]?\s*(\(\d{3,5}\)\s*\d{2,3}[\s-]?\d{2}[\s-]?\d{2})", re.IGNORECASE)),
    ("PHONE_LANDLINE_FMT", re.compile(r"(?<!\d)\(\d{3,4}\)\s*\d{2,3}-\d{2}-\d{2}(?!\d)")),
    ("SNILS", re.compile(r"\b\d{3}-\d{3}-\d{3}[- ]\d{2}\b")),
    ("CARD", re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}\b")),
    ("ACCOUNT", re.compile(r"(?:р/с|расчетный счет|расчётный счёт|счет №|счёт №)\s*(\d{20})\b", re.IGNORECASE)),
    ("INN", re.compile(r"(?:ИНН)[:\s]*(\d{10}|\d{12})\b")),
    ("OGRN", re.compile(r"(?:ОГРНИП|ОГРН)[:\s]*(\d{13}|\d{15})\b")),
    ("KPP", re.compile(r"(?:КПП)[:\s]*(\d{9})\b")),
    ("PASSPORT", re.compile(
        r"(?:паспорт(?:\s+РФ)?|серия)[:\s]*(\d{4})\s*(?:№|N|номер)?\s*(\d{6})\b", re.IGNORECASE)),
    # Дата рождения: маркер + дата (dd.mm.yyyy или "3 июня 1987")
    ("BIRTH_DATE", re.compile(
        r"(?:дата рождения|родил(?:ся|ась)|г\.\s?р\.)[:\s]*"
        r"(\d{1,2}[./]\d{1,2}[./]\d{4}(?:\s?г(?:ода|\.)?)?"
        r"|\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}(?:\s?года)?)",
        re.IGNORECASE)),
    # Адрес: маркер + структурный паттерн (г. X, ул. Y, д. N, кв. M) — не жадный,
    # чтобы не заглатывать следующее предложение
    ("ADDRESS", re.compile(
        r"(?:адрес(?:\s+регистрации|\s+проживания)?|зарегистрирован(?:а)?\s+по\s+адресу|проживает по адресу)"
        r"[:\s]+((?:г\.|город)\s*[А-ЯЁ][а-яё\-]+"
        r"(?:\s*,\s*(?:ул\.|улица|пер\.|просп\.|пр-т|наб\.)\s*[А-ЯЁ][а-яё\-]+)?"
        r"(?:\s*,\s*д\.\s*\d+[А-Яа-я]?)?"
        r"(?:\s*,\s*(?:корп\.|стр\.)\s*\d+)?"
        r"(?:\s*,\s*(?:кв\.|оф\.|пом\.)\s*\d+)?)", re.IGNORECASE)),
    # ФИО с инициалами: "Иванов И.И." / "И.И. Иванов" — страховка для NER
    ("PERSON_INITIALS", re.compile(
        r"\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.(?!\s*[а-яё])|\b[А-ЯЁ]\.\s?[А-ЯЁ]\.\s+[А-ЯЁ][а-яё]+\b")),
]

# Типы, где ПД — только captured group, а не весь матч (маркер оставляем в тексте)
GROUP_TYPES = {"INN", "OGRN", "KPP", "ACCOUNT", "BIRTH_DATE", "ADDRESS", "PHONE_LANDLINE"}
TYPE_MAP = {"PERSON_INITIALS": "PERSON", "PHONE_LANDLINE": "PHONE", "PHONE_LANDLINE_FMT": "PHONE"}


def find_regex_pii(text: str) -> list[Span]:
    spans: list[Span] = []
    for ptype, rx in PATTERNS:
        for m in rx.finditer(text):
            if ptype == "PASSPORT" and m.lastindex and m.lastindex >= 2:
                for g in (1, 2):
                    spans.append((m.start(g), m.end(g), ptype, m.group(g)))
                continue
            if ptype in GROUP_TYPES and m.lastindex:
                spans.append((m.start(1), m.end(1), TYPE_MAP.get(ptype, ptype), m.group(1)))
            else:
                out_type = TYPE_MAP.get(ptype, ptype)
                spans.append((m.start(), m.end(), out_type, m.group()))
    return spans
