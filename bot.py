from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from flask import Flask
import threading
import logging
import json
import random
import os
import sys

# ---------- Flask для Render ----------
app_web = Flask('')

@app_web.route('/')
def home():
    return "✅ Telegram бот работает!"

def run_web():
    app_web.run(host='0.0.0.0', port=10000)

threading.Thread(target=run_web).start()

# ---------- Логирование ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ---------- Константы ----------
DATA_FILE = "data.json"
ADMIN_USERNAME = "mellfreezy"

# ---------- Загрузка данных ----------
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"users": {}, "banned": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

data = load_data()

# ---------- Состояния ----------
SEND_MESSAGE, BROADCAST, BAN, UNBAN = range(4)

# ---------- Проверка админа ----------
def is_admin(update: Update) -> bool:
    return update.effective_user.username == ADMIN_USERNAME

# ---------- Команда /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Создаём анонимный ник, если нового пользователя
    if str(user.id) not in data["users"]:
        random_id = random.randint(1000, 9999)
        anon_name = f"Аноним#{random_id}"
        data["users"][str(user.id)] = {"username": user.username, "anon_name": anon_name}
        save_data(data)

    if is_admin(update):
        await admin_panel(update, context)
    else:
        # Меню для обычных пользователей
        keyboard = [
            [InlineKeyboardButton("🗨️ Отправить сообщение", callback_data="send_message")],
            [InlineKeyboardButton("💖 Поддержать автора", url="https://t.me/mellfreezy_dons")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "👋 Привет! Выбери действие:", reply_markup=reply_markup
        )

# ---------- Команда /admin ----------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("🚫 У тебя нет доступа.")
        return

    keyboard = [
        [InlineKeyboardButton("👥 Пользователи", callback_data="users"),
         InlineKeyboardButton("🚫 Забаненные", callback_data="banned")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton("⛔ Бан", callback_data="ban"),
         InlineKeyboardButton("✅ Разбан", callback_data="unban")],
        [InlineKeyboardButton("🗑 Очистить всех", callback_data="clear")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🔧 Админ панель:", reply_markup=reply_markup)

# ---------- Обработчик кнопок админа ----------
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        return

    if query.data == "users":
        if not data["users"]:
            await query.edit_message_text("❌ Нет пользователей.")
        else:
            users_list = "\n".join(
                [f"@{info['username']} — {info['anon_name']}" for info in data["users"].values()]
            )
            await query.edit_message_text(f"👥 Пользователи:\n{users_list}")

    elif query.data == "banned":
        if not data["banned"]:
            await query.edit_message_text("✅ Нет забаненных.")
        else:
            banned_list = "\n".join(f"@{u}" for u in data["banned"])
            await query.edit_message_text(f"🚫 Забаненные пользователи:\n{banned_list}")

    elif query.data == "broadcast":
        await query.edit_message_text("✍️ Введи текст для рассылки:")
        return BROADCAST

    elif query.data == "ban":
        await query.edit_message_text("🚫 Введи @username для блокировки:")
        return BAN

    elif query.data == "unban":
        await query.edit_message_text("✅ Введи @username для разблокировки:")
        return UNBAN

    elif query.data == "clear":
        data["users"].clear()
        data["banned"].clear()
        save_data(data)
        await query.edit_message_text("🗑 Все пользователи удалены.")

    return ConversationHandler.END

# ---------- Рассылка ----------
async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    for uid, info in data["users"].items():
        if info["username"] not in data["banned"]:
            try:
                await context.bot.send_message(chat_id=int(uid), text=f"📢 {text}")
            except Exception as e:
                logging.warning(f"Не удалось отправить {uid}: {e}")
    await update.message.reply_text("✅ Рассылка завершена.")
    return ConversationHandler.END

# ---------- Бан ----------
async def do_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip().lstrip("@")
    if username not in data["banned"]:
        data["banned"].append(username)
        save_data(data)
        await update.message.reply_text(f"🚫 Пользователь @{username} заблокирован.")
    else:
        await update.message.reply_text("⚠️ Этот пользователь уже в бане.")
    return ConversationHandler.END

# ---------- Разбан ----------
async def do_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip().lstrip("@")
    if username in data["banned"]:
        data["banned"].remove(username)
        save_data(data)
        await update.message.reply_text(f"✅ Пользователь @{username} разблокирован.")
    else:
        await update.message.reply_text("⚠️ Такого пользователя нет в бане.")
    return ConversationHandler.END

# ---------- Команда /send ----------
async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.username in data["banned"]:
        await update.message.reply_text("🚫 Вы заблокированы и не можете отправлять сообщения.")
        return ConversationHandler.END

    await update.message.reply_text("🗨️ Введите сообщение для отправки…")
    return SEND_MESSAGE

# ---------- Обработка кнопки меню для пользователей ----------
async def user_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "send_message":
        await query.message.reply_text("🗨️ Введите сообщение для отправки…")
        return SEND_MESSAGE

# ---------- Отправка сообщений ----------
async def handle_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    anon_name = data["users"].get(str(user.id), {}).get("anon_name", "Аноним")

    text = update.message.text
    for uid, info in data["users"].items():
        if info["username"] not in data["banned"] and uid != str(user.id):
            try:
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=f"💬 {anon_name}: {text}"
                )
            except Exception as e:
                logging.warning(f"Не удалось отправить сообщение {uid}: {e}")

    await update.message.reply_text("✅ Сообщение отправлено!")
    return ConversationHandler.END

# ---------- Отмена ----------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Действие отменено.")
    return ConversationHandler.END

# ---------- Main ----------
def main():
    # читаем токен из переменной окружения (без токена бот не запустится)
    TOKEN = os.environ.get("YOUR_BOT_TOKEN")
    if not TOKEN:
        logging.error("Переменная окружения YOUR_BOT_TOKEN не задана. Установи её и перезапусти.")
        sys.exit(1)

    app = Application.builder().token(TOKEN).build()

    # ConversationHandler для /send всех пользователей (должен идти **перед** обычным MessageHandler)
    user_conv = ConversationHandler(
        entry_points=[CommandHandler("send", send_command)],
        states={
            SEND_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_send_message)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    app.add_handler(user_conv)

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("cancel", cancel))

    # Админ-панель
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_menu_handler)],
        states={
            BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_broadcast)],
            BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_ban)],
            UNBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, do_unban)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    app.add_handler(admin_conv)

    # Меню для кнопки "Отправить сообщение"
    app.add_handler(CallbackQueryHandler(user_menu_handler, pattern="send_message"))

    # Обычные сообщения пересылаем всем (должен идти после ConversationHandler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_message))

    # Запуск
    app.run_polling()

if __name__ == "__main__":
    main()
