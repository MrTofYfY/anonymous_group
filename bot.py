# bot.py
import os
import json
import time
import random
import logging
import threading
from dotenv import load_dotenv
from flask import Flask
from io import BytesIO

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# -------------------------
# Настройка и загрузка TOKEN
# -------------------------
load_dotenv()
TOKEN = os.getenv("YOUR_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Переменная окружения YOUR_BOT_TOKEN не задана. Установи и перезапусти.")

# -------------------------
# Логирование в консоль и файл logs.txt
# -------------------------
if not os.path.exists("logs.txt"):
    open("logs.txt", "w", encoding="utf-8").close()

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
# Flask (для Render)
# -------------------------
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "✅ Telegram bot is running!"

# -------------------------
# Файл данных
# -------------------------
DATA_FILE = "data.json"

def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "users": {},
            "admins": [],
            "banned": [],
            "permissions": {},
            "message_count": 0,
            "admin_chat_enabled": False
        }

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(DATA, f, ensure_ascii=False, indent=2)

DATA = load_data()

# -------------------------
# Константы / состояния
# -------------------------
STATE_WAIT_ADMIN_USERNAME = "WAIT_ADMIN_USERNAME"
STATE_WAIT_REMOVE_ADMIN = "WAIT_REMOVE_ADMIN"
STATE_WAIT_PERMS_USERNAME = "WAIT_PERMS_USERNAME"
STATE_WAIT_MUTE = "WAIT_MUTE"
STATE_WAIT_IMPERSONATE = "WAIT_IMPERSONATE"
STATE_WAIT_BROADCAST = "WAIT_BROADCAST"
STATE_USER_SEND = "USER_SEND"
STATE_PRIVATE_REPLY = "PRIVATE_REPLY"

ALL_PERMS = ["broadcast", "impersonate", "manage_perms", "stats", "mute", "export", "admin_chat", "private_reply"]

# -------------------------
# Вспомогательные функции
# -------------------------
def ensure_user_registered(user):
    uid = str(user.id)
    if uid not in DATA["users"]:
        anon = random.randint(1, 99999)
        DATA["users"][uid] = {
            "username": user.username if user.username else None,
            "anon": anon,
            "muted_until": 0
        }
        save_data()

def get_anon_display(uid):
    info = DATA["users"].get(str(uid))
    if not info:
        return "Аноним"
    return f"Аноним#{info['anon']}"

def is_banned_username(username):
    return username and username.startswith("@") and username in DATA["banned"]

def is_admin_username(username):
    return username and username.startswith("@") and username in DATA["admins"]

def check_permission(username, perm):
    perms = DATA["permissions"].get(username, {})
    return perms.get(perm, False)

def init_admin_if_none(admin_username):
    if admin_username not in DATA["admins"]:
        DATA["admins"].append(admin_username)
    if admin_username not in DATA["permissions"]:
        DATA["permissions"][admin_username] = {p: True for p in ALL_PERMS}
    save_data()

init_admin_if_none("@mellfreezy")

# -------------------------
# UI helpers
# -------------------------
def perms_to_keyboard_for_user(target_username):
    perms = DATA["permissions"].get(target_username, {p: False for p in ALL_PERMS})
    rows = []
    for p in ALL_PERMS:
        mark = "✅" if perms.get(p, False) else "❌"
        rows.append([InlineKeyboardButton(f"{mark} {p}", callback_data=f"TOGGLE|{target_username}|{p}")])
    rows.append([InlineKeyboardButton("Назад", callback_data="ADMIN_PANEL")])
    return InlineKeyboardMarkup(rows)

def admin_panel_keyboard():
    kb = [
        [InlineKeyboardButton("👥 Пользователи", callback_data="SHOW_USERS")],
        [InlineKeyboardButton("🧑‍💼 Администраторы", callback_data="SHOW_ADMINS")],
        [InlineKeyboardButton("📊 Статистика", callback_data="SHOW_STATS")],
        [InlineKeyboardButton("➕ Добавить админа", callback_data="ADD_ADMIN"),
         InlineKeyboardButton("➖ Удалить админа", callback_data="REMOVE_ADMIN")],
        [InlineKeyboardButton("⚙️ Установить разрешения", callback_data="SET_PERMS"),
         InlineKeyboardButton("⏱️ Тайм-аут / Мут", callback_data="MUTE_USER")],
        [InlineKeyboardButton("📤 Экспорт данных", callback_data="EXPORT_DATA"),
         InlineKeyboardButton("📢 Рассылка", callback_data="BROADCAST")],
        [InlineKeyboardButton("🧑‍💬 Писать от имени", callback_data="IMPERSONATE"),
         InlineKeyboardButton("💬 Режим только админов", callback_data="TOGGLE_ADMIN_CHAT")],
        [InlineKeyboardButton("📝 Сохранить Логи", callback_data="SAVE_LOGS")]
    ]
    return InlineKeyboardMarkup(kb)

# -------------------------
# Хендлеры команд
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user_registered(user)
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

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user_registered(user)
    uid = str(user.id)
    if DATA["users"][uid].get("muted_until", 0) > time.time():
        await update.message.reply_text("⏱️ Вы замьючены и не можете отправлять сообщения.")
        return
    await update.message.reply_text("🗨️ Введите сообщение для отправки (анонимно):")
    context.user_data["state"] = STATE_USER_SEND

# -------------------------
# CallbackQuery handler (кнопки)
# -------------------------
async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    uname = f"@{user.username}" if user.username else None

    if data == "SAVE_LOGS":
        if not uname or uname not in DATA["admins"]:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        with open("logs.txt", "rb") as f:
            await query.message.reply_document(document=InputFile(f, filename="logs.txt"))
        await query.edit_message_text("📝 Логи отправлены.")
        return

    # остальные кнопки (ADMIN_PANEL, SHOW_USERS, SHOW_ADMINS, TOGGLE и т.д.)
    # можно использовать предыдущую реализацию callback_query_handler

# -------------------------
# Обработка текстовых сообщений
# -------------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # обработка отправки сообщений, добавления админов, mute, broadcast и т.д.
    pass  # реализация аналогична предыдущему примеру

# -------------------------
# Запуск
# -------------------------
def main():
    app_tg = ApplicationBuilder().token(TOKEN).build()

    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("admin", admin_command))
    app_tg.add_handler(CallbackQueryHandler(callback_query_handler))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    threading.Thread(target=app_tg.run_polling).start()
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    main()
