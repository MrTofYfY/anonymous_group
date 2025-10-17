# bot.py
import os
import json
import time
import random
import logging
import threading
from dotenv import load_dotenv
from flask import Flask, send_file
from io import BytesIO

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)

# -------------------------
# Настройка и загрузка TOKEN
# -------------------------
load_dotenv()
TOKEN = os.getenv("YOUR_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Переменная окружения YOUR_BOT_TOKEN не задана. Установи и перезапусти.")

# -------------------------
# Логирование
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
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
        # базовая структура
        return {
            "users": {},         # str(user_id) -> {"username": str|None, "anon": int, "muted_until": 0}
            "admins": [],        # list of "@username"
            "banned": [],        # list of "@username"
            "permissions": {},   # "@username" -> {perm: bool, ...}
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
STATE_WAIT_PERM_TOGGLE = "WAIT_PERM_TOGGLE"  # internal message state for toggles (not used for message handler)
STATE_USER_SEND = "USER_SEND"

# список доступных прав
ALL_PERMS = ["broadcast", "impersonate", "manage_perms", "stats", "mute", "export", "admin_chat"]

# -------------------------
# Вспомогательные функции
# -------------------------
def ensure_user_registered(user):
    """Добавляем пользователя в DATA['users'] если нет"""
    uid = str(user.id)
    if uid not in DATA["users"]:
        anon = random.randint(1000, 9999)
        DATA["users"][uid] = {
            "username": user.username if user.username else None,
            "anon": anon,
            "muted_until": 0
        }
        save_data()

def get_anon_display(uid):
    """возвращает 'Аноним#1234' для user_id строкой"""
    info = DATA["users"].get(str(uid))
    if not info:
        return "Аноним"
    return f"Аноним#{info['anon']}"

def is_banned_username(username):
    if not username:
        return False
    return username.startswith("@") and username in DATA["banned"]

def is_admin_username(username):
    if not username:
        return False
    return username.startswith("@") and username in DATA["admins"]

def username_of_user_id(uid):
    info = DATA["users"].get(str(uid))
    return info.get("username") if info else None

def check_permission(username, perm):
    """username like '@mellfreezy'"""
    perms = DATA["permissions"].get(username, {})
    return perms.get(perm, False)

def init_admin_if_none(admin_username):
    """Если нет ни одного админа, добавляем заданного (используется при первом старте)"""
    if admin_username not in DATA["admins"]:
        DATA["admins"].append(admin_username)
    if admin_username not in DATA["permissions"]:
        # по умолчанию даём все права основателю
        DATA["permissions"][admin_username] = {p: True for p in ALL_PERMS}
    save_data()

# -------------------------
# UI helpers
# -------------------------
def perms_to_keyboard_for_user(target_username):
    """Возвращает InlineKeyboard с кнопками для переключения прав для target_username"""
    perms = DATA["permissions"].get(target_username, {p: False for p in ALL_PERMS})
    rows = []
    for p in ALL_PERMS:
        mark = "✅" if perms.get(p, False) else "❌"
        # callback пример: "TOGGLE|@user|perm"
        rows.append([InlineKeyboardButton(f"{mark} {p}", callback_data=f"TOGGLE|{target_username}|{p}")])
    # кнопка назад
    rows.append([InlineKeyboardButton("Назад", callback_data="ADMIN_PANEL")])
    return InlineKeyboardMarkup(rows)

def admin_panel_keyboard():
    kb = [
        [InlineKeyboardButton("👥 Пользователи", callback_data="SHOW_USERS")],
        [InlineKeyboardButton("🚫 Забаненные", callback_data="SHOW_BANNED")],
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
    ]
    return InlineKeyboardMarkup(kb)

# -------------------------
# Хендлеры команд
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user_registered(user)
    uid = str(user.id)

    # приветственное меню
    kb = [
        [InlineKeyboardButton("🗨️ Отправить сообщение", callback_data="USER_SEND")],
        [InlineKeyboardButton("💖 Поддержать автора", url="https://t.me/mellfreezy_dons")]
    ]
    await update.message.reply_text("👋 Привет! Выбери действие:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uname = f"@{user.username}" if user.username else None
    if not uname or uname not in DATA["admins"]:
        await update.message.reply_text("⛔ У тебя нет доступа в админ-панель.")
        return
    await update.message.reply_text("🔧 Админ-панель:", reply_markup=admin_panel_keyboard())

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user_registered(user)
    uid = str(user.id)
    # проверка мут/бан
    if DATA["users"][uid].get("muted_until", 0) > time.time():
        await update.message.reply_text("⏱️ Вы замьючены и не можете отправлять сообщения.")
        return
    await update.message.reply_text("🗨️ Введите сообщение для отправки (будет разослано другим):")
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
    admin_name = uname

    # Админ-панель главная
    if data == "ADMIN_PANEL" or data == "OPEN_ADMIN":
        if not admin_name or admin_name not in DATA["admins"]:
            await query.edit_message_text("⛔ У тебя нет доступа.")
            return
        await query.edit_message_text("🔧 Админ-панель:", reply_markup=admin_panel_keyboard())
        return

    # SHOW users
    if data == "SHOW_USERS":
        if not admin_name or admin_name not in DATA["admins"]:
            await query.edit_message_text("⛔ Доступ запрещён.")
            return
        lines = []
        for uid, info in DATA["users"].items():
            username = f"@{info['username']}" if info.get("username") else "(без username)"
            if username in DATA["banned"]:
                lines.append(f"Забанен — {username}")
            else:
                lines.append(f"Аноним#{info['anon']} — {username}")
        text = "👥 Пользователи:\n" + ("\n".join(lines) if lines else "— нет пользователей —")
        await query.edit_message_text(text)
        return

    # SHOW banned
    if data == "SHOW_BANNED":
        if not admin_name or admin_name not in DATA["admins"]:
            await query.edit_message_text("⛔ Доступ запрещён.")
            return
        lines = [u for u in DATA["banned"]] if DATA["banned"] else []
        text = "🚫 Забаненные:\n" + ("\n".join(lines) if lines else "— нет забаненных —")
        await query.edit_message_text(text)
        return

    # SHOW admins
    if data == "SHOW_ADMINS":
        if not admin_name or admin_name not in DATA["admins"]:
            await query.edit_message_text("⛔ Доступ запрещён.")
            return
        lines = []
        for a in DATA["admins"]:
            perms = DATA["permissions"].get(a, {})
            perms_str = ", ".join(f"{k}:{'✅' if perms.get(k) else '❌'}" for k in ALL_PERMS)
            lines.append(f"{a} — {perms_str}")
        text = "🧑‍💼 Администраторы:\n" + ("\n".join(lines) if lines else "— нет админов —")
        await query.edit_message_text(text)
        return

    # ADD_ADMIN
    if data == "ADD_ADMIN":
        if not admin_name or admin_name not in DATA["admins"] or not check_permission(admin_name, "manage_perms"):
            await query.edit_message_text("⛔ Нет прав.")
            return
        # ждем ввода username
        context.user_data["await_action"] = STATE_WAIT_ADMIN_USERNAME
        await query.edit_message_text("Введите @username для добавления в админы:")
        return

    # REMOVE_ADMIN
    if data == "REMOVE_ADMIN":
        if not admin_name or admin_name not in DATA["admins"] or not check_permission(admin_name, "manage_perms"):
            await query.edit_message_text("⛔ Нет прав.")
            return
        context.user_data["await_action"] = STATE_WAIT_REMOVE_ADMIN
        await query.edit_message_text("Введите @username для удаления из админов:")
        return

    # SET_PERMS
    if data == "SET_PERMS":
        if not admin_name or admin_name not in DATA["admins"] or not check_permission(admin_name, "manage_perms"):
            await query.edit_message_text("⛔ Нет прав.")
            return
        context.user_data["await_action"] = STATE_WAIT_PERMS_USERNAME
        await query.edit_message_text("Введите @username для настройки разрешений:")
        return

    # MUTE user
    if data == "MUTE_USER":
        if not admin_name or admin_name not in DATA["admins"] or not check_permission(admin_name, "mute"):
            await query.edit_message_text("⛔ Нет прав.")
            return
        context.user_data["await_action"] = STATE_WAIT_MUTE
        await query.edit_message_text("Введите в формате: @username minutes (например: @joe 30)")
        return

    # EXPORT DATA
    if data == "EXPORT_DATA":
        if not admin_name or admin_name not in DATA["admins"] or not check_permission(admin_name, "export"):
            await query.edit_message_text("⛔ Нет прав.")
            return
        # отправляем data.json как файл
        buf = BytesIO()
        buf.write(json.dumps(DATA, ensure_ascii=False, indent=2).encode("utf-8"))
        buf.seek(0)
        await query.message.reply_document(document=InputFile(buf, filename="data.json"))
        await query.edit_message_text("📤 Экспортирован data.json")
        return

    # BROADCAST
    if data == "BROADCAST":
        if not admin_name or admin_name not in DATA["admins"] or not check_permission(admin_name, "broadcast"):
            await query.edit_message_text("⛔ Нет прав.")
            return
        context.user_data["await_action"] = STATE_WAIT_BROADCAST
        await query.edit_message_text("✍️ Введи текст для рассылки всем пользователям:")
        return

    # IMPERSONATE
    if data == "IMPERSONATE":
        if not admin_name or admin_name not in DATA["admins"] or not check_permission(admin_name, "impersonate"):
            await query.edit_message_text("⛔ Нет прав.")
            return
        context.user_data["await_action"] = STATE_WAIT_IMPERSONATE
        await query.edit_message_text("Введите в формате: anon_id текст (например: 1234 Привет всем)")
        return

    # TOGGLE_ADMIN_CHAT
    if data == "TOGGLE_ADMIN_CHAT":
        if not admin_name or admin_name not in DATA["admins"] or not check_permission(admin_name, "admin_chat"):
            await query.edit_message_text("⛔ Нет прав.")
            return
        DATA["admin_chat_enabled"] = not DATA.get("admin_chat_enabled", False)
        save_data()
        await query.edit_message_text(f"💬 Режим только админов: {'ВКЛ' if DATA['admin_chat_enabled'] else 'ВЫКЛ'}")
        return

    # TOGGLE perm callback e.g. "TOGGLE|@user|perm"
    if data.startswith("TOGGLE|"):
        parts = data.split("|")
        if len(parts) != 3:
            await query.answer("Неверный формат.")
            return
        target = parts[1]
        perm = parts[2]
        if not admin_name or admin_name not in DATA["admins"] or not check_permission(admin_name, "manage_perms"):
            await query.edit_message_text("⛔ Нет прав.")
            return
        # ensure perms dict
        if target not in DATA["permissions"]:
            DATA["permissions"][target] = {p: False for p in ALL_PERMS}
        DATA["permissions"][target][perm] = not DATA["permissions"][target].get(perm, False)
        save_data()
        # обновляем сообщение с клавиатурой
        await query.edit_message_text(f"Настройки для {target}:", reply_markup=perms_to_keyboard_for_user(target))
        return

    # USER_SEND button pressed by normal user
    if data == "USER_SEND":
        # set user state to send
        context.user_data["state"] = STATE_USER_SEND
        await query.message.reply_text("🗨️ Введите сообщение для отправки всем (анонимно):")
        return

    # Back to admin panel
    if data == "ADMIN_PANEL":
        if not admin_name or admin_name not in DATA["admins"]:
            await query.edit_message_text("⛔ Нет доступа.")
            return
        await query.edit_message_text("🔧 Админ-панель:", reply_markup=admin_panel_keyboard())
        return

    # fallback
    await query.edit_message_text("❌ Неизвестная команда.")

# -------------------------
# Обработка текстовых сообщений (все входящие)
# -------------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    text = update.message.text.strip()
    ensure_user_registered(user)

    # если админ в режиме ожидания action (add/remove/set perms/mute/broadcast/impersonate)
    action = context.user_data.get("await_action")

    # ---- ADD ADMIN ----
    if action == STATE_WAIT_ADMIN_USERNAME:
        context.user_data.pop("await_action", None)
        username = text.split()[0]
        if not username.startswith("@"):
            await update.message.reply_text("Укажи корректный @username.")
            return
        if username in DATA["admins"]:
            await update.message.reply_text("Пользователь уже админ.")
            return
        DATA["admins"].append(username)
        # дать стандартные права (по желанию)
        DATA["permissions"][username] = {p: False for p in ALL_PERMS}
        DATA["permissions"][username]["manage_perms"] = True
        DATA["permissions"][username]["stats"] = True
        save_data()
        await update.message.reply_text(f"✅ {username} добавлен как админ.")
        return

    # ---- REMOVE ADMIN ----
    if action == STATE_WAIT_REMOVE_ADMIN:
        context.user_data.pop("await_action", None)
        username = text.split()[0]
        if not username.startswith("@"):
            await update.message.reply_text("Укажи корректный @username.")
            return
        if username not in DATA["admins"]:
            await update.message.reply_text("Такого админа нет.")
            return
        DATA["admins"].remove(username)
        DATA["permissions"].pop(username, None)
        save_data()
        await update.message.reply_text(f"✅ {username} удалён из админов.")
        return

    # ---- SET PERMISSIONS: ожидание username ----
    if action == STATE_WAIT_PERMS_USERNAME:
        context.user_data.pop("await_action", None)
        username = text.split()[0]
        if not username.startswith("@"):
            await update.message.reply_text("Укажи корректный @username.")
            return
        # ensure entry
        if username not in DATA["permissions"]:
            DATA["permissions"][username] = {p: False for p in ALL_PERMS}
        save_data()
        # отправляем клавиатуру с правами
        await update.message.reply_text(f"Настройки для {username}:", reply_markup=perms_to_keyboard_for_user(username))
        return

    # ---- MUTE user (format: @user minutes) ----
    if action == STATE_WAIT_MUTE:
        context.user_data.pop("await_action", None)
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("Неправильный формат. Пример: @user 30")
            return
        username = parts[0]
        try:
            minutes = int(parts[1])
        except:
            await update.message.reply_text("Укажи число минут.")
            return
        # find user id by username
        target_uid = None
        for uid_k, info in DATA["users"].items():
            if info.get("username") and f"@{info['username']}" == username:
                target_uid = uid_k
                break
        if not target_uid:
            await update.message.reply_text("Пользователь не найден.")
            return
        DATA["users"][target_uid]["muted_until"] = int(time.time()) + minutes*60
        save_data()
        await update.message.reply_text(f"⏱️ {username} замьючен на {minutes} минут.")
        return

    # ---- BROADCAST by admin ----
    if action == STATE_WAIT_BROADCAST:
        context.user_data.pop("await_action", None)
        # убедимся что пользователь админ и имеет право
        uname = f"@{user.username}" if user.username else None
        if not uname or uname not in DATA["admins"] or not check_permission(uname, "broadcast"):
            await update.message.reply_text("⛔ Нет прав.")
            return
        text_to_send = text
        # рассылаем всем не забаненным
        DATA["message_count"] = DATA.get("message_count", 0) + 1
        save_data()
        for uid_k, info in DATA["users"].items():
            username_k = f"@{info['username']}" if info.get("username") else None
            if username_k in DATA["banned"]:
                continue
            try:
                await context.bot.send_message(chat_id=int(uid_k), text=f"📢 Рассылка:\n\n{text_to_send}")
            except Exception as e:
                logger.warning(f"Broadcast failed for {uid_k}: {e}")
        await update.message.reply_text("✅ Рассылка завершена.")
        return

    # ---- IMPERSONATE (format: anon_id текст...) ----
    if action == STATE_WAIT_IMPERSONATE:
        context.user_data.pop("await_action", None)
        uname = f"@{user.username}" if user.username else None
        if not uname or uname not in DATA["admins"] or not check_permission(uname, "impersonate"):
            await update.message.reply_text("⛔ Нет прав.")
            return
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("Формат: anon_id текст (например: 1234 Привет всем)")
           
