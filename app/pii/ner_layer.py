"""
Слой 2: NER (Natasha) — русскоязычные ФИО, организации.
Версия 2 — с фильтром шума, откалиброванным на реальном документе с zakupki.gov.ru
(документация АО «Почта России», 87 тыс. символов): без фильтра Natasha помечала
как ORG аббревиатуры (ЕИС, ЭП, НМЦ), слова-роли («Заказчик», «Общество», «Комиссия»)
и юридические ссылки («Гражданского кодекса», «Правительства РФ»), ломая документ.

Политика (зафиксирована как решение, обсуждаемо с заказчиком):
- PER  -> PERSON, всегда обезличиваем ("Тел." отфильтровываем — ложное срабатывание NER)
- ORG  -> обезличиваем коммерческие организации и их филиалы;
  НЕ трогаем: аббревиатуры-термины, слова-роли из договоров, ссылки на кодексы,
  органы власти и госинституты (они публичны и являются частью правового контекста,
  а не ПД — если заказчик решит иначе, стоп-лист сокращается в одну строку).
"""
from functools import lru_cache

from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter

Span = tuple[int, int, str, str]

# Аббревиатуры-термины закупочной документации (не организации)
_ABBR_STOPLIST = {
    "еис", "эп", "нмц", "нмцк", "тру", "мр", "лс", "рф", "ндс", "смсп",
    "окпд", "окпд2", "оквэд", "оквэд2", "октмо", "окпо", "бик", "ктру",
}
# Слова-роли и юридический контекст (начало нормализованной строки)
_PREFIX_STOPLIST = (
    "заказчик", "исполнител", "поставщик", "подрядчик", "участник", "оператор",
    "общество", "комисси", "сторон", "гарант", "рассмотрен", "реестр",
    "правительств", "центральн", "гражданск", "налогов", "уголовн", "трудов",
    "кодекс", "положени", "минздрав", "министерств", "федеральн", "казначе",
    "информационн", "единая информационная",
)
# Ложные PER, встреченные на реальных документах
_PERSON_STOPLIST = {"тел", "тел.", "факс", "инн", "кпп"}


def _norm(text: str) -> str:
    return text.strip().strip('«»""().,:;').lower()


def _is_noise_org(text: str) -> bool:
    t = _norm(text)
    if not t:
        return True
    if t in _ABBR_STOPLIST:
        return True
    return any(t.startswith(p) for p in _PREFIX_STOPLIST)


@lru_cache(maxsize=1)
def _pipeline():
    return Segmenter(), NewsNERTagger(NewsEmbedding())


def find_ner_pii(text: str) -> list[Span]:
    segmenter, tagger = _pipeline()
    doc = Doc(text)
    doc.segment(segmenter)
    doc.tag_ner(tagger)
    spans: list[Span] = []
    for s in doc.spans:
        value = text[s.start:s.stop]
        if s.type == "PER":
            if _norm(value) in _PERSON_STOPLIST:
                continue
            spans.append((s.start, s.stop, "PERSON", value))
        elif s.type == "ORG":
            if _is_noise_org(value):
                continue
            spans.append((s.start, s.stop, "ORG", value))
        # LOC вне адресного контекста намеренно пропускаем (keep-rate важнее)
    return spans
