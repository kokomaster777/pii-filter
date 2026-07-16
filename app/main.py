"""
PII-фильтр: прослойка для корпоративного LLM-гейтвея.
Один эндпоинт /clean: принимает текст ИЛИ файл -> возвращает обезличенный текст,
словарь замен, тайминги по слоям и расход токенов LLM-слоя.

Каскад: regex (форматы) -> NER Natasha (ФИО/организации) -> LLM (контекстные даты, опционально).
LLM-слой включается переменной PII_LLM=on (нужна запущенная Ollama); без него
немаркированные даты не трогаются (маркированные "дата рождения: ..." ловит regex).

Защита от повреждённого входа: если текст выглядит как каша после плохого OCR
(PDF-скан с кривым текстовым слоем), очистка ОТКЛОНЯЕТСЯ с явной ошибкой.
Причина: на таком тексте regex и NER молча пропускают ПД ("Ten+1(3463) 45-50-17"
не ловится паттерном телефона) — тихий успех опаснее отказа.
"""
import os
import re
import time

from fastapi import FastAPI, File, UploadFile, Form
from pydantic import BaseModel

from .extract import extract_text
from .pii.anonymizer import anonymize, merge_spans
from .pii.ner_layer import find_ner_pii
from .pii.regex_layer import find_regex_pii

app = FastAPI(title="PII filter for LLM gateway")
LLM_ENABLED = os.environ.get("PII_LLM", "off").lower() in ("on", "1", "true")

# Минимальная доля кириллицы среди букв, чтобы считать русский текст «здоровым».
# У нормальных русских документов она > 0.7; у OCR-каши («Merqepqrcosa B.[.») — близка к 0.
CYRILLIC_MIN_RATIO = float(os.environ.get("PII_CYRILLIC_MIN_RATIO", "0.5"))


class CleanRequest(BaseModel):
    text: str


def _cyrillic_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
    if not letters:
        return 1.0  # нет букв вообще (пусто/цифры) — пусть решают слои дальше
    cyr = re.findall(r"[А-Яа-яЁё]", text)
    return len(cyr) / len(letters)


def clean_text(text: str) -> dict:
    # --- Защита: повреждённый вход (обычно PDF-скан с кривым OCR-слоем) ---
    ratio = _cyrillic_ratio(text)
    if ratio < CYRILLIC_MIN_RATIO:
        return {
            "cleaned_text": None,
            "error": (
                f"Текст выглядит повреждённым (доля кириллицы {ratio:.0%} < "
                f"{CYRILLIC_MIN_RATIO:.0%}). Вероятно, PDF-скан с некачественным "
                "OCR-слоем. Очистка отклонена: на таком тексте детекторы молча "
                "пропускают ПД. Нужен документ с нормальным текстовым слоем "
                "или предварительный OCR (например, Tesseract)."
            ),
            "replacements": {},
            "entities_found": 0,
            "timings": {},
            "llm_usage": None,
        }

    timings = {}
    t = time.perf_counter()
    spans = find_regex_pii(text)
    timings["regex_ms"] = round((time.perf_counter() - t) * 1000, 2)

    t = time.perf_counter()
    spans += find_ner_pii(text)
    timings["ner_ms"] = round((time.perf_counter() - t) * 1000, 2)

    llm_usage = None
    if LLM_ENABLED:
        from .pii.llm_layer import llm_contextual_spans
        merged_so_far = merge_spans(spans)
        llm_spans, llm_usage = llm_contextual_spans(text, merged_so_far)
        spans += llm_spans
        timings["llm_ms"] = llm_usage["latency_ms"]

    cleaned, mapping = anonymize(text, spans)
    timings["total_ms"] = round(sum(v for v in timings.values()), 2)
    return {
        "cleaned_text": cleaned,
        "replacements": mapping,
        "entities_found": len(mapping),
        "timings": timings,
        "llm_usage": llm_usage,
    }


@app.post("/clean")
async def clean(text: str | None = Form(None), file: UploadFile | None = File(None)):
    """Гейтвей шлёт либо form-поле text, либо файл. Интерфейс один."""
    if file is not None:
        try:
            raw = extract_text(file.filename or "upload.txt", await file.read())
        except ValueError as e:  # напр., старый .doc
            return {"cleaned_text": None, "error": str(e), "replacements": {},
                    "entities_found": 0, "timings": {}, "llm_usage": None}
    elif text is not None:
        raw = text
    else:
        return {"error": "передайте text или file"}
    return clean_text(raw)


@app.post("/clean/json")
def clean_json(body: CleanRequest):
    """То же самое для JSON-клиентов."""
    return clean_text(body.text)


@app.get("/health")
def health():
    return {"status": "ok", "llm_layer": LLM_ENABLED}
