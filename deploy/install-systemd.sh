#!/bin/bash
# Установка автозапуска бота + сайта. Запуск: sudo bash deploy/install-systemd.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="pythonboteng"
UNIT="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ ! -f "$ROOT/run_all.py" ]]; then
  echo "Не найден run_all.py в $ROOT"
  exit 1
fi
if [[ ! -f "$ROOT/.env" ]]; then
  echo "Создайте .env в $ROOT"
  exit 1
fi
if [[ ! -x "$ROOT/venv/bin/python" ]]; then
  echo "Создайте venv: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

cat > "$UNIT" << EOF
[Unit]
Description=Telegram bot + web admin (run_all.py)
After=network.target

[Service]
Type=simple
WorkingDirectory=${ROOT}
EnvironmentFile=${ROOT}/.env
ExecStart=${ROOT}/venv/bin/python ${ROOT}/run_all.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager
echo "Готово. Логи: journalctl -u ${SERVICE_NAME} -f"
