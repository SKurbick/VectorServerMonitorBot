#!/bin/bash
set -e

PROJECT_DIR="/home/vector/APPS/VectorServerMonitorBot"
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_NAME="vector-monitor-bot"
SERVICE_USER="vector"
PYTHON="/usr/bin/python3"

echo "=== Установка VectorServerMonitorBot ==="

# 1. Останавливаем Docker контейнер если запущен
echo "Останавливаем Docker контейнер..."
cd "$PROJECT_DIR"
docker compose down 2>/dev/null || true

# 2. Исправляем права
echo "Исправляем права..."
sudo chown -R vector:vector "$PROJECT_DIR/data"
sudo chown vector:vector "$PROJECT_DIR/.env" 2>/dev/null || true

# 3. Создаём виртуальное окружение
echo "Создаём venv..."
"$PYTHON" -m venv "$VENV_DIR"

# 4. Устанавливаем зависимости
echo "Устанавливаем зависимости..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --quiet

# 5. Создаём папку для данных
mkdir -p "$PROJECT_DIR/data"

# 6. Создаём systemd unit файл
echo "Создаём systemd сервис..."
sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null << EOF
[Unit]
Description=Vector Server Monitor Bot
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$VENV_DIR/bin/python -m app.main
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

[Install]
WantedBy=multi-user.target
EOF

# 7. Включаем и запускаем
echo "Запускаем сервис..."
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl restart $SERVICE_NAME

echo ""
echo "=== Готово! ==="
echo ""
echo "Статус:  systemctl status $SERVICE_NAME"
echo "Логи:    journalctl -u $SERVICE_NAME -f"
echo "Стоп:    systemctl stop $SERVICE_NAME"
echo "Рестарт: systemctl restart $SERVICE_NAME"
