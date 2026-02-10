from __future__ import annotations

import dataclasses
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Dict, Optional

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Request:
    request_id: str
    title: str
    created_by: str
    created_at: datetime
    chat_id: int


REQUESTS: Dict[str, Request] = {}
PENDING_RESPONSES: Dict[int, str] = {}


def parse_admin_ids(raw: str) -> list[int]:
    admin_ids = []
    for value in raw.split(","):
        value = value.strip()
        if not value:
            continue
        admin_ids.append(int(value))
    return admin_ids


def format_request(request: Request) -> str:
    created_time = request.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        "Новая заявка:\n"
        f"• Тема: {request.title}\n"
        f"• Создал: {request.created_by}\n"
        f"• Время: {created_time}\n\n"
        "Нажмите кнопку ниже и отправьте ваш ответ."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Я бот для сбора заявок в группе.\n"
        "Администратор: /request <тема заявки>.\n"
        "Участники: нажмите кнопку и отправьте ответ."
    )


async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    admin_ids = context.bot_data.get("admin_ids", [])
    if admin_ids and update.effective_user.id not in admin_ids:
        await update.message.reply_text("Эта команда доступна только администраторам.")
        return

    if not context.args:
        await update.message.reply_text("Укажите тему заявки: /request молоко")
        return

    title = " ".join(context.args).strip()
    request_id = secrets.token_hex(4)
    created_by = update.effective_user.full_name
    request = Request(
        request_id=request_id,
        title=title,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
        chat_id=update.effective_chat.id,
    )
    REQUESTS[request_id] = request

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Заполнить заявку", callback_data=f"fill:{request_id}")]]
    )

    await update.message.reply_text(format_request(request), reply_markup=keyboard)


async def handle_fill_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    payload = query.data or ""
    if not payload.startswith("fill:"):
        return

    request_id = payload.split(":", 1)[1]
    request = REQUESTS.get(request_id)
    if request is None:
        await query.edit_message_text("Эта заявка уже закрыта или не найдена.")
        return

    user_id = query.from_user.id
    PENDING_RESPONSES[user_id] = request_id

    await query.message.reply_text(
        "Пожалуйста, отправьте ваш ответ одним сообщением (например: количество, комментарий)."
    )


async def handle_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    user_id = update.effective_user.id
    request_id = PENDING_RESPONSES.pop(user_id, None)
    if request_id is None:
        return

    request = REQUESTS.get(request_id)
    if request is None:
        await update.message.reply_text("Заявка не найдена. Попробуйте еще раз.")
        return

    response_text = update.message.text or ""
    admin_ids: list[int] = context.bot_data.get("admin_ids", [])

    response_message = (
        "Ответ на заявку:\n"
        f"• Тема: {request.title}\n"
        f"• Участник: {update.effective_user.full_name} (ID: {user_id})\n"
        f"• Ответ: {response_text}"
    )

    if admin_ids:
        for admin_id in admin_ids:
            await context.bot.send_message(chat_id=admin_id, text=response_message)
    else:
        logger.warning("Admin IDs не настроены, ответ не отправлен администраторам")

    await update.message.reply_text("Спасибо! Ваш ответ отправлен администраторам.")


async def close_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    admin_ids = context.bot_data.get("admin_ids", [])
    if admin_ids and update.effective_user.id not in admin_ids:
        await update.message.reply_text("Эта команда доступна только администраторам.")
        return

    if not context.args:
        await update.message.reply_text("Укажите ID заявки: /close <id>")
        return

    request_id = context.args[0]
    removed = REQUESTS.pop(request_id, None)
    if removed:
        await update.message.reply_text(f"Заявка {request_id} закрыта.")
    else:
        await update.message.reply_text("Заявка не найдена.")


def build_application() -> Optional[object]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN не задан")
        return None

    admin_ids_raw = os.getenv("ADMIN_IDS", "")
    admin_ids = parse_admin_ids(admin_ids_raw) if admin_ids_raw else []

    application = (
        ApplicationBuilder()
        .token(token)
        .build()
    )

    application.bot_data["admin_ids"] = admin_ids

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("request", request_command))
    application.add_handler(CommandHandler("close", close_command))
    application.add_handler(CallbackQueryHandler(handle_fill_callback, pattern=r"^fill:"))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_response)
    )

    return application


def main() -> None:
    application = build_application()
    if application is None:
        raise SystemExit(1)

    logger.info("Bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
