#!/bin/sh
# Respaldo de IRIS 3.0 (POSIX sh, compatible con las imágenes Alpine de PostgreSQL)
#
# 1. Vuelca la base PostgreSQL (pg_dump, formato custom)
# 2. Empaqueta los adjuntos
# 3. Calcula el checksum SHA-256
# 4. PRUEBA DE RESTAURACIÓN en una base temporal y compara tablas
# 5. Depura respaldos antiguos según retención
#
# Uso:
#   DATABASE_URL=postgresql://usuario:clave@host:5432/iris sh deploy/backup/backup.sh
# Variables:
#   IRIS_BACKUP_DIR             carpeta destino (por defecto ./backups)
#   IRIS_RESTORE_TEST_URL       base temporal para la prueba (recomendada)
#   IRIS_BACKUP_RETENCION_DIAS  días a conservar (por defecto 14)
#   UPLOAD_DIR                  carpeta de adjuntos (por defecto ./uploads)
set -eu

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${IRIS_BACKUP_DIR:-./backups}"
RETENCION="${IRIS_BACKUP_RETENCION_DIAS:-14}"
UPLOADS="${UPLOAD_DIR:-./uploads}"
DATABASE_URL="${DATABASE_URL:-${PGURL:-}}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [ -z "$DATABASE_URL" ]; then
  echo "ERROR: define DATABASE_URL (o PGURL) con la cadena de conexión PostgreSQL." >&2
  exit 1
fi
for bin in pg_dump psql; do
  command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: falta $bin (instala postgresql-client)." >&2; exit 1; }
done

mkdir -p "$BACKUP_DIR"
DUMP="$BACKUP_DIR/iris-${STAMP}.dump"
ADJUNTOS="$BACKUP_DIR/iris-adjuntos-${STAMP}.tar.gz"

log "1/5 · Volcando la base de datos…"
pg_dump --no-owner --no-privileges --format=custom --file "$DUMP" "$DATABASE_URL"

if [ -d "$UPLOADS" ] && [ -n "$(ls -A "$UPLOADS" 2>/dev/null)" ]; then
  log "2/5 · Empaquetando adjuntos…"
  tar -czf "$ADJUNTOS" -C "$UPLOADS" .
  ADJUNTOS_JSON="$(basename "$ADJUNTOS")"
else
  log "2/5 · Sin adjuntos que empaquetar (se omite)."
  ADJUNTOS_JSON="null"
fi

CHECKSUM="$(sha256sum "$DUMP" | cut -d' ' -f1)"
printf '%s  %s\n' "$CHECKSUM" "$(basename "$DUMP")" > "$DUMP.sha256"
log "3/5 · Checksum del dump: $CHECKSUM"

TESTEADO="no"
DETALLE="Prueba de restauración omitida (define IRIS_RESTORE_TEST_URL)"
if [ -n "${IRIS_RESTORE_TEST_URL:-}" ]; then
  log "4/5 · PRUEBA DE RESTAURACIÓN en base temporal…"
  TABLAS_ORIGEN="$(psql "$DATABASE_URL" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
  psql "$IRIS_RESTORE_TEST_URL" -q -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" >/dev/null
  pg_restore --no-owner --no-privileges --dbname "$IRIS_RESTORE_TEST_URL" "$DUMP" >/dev/null 2>&1 || true
  psql "$IRIS_RESTORE_TEST_URL" -q -c "ANALYZE;" >/dev/null 2>&1 || true
  TABLAS_RESTAURADAS="$(psql "$IRIS_RESTORE_TEST_URL" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
  FILAS_RESTAURADAS="$(psql "$IRIS_RESTORE_TEST_URL" -tAc "SELECT COALESCE(SUM(n_live_tup),0) FROM pg_stat_user_tables")"
  log "    tablas origen=$TABLAS_ORIGEN · restauradas=$TABLAS_RESTAURADAS · filas restauradas=$FILAS_RESTAURADAS"
  if [ "$TABLAS_RESTAURADAS" -ge "$TABLAS_ORIGEN" ]; then
    TESTEADO="ok"
    DETALLE="Restauración verificada: ${TABLAS_RESTAURADAS} tablas, ${FILAS_RESTAURADAS} filas"
    log "    OK · prueba de restauración superada"
  else
    TESTEADO="fallido"
    DETALLE="Faltan tablas: origen=${TABLAS_ORIGEN} restauradas=${TABLAS_RESTAURADAS}"
    log "    FALLO · la restauración no trae todas las tablas" >&2
  fi
else
  log "4/5 · $DETALLE"
fi

log "5/5 · Depurando respaldos con más de ${RETENCION} días…"
find "$BACKUP_DIR" -type f \( -name 'iris-*.dump' -o -name 'iris-adjuntos-*.tar.gz' -o -name 'iris-*.dump.sha256' \) -mtime "+${RETENCION}" -delete

TAMANO="$(stat -c %s "$DUMP" 2>/dev/null || wc -c < "$DUMP")"
cat > "$BACKUP_DIR/iris-backup-${STAMP}.json" <<JSON
{
  "generado_en": "$(date -Iseconds 2>/dev/null || date)",
  "dump": "$(basename "$DUMP")",
  "checksum_sha256": "${CHECKSUM}",
  "adjuntos": ${ADJUNTOS_JSON},
  "tamano_dump_bytes": ${TAMANO},
  "prueba_restauracion": "${TESTEADO}",
  "detalle_prueba": "${DETALLE}",
  "retencion_dias": ${RETENCION}
}
JSON

log "Respaldo completado: $(basename "$DUMP") · prueba de restauración: ${TESTEADO}"

if [ "$TESTEADO" = "fallido" ]; then
  exit 2
fi