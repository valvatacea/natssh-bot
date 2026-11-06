#!/bin/bash
systemctl disable --now natssh-bot 2>/dev/null || true
rm -f /etc/systemd/system/natssh-bot.service
systemctl daemon-reload
rm -rf /opt/natssh-bot
echo "Uninstalled."
