import os
import base64
import logging
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from gpt import generate_report, parse_expense, parse_income, parse_receipt
from sheets import add_transaction, ensure_sheets_exist, get_balance, get_month_transactions

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MY_TELEGRAM_ID = int(os.getenv("MY_TELEGRAM_ID", "0"))

INCOME_KEYWORDS = [
    "получил", "получила", "получили",
    "пришло", "поступило", "зарплата", "зп",
    "доход", "поступление", "заработал", "заработала",
    "перевод", "аванс",
]

CATEGORIES = [
    "Продукты", "Рестораны/кафе", "Транспорт", "Здоровье/аптека",
    "Одежда", "Дети", "Подписки", "Развлечения", "Коммуналка", "Прочее",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _is_income(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in INCOME_KEYWORDS)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Да", callback_data="confirm_yes"),
        InlineKeyboardButton("❌ Нет", callback_data="confirm_no"),
    ]])


def _category_keyboard() -> InlineKeyboardMarkup:
    rows, row = [], []
    for cat in CATEGORIES:
        row.append(InlineKeyboardButton(cat, callback_data=f"cat_{cat}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _format_entry(data: dict) -> str:
    if data["type"] == "доход":
        return (
            f"📥 *Доход:* {data['amount']:,.0f} ₽\n"
            f"💬 {data.get('comment', '—')}"
        )
    return (
        f"📤 *Расход:* {data['amount']:,.0f} ₽\n"
        f"🏷 Категория: {data.get('category', '—')}\n"
        f"💬 {data.get('comment', '—')}"
    )


def _needs_category(data: dict) -> bool:
    return data["type"] == "расход" and data.get("category") in (
        None, "", "Прочее", "Не определено", "прочее",
    )


# ── command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет\\! Я бот для учёта семейного бюджета\\.\n\n"
        "*Как пользоваться:*\n"
        "• Отправь текст с расходом:\n"
        "  _«Потратил 1500 на продукты в Перекрёстке»_\n"
        "• Или с доходом:\n"
        "  _«Пришла зарплата 80000»_\n"
        "• Или просто фото чека 🧾\n\n"
        "*Команды:*\n"
        "/balance — баланс за текущий месяц\n"
        "/report — отчёт за месяц \\(только для владельца\\)",
        parse_mode="MarkdownV2",
    )


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bal = get_balance()
        month = datetime.now().strftime("%B %Y")
        sign = "✅" if bal["balance"] >= 0 else "⚠️"
        text = (
            f"💰 *Баланс за {month}*\n\n"
            f"📈 Доходы: `{bal['income']:,.0f} ₽`\n"
            f"📉 Расходы: `{bal['expense']:,.0f} ₽`\n"
            f"{sign} Остаток: `{bal['balance']:,.0f} ₽`"
        )
    except Exception as e:
        logger.error("balance error: %s", e)
        text = "❌ Не удалось получить баланс. Попробуйте позже."
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MY_TELEGRAM_ID:
        await update.message.reply_text("⛔ Эта команда доступна только владельцу.")
        return
    await update.message.reply_text("⏳ Генерирую отчёт…")
    try:
        now = datetime.now()
        transactions = get_month_transactions(now.year, now.month)
        bal = get_balance()
        text = generate_report(transactions, bal)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error("report error: %s", e)
        await update.message.reply_text("❌ Ошибка при генерации отчёта.")


# ── message handlers ──────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_name = update.effective_user.first_name or str(update.effective_user.id)
    try:
        data = parse_income(text) if _is_income(text) else parse_expense(text)
        data["user"] = user_name
        context.user_data["pending"] = data

        if _needs_category(data):
            await update.message.reply_text(
                f"Категория не определена.\n\n{_format_entry(data)}\n\nВыберите категорию:",
                reply_markup=_category_keyboard(),
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"Записать?\n\n{_format_entry(data)}",
                reply_markup=_confirm_keyboard(),
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error("text handler error: %s", e)
        await update.message.reply_text(
            "❌ Не удалось распознать сообщение.\n"
            "Попробуйте написать иначе, например:\n"
            "«Потратил 500 на кофе» или «Зарплата 80000»"
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name or str(update.effective_user.id)
    msg = await update.message.reply_text("🔍 Распознаю чек…")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")

        data = parse_receipt(image_b64)
        data["user"] = user_name
        context.user_data["pending"] = data

        await msg.delete()

        if _needs_category(data):
            await update.message.reply_text(
                f"Чек распознан, но категория не определена.\n\n{_format_entry(data)}\n\nВыберите категорию:",
                reply_markup=_category_keyboard(),
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"Записать?\n\n{_format_entry(data)}",
                reply_markup=_confirm_keyboard(),
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error("photo handler error: %s", e)
        await msg.edit_text("❌ Не удалось распознать чек. Попробуйте ещё раз.")


# ── callback handler ──────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data

    if key.startswith("cat_"):
        category = key[4:]
        pending = context.user_data.get("pending")
        if not pending:
            await query.edit_message_text("⚠️ Сессия устарела. Отправьте сообщение заново.")
            return
        pending["category"] = category
        await query.edit_message_text(
            f"Записать?\n\n{_format_entry(pending)}",
            reply_markup=_confirm_keyboard(),
            parse_mode="Markdown",
        )
        return

    if key == "confirm_no":
        context.user_data.pop("pending", None)
        await query.edit_message_text("❌ Отменено.")
        return

    if key == "confirm_yes":
        pending = context.user_data.pop("pending", None)
        if not pending:
            await query.edit_message_text("⚠️ Нет данных для записи. Отправьте сообщение заново.")
            return
        try:
            add_transaction(
                date=datetime.now().strftime("%d.%m.%Y"),
                type_=pending["type"],
                amount=pending["amount"],
                category=pending.get("category", "—"),
                comment=pending.get("comment", ""),
                user=pending.get("user", "—"),
            )
            await query.edit_message_text(
                f"✅ Записано!\n\n{_format_entry(pending)}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("save error: %s", e)
            await query.edit_message_text("❌ Ошибка при сохранении. Попробуйте позже.")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ensure_sheets_exist()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Budget bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
