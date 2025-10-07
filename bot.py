import logging
import os
import threading
from dotenv import load_dotenv
from flask import Flask
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Загружаем переменные окружения (.env)
load_dotenv()

# Получаем токен из окружения
TOKEN = os.getenv("YOUR_BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ Ошибка: переменная окружения YOUR_BOT_TOKEN не найдена!")

# Включаем логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask сервер для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Бот работает!"

# --- Основные данные ---
ADMIN_USERNAME = "@mellfreezy"
users = set()
banned_users = set()
send_mode = {}

# --- Команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.full_name or "Без имени"

    if username not in [b[1] for b in banned_users]:
        users.add((user.id, username))
        keyboard = [
            [InlineKeyboardButton("✉️ Отправить сообщение", callback_data="send_message")],
            [InlineKeyboardButton("💖 Поддержать автора", url="https://t.me/mellfreezy_dons")]
        ]
        await update.message.reply_text(
            f"Привет, {username}! 👋\n\nЯ анонимный чат-бот.\nВыбери действие:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text("🚫 Вы заблокированы и не можете использовать бота.")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if f"@{update.effective_user.username}" != ADMIN_USERNAME:
        return await update.message.reply_text("⛔ Доступ запрещён.")

    keyboard = [
        [InlineKeyboardButton("👥 Пользователи", callback_data="show_users")],
        [InlineKeyboardButton("🚫 Забаненные пользователи", callback_data="show_banned")]
    ]
    await update.message.reply_text("⚙️ Админ-панель:", reply_markup=InlineKeyboardMarkup(keyboard))

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.full_name
    if username in [b[1] for b in banned_users]:
        return await update.message.reply_text("🚫 Вы заблокированы.")
    send_mode[update.effective_user.id] = True
    await update.message.reply_text("🗨️ Введите сообщение для отправки…")

# --- Кнопки ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    username = f"@{user.username}" if user.username else user.full_name
    await query.answer()

    if query.data == "send_message":
        if username in [b[1] for b in banned_users]:
            return await query.message.reply_text("🚫 Вы заблокированы.")
        send_mode[user.id] = True
        await query.message.reply_text("🗨️ Введите сообщение для отправки…")

    elif query.data == "show_users":
        if f"@{user.username}" != ADMIN_USERNAME:
            return
        text = "👥 Пользователи:\n" + "\n".join(
            [name for _, name in users]
        ) if users else "Пока нет пользователей."
        await query.message.reply_text(text)

    elif query.data == "show_banned":
        if f"@{user.username}" != ADMIN_USERNAME:
            return
        text = "🚫 Забаненные пользователи:\n" + "\n".join(
            [name for _, name in banned_users]
        ) if banned_users else "Нет забаненных."
        await query.message.reply_text(text)

# --- Обработка сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.full_name
    text = update.message.text

    if username in [b[1] for b in banned_users]:
        return await update.message.reply_text("🚫 Вы заблокированы.")

    if send_mode.get(user.id):
        send_mode[user.id] = False
        for uid, uname in users:
            if uid != user.id and uname not in [b[1] for b in banned_users]:
                try:
                    await context.bot.send_message(uid, f"💬 Анонимное сообщение:\n\n{text}")
                except Exception as e:
                    logger.warning(f"Ошибка при отправке пользователю {uid}: {e}")
        await update.message.reply_text("✅ Сообщение отправлено всем!")
    else:
        await update.message.reply_text("Используйте /send, чтобы отправить сообщение.")

# --- Запуск бота ---
def main():
    app_tg = ApplicationBuilder().token(TOKEN).build()

    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("admin", admin))
    app_tg.add_handler(CommandHandler("send", send_command))
    app_tg.add_handler(CallbackQueryHandler(button_callback))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app_tg.run_polling()

if __name__ == "__main__":
    threading.Thread(target=main).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
