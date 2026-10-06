#!/usr/bin/env bash
# Instala el respaldo diario de IRIS en el crontab del usuario actual.
#   ./deploy/backup/install-cron.sh [hora] [minuto]
# Ejemplo: ./deploy/backup/install-cron.sh 3 15   -> todos los días 03:15
set -euo pipefail

HORA="${1:-3}"
MINUTO="${2:-15}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${IRIS_BACKUP_DIR:-$RAIZ/backups}"

mkdir -p "$LOG_DIR"
LINEA="${MINUTO} ${HORA} * * * cd ${RAIZ} && /usr/bin/env bash deploy/backup/backup.sh >> ${LOG_DIR}/respaldo.log 2>&1"

if crontab -l 2>/dev/null | grep -Fq "deploy/backup/backup.sh"; then
  echo "Ya existe una tarea de respaldo de IRIS en el crontab:"
  crontab -l | grep -F "deploy/backup/backup.sh"
  exit 0
fi

( crontab -l 2>/dev/null; echo "# IRIS 3.0 · respaldo diario con prueba de restauración"; echo "$LINEA" ) | crontab -
echo "Tarea instalada: $LINEA"
echo "Registros en ${LOG_DIR}/respaldo.log"