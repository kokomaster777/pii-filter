"""
Слой 3 (опциональный, PII_LLM=on): контекстные решения через локальную LLM (Ollama).
Данные не покидают контур — модель локальная, в этом весь смысл.

Зона ответственности слоя — то, что не решается ни форматом, ни типом сущности:
даты без явных маркеров. "12.05.1985" рядом со словом "родился" ловит regex,
а вот "стороны договорились 12.05.1985" трогать нельзя. LLM видит окно контекста
вокруг каждой немаркированной даты и решает: ПД или условие документа.

Дизайн-принцип: LLM НЕ сканирует документ целиком (медленно, дорого, риск пропуска),
а классифицирует короткие кандидат-фрагменты, найденные детерминированно.
"""
import json
import os
import re
import time

import requests

Span = tuple[int, int, str, str]

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("LLM_MODEL", "qwen2.5:3b-instruct")
WINDOW = 90  # символов контекста с каждой стороны

DATE_RX = re.compile(
    r"\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\b"
    r"|\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(?:19|20)\d{2}",
    re.IGNORECASE)

SYSTEM = """Ты определяешь, является ли дата в документе персональными данными.
ПД (ответ REDACT): дата рождения, дата выдачи паспорта, личные даты человека.
НЕ ПД (ответ KEEP): дата договора, срок исполнения, дата публикации, дедлайны, даты законов.
Примеры:
"...Петров, родившийся <ДАТА>12.05.1985</ДАТА>, обязуется..." -> REDACT
"...договор заключен <ДАТА>15.03.2024</ДАТА> сроком на год..." -> KEEP
"...паспорт выдан <ДАТА>01.02.2010</ДАТА> ОВД района..." -> REDACT
"...поставка до <ДАТА>31.12.2026</ДАТА> включительно..." -> KEEP
Ответ: ТОЛЬКО JSON {"decisions": [{"id": 1, "action": "KEEP|REDACT"}, ...]}"""


# Диапазон лет, при которых дата МОЖЕТ быть датой рождения. Даты с годами вне
# диапазона (свежие сроки договоров, дедлайны) оставляются автоматически, без LLM:
# найдено на живом тесте — qwen2.5:3b перестраховывалась и вырезала даты договоров.
# Эвристика снимает с маленькой модели 80-90% кандидатов детерминированно.
BIRTH_YEAR_RANGE = (1930, 2012)
_YEAR_RX = re.compile(r"(19|20)\d{2}")


def _plausible_birth(value: str) -> bool:
    m = _YEAR_RX.search(value)
    if not m:
        return True  # год не распознан — перестраховка, отдаём LLM
    return BIRTH_YEAR_RANGE[0] <= int(m.group()) <= BIRTH_YEAR_RANGE[1]


def _candidates(text: str, taken: list[Span]) -> list[tuple[int, int, str]]:
    """Даты, не накрытые другими слоями И с правдоподобным годом рождения."""
    out = []
    for m in DATE_RX.finditer(text):
        if any(s0 <= m.start() < s1 for s0, s1, *_ in taken):
            continue
        if not _plausible_birth(m.group()):
            continue  # свежий год -> это срок/подписание, оставляем без LLM
        out.append((m.start(), m.end(), m.group()))
    return out


def llm_contextual_spans(text: str, taken: list[Span]) -> tuple[list[Span], dict]:
    usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0, "latency_ms": 0}
    cands = _candidates(text, taken)
    if not cands:
        return [], usage

    lines = []
    for i, (s, e, val) in enumerate(cands, 1):
        ctx = text[max(0, s - WINDOW):s] + f"<ДАТА>{val}</ДАТА>" + text[e:e + WINDOW]
        lines.append(f'{i}. "...{ctx.strip()}..."')
    prompt = "Фрагменты:\n" + "\n".join(lines)

    t0 = time.perf_counter()
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": MODEL, "stream": False,
                  "options": {"temperature": 0, "num_predict": 400},
                  "messages": [{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": prompt}]},
            timeout=300)
        resp.raise_for_status()
        data = resp.json()
        usage.update(requests=1,
                     input_tokens=data.get("prompt_eval_count", 0),
                     output_tokens=data.get("eval_count", 0),
                     latency_ms=int((time.perf_counter() - t0) * 1000))
        m = re.search(r"\{.*\}", data["message"]["content"], re.DOTALL)
        decisions = json.loads(m.group(0))["decisions"] if m else []
        redact_ids = {int(d["id"]) for d in decisions if str(d.get("action")).upper() == "REDACT"}
    except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, TypeError, ValueError):
        redact_ids = set(range(1, len(cands) + 1))  # деградация в safe-режим: сомнение -> вырезать

    return [(s, e, "DATE_PII", v) for i, (s, e, v) in enumerate(cands, 1) if i in redact_ids], usage
