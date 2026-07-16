"""
Оценка PII-фильтра на корпусе с ground truth.
- recall: доля ПД-сущностей, чьё значение исчезло из очищенного текста (цель ~99%)
- keep-rate: доля keep-сущностей (даты договоров, сроки, номера), оставшихся нетронутыми
- latency: мс/документ по слоям
Запуск:  python evaluate.py            (regex + NER)
         PII_LLM=on python evaluate.py (полный каскад, нужна Ollama)
"""
import json
import statistics
import time
from collections import defaultdict

from app.main import clean_text


def value_gone(cleaned: str, value: str) -> bool:
    """ПД считается вычищенным, если его значение не встречается в тексте.
    Для составных значений (ФИО, адрес) — не должно остаться ни одного
    информативного куска длиннее 3 символов."""
    if value in cleaned:
        return False
    parts = [p for p in value.replace(",", " ").split() if len(p) > 3 and not p.isdigit()]
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits and len(digits) >= 6 and digits in "".join(ch for ch in cleaned if ch.isdigit()):
        return False
    return not any(p in cleaned for p in parts)


def main():
    with open("data/corpus.json", encoding="utf-8") as f:
        docs = json.load(f)

    pii_stats = defaultdict(lambda: {"n": 0, "gone": 0})
    keep_total = keep_ok = 0
    latencies = []
    llm_tokens = {"input": 0, "output": 0}
    misses, false_redactions = [], []

    for d in docs:
        t0 = time.perf_counter()
        res = clean_text(d["text"])
        latencies.append((time.perf_counter() - t0) * 1000)
        cleaned = res["cleaned_text"]
        if res.get("llm_usage"):
            llm_tokens["input"] += res["llm_usage"]["input_tokens"]
            llm_tokens["output"] += res["llm_usage"]["output_tokens"]

        for ent in d["pii"]:
            pii_stats[ent["field"].rstrip("123456789")]["n"] += 1
            if value_gone(cleaned, ent["value"]):
                pii_stats[ent["field"].rstrip("123456789")]["gone"] += 1
            else:
                misses.append((d["id"], ent["field"], ent["value"]))
        for ent in d["keep"]:
            keep_total += 1
            if ent["value"] in cleaned:
                keep_ok += 1
            else:
                false_redactions.append((d["id"], ent["field"], ent["value"]))

    n_pii = sum(s["n"] for s in pii_stats.values())
    n_gone = sum(s["gone"] for s in pii_stats.values())

    lines = ["# Отчёт: PII-фильтр\n"]
    lines.append(f"Документов: **{len(docs)}**, ПД-сущностей: **{n_pii}**, keep-сущностей: **{keep_total}**\n")
    lines.append(f"## Recall (вычищено ПД): **{n_gone/n_pii:.2%}**")
    lines.append(f"## Keep-rate (не тронуто лишнего): **{keep_ok/keep_total:.2%}**")
    lines.append(f"## Задержка: медиана **{statistics.median(latencies):.1f} мс/док**, "
                 f"p95 {sorted(latencies)[int(len(latencies)*0.95)]:.1f} мс\n")
    if llm_tokens["input"]:
        lines.append(f"LLM-слой: {llm_tokens['input']} in / {llm_tokens['output']} out токенов "
                     f"({llm_tokens['input']/len(docs):.0f} ток./док)\n")
    lines.append("## Recall по типам\n")
    lines.append("| Тип | N | Вычищено |")
    lines.append("|---|---|---|")
    for field, s in sorted(pii_stats.items(), key=lambda x: -x[1]["n"]):
        lines.append(f"| {field} | {s['n']} | {s['gone']/s['n']:.1%} |")
    if misses:
        lines.append("\n## Пропуски (для разбора)\n")
        for doc_id, field, value in misses[:15]:
            lines.append(f"- док {doc_id}, {field}: `{value}`")
    if false_redactions:
        lines.append("\n## Ложные вырезания keep-сущностей\n")
        for doc_id, field, value in false_redactions[:15]:
            lines.append(f"- док {doc_id}, {field}: `{value}`")

    report = "\n".join(lines)
    import os
    os.makedirs("results", exist_ok=True)
    with open("results/report.md", "w", encoding="utf-8") as f:
        f.write(report)
    print(report)


if __name__ == "__main__":
    main()
