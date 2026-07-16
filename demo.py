"""Демо «до/после»: чистим документ и печатаем результат. python demo.py [файл]"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.main import clean_text
from app.extract import extract_text

if len(sys.argv) > 1:
    path = sys.argv[1]
    with open(path, "rb") as f:
        try:
            text = extract_text(path, f.read())
        except ValueError as e:
            print(f"ОТКАЗ НА ЭТАПЕ ЧТЕНИЯ ФАЙЛА: {e}")
            sys.exit(1)
else:
    text = open("data/sample_contract.txt", encoding="utf-8").read()

res = clean_text(text)
if res.get("error"):
    print("=== ДО (первые 500 символов) ===\n" + text[:500])
    print(f"\nОЧИСТКА ОТКЛОНЕНА: {res['error']}")
    sys.exit(1)

print("=== ДО ===\n" + text)
print("\n=== ПОСЛЕ ===\n" + res["cleaned_text"])
print(f"\nСущностей обезличено: {res['entities_found']} | тайминги: {res['timings']}")
if res.get("llm_usage"):
    print("LLM:", res["llm_usage"])
