from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from app.database import engine, Base, SessionLocal
from app.dependencies import SECRET_KEY, ALGORITHM
import os, re, logging
from pathlib import Path
from app import models as iris_models
import app.models_qr
import app.models_v3
import app.models_contador
from app.seed_demo import ensure_demo_users, ensure_bootstrap_admin
from app.seed_datos import ensure_datos_demo
from app.seed_v3 import ensure_datos_v3
from app.routers import auth, conjuntos, inmuebles, zonas_comunes, reservas, pqrs, qr, gestion, feature_plus
from app.routers import (
    v3_pagos, v3_avisos, v3_mantenimiento, v3_visitantes, v3_seguridad,
    v3_contabilidad, v3_asambleas, v3_reservas, v3_indicadores, v3_admin, v3_files,
    v3_contador_profesional,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


def migrate_schema():
    """Migración aditiva e idempotente para instalaciones heredadas SQLite/MySQL/PostgreSQL."""
    additions = {
        "usuarios": {"rol": "VARCHAR(20) NOT NULL DEFAULT 'residente'", "email_verificado": "BOOLEAN NOT NULL DEFAULT TRUE", "cambio_password_requerido": "BOOLEAN NOT NULL DEFAULT FALSE"},
        "zonas_comunes": {"hora_apertura": "VARCHAR(5) NOT NULL DEFAULT '06:00'", "hora_cierre": "VARCHAR(5) NOT NULL DEFAULT '22:00'", "duracion_max_minutos": "INTEGER NOT NULL DEFAULT 240", "max_dias_anticipacion": "INTEGER NOT NULL DEFAULT 30", "max_reservas_dia_inmueble": "INTEGER NOT NULL DEFAULT 2"},
        "comunicados": {"adjunto_url": "VARCHAR(500)"},
        "paquetes": {"foto_url": "VARCHAR(500)", "codigo_retiro_hash": "VARCHAR(64)"},
        "parqueaderos": {"tarifa_mensual": "NUMERIC(12, 2) NOT NULL DEFAULT 0"},
    }
    with engine.begin() as conn:
        for table, columns in additions.items():
            if table not in set(inspect(conn).get_table_names()):
                continue
            existing = {col["name"] for col in inspect(conn).get_columns(table)}
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def migrate_schema_v3():
    """Migración aditiva e idempotente para las tablas de IRIS 3.0.

    Las tablas nuevas se crean con Base.metadata.create_all; aquí sólo se
    completan columnas que se hayan añadido a tablas v3 ya existentes, para
    permitir actualizaciones sin pérdida de datos.
    """
    additions = {
        "v3_pasarela_config": {"conciliacion_automatica": "BOOLEAN NOT NULL DEFAULT TRUE", "merchant_id": "VARCHAR(120)"},
        "v3_transacciones_pago": {"conciliado": "BOOLEAN NOT NULL DEFAULT FALSE", "conciliado_en": "TIMESTAMP", "pago_id": "INTEGER"},
        "v3_plantillas_aviso": {"activo": "BOOLEAN NOT NULL DEFAULT TRUE"},
        "v3_ordenes_mantenimiento": {"costo_final": "NUMERIC(12, 2)", "cerrada_en": "TIMESTAMP"},
        "v3_cotizaciones_mantenimiento": {
            "aprobacion_estado": "VARCHAR(20) NOT NULL DEFAULT 'pendiente'",
            "aprobada_por": "INTEGER",
            "aprobada_en": "TIMESTAMP",
            "nota_aprobacion": "TEXT",
        },
        "v3_autorizaciones_visita": {"permite_vehiculo": "BOOLEAN NOT NULL DEFAULT FALSE", "pin_hash": "VARCHAR(64)", "observacion": "VARCHAR(255)"},
        "v3_registros_acceso": {"alerta_enviada": "BOOLEAN NOT NULL DEFAULT FALSE", "alerta_detalle": "VARCHAR(255)"},
        "v3_respaldos": {"duracion_prueba_ms": "INTEGER", "motor": "VARCHAR(30) NOT NULL DEFAULT 'postgresql'"},
    }
    with engine.begin() as conn:
        tablas = set(inspect(conn).get_table_names())
        for table, columns in additions.items():
            if table not in tablas:
                continue
            existing = {col["name"] for col in inspect(conn).get_columns(table)}
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


Base.metadata.create_all(bind=engine)
migrate_schema()
migrate_schema_v3()
APP_ENV = os.getenv("APP_ENV", "development").lower()
if APP_ENV == "production":
    ensure_bootstrap_admin()
else:
    ensure_demo_users()
    ensure_datos_demo()
    ensure_datos_v3()

app = FastAPI(title="Sistema de Conjuntos Residenciales IRIS", version="3.1.0", docs_url="/docs" if APP_ENV != "production" else None, redoc_url=None, openapi_url="/openapi.json" if APP_ENV != "production" else None)
cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads")); UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.middleware("http")
async def audit_mutations(request: Request, call_next):
    response = await call_next(request)
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and response.status_code < 400 and not request.url.path.startswith(("/auth/", "/health", "/v2/admin/backup")):
        session = None
        try:
            auth_header = request.headers.get("authorization", "")
            token = auth_header.split(" ", 1)[1] if auth_header.lower().startswith("bearer ") else None
            claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]) if token else {}
            session = SessionLocal()
            email = claims.get("sub")
            actor = session.query(iris_models.Usuario).filter_by(email=email).first() if email else None
            path = request.url.path
            cid_match = re.match(r"^/conjuntos/(\d+)(?:/|$)", path)
            conjunto_id = int(cid_match.group(1)) if cid_match else None
            if conjunto_id is None:
                if path.startswith("/reservas/"):
                    try:
                        row = session.query(iris_models.Reserva).filter_by(id=int(path.split("/")[2])).first()
                        zone = session.query(iris_models.ZonaComun).filter_by(id=row.zona_id).first() if row else None
                        conjunto_id = zone.conjunto_id if zone else None
                    except (ValueError, IndexError): pass
                elif path.startswith("/pqrs/"):
                    try:
                        row = session.query(iris_models.PQRS).filter_by(id=int(path.split("/")[2])).first()
                        unit = session.query(iris_models.Inmueble).filter_by(id=row.inmueble_id).first() if row else None
                        conjunto_id = unit.conjunto_id if unit else None
                    except (ValueError, IndexError): pass
            if conjunto_id is None and path.startswith("/v2/"):
                try:
                    requested_set = request.query_params.get("conjunto_id")
                    membership_ids = {x[0] for x in session.query(iris_models.ConjuntoMembership.conjunto_id).filter_by(usuario_id=actor.id).all()} if actor and not actor.es_super_admin else set()
                    if requested_set and int(requested_set) in membership_ids:
                        conjunto_id = int(requested_set)
                    else:
                        match = re.match(r"^/v2/(incidents|payments|reservation-blocks|emergency-contacts)/(\d+)(?:/|$)", path)
                        if match:
                            table, item_id = match.group(1), int(match.group(2))
                            if table == "incidents":
                                obj = session.query(iris_models.Incidente).filter_by(id=item_id).first(); conjunto_id = obj.conjunto_id if obj else None
                            elif table == "payments":
                                obj = session.query(iris_models.Pago).filter_by(id=item_id).first(); unit = session.query(iris_models.Inmueble).filter_by(id=obj.inmueble_id).first() if obj else None; conjunto_id = unit.conjunto_id if unit else None
                            elif table == "reservation-blocks":
                                obj = session.query(iris_models.BloqueoReserva).filter_by(id=item_id).first(); zone = session.query(iris_models.ZonaComun).filter_by(id=obj.zona_id).first() if obj else None; conjunto_id = zone.conjunto_id if zone else None
                            else:
                                obj = session.query(iris_models.ContactoEmergencia).filter_by(id=item_id).first(); conjunto_id = obj.conjunto_id if obj else None
                        if conjunto_id is None and len(membership_ids) == 1:
                            conjunto_id = next(iter(membership_ids))
                        if conjunto_id is None and actor and not actor.es_super_admin and actor.rol == "residente":
                            resident_sets = {x[0] for x in session.query(iris_models.Inmueble.conjunto_id).filter((iris_models.Inmueble.propietario_id == actor.id) | (iris_models.Inmueble.inquilino_id == actor.id)).all()}
                            if len(resident_sets) == 1: conjunto_id = next(iter(resident_sets))
                except Exception:
                    logging.getLogger("iris.audit").debug("No se pudo asociar el evento v2 al conjunto")
            client_ip = request.client.host if request.client else None
            session.add(iris_models.Auditoria(conjunto_id=conjunto_id, usuario_id=actor.id if actor else None, email_usuario=email, accion=request.method, ruta=path[:255], metodo=request.method, codigo_http=response.status_code, ip=client_ip, agente=request.headers.get("user-agent", "")[:255]))
            session.commit()
            financial_event = path.startswith(("/v2/payments", "/v3/pagos", "/reservas/", "/v3/reservas/", "/cuotas/"))
            signed_payment_webhook = path.startswith("/v3/pagos/webhook/")
            if financial_event and (actor or signed_payment_webhook):
                try:
                    from app.routers.v3_contador_profesional import sincronizar_asientos
                    if signed_payment_webhook:
                        # El proveedor autentica el webhook por firma, no con JWT de usuario.
                        finance_sets = [row.id for row in session.query(iris_models.Conjunto.id).all()]
                    elif actor.es_super_admin:
                        finance_sets = [row.id for row in session.query(iris_models.Conjunto.id).all()]
                    elif actor.rol in ("admin", "contador"):
                        finance_sets = [row[0] for row in session.query(iris_models.ConjuntoMembership.conjunto_id).filter_by(usuario_id=actor.id, rol=actor.rol).all()]
                    else:
                        finance_sets = [row[0] for row in session.query(iris_models.Inmueble.conjunto_id).filter(
                            (iris_models.Inmueble.propietario_id == actor.id) | (iris_models.Inmueble.inquilino_id == actor.id)).distinct().all()]
                    for finance_set in finance_sets:
                        sincronizar_asientos(session, finance_set, actor.id)
                except Exception:
                    session.rollback()
                    logging.getLogger("iris.accounting").exception("No se pudieron sincronizar los asientos automáticos")
        except Exception:
            if session:
                session.rollback()
            logging.getLogger("iris.audit").exception("No se pudo guardar evento de auditoría")
        finally:
            if session:
                session.close()
    return response

for route in (auth, conjuntos, inmuebles, zonas_comunes, reservas, pqrs, qr, gestion, feature_plus,
              v3_pagos, v3_avisos, v3_mantenimiento, v3_visitantes, v3_seguridad,
              v3_contabilidad, v3_asambleas, v3_reservas, v3_indicadores, v3_admin, v3_files,
              v3_contador_profesional):
    app.include_router(route.router)

@app.get("/")
def root():
    return {"mensaje": "API funcionando", "version": app.version}

@app.get("/health")
def health():
    return {"ok": True}
