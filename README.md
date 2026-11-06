# natssh-bot (prototype)

Bot Telegram terpisah yang memanggil API natssh via HTTP.

Env:
- TELEGRAM_BOT_TOKEN
- NATSSH_API_URL (default http://127.0.0.1:8099)
- NATSSH_API_TOKEN
- ADMIN_IDS (comma-separated)
- BOT_DB (default /root/natssh-bot/bot.db)

Run:
pip install -r requirements.txt
python3 main.py
