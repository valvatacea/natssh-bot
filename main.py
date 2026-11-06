import os, sqlite3, requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

API_URL = os.environ.get("NATSSH_API_URL", "http://127.0.0.1:8099")
API_TOKEN = os.environ.get("NATSSH_API_TOKEN", "change-me")
DB_PATH = os.environ.get("BOT_DB", "/root/natssh-bot/bot.db")
ADMIN_IDS = set(int(x) for x in os.environ.get("ADMIN_IDS", "").split() if x)


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE, role TEXT, balance INTEGER DEFAULT 0)""")
    con.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY, user_id INTEGER, amount INTEGER, type TEXT, note TEXT, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS owned_accounts (
        id INTEGER PRIMARY KEY, user_id INTEGER, ssh_user TEXT, created_at TEXT)""")
    con.commit()
    con.close()


def api(path, method="GET", **kw):
    headers = {"X-API-Token": API_TOKEN}
    url = f"{API_URL}{path}"
    return requests.request(method, url, headers=headers, timeout=30, **kw)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"Halo {uid}. Gunakan /help untuk menu.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = api("/status")
    await update.message.reply_text(str(r.json()))


async def accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = api("/accounts")
    await update.message.reply_text(str(r.json()))


async def suspend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Tidak diizinkan.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /suspend <user>")
        return
    user = context.args[0]
    r = api(f"/accounts/{user}/suspend", method="POST")
    await update.message.reply_text(str(r.json()))


def main():
    init_db()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("accounts", accounts))
    app.add_handler(CommandHandler("suspend", suspend))
    app.run_polling()


if __name__ == "__main__":
    main()
