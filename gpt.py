import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CATEGORIES = [
    "Продукты", "Рестораны/кафе", "Транспорт", "Здоровье/аптека",
    "Одежда", "Дети", "Подписки", "Развлечения", "Коммуналка", "Прочее",
]
CATEGORIES_STR = ", ".join(CATEGORIES)


def _extract_json(content: str) -> dict:
    content = content.strip()
    # Strip markdown code blocks if present
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
    return json.loads(content)


def parse_expense(text: str) -> dict:
    prompt = (
        f"Ты — финансовый ассистент. Извлеки из текста информацию о расходе.\n\n"
        f"Категории: {CATEGORIES_STR}\n\n"
        "Верни JSON строго в формате:\n"
        '{"type": "расход", "amount": <число>, "category": "<категория>", "comment": "<комментарий>"}\n\n'
        "Правила:\n"
        "- amount — число (без ₽ и пробелов)\n"
        "- category — строго из списка выше\n"
        "- comment — название магазина/услуги кратко\n"
        "- Если категория неизвестна — используй «Прочее»\n\n"
        f"Текст: {text}"
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=200,
    )
    return _extract_json(response.choices[0].message.content)


def parse_income(text: str) -> dict:
    prompt = (
        "Ты — финансовый ассистент. Извлеки из текста информацию о доходе.\n\n"
        "Верни JSON строго в формате:\n"
        '{"type": "доход", "amount": <число>, "comment": "<комментарий>"}\n\n'
        "Правила:\n"
        "- amount — число (без ₽)\n"
        "- comment — источник дохода кратко (например: Зарплата, Фриланс, Аренда)\n\n"
        f"Текст: {text}"
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=200,
    )
    return _extract_json(response.choices[0].message.content)


def parse_receipt(image_base64: str) -> dict:
    prompt = (
        f"Ты — финансовый ассистент. Распознай чек на изображении и извлеки данные о расходе.\n\n"
        f"Категории: {CATEGORIES_STR}\n\n"
        "Верни JSON строго в формате:\n"
        '{"type": "расход", "amount": <итоговая сумма числом>, "category": "<категория>", "comment": "<название магазина>"}\n\n'
        "Правила:\n"
        "- amount — итоговая сумма к оплате (числом, без ₽)\n"
        "- category — строго из списка выше\n"
        "- comment — название магазина/заведения с чека\n"
        "- Если категория неизвестна — используй «Прочее»"
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        temperature=0,
        max_tokens=300,
    )
    return _extract_json(response.choices[0].message.content)


def generate_report(transactions: list, balance: dict) -> str:
    if not transactions:
        return "📊 За этот месяц нет транзакций."

    prompt = (
        "Ты — семейный финансовый аналитик. Составь детальный отчёт по бюджету на русском языке.\n\n"
        f"Транзакции за месяц:\n{json.dumps(transactions, ensure_ascii=False, indent=2)}\n\n"
        f"Баланс: доходы {balance['income']} ₽, расходы {balance['expense']} ₽, "
        f"остаток {balance['balance']} ₽\n\n"
        "Структура отчёта (используй Markdown):\n"
        "1. **Итоговая сводка** — получено / потрачено / остаток\n"
        "2. **Расходы по категориям** — сумма и % от общего, отсортировано по убыванию\n"
        "3. **Топ-3 категории перерасхода** — конкретные цифры\n"
        "4. **Рекомендации по экономии** — конкретные действия с указанием суммы в рублях\n\n"
        "Будь конкретным, используй реальные цифры из данных. Без воды."
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1500,
    )
    return response.choices[0].message.content
