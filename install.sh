#!/bin/bash
set -e
if [ ! -d /root/natssh ] || [ ! -f /root/natssh/menu.sh ]; then
    echo "natssh belum terpasang. Install natssh terlebih dahulu."
    exit 1
fi
if [ ! -f /root/natssh-bot/.env ]; then
cat > /root/natssh-bot/.env <<EOF
TELEGRAM_BOT_TOKEN=change-me
NATSSH_API_URL=http://127.0.0.1:8099
NATSSH_API_TOKEN=change-me
ADMIN_IDS=
BOT_DB=/root/natssh-bot/bot.db
PRICE_30D=5000
EOF
fi
python3 -m venv /opt/natssh-bot 2>/dev/null || true
/opt/natssh-bot/bin/pip install -r /root/natssh-bot/requirements.txt
cp /root/natssh-bot/main.py /opt/natssh-bot/main.py
cat > /etc/systemd/system/natssh-bot.service <<EOF
[Unit]
Description=NATSSH Telegram Bot
After=network.target natssh-ws.service

[Service]
EnvironmentFile=/root/natssh-bot/.env
ExecStart=/opt/natssh-bot/bin/python /opt/natssh-bot/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now natssh-bot
echo "Installed."
