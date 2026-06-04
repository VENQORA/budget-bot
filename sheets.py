import os
import json
from datetime import datetime
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_ID = os.getenv("GOOGLE_SHEETS_ID")
CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

HEADERS = ["Дата", "Тип", "Сумма", "Категория", "Комментарий", "Кто внёс"]


def _get_client():
    creds_dict = json.loads(CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_spreadsheet():
    return _get_client().open_by_key(SHEET_ID)


def _get_transactions_sheet():
    spreadsheet = _get_spreadsheet()
    try:
        sheet = spreadsheet.worksheet("Транзакции")
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet("Транзакции", rows=1000, cols=10)
        sheet.append_row(HEADERS)
    return sheet


def ensure_sheets_exist():
    """Create sheets with headers if they don't exist yet."""
    spreadsheet = _get_spreadsheet()
    existing = [ws.title for ws in spreadsheet.worksheets()]

    if "Транзакции" not in existing:
        sheet = spreadsheet.add_worksheet("Транзакции", rows=1000, cols=10)
        sheet.append_row(HEADERS)

    if "Настройки" not in existing:
        settings = spreadsheet.add_worksheet("Настройки", rows=20, cols=3)
        settings.append_row(["Категория", "Лимит (₽)", "Комментарий"])
        categories = [
            "Продукты", "Рестораны/кафе", "Транспорт", "Здоровье/аптека",
            "Одежда", "Дети", "Подписки", "Развлечения", "Коммуналка", "Прочее",
        ]
        for cat in categories:
            settings.append_row([cat, "", ""])


def add_transaction(date: str, type_: str, amount: float, category: str, comment: str, user: str):
    sheet = _get_transactions_sheet()
    sheet.append_row([date, type_, float(amount), category, comment, user])


def get_month_transactions(year: int, month: int) -> list[dict]:
    sheet = _get_transactions_sheet()
    rows = sheet.get_all_records()
    result = []
    for row in rows:
        date_str = str(row.get("Дата", "")).strip()
        if not date_str:
            continue
        try:
            date = datetime.strptime(date_str, "%d.%m.%Y")
        except ValueError:
            continue
        if date.year == year and date.month == month:
            result.append(row)
    return result


def get_balance() -> dict:
    now = datetime.now()
    transactions = get_month_transactions(now.year, now.month)
    income = sum(
        float(t.get("Сумма", 0) or 0)
        for t in transactions
        if str(t.get("Тип", "")).strip() == "доход"
    )
    expense = sum(
        float(t.get("Сумма", 0) or 0)
        for t in transactions
        if str(t.get("Тип", "")).strip() == "расход"
    )
    return {"income": income, "expense": expense, "balance": income - expense}
