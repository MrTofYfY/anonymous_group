# bot.py
import os
import json
import random
import logging
from dotenv import load_dotenv
from flask import Flask, send_file
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# -------------------------
# Настройка и загрузка TOKEN
# -------------------------
load_dotenv()
TOKEN = os.getenv("YOUR_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Переменная окружения YOUR_BOT_TOKEN не задана.")

# -------------------------
# Логирование
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs.txt", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# -------------------------
# Flask
# -------------------------
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "✅ Telegram bot is running!"

@flask_app.route("/logs")
def serve_logs():
    return send_file("logs.txt", as_attachment=True)

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

# -------------------------
# Данные
# -------------------------
DATA_FILE = "data.json"

def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}, "admins": [], "banned": [], "permissions": {}, "message_count": 0, "admin_chat_enabled": False}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(DATA, f, ensure_ascii=False, indent=2)

DATA = load_data()

# -------------------------
# Вспомогательные функции
# -------------------------
def ensure_user_registered(user):
    uid = str(user.id)
    if uid not in DATA["users"]:
        anon = random.randint(1, 99999)
        DATA["users"][uid] = {"username": user.username if user.username else None, "anon": anon, "muted_until": 0}
        save_data()

def init_admin_if_none(admin_username="@mellfreezy"):
    if admin_username not in DATA["admins"]:
        DATA["admins"].append(admin_username)
    if admin_username not in DATA["permissions"]:
        DATA["permissions"][admin_username] = {p: True for p in ["broadcast","impersonate","manage_perms","stats","mute","export","admin_chat","private_reply"]}
    save_data()

init_admin_if_none()

# -------------------------
# UI
# -------------------------
def admin_panel_keyboard():
    kb = [
        [InlineKeyboardButton("👥 Пользователи", callback_data="SHOW_USERS")],
        [InlineKeyboardButton("🧑‍💼 Администраторы", callback_data="SHOW_ADMINS")],
        [InlineKeyboardButton("📊 Статистика", callback_data="SHOW_STATS")],
        [InlineKeyboardButton("➕ Добавить админа", callback_data="ADD_ADMIN"),
         InlineKeyboardButton("➖ Удалить админа", callback_data="REMOVE_ADMIN")],
        [InlineKeyboardButton("⚙️ Настроить права", callback_data="SET_PERMS"),
         InlineKeyboardButton("⏱️ Тайм-аут / Мут", callback_data="MUTE_USER")],
        [InlineKeyboardButton("📤 Экспорт данных", callback_data="EXPORT_DATA"),
         InlineKeyboardButton("📢 Рассылка", callback_data="BROADCAST")],
        [InlineKeyboardButton("🧑‍💬 Писать от имени", callback_data="IMPERSONATE"),
         InlineKeyboardButton("💬 Режим только админов", callback_data="TOGGLE_ADMIN_CHAT")],
        [InlineKeyboardButton("📝 Скачать Логи", url="http://YOUR_DOMAIN/logs")]
    ]
    return InlineKeyboardMarkup(kb)

# -------------------------
# Хендлеры
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user_registered(update.effective_user)
    kb = [
        [InlineKeyboardButton("🗨️ Отправить сообщение", callback_data="USER_SEND")],
        [InlineKeyboardButton("💖 Поддержать автора", url="https://t.me/mellfreezy_dons")]
    ]
    await update.message.reply_text("👋 Привет! Выбери действие:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = f"@{update.effective_user.username}" if update.effective_user.username else None
    if not uname or uname not in DATA["admins"]:
        await update.message.reply_text("⛔ У тебя нет доступа в админ-панель.")
        return
    await update.message.reply_text("🔧 Админ-панель:", reply_markup=admin_panel_keyboard())

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(f"⚠️ Кнопка '{query.data}' нажата, обработка пока не реализована")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user_registered(update.effective_user)
    await update.message.reply_text("⚠️ Текстовая обработка пока не реализована.")

# -------------------------
# Основной запуск
# -------------------------
def main():
    # Flask в отдельном потоке
    Thread(target=run_flask, daemon=True).start()

    # Запуск Telegram бота
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Используем безопасный метод run_polling
    application.run_polling()

if __name__ == "__main__":
    main()
