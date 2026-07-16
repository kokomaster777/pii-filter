"""
Обезличивание: слияние спанов от всех слоёв + стабильные плейсхолдеры.
Стабильность: один и тот же Иванов во всём документе -> всегда {PERSON_1},
иначе текст теряет связность для LLM на принимающей стороне.
Возвращаем словарь замен -> возможна обратная подстановка (де-анонимизация ответа).
"""
import re

Span = tuple[int, int, str, str]


def merge_spans(spans: list[Span]) -> list[Span]:
    """Убираем перекрытия: приоритет более длинному спану (обычно точнее)."""
    spans = sorted(spans, key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list[Span] = []
    last_end = -1
    for s in spans:
        if s[0] >= last_end:
            merged.append(s)
            last_end = s[1]
        elif s[1] > last_end:  # частичное перекрытие — расширяем предыдущий
            prev = merged[-1]
            merged[-1] = (prev[0], s[1], prev[2], prev[3])
            last_end = s[1]
    return merged


def _norm(value: str) -> str:
    v = re.sub(r"[\s\-().]", "", value.lower())
    return v


def anonymize(text: str, spans: list[Span]) -> tuple[str, dict[str, str]]:
    spans = merge_spans(spans)
    counters: dict[str, int] = {}
    placeholder_by_key: dict[tuple[str, str], str] = {}
    mapping: dict[str, str] = {}  # placeholder -> исходное значение

    out: list[str] = []
    cursor = 0
    for start, end, ptype, value in spans:
        key = (ptype, _norm(value))
        if key not in placeholder_by_key:
            counters[ptype] = counters.get(ptype, 0) + 1
            ph = f"{{{ptype}_{counters[ptype]}}}"
            placeholder_by_key[key] = ph
            mapping[ph] = value
        out.append(text[cursor:start])
        out.append(placeholder_by_key[key])
        cursor = end
    out.append(text[cursor:])
    return "".join(out), mapping
