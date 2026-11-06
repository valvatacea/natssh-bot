import os, sqlite3, requests, secrets, string
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

API_URL = os.environ.get("NATSSH_API_URL", "http://127.0.0.1:8099")
API_TOKEN = os.environ.get("NATSSH_API_TOKEN", "change-me")
DB_PATH = os.environ.get("BOT_DB", "/root/natssh-bot/bot.db")
ADMIN_IDS = set(int(x) for x in os.environ.get("ADMIN_IDS", "").split() if x)
PRICE_30D = int(os.environ.get("PRICE_30D", "5000"))


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE, role TEXT, balance INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY, user_id INTEGER, amount INTEGER, type TEXT, note TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS owned_accounts (
        id INTEGER PRIMARY KEY, user_id INTEGER, ssh_user TEXT, created_at TEXT);
    """)
    con.commit()
    con.close()


def get_user(tid):
    con = db()
    row = con.execute("SELECT * FROM users WHERE telegram_id=?", (tid,)).fetchone()
    con.close()
    return row


def api(path, method="GET", **kw):
    headers = {"X-API-Token": API_TOKEN}
    url = f"{API_URL}{path}"
    return requests.request(method, url, headers=headers, timeout=30, **kw)


def gen_pass(n=12):
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo. Gunakan /help")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/status /accounts /myaccounts /create [days] /balance /topup <tg_id> <amount> /adduser <tg_id> <role>")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = api("/status")
    await update.message.reply_text(str(r.json()))


async def accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u or u["role"] not in ("admin", "operator"):
        await update.message.reply_text("Tidak diizinkan.")
        return
    r = api("/accounts")
    await update.message.reply_text(str(r.json()))


async def myaccounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("Belum terdaftar.")
        return
    con = db()
    rows = con.execute("SELECT ssh_user, created_at FROM owned_accounts WHERE user_id=?", (u["id"],)).fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("Belum ada akun.")
        return
    await update.message.reply_text("\n".join(f"{r['ssh_user']} ({r['created_at']})" for r in rows))


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("Belum terdaftar.")
        return
    await update.message.reply_text(f"Saldo: {u['balance']}")


async def create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("Belum terdaftar.")
        return
    days = 30
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Usage: /create [days]")
            return
    price = int(PRICE_30D * (days / 30))
    if u["balance"] < price:
        await update.message.reply_text(f"Saldo tidak cukup. Harga: {price}, saldo: {u['balance']}")
        return
    username = f"u{u['id']}{secrets.randbelow(9999):04d}"
    password = gen_pass()
    r = api("/accounts", method="POST", json={"user": username, "password": password, "days": days})
    if r.status_code != 200:
        await update.message.reply_text(f"Gagal: {r.text}")
        return
    con = db()
    con.execute("UPDATE users SET balance=balance-? WHERE id=?", (price, u["id"]))
    con.execute("INSERT INTO transactions (user_id, amount, type, note, created_at) VALUES (?,?,?,?,datetime('now'))",
                (u["id"], -price, "purchase", f"create {username}"))
    con.execute("INSERT INTO owned_accounts (user_id, ssh_user, created_at) VALUES (?,?,datetime('now'))",
                (u["id"], username))
    con.commit()
    con.close()
    await update.message.reply_text(f"Akun dibuat:\nUsername: {username}\nPassword: {password}\nExpired: {days} hari")


async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Tidak diizinkan.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /adduser <telegram_id> <role>")
        return
    tid = int(context.args[0])
    role = context.args[1]
    if role not in ("admin", "operator", "user"):
        await update.message.reply_text("Role invalid.")
        return
    con = db()
    con.execute("INSERT OR IGNORE INTO users (telegram_id, role, balance) VALUES (?,?,0)", (tid, role))
    con.execute("UPDATE users SET role=? WHERE telegram_id=?", (role, tid))
    con.commit()
    con.close()
    await update.message.reply_text("OK")


async def topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Tidak diizinkan.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /topup <telegram_id> <amount>")
        return
    tid = int(context.args[0])
    amount = int(context.args[1])
    con = db()
    row = con.execute("SELECT id FROM users WHERE telegram_id=?", (tid,)).fetchone()
    if not row:
        await update.message.reply_text("User tidak ditemukan.")
        con.close()
        return
    uid = row["id"]
    con.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))
    con.execute("INSERT INTO transactions (user_id, amount, type, note, created_at) VALUES (?,?,?,?,datetime('now'))",
                (uid, amount, "topup", "admin topup"))
    con.commit()
    con.close()
    await update.message.reply_text("OK")


def main():
    init_db()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("accounts", accounts))
    app.add_handler(CommandHandler("myaccounts", myaccounts))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("create", create))
    app.add_handler(CommandHandler("adduser", adduser))
    app.add_handler(CommandHandler("topup", topup))
    app.run_polling()


if __name__ == "__main__":
    main()
