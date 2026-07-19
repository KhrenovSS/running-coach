#!/bin/bash
# Обёртка для docker compose с sudo (Docker wrapper with sudo)
# Безопасно читает пароль из .env, не хранит в истории и не показывает в ps
set -a
source "$(dirname "$0")/../.env"
set +a

# DB SAFETY: block `down -v` / `--volumes` without explicit CONFIRM
for arg in "$@"; do
    if [[ "$arg" == "-v" || "$arg" == "--volumes" ]]; then
        echo "⚠️  WARNING: This will DESTROY all database data (trainings, users, settings)!"
        read -p "Type CONFIRM to continue: " confirm
        if [[ "$confirm" != "CONFIRM" ]]; then
            echo "Aborted. Data preserved."
            exit 1
        fi
    fi
done

echo "$SUDO_PASSWORD" | sudo -S docker compose -f "$(dirname "$0")/../docker-compose.yml" "$@"