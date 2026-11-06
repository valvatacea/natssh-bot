#!/bin/bash
set -e
python3 -m venv /opt/natssh-bot 2>/dev/null || true
/opt/natssh-bot/bin/pip install -r /root/natssh-bot/requirements.txt
cp /root/natssh-bot/main.py /opt/natssh-bot/main.py
cat > /etc/systemd/system/natssh-bot.service <<EOF
[Unit]
Description=NATSSH Telegram Bot
After=network.target

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
