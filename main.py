import os, sqlite3, requests, secrets, string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

API_URL = os.environ.get("NATSSH_API_URL", "http://127.0.0.1:8099")
API_TOKEN = os.environ.get("NATSSH_API_TOKEN", "")
if not API_TOKEN or API_TOKEN == "change-me":
    try:
        API_TOKEN = open("/root/natssh/.api_token").read().strip()
    except Exception:
        API_TOKEN = "change-me"
DB_PATH = os.environ.get("BOT_DB", "/root/natssh-bot/bot.db")
ADMIN_IDS = set(int(x) for x in os.environ.get("ADMIN_IDS", "").split() if x)
ADMIN_CONTACT = os.environ.get("ADMIN_CONTACT", "admin")
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
    CREATE TABLE IF NOT EXISTS topup_requests (
        id INTEGER PRIMARY KEY, user_id INTEGER, code TEXT, amount INTEGER DEFAULT 0, status TEXT DEFAULT 'pending', created_at TEXT);
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


def ensure_user(tid):
    u = get_user(tid)
    role = "admin" if tid in ADMIN_IDS else "customer"
    if u:
        if u["role"] != role and tid in ADMIN_IDS:
            con = db()
            con.execute("UPDATE users SET role=? WHERE telegram_id=?", (role, tid))
            con.commit()
            con.close()
        return get_user(tid)
    con = db()
    con.execute("INSERT OR IGNORE INTO users (telegram_id, role, balance) VALUES (?,?,0)", (tid, role))
    con.commit()
    row = con.execute("SELECT * FROM users WHERE telegram_id=?", (tid,)).fetchone()
    con.close()
    return row


def api(path, method="GET", **kw):
    headers = {"X-API-Token": API_TOKEN}
    url = f"{API_URL}{path}"
    return requests.request(method, url, headers=headers, timeout=30, **kw)


def gen_pass(n=12):
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))


def main_menu_kb(user):
    rows = []
    role = user["role"] if user else None
    if role in ("customer", "reseller", None):
        rows.append([InlineKeyboardButton("➕ Buat Akun", callback_data="create_30")])
        rows.append([InlineKeyboardButton("💳 Topup", callback_data="topup_request")])
    if role in ("admin", "operator"):
        rows.append([InlineKeyboardButton("📊 Status", callback_data="status_menu")])
        rows.append([InlineKeyboardButton("📋 Daftar Akun", callback_data="accounts")])
    if role == "admin":
        rows.append([InlineKeyboardButton("💳 Topup", callback_data="topup_menu")])
    rows.append([InlineKeyboardButton("👤 Akun Saya", callback_data="myaccounts")])
    if role != "admin":
        rows.append([InlineKeyboardButton("📞 Hubungi Admin", callback_data="contact_admin")])
    if role == "admin":
        rows.append([InlineKeyboardButton("⚙️ Konfigurasi", callback_data="info")])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = ensure_user(update.effective_user.id)
    await update.message.reply_text("Menu utama:", reply_markup=main_menu_kb(u))


async def topup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    u = get_user(tid)
    if not u or u["role"] != "admin":
        await update.message.reply_text("Tidak diizinkan.")
        return
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /topup <telegram_id> <amount>")
        return
    try:
        target_tid = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("telegram_id dan amount harus angka.")
        return
    if amount <= 0:
        await update.message.reply_text("Amount harus > 0.")
        return
    target = ensure_user(target_tid)
    con = db()
    con.execute("UPDATE users SET balance=balance+? WHERE telegram_id=?", (amount, target_tid))
    con.execute("INSERT INTO transactions (user_id, amount, type, note, created_at) VALUES (?,?,?,?,datetime('now'))",
                (target["id"], amount, "topup", f"admin {tid}"))
    con.commit()
    row = con.execute("SELECT balance FROM users WHERE telegram_id=?", (target_tid,)).fetchone()
    con.close()
    await update.message.reply_text(f"Topup OK. Saldo {target_tid}: {row['balance']}")


async def topup_requests_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    u = get_user(tid)
    if not u or u["role"] != "admin":
        await update.message.reply_text("Tidak diizinkan.")
        return
    con = db()
    rows = con.execute("SELECT id, user_id, code, status, created_at FROM topup_requests WHERE status='pending' ORDER BY id").fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("Tidak ada request pending.")
        return
    text = "\n".join(f"#{r['id']} user={r['user_id']} code={r['code']} ({r['created_at']})" for r in rows)
    await update.message.reply_text(text)


async def approve_topup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    u = get_user(tid)
    if not u or u["role"] != "admin":
        await update.message.reply_text("Tidak diizinkan.")
        return
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /approve_topup <request_id> <amount>")
        return
    try:
        req_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("request_id dan amount harus angka.")
        return
    if amount <= 0:
        await update.message.reply_text("Amount harus > 0.")
        return
    con = db()
    req = con.execute("SELECT * FROM topup_requests WHERE id=? AND status='pending'", (req_id,)).fetchone()
    if not req:
        con.close()
        await update.message.reply_text("Request tidak ditemukan/pending.")
        return
    target_tid = con.execute("SELECT telegram_id FROM users WHERE id=?", (req["user_id"],)).fetchone()["telegram_id"]
    con.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, req["user_id"]))
    con.execute("UPDATE topup_requests SET amount=?, status='approved' WHERE id=?", (amount, req_id))
    con.execute("INSERT INTO transactions (user_id, amount, type, note, created_at) VALUES (?,?,?,?,datetime('now'))",
                (req["user_id"], amount, "topup", f"approve {req_id} code={req['code']}"))
    con.commit()
    row = con.execute("SELECT balance FROM users WHERE id=?", (req["user_id"],)).fetchone()
    con.close()
    await update.message.reply_text(f"Approved #{req_id}. Saldo user {target_tid}: {row['balance']}")


async def passwd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    u = get_user(tid)
    if not u or u["role"] != "admin":
        await update.message.reply_text("Tidak diizinkan.")
        return
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /passwd <ssh_user> <password_baru>")
        return
    ssh_user, new_pass = context.args[0], context.args[1]
    if len(new_pass) < 6:
        await update.message.reply_text("Password minimal 6 karakter.")
        return
    r = api(f"/accounts/{ssh_user}/password", method="POST", json={"password": new_pass})
    if r.status_code != 200:
        await update.message.reply_text(f"Gagal: {r.text}")
        return
    await update.message.reply_text(f"Password {ssh_user} berhasil diubah.")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Gunakan tombol inline. /start untuk menu.")


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id
    u = get_user(uid)
    role = u["role"] if u else None

    admin_only = {"accounts", "suspend_menu", "topup_menu", "config_menu", "topup_requests"}
    operator_ok = {"status", "accounts", "suspend_menu"}
    if data in ("accounts", "suspend_menu", "topup_menu", "config_menu"):
        if role not in ("admin", "operator"):
            await q.answer("Tidak diizinkan.", show_alert=True)
            return
    if data in ("topup_menu", "config_menu"):
        if role != "admin":
            await q.answer("Tidak diizinkan.", show_alert=True)
            return

    if data == "status":
        if role not in ("admin", "operator"):
            await q.answer("Tidak diizinkan.", show_alert=True)
            return
        r = api("/status")
        await q.edit_message_text(str(r.json()), reply_markup=main_menu_kb(u))
        return

    if data == "accounts":
        if not u or u["role"] not in ("admin", "operator"):
            await q.edit_message_text("Tidak diizinkan.", reply_markup=main_menu_kb(u))
            return
        r = api("/accounts")
        await q.edit_message_text(str(r.json()), reply_markup=main_menu_kb(u))
        return

    if data == "myaccounts":
        if not u:
            await q.edit_message_text("Belum terdaftar.", reply_markup=main_menu_kb(u))
            return
        con = db()
        rows = con.execute("SELECT ssh_user, created_at FROM owned_accounts WHERE user_id=?", (u["id"],)).fetchall()
        con.close()
        text = "\n".join(f"{r['ssh_user']} ({r['created_at']})" for r in rows) if rows else "Belum ada akun."
        await q.edit_message_text(text, reply_markup=main_menu_kb(u))
        return

    if data == "balance":
        if not u:
            await q.edit_message_text("Belum terdaftar.", reply_markup=main_menu_kb(u))
            return
        await q.edit_message_text(f"Saldo: {u['balance']}", reply_markup=main_menu_kb(u))
        return

    if data.startswith("create_"):
        if not u:
            await q.edit_message_text("Belum terdaftar.", reply_markup=main_menu_kb(u))
            return
        days = int(data.split("_")[1])
        price = int(PRICE_30D * (days / 30))
        if u["balance"] < price:
            await q.edit_message_text(f"Saldo tidak cukup. Harga: {price}, saldo: {u['balance']}",
                                     reply_markup=main_menu_kb(u))
            return
        username = f"u{u['id']}{secrets.randbelow(9999):04d}"
        password = gen_pass()
        r = api("/accounts", method="POST", json={"user": username, "password": password, "days": days})
        if r.status_code != 200:
            await q.edit_message_text(f"Gagal: {r.text}", reply_markup=main_menu_kb(u))
            return
        con = db()
        con.execute("UPDATE users SET balance=balance-? WHERE id=?", (price, u["id"]))
        con.execute("INSERT INTO transactions (user_id, amount, type, note, created_at) VALUES (?,?,?,?,datetime('now'))",
                    (u["id"], -price, "purchase", f"create {username}"))
        con.execute("INSERT INTO owned_accounts (user_id, ssh_user, created_at) VALUES (?,?,datetime('now'))",
                    (u["id"], username))
        con.commit()
        con.close()
        await q.edit_message_text(f"Akun dibuat:\nUsername: {username}\nPassword: {password}\nExpired: {days} hari",
                                 reply_markup=main_menu_kb(u))
        return

    if data == "suspend_menu":
        if not u or u["role"] not in ("admin", "operator"):
            await q.edit_message_text("Tidak diizinkan.", reply_markup=main_menu_kb(u))
            return
        await q.edit_message_text("Kirim: /suspend <user>", reply_markup=main_menu_kb(u))
        return

    if data == "topup_menu":
        if not u or u["role"] != "admin":
            await q.edit_message_text("Tidak diizinkan.", reply_markup=main_menu_kb(u))
            return
        await q.edit_message_text("Kirim: /topup <telegram_id> <amount>", reply_markup=main_menu_kb(u))
        return

    if data == "config_menu":
        if not u or u["role"] != "admin":
            await q.edit_message_text("Tidak diizinkan.", reply_markup=main_menu_kb(u))
            return
        await q.edit_message_text("Config via API/command.", reply_markup=main_menu_kb(u))
        return

    if data == "topup_request":
        if not u:
            await q.edit_message_text("Belum terdaftar.", reply_markup=main_menu_kb(u))
            return
        code = f"TP{u['id']}{secrets.randbelow(999999):06d}"
        con = db()
        con.execute("INSERT INTO topup_requests (user_id, code, status, created_at) VALUES (?,?, 'pending', datetime('now'))",
                    (u["id"], code))
        con.commit()
        con.close()
        await q.edit_message_text(
            f"Topup mandiri:\n1) Transfer ke QRIS statis.\n2) Kode unik: {code}\n3) Kirim bukti ke admin.\nAdmin akan approve dengan /approve_topup <id> <amount>.",
            reply_markup=main_menu_kb(u))
        return

    if data == "contact_admin":
        await q.edit_message_text(f"Hubungi admin: {ADMIN_CONTACT}", reply_markup=main_menu_kb(u))
        return

    if data == "info":
        r = api("/info")
        await q.edit_message_text(str(r.json()), reply_markup=main_menu_kb(u))
        return

    if data == "status_menu":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Status Server", callback_data="status_server")],
            [InlineKeyboardButton("Info Server", callback_data="status_info")],
            [InlineKeyboardButton("System Resources", callback_data="status_system")],
            [InlineKeyboardButton("Ws Peak", callback_data="status_wspeak")],
            [InlineKeyboardButton("Riwayat", callback_data="status_history")],
            [InlineKeyboardButton("Kembali", callback_data="back_main")],
        ])
        await q.edit_message_text("Menu Status:", reply_markup=kb)
        return

    if data == "status_server":
        r = api("/status").json()
        lr = api("/live").json()
        sessions = lr.get("live", [])
        lines = [
            "Status Server:",
            "──────────────",
            f"WS: {r.get('ws')}",
            f"Live connections: {r.get('live_connections')}",
            "──────────────",
            "Sesi Live:",
        ]
        if not sessions:
            lines.append("Tidak ada sesi live.")
        else:
            for s in sessions:
                city = s.get("city") or "-"
                lines.append(f"- {s.get('ip')} | {city} | up={s.get('up')} down={s.get('down')}")
        await q.message.reply_text("\n".join(lines))
        await q.answer()
        return

    if data == "status_info":
        r = api("/info").json()
        text = f"Host: {r.get('host')}\nCF Port: {r.get('cf_port')}\nWS Port: {r.get('ws_port')}"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Kembali", callback_data="status_menu")]]))
        return

    if data == "status_system":
        r = api("/system").json()
        text = f"RAM: {r.get('ram')}\nCPU: {r.get('cpu')}\nDisk: {r.get('disk')}"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Kembali", callback_data="status_menu")]]))
        return

    if data == "status_wspeak":
        r = api("/ws_peak").json()
        text = f"Puncak: {r.get('peak')} slot\nDitolak: {r.get('tolak')}x\nBatas: {r.get('max_total')} slot"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Kembali", callback_data="status_menu")]]))
        return

    if data == "status_history":
        r = api("/accounts").json()
        accounts = r.get("accounts", [])
        kb = []
        for a in accounts:
            u = a.get("user")
            if not u or not os.path.isdir(f"/home/{u}"):
                continue
            kb.append([InlineKeyboardButton(u, callback_data=f"hist_{u}")])
        kb.append([InlineKeyboardButton("Kembali", callback_data="status_menu")])
        await q.edit_message_text("Pilih akun untuk lihat riwayat:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("hist_"):
        user = data[5:]
        r = api(f"/accounts/{user}/history").json()
        rows = r.get("history", [])
        if not rows:
            text = "Tidak ada riwayat."
        else:
            lines = [f"Riwayat {user} ({len(rows)} sesi):", "──────────────"]
            for i, row in enumerate(rows, 1):
                lines.append(f"{i}. {row}")
            text = "\n".join(lines)
        await q.message.reply_text(text)
        await q.answer()
        return

    if data == "back_main":
        await q.edit_message_text("Menu utama:", reply_markup=main_menu_kb(u))
        return

    await q.edit_message_text("Unknown action.", reply_markup=main_menu_kb(u))


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


def main():
    init_db()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("topup", topup_cmd))
    app.add_handler(CommandHandler("topup_requests", topup_requests_cmd))
    app.add_handler(CommandHandler("approve_topup", approve_topup_cmd))
    app.add_handler(CommandHandler("passwd", passwd_cmd))
    app.add_handler(CallbackQueryHandler(callback))
    app.run_polling()


if __name__ == "__main__":
    main()
