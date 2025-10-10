import json, os, random, logging
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# === НАСТРОЙКИ ===
ADMIN_USERNAME = "mellfreezy"
DATA_FILE = "data.json"
MUTE_DURATION = {}  # user_id: datetime

# === СОСТОЯНИЯ ===
SEND, BAN, UNBAN, REPLY, MUTE, PERM_CHANGE = range(6)

# === ЛОГИ ===
logging.basicConfig(level=logging.INFO)

# === ХРАНИЛИЩЕ ===
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"users": {}, "banned": {}, "admins": [ADMIN_USERNAME]}, f)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()


# === ВСПОМОГАТЕЛЬНЫЕ ===
def is_admin(update: Update) -> bool:
    return update.effective_user.username in data.get("admins", [])


def get_user_name(user):
    if is_admin_from_name(user.username):
        return f"@{user.username}"
    uid = str(user.id)
    if uid not in data["users"]:
        anon_id = random.randint(1000, 9999)
        data["users"][uid] = {"anon": f"Аноним#{anon_id}", "username": user.username}
        save_data(data)
    return data["users"][uid]["anon"]


def is_admin_from_name(username):
    return username in data.get("admins", [])


# === ОБЫЧНЫЕ ПОЛЬЗОВАТЕЛИ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)

    if uid not in data["users"]:
        anon_id = random.randint(1000, 9999)
        data["users"][uid] = {"anon": f"Аноним#{anon_id}", "username": user.username}
        save_data(data)

    if is_admin(update):
        await admin_panel(update, context)
        return

    keyboard = [
        [InlineKeyboardButton("🗨️ Отправить сообщение", callback_data="send_message")],
        [InlineKeyboardButton("💖 Поддержать автора", url="https://t.me/mellfreezy_dons")]
    ]
    await update.message.reply_text("👋 Привет! Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_user_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "send_message":
        await query.edit_message_text("🗨️ Введите сообщение для отправки…")
        return SEND
    return ConversationHandler.END


async def handle_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)

    # Проверяем бан
    if uid in data["banned"]:
        await update.message.reply_text("🚫 Вы забанены.")
        return ConversationHandler.END

    # Проверяем мут
    if uid in MUTE_DURATION and datetime.now() < MUTE_DURATION[uid]:
        remain = (MUTE_DURATION[uid] - datetime.now()).seconds // 60
        await update.message.reply_text(f"⏳ Вы временно не можете писать ({remain} мин.)")
        return ConversationHandler.END

    text = update.message.text
    name = get_user_name(user)

    # Рассылка всем
    for u in data["users"]:
        if u != uid and u not in data["banned"]:
            try:
                await context.bot.send_message(chat_id=int(u), text=f"💬 {name}:\n{text}")
            except Exception as e:
                logging.warning(e)
    await update.message.reply_text("✅ Сообщение отправлено!")
    return ConversationHandler.END


# === АДМИНЫ ===
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👥 Пользователи", callback_data="users"),
         InlineKeyboardButton("🚫 Бан", callback_data="ban"),
         InlineKeyboardButton("✅ Разбан", callback_data="unban")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats"),
         InlineKeyboardButton("⏳ Мут", callback_data="mute")],
        [InlineKeyboardButton("💬 Ответить", callback_data="reply"),
         InlineKeyboardButton("📤 Сохранить базу", callback_data="export")],
        [InlineKeyboardButton("💬 Чат админов", callback_data="admin_chat")]
    ]
    await update.message.reply_text("🔧 Админ панель:", reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update):
        return

    data_store = load_data()

    if query.data == "users":
        text = "👥 Пользователи:\n"
        for uid, info in data_store["users"].items():
            if uid in data_store["banned"]:
                text += f"🚫 {info.get('username', 'Без юзернейма')} (Забанен)\n"
            else:
                text += f"{info.get('anon', 'Аноним')} — @{info.get('username')}\n"
        await query.edit_message_text(text or "❌ Нет пользователей.")

    elif query.data == "ban":
        await query.edit_message_text("🚫 Введите @username для блокировки:")
        return BAN

    elif query.data == "unban":
        await query.edit_message_text("✅ Введите @username для разблокировки:")
        return UNBAN

    elif query.data == "stats":
        total = len(data_store["users"])
        banned = len(data_store["banned"])
        admins = len(data_store["admins"])
        await query.edit_message_text(f"📊 Статистика:\n👥 Пользователей: {total}\n🚫 Забанено: {banned}\n🧑‍💼 Админов: {admins}")

    elif query.data == "mute":
        await query.edit_message_text("⏳ Введите @username и время в минутах (через пробел):")
        return MUTE

    elif query.data == "reply":
        await query.edit_message_text("💬 Введите @username и текст ответа:")
        return REPLY

    elif query.data == "export":
        save_data(data_store)
        await query.edit_message_text("📤 База данных сохранена (data.json).")

    elif query.data == "admin_chat":
        await query.edit_message_text("💬 Все сообщения, отправленные здесь, будут видны только админам.")
        context.user_data["admin_chat"] = True

    return ConversationHandler.END


# === ДОПОЛНИТЕЛЬНЫЕ АДМИН КОМАНДЫ ===
async def do_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip().replace("@", "")
    for uid, info in data["users"].items():
        if info.get("username") == username:
            data["banned"][uid] = True
            save_data(data)
            await update.message.reply_text(f"🚫 @{username} забанен.")
            return ConversationHandler.END
    await update.message.reply_text("❌ Пользователь не найден.")
    return ConversationHandler.END


async def do_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip().replace("@", "")
    for uid, info in data["users"].items():
        if info.get("username") == username:
            data["banned"].pop(uid, None)
            save_data(data)
            await update.message.reply_text(f"✅ @{username} разбанен.")
            return ConversationHandler.END
    await update.message.reply_text("❌ Пользователь не найден.")
    return ConversationHandler.END


async def do_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        username, minutes = update.message.text.strip().replace("@", "").split()
        minutes = int(minutes)
        for uid, info in data["users"].items():
            if info.get("username") == username:
                MUTE_DURATION[uid] = datetime.now() + timedelta(minutes=minutes)
                await update.message.reply_text(f"⏳ @{username} замьючен на {minutes} мин.")
                return ConversationHandler.END
        await update.message.reply_text("❌ Пользователь не найден.")
    except Exception:
        await update.message.reply_text("⚠️ Формат: @username время_в_минутах")
    return ConversationHandler.END


async def do_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split(" ", 1)
        username, msg = parts[0].replace("@", ""), parts[1]
        for uid, info in data["users"].items():
            if info.get("username") == username:
                await context.bot.send_message(chat_id=int(uid), text=f"💬 Сообщение от администратора:\n{msg}")
                await update.message.reply_text("✅ Отправлено.")
                return ConversationHandler.END
        await update.message.reply_text("❌ Пользователь не найден.")
    except Exception:
        await update.message.reply_text("⚠️ Формат: @username текст_сообщения")
    return ConversationHandler.END


# === MAIN ===
def main():
    TOKEN = os.getenv("YOUR_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_buttons)],
        states={
            BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_ban)],
            UNBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_unban)],
            REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_reply)],
            MUTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_mute)],
        },
        fallbacks=[]
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_user_buttons)],
        states={
            SEND: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_send)],
        },
        fallbacks=[]
    ))

    app.run_polling()


if __name__ == "__main__":
    main()
