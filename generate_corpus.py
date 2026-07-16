"""
Генератор тестового корпуса: фрагменты, стилизованные под документы госзакупок,
договоры и письма. Для каждой вставленной сущности фиксируется ground truth:
- pii-сущности (должны быть вычищены) -> считаем recall
- keep-сущности (даты договоров, сроки, ФЗ, суммы) -> считаем keep-rate
Корпус синтетический: реальные документы с госзакупок использовать для ручной
проверки, но метки на них надо ставить руками (следующий шаг).
"""
import json
import os
import random

random.seed(11)

FIRST = ["Иван", "Пётр", "Сергей", "Алексей", "Мария", "Ольга", "Елена", "Дмитрий", "Анна", "Николай"]
LAST_M = ["Иванов", "Петров", "Сидоров", "Кузнецов", "Смирнов", "Васильев", "Морозов", "Волков"]
LAST_F = ["Иванова", "Петрова", "Кузнецова", "Смирнова", "Морозова", "Волкова"]
MIDDLE_M = ["Иванович", "Петрович", "Сергеевич", "Алексеевич", "Николаевич"]
MIDDLE_F = ["Ивановна", "Петровна", "Сергеевна", "Алексеевна", "Николаевна"]
ORG_WORDS = ["Вектор", "Прогресс", "СтройГарант", "ТехноСфера", "Атлант", "Меридиан", "ЭнергоСоюз", "РегионСнаб"]
CITIES = ["Москва", "Санкт-Петербург", "Казань", "Екатеринбург", "Новосибирск", "Воронеж"]
STREETS = ["Ленина", "Гагарина", "Советская", "Мира", "Центральная", "Промышленная"]


def fio():
    if random.random() < 0.5:
        return f"{random.choice(LAST_M)} {random.choice(FIRST[:5] + ['Пётр','Дмитрий','Николай'])} {random.choice(MIDDLE_M)}"
    return f"{random.choice(LAST_F)} {random.choice(['Мария','Ольга','Елена','Анна'])} {random.choice(MIDDLE_F)}"


def fio_initials():
    return f"{random.choice(LAST_M + LAST_F)} {random.choice('АВДЕИКМНОПС')}.{random.choice('АВДЕИКМНОПС')}."


def phone():
    return random.choice(["+7 ({}) {}-{}-{}", "8({}){}-{}-{}", "+7{}{}{}{}"]).format(
        random.randint(900, 999), random.randint(100, 999), random.randint(10, 99), random.randint(10, 99))


def date_str():
    return f"{random.randint(1,28):02d}.{random.randint(1,12):02d}.{random.randint(1960, 2005)}"


def contract_date():
    return f"{random.randint(1,28):02d}.{random.randint(1,12):02d}.{random.randint(2023, 2026)}"


def org():
    return f"ООО «{random.choice(ORG_WORDS)}»"


# Каждый шаблон: текст с {метками}. pii-поля и keep-поля перечислены явно.
TEMPLATES = [
    {
        "text": "Контракт № {knum} заключен {kdate} между {org1} (ИНН {inn}, КПП {kpp}) в лице директора {fio1} и {org2}. "
                "Срок исполнения обязательств — до {kdate2}. Контактное лицо: {fio2}, тел. {phone}, e-mail {email}.",
        "pii": ["org1", "inn", "kpp", "fio1", "org2", "fio2", "phone", "email"],
        "keep": ["kdate", "kdate2", "knum"],
    },
    {
        "text": "Извещение о проведении закупки по 44-ФЗ. Заказчик: {org1}, адрес: {addr}. "
                "Дата публикации извещения: {kdate}. Ответственный сотрудник — {fio1} ({email}). "
                "Подача заявок до {kdate2}. Начальная цена контракта: {money} руб.",
        "pii": ["org1", "addr", "fio1", "email"],
        "keep": ["kdate", "kdate2", "money"],
    },
    {
        "text": "Заявитель: {fio1}, дата рождения {bdate}, паспорт {pass4} {pass6}, СНИЛС {snils}, "
                "зарегистрирован по адресу: {addr}. Заявление подано {kdate}.",
        "pii": ["fio1", "bdate", "pass4", "pass6", "snils", "addr"],
        "keep": ["kdate"],
    },
    {
        "text": "Победителем признано {org1} (филиал «{branch}» в г. {city_keep}). Договор будет подписан не позднее {kdate}. "
                "Представитель победителя {fio_init} подтвердил готовность. Банковские реквизиты: р/с {account}.",
        "pii": ["org1", "branch", "fio_init", "account"],
        "keep": ["kdate", "city_keep"],
    },
    {
        "text": "Служебная записка. Прошу оформить пропуск для {fio1} (тел. {phone}) на период с {kdate} по {kdate2}. "
                "Основание: договор подряда с {org1} от {kdate3}, ОГРН {ogrn}.",
        "pii": ["fio1", "phone", "org1", "ogrn"],
        "keep": ["kdate", "kdate2", "kdate3"],
    },
    {
        "text": "Акт приема-передачи подписан {kdate}. От заказчика: {fio_init}, от исполнителя: {fio1}, родился {bdate2}. "
                "Оплата на карту {card} произведена в полном объёме {kdate2}.",
        "pii": ["fio_init", "fio1", "bdate2", "card"],
        "keep": ["kdate", "kdate2"],
    },
]


def make_value(field: str):
    if field.startswith("fio_init"):
        return fio_initials()
    if field.startswith("fio"):
        return fio()
    if field.startswith("org"):
        return org()
    if field == "branch":
        return random.choice(["Северный", "Приволжский", "Уральский", "Западный"])
    if field == "inn":
        return str(random.randint(10**9, 10**10 - 1))
    if field == "kpp":
        return str(random.randint(10**8, 10**9 - 1))
    if field == "ogrn":
        return str(random.randint(10**12, 10**13 - 1))
    if field == "snils":
        return f"{random.randint(100,999)}-{random.randint(100,999)}-{random.randint(100,999)} {random.randint(10,99)}"
    if field == "pass4":
        return f"{random.randint(1000,9999)}"
    if field == "pass6":
        return f"{random.randint(100000,999999)}"
    if field == "account":
        return "40702810" + str(random.randint(10**11, 10**12 - 1))
    if field == "card":
        return f"{random.randint(4000,5599)} {random.randint(1000,9999)} {random.randint(1000,9999)} {random.randint(1000,9999)}"
    if field == "phone":
        return phone()
    if field == "email":
        return f"{random.choice(['ivanov','petrov','info','tender','zakupki'])}{random.randint(1,99)}@{random.choice(['mail.ru','yandex.ru','company.ru'])}"
    if field.startswith("bdate"):
        return date_str()
    if field == "addr":
        return f"г. {random.choice(CITIES)}, ул. {random.choice(STREETS)}, д. {random.randint(1,120)}, кв. {random.randint(1,300)}"
    if field.startswith("kdate"):
        return contract_date()
    if field == "knum":
        return f"{random.randint(2024,2026)}-{random.randint(100,999)}"
    if field == "money":
        return f"{random.randint(100,9999)} 000"
    if field == "city_keep":
        return random.choice(CITIES)
    raise ValueError(field)


def generate(n_docs: int = 80):
    docs = []
    for i in range(n_docs):
        tpl = random.choice(TEMPLATES)
        values = {}
        for field in tpl["pii"] + tpl["keep"]:
            values[field] = make_value(field)
        text = tpl["text"].format(**values)
        docs.append({
            "id": i + 1,
            "text": text,
            "pii": [{"field": f, "value": values[f]} for f in tpl["pii"]],
            "keep": [{"field": f, "value": values[f]} for f in tpl["keep"]],
        })
    return docs


if __name__ == "__main__":
    docs = generate(80)
    os.makedirs("data", exist_ok=True)
    with open("data/corpus.json", "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=1)
    n_pii = sum(len(d["pii"]) for d in docs)
    n_keep = sum(len(d["keep"]) for d in docs)
    print(f"Корпус: {len(docs)} документов, {n_pii} ПД-сущностей, {n_keep} keep-сущностей -> data/corpus.json")
