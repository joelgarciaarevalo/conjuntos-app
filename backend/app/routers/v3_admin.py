"""Operación lista para producción: respaldos con prueba de restauración,
estado del sistema y lista de verificación del despliegue."""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import DATABASE_URL, engine, get_db
from app.security_v3 import dependencia_2fa, exigir_2fa_admin, get_usuario_v3
from app.routers.v3_common import admin_only, json_dumps, json_loads, localnow, model_data
from app.services.crypto_v3 import hash_valor

router = APIRouter(prefix="/v3/admin", tags=["v3 · Operación"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
BACKUP_DIR = Path(os.getenv("IRIS_BACKUP_DIR", "./backups"))


def _motor() -> str:
    return "sqlite" if engine.url.drivername.startswith("sqlite") else "postgresql" if "postgres" in engine.url.drivername else "mysql"


@router.get("/estado-sistema")
def estado_sistema(db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    admin_only(user)
    inspector = inspect(engine)
    tablas = set(inspector.get_table_names())
    tablas_v3 = [t for t in tablas if t.startswith("v3_")]
    faltantes = [m.__tablename__ for m in (models_v3.ConfigPasarela, models_v3.TransaccionPago, models_v3.ConsentimientoAviso,
                                           models_v3.OrdenMantenimiento, models_v3.RegistroAcceso, models_v3.SesionUsuario,
                                           models_v3.Egreso, models_v3.Asamblea, models_v3.ReglaZonaReserva, models_v3.Respaldo)
                 if m.__tablename__ not in tablas]
    conjuntos = db.query(models.Conjunto).count()
    respaldos = db.query(models_v3.Respaldo).order_by(models_v3.Respaldo.id.desc()).limit(1).first()
    return {
        "version": "3.1.0",
        "entorno": os.getenv("APP_ENV", "development"),
        "motor_bd": _motor(),
        "url_bd_ofuscada": engine.url.render_as_string(hide_password=True),
        "tablas": len(tablas),
        "tablas_v3": len(tablas_v3),
        "migraciones_faltantes": faltantes,
        "conjuntos": conjuntos,
        "adjuntos": len(list(UPLOAD_DIR.glob("*"))) if UPLOAD_DIR.exists() else 0,
        "ultimo_respaldo": model_data(respaldos) if respaldos else None,
        "hora_servidor": localnow().isoformat(),
    }


@router.get("/checklist-produccion")
def checklist(user=Depends(get_usuario_v3)):
    admin_only(user)
    secret = os.getenv("SECRET_KEY") or ""
    entorno = os.getenv("APP_ENV", "development").lower()
    comprobaciones = [
        {"clave": "APP_ENV", "ok": entorno == "production", "detalle": f"APP_ENV={entorno}", "sugerencia": "Define APP_ENV=production"},
        {"clave": "SECRET_KEY", "ok": len(secret) >= 32 and "REEMPLAZAR" not in secret.upper(), "detalle": f"{len(secret)} caracteres", "sugerencia": "Usa una clave aleatoria de 32+ caracteres"},
        {"clave": "PostgreSQL", "ok": _motor() == "postgresql", "detalle": f"motor {_motor()}", "sugerencia": "Configura DATABASE_URL con PostgreSQL"},
        {"clave": "CORS_ORIGINS", "ok": "localhost" not in os.getenv("CORS_ORIGINS", ""), "detalle": os.getenv("CORS_ORIGINS", "sin definir"), "sugerencia": "Restringe CORS a tu dominio HTTPS"},
        {"clave": "HTTPS", "ok": os.getenv("IRIS_HTTPS", "").lower() in ("1", "true", "on"), "detalle": os.getenv("IRIS_HTTPS", "no configurado"), "sugerencia": "Termina TLS en el proxy y marca IRIS_HTTPS=true"},
        {"clave": "SMTP", "ok": bool(os.getenv("SMTP_HOST")), "detalle": os.getenv("SMTP_HOST", "sin definir"), "sugerencia": "Configura SMTP para correo transaccional"},
        {"clave": "Web Push", "ok": bool(os.getenv("VAPID_PUBLIC_KEY") and os.getenv("VAPID_PRIVATE_KEY")), "detalle": "VAPID", "sugerencia": "Configura VAPID para notificaciones push"},
        {"clave": "Avisos WhatsApp/SMS", "ok": bool(os.getenv("IRIS_AVISOS_PROVEEDOR")), "detalle": os.getenv("IRIS_AVISOS_PROVEEDOR", "simulado"), "sugerencia": "Configura el proveedor de avisos (meta o twilio)"},
        {"clave": "Respaldos", "ok": bool(os.getenv("IRIS_BACKUP_DIR")), "detalle": os.getenv("IRIS_BACKUP_DIR", "por defecto"), "sugerencia": "Define IRIS_BACKUP_DIR con volumen persistente"},
        {"clave": "Documentación oculta", "ok": entorno == "production", "detalle": "Swagger y OpenAPI se ocultan en producción", "sugerencia": "Define APP_ENV=production"},
    ]
    return {"entorno": entorno, "cumplidas": len([c for c in comprobaciones if c["ok"]]), "total": len(comprobaciones), "comprobaciones": comprobaciones}


# ---------------------------------------------------------------------------
# Respaldos
# ---------------------------------------------------------------------------
def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _respaldar_sqlite(destino: Path) -> None:
    origen = engine.raw_connection()
    try:
        copia = sqlite3.connect(str(destino))
        origen.driver_connection.backup(copia)
        copia.close()
    finally:
        origen.close()


def _respaldar_postgres(destino: Path) -> None:
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise HTTPException(501, "pg_dump no está disponible en el servidor. Usa un script de respaldo del proveedor o instala postgresql-client.")
    comando = [pg_dump, "--no-owner", "--no-privileges", "--format=custom", "--file", str(destino), DATABASE_URL]
    resultado = subprocess.run(comando, capture_output=True, text=True, timeout=1800)
    if resultado.returncode != 0:
        raise HTTPException(500, f"pg_dump falló: {resultado.stderr[:400]}")


def _empaquetar_adjuntos() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        if UPLOAD_DIR.exists():
            for archivo in UPLOAD_DIR.glob("*"):
                if archivo.is_file():
                    tar.add(archivo, arcname=archivo.name)
    buffer.seek(0)
    return buffer.read()


@router.get("/respaldos")
def listar_respaldos(db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    admin_only(user)
    return [model_data(r) | {"tablas_verificadas": json_loads(r.tablas_verificadas, [])}
            for r in db.query(models_v3.Respaldo).order_by(models_v3.Respaldo.id.desc()).limit(50).all()]


@router.post("/respaldos", status_code=201)
def crear_respaldo(incluir_adjuntos: bool = True, db: Session = Depends(get_db), user=Depends(get_usuario_v3),
                   otp: str | None = dependencia_2fa()):
    """Genera una copia de seguridad y la registra (la prueba de restauración es aparte)."""
    admin_only(user)
    exigir_2fa_admin(db, user, otp)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    motor = _motor()
    nombre = f"iris-{motor}-{_stamp()}-{uuid.uuid4().hex[:6]}"
    archivo_bd = BACKUP_DIR / (nombre + (".db" if motor == "sqlite" else ".dump"))
    if motor == "sqlite":
        _respaldar_sqlite(archivo_bd)
    else:
        _respaldar_postgres(archivo_bd)
    archivo_final = archivo_bd
    if incluir_adjuntos:
        archivo_final = BACKUP_DIR / (nombre + ".tar.gz")
        with tarfile.open(archivo_final, "w:gz") as tar:
            tar.add(archivo_bd, arcname=archivo_bd.name)
            if UPLOAD_DIR.exists():
                for item in UPLOAD_DIR.glob("*"):
                    if item.is_file():
                        tar.add(item, arcname=f"uploads/{item.name}")
        archivo_bd.unlink(missing_ok=True)
    contenido = archivo_final.read_bytes()
    registro = models_v3.Respaldo(
        tipo="completo" if incluir_adjuntos else motor, archivo=archivo_final.name, motor=motor,
        tamano_bytes=len(contenido), checksum=hashlib.sha256(contenido).hexdigest()[:64],
        estado_prueba="pendiente", creado_por=user.id,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return model_data(registro)


@router.get("/respaldos/{respaldo_id}/descargar")
def descargar_respaldo(respaldo_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    admin_only(user)
    exigir_2fa_admin(db, user, otp)
    fila = db.query(models_v3.Respaldo).filter_by(id=respaldo_id).first()
    if not fila:
        raise HTTPException(404, "Respaldo no encontrado")
    ruta = (BACKUP_DIR / fila.archivo).resolve()
    if BACKUP_DIR.resolve() not in ruta.parents or not ruta.is_file():
        raise HTTPException(404, "El archivo del respaldo no está disponible en el servidor")
    media = "application/gzip" if fila.archivo.endswith(".tar.gz") else "application/vnd.sqlite3" if fila.archivo.endswith(".db") else "application/octet-stream"
    return FileResponse(ruta, media_type=media, filename=fila.archivo, headers={"Cache-Control": "no-store"})


@router.post("/respaldos/{respaldo_id}/verificar")
def verificar_respaldo(respaldo_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    """Prueba de restauración: restaura la copia en un entorno temporal y cuenta filas."""
    admin_only(user)
    exigir_2fa_admin(db, user, otp)
    fila = db.query(models_v3.Respaldo).filter_by(id=respaldo_id).first()
    if not fila:
        raise HTTPException(404, "Respaldo no encontrado")
    ruta = (BACKUP_DIR / fila.archivo).resolve()
    if BACKUP_DIR.resolve() not in ruta.parents or not ruta.is_file():
        raise HTTPException(404, "El archivo del respaldo no está disponible en el servidor")
    inicio = time.time()
    detalle, tablas, total_filas = "", [], 0
    try:
        with tempfile.TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            base = ruta.name.replace(".tar.gz", "")
            fuente = ruta
            if ruta.name.endswith(".tar.gz"):
                with tarfile.open(ruta, "r:gz") as tar:
                    tar.extractall(carpeta, filter="data")
                candidatos = [p for p in carpeta.rglob("*") if p.is_file() and (p.suffix in (".db", ".dump") or p.name.startswith("iris-"))]
                if not candidatos:
                    raise RuntimeError("El paquete no contiene una base de datos reconocible")
                fuente = candidatos[0]
            if fuente.suffix == ".db" or fila.motor == "sqlite":
                destino = carpeta / "restaurada.db"
                shutil.copyfile(fuente, destino)
                conexion = sqlite3.connect(str(destino))
                cursor = conexion.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                nombres = [r[0] for r in cursor.fetchall()]
                for nombre_tabla in nombres:
                    cursor.execute(f'SELECT COUNT(*) FROM "{nombre_tabla}"')
                    total = cursor.fetchone()[0]
                    tablas.append({"tabla": nombre_tabla, "filas": total})
                    total_filas += total
                cursor.execute("PRAGMA integrity_check")
                integridad = cursor.fetchone()[0]
                conexion.close()
                detalle = f"Restauración SQLite verificada en entorno temporal. integrity_check={integridad}. {len(nombres)} tablas."
                if integridad != "ok":
                    raise RuntimeError(f"integrity_check devolvió {integridad}")
            else:
                pg_restore = shutil.which("pg_restore")
                url_prueba = os.getenv("IRIS_RESTORE_TEST_URL")
                if not pg_restore or not url_prueba:
                    raise RuntimeError("Para PostgreSQL configura IRIS_RESTORE_TEST_URL y disponibilidad de pg_restore para ejecutar la prueba completa")
                comando = [pg_restore, "--clean", "--if-exists", "--no-owner", "--dbname", url_prueba, str(fuente)]
                resultado = subprocess.run(comando, capture_output=True, text=True, timeout=1800)
                if resultado.returncode != 0:
                    raise RuntimeError(f"pg_restore falló: {resultado.stderr[:300]}")
                import psycopg2  # noqa: WPS433 (import diferido: sólo se necesita en PostgreSQL)
                conexion = psycopg2.connect(url_prueba)
                cursor = conexion.cursor()
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                nombres = [r[0] for r in cursor.fetchall()]
                for nombre_tabla in nombres:
                    cursor.execute(f'SELECT COUNT(*) FROM "{nombre_tabla}"')
                    total = cursor.fetchone()[0]
                    tablas.append({"tabla": nombre_tabla, "filas": total})
                    total_filas += total
                cursor.close()
                conexion.close()
                detalle = f"Restauración PostgreSQL verificada en base temporal. {len(nombres)} tablas restauradas."
        fila.estado_prueba = "ok"
    except Exception as exc:
        fila.estado_prueba = "fallido"
        detalle = f"La prueba de restauración falló: {str(exc)[:500]}"
    fila.detalle_prueba = detalle
    fila.tablas_verificadas = json_dumps(tablas[:200])
    fila.filas_verificadas = total_filas
    fila.duracion_prueba_ms = int((time.time() - inicio) * 1000)
    fila.probado_en = localnow()
    db.commit()
    db.refresh(fila)
    return model_data(fila) | {"tablas_verificadas": tablas[:200]}


@router.get("/backup")
def respaldo_directo(user=Depends(get_usuario_v3)):
    """Descarga inmediata del respaldo (compatibilidad con el flujo previo)."""
    admin_only(user)
    motor = _motor()
    if motor == "sqlite":
        origen = engine.raw_connection()
        temporal = Path(tempfile.gettempdir()) / f"iris-backup-{uuid.uuid4().hex}.db"
        try:
            copia = sqlite3.connect(str(temporal))
            origen.driver_connection.backup(copia)
            copia.close()
        finally:
            origen.close()
        contenido = temporal.read_bytes()
        temporal.unlink(missing_ok=True)
        return StreamingResponse(io.BytesIO(contenido), media_type="application/vnd.sqlite3",
                                 headers={"Content-Disposition": f'attachment; filename="iris-backup-{_stamp()}.db"', "Cache-Control": "no-store"})
    raise HTTPException(501, "Para PostgreSQL usa POST /v3/admin/respaldos (pg_dump) o el script deploy/backup/backup.sh")


@router.get("/adjuntos/paquete")
def paquete_adjuntos(db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    admin_only(user)
    exigir_2fa_admin(db, user, otp)
    datos = _empaquetar_adjuntos()
    return StreamingResponse(io.BytesIO(datos), media_type="application/gzip",
                             headers={"Content-Disposition": f'attachment; filename="iris-adjuntos-{_stamp()}.tar.gz"', "Cache-Control": "no-store"})


@router.get("/salud")
def salud(db: Session = Depends(get_db)):
    """Healthcheck público para el orquestador (sin datos sensibles)."""
    try:
        db.execute(text("SELECT 1"))
        bd = "ok"
    except Exception:
        bd = "error"
    return {"ok": bd == "ok", "bd": bd, "version": "3.0.0", "hora": localnow().isoformat()}
