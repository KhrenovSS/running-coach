#!/bin/bash
# Автоматический бэкап PostgreSQL перед деплоем (Auto backup before deploy)
set -a
source "$(dirname "$0")/../.env"
set +a

BACKUP_DIR="$(dirname "$0")/../backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
FILENAME="$BACKUP_DIR/backup_${TIMESTAMP}.sql.gz"

echo "Creating backup: $FILENAME"
echo "$SUDO_PASSWORD" | sudo -S docker compose -f "$(dirname "$0")/../docker-compose.yml" exec -T db pg_dump -U running_coach running_coach | gzip > "$FILENAME"

if [ -s "$FILENAME" ]; then
    echo "Backup saved: $FILENAME ($(du -h "$FILENAME" | cut -f1))"
else
    echo "ERROR: Backup is empty! Check if db container is running."
    rm -f "$FILENAME"
    exit 1
fi

# Ротация: хранить последние 7 бэкапов (Rotation: keep last 7)
ls -t "$BACKUP_DIR"/backup_*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm
REMAINING=$(ls "$BACKUP_DIR"/backup_*.sql.gz 2>/dev/null | wc -l)
echo "Old backups cleaned (keeping last 7, $REMAINING remaining)"
