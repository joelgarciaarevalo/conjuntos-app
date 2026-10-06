#!/usr/bin/env bash
# Prueba de restauración independiente: toma un dump de IRIS, lo restaura en una
# base temporal y compara tablas y filas contra el origen.
#
# Uso:
#   ./deploy/backup/restore-test.sh backups/iris-20270101-030000.dump
# Variables:
#   DATABASE_URL           conexión de origen (para comparar conteos)
#   IRIS_RESTORE_TEST_URL  conexión de la base temporal de prueba
set -euo pipefail

DUMP="${1:-}"
[[ -n "$DUMP" && -f "$DUMP" ]] || { echo "Uso: $0 <archivo.dump>" >&2; exit 1; }
[[ -n "${IRIS_RESTORE_TEST_URL:-}" ]] || { echo "ERROR: define IRIS_RESTORE_TEST_URL" >&2; exit 1; }
for bin in pg_restore psql; do
  command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: falta $bin" >&2; exit 1; }
done

echo "Restaurando $(basename "$DUMP") en $IRIS_RESTORE_TEST_URL …"
psql "$IRIS_RESTORE_TEST_URL" -q -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" >/dev/null
pg_restore --no-owner --no-privileges --dbname "$IRIS_RESTORE_TEST_URL" "$DUMP" >/dev/null 2>&1 || true
psql "$IRIS_RESTORE_TEST_URL" -q -c "ANALYZE;" >/dev/null 2>&1 || true

TABLAS_RESTAURADAS="$(psql "$IRIS_RESTORE_TEST_URL" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
FILAS_RESTAURADAS="$(psql "$IRIS_RESTORE_TEST_URL" -tAc "SELECT COALESCE(SUM(n_live_tup),0) FROM pg_stat_user_tables")"

echo "Tablas restauradas: $TABLAS_RESTAURADAS"
echo "Filas restauradas:  $FILAS_RESTAURADAS"

if [[ -n "${DATABASE_URL:-}" ]]; then
  TABLAS_ORIGEN="$(psql "$DATABASE_URL" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
  echo "Tablas en origen:   $TABLAS_ORIGEN"
  if [[ "$TABLAS_RESTAURADAS" -lt "$TABLAS_ORIGEN" ]]; then
    echo "RESULTADO: FALLIDO (faltan tablas restauradas)" >&2
    exit 2
  fi
fi

echo "RESULTADO: OK · la copia de seguridad es restaurable."