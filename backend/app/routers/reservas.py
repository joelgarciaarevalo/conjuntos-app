from datetime import datetime, time
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.dependencies import get_usuario_actual
from app.permissions import allowed_set_ids, require_access_set, require_admin_set

router = APIRouter(prefix="/reservas", tags=["Reservas"])
TZ = ZoneInfo("America/Bogota")


def is_admin(user):
    return bool(user.es_super_admin or user.rol == "admin")


def local_naive(value: datetime) -> datetime:
    # Entradas sin offset se interpretan como hora local del conjunto (Bogotá).
    if value.tzinfo is not None:
        value = value.astimezone(TZ).replace(tzinfo=None)
    return value


@router.post("/", response_model=schemas.ReservaResponse, status_code=201)
def crear_reserva(datos: schemas.ReservaCreate, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    inmueble = db.query(models.Inmueble).filter_by(id=datos.inmueble_id).first()
    if not inmueble: raise HTTPException(404, "Inmueble no encontrado")
    zona = db.query(models.ZonaComun).filter_by(id=datos.zona_id).first()
    if not zona: raise HTTPException(404, "Zona común no encontrada")
    require_access_set(db, usuario_actual, zona.conjunto_id)
    if zona.conjunto_id != inmueble.conjunto_id: raise HTTPException(400, "La zona no pertenece al conjunto de este inmueble")
    if usuario_actual.id not in (inmueble.propietario_id, inmueble.inquilino_id): raise HTTPException(403, "No tienes permiso para reservar este inmueble")
    inicio, fin = local_naive(datos.fecha_inicio), local_naive(datos.fecha_fin)
    if fin <= inicio: raise HTTPException(400, "La fecha de fin debe ser posterior a la de inicio")
    if inicio < datetime.now(TZ).replace(tzinfo=None): raise HTTPException(400, "La fecha de inicio no puede estar en el pasado")
    if inicio.date() != fin.date(): raise HTTPException(400, "La reserva debe iniciar y terminar el mismo día")
    apertura = time.fromisoformat(zona.hora_apertura or "06:00")
    cierre = time.fromisoformat(zona.hora_cierre or "22:00")
    if inicio.time() < apertura or fin.time() > cierre: raise HTTPException(400, f"La zona está disponible de {apertura.strftime('%H:%M')} a {cierre.strftime('%H:%M')}")
    duracion_min = (fin - inicio).total_seconds() / 60
    if duracion_min > zona.duracion_max_minutos: raise HTTPException(400, f"La duración máxima para esta zona es {zona.duracion_max_minutos} minutos")
    if inicio.date() > datetime.now(TZ).date() + __import__("datetime").timedelta(days=zona.max_dias_anticipacion): raise HTTPException(400, f"Las reservas solo pueden hacerse con {zona.max_dias_anticipacion} días de anticipación")
    day_start = inicio.replace(hour=0, minute=0, second=0, microsecond=0); day_end = day_start.replace(hour=23, minute=59, second=59)
    daily = db.query(models.Reserva).filter(models.Reserva.inmueble_id == inmueble.id, models.Reserva.zona_id == zona.id, models.Reserva.estado.in_(["pendiente", "aprobada"]), models.Reserva.fecha_inicio >= day_start, models.Reserva.fecha_inicio <= day_end).count()
    if daily >= zona.max_reservas_dia_inmueble: raise HTTPException(409, f"El inmueble alcanzó el máximo de {zona.max_reservas_dia_inmueble} reservas para esa zona y fecha")
    blocked = db.query(models.BloqueoReserva).filter(models.BloqueoReserva.zona_id == zona.id, models.BloqueoReserva.fecha_inicio < fin, models.BloqueoReserva.fecha_fin > inicio).first()
    if blocked: raise HTTPException(409, f"La zona está bloqueada: {blocked.motivo}")
    conflict = db.query(models.Reserva).filter(models.Reserva.zona_id == zona.id, models.Reserva.estado.in_(["pendiente", "aprobada"]), models.Reserva.fecha_inicio < fin, models.Reserva.fecha_fin > inicio).first()
    if conflict: raise HTTPException(409, detail=f"Ya existe una reserva entre {conflict.fecha_inicio} y {conflict.fecha_fin}")
    estado = "pendiente" if zona.requiere_aprobacion else "aprobada"
    row = models.Reserva(zona_id=zona.id, inmueble_id=inmueble.id, solicitante_id=usuario_actual.id, fecha_inicio=inicio, fecha_fin=fin, estado=estado)
    db.add(row); db.commit(); db.refresh(row)
    if not zona.requiere_aprobacion:
        from app.routers.gestion import add_notification
        add_notification(db, usuario_actual.id, "Reserva aprobada", f"Tu reserva para {zona.nombre} fue aprobada automáticamente")
        db.commit()
    return row


@router.get("/disponibilidad", response_model=list[schemas.ReservaResponse])
def disponibilidad(zona_id: int, desde: datetime, hasta: datetime, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    if hasta <= desde: raise HTTPException(400, "Rango de fechas inválido")
    return db.query(models.Reserva).filter(models.Reserva.zona_id == zona_id, models.Reserva.estado.in_(["pendiente", "aprobada"]), models.Reserva.fecha_inicio < local_naive(hasta), models.Reserva.fecha_fin > local_naive(desde)).order_by(models.Reserva.fecha_inicio).all()


@router.get("/", response_model=list[schemas.ReservaResponse])
def listar_reservas(db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    if is_admin(usuario_actual) or usuario_actual.rol == "portero":
        ids = allowed_set_ids(db, usuario_actual)
        return db.query(models.Reserva).join(models.ZonaComun).filter(models.ZonaComun.conjunto_id.in_(ids)).order_by(models.Reserva.fecha_inicio.desc()).all()
    return db.query(models.Reserva).filter_by(solicitante_id=usuario_actual.id).order_by(models.Reserva.fecha_inicio.desc()).all()


@router.get("/{reserva_id}", response_model=schemas.ReservaResponse)
def obtener_reserva(reserva_id: int, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    row = db.query(models.Reserva).filter_by(id=reserva_id).first()
    if not row: raise HTTPException(404, "Reserva no encontrada")
    zone = db.query(models.ZonaComun).filter_by(id=row.zona_id).first(); require_access_set(db, usuario_actual, zone.conjunto_id)
    if not is_admin(usuario_actual) and usuario_actual.rol != "portero" and row.solicitante_id != usuario_actual.id: raise HTTPException(403, "No tienes permiso para ver esta reserva")
    return row


@router.post("/{reserva_id}/cancelar", response_model=schemas.ReservaResponse)
def cancelar_reserva(reserva_id: int, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    row = db.query(models.Reserva).filter_by(id=reserva_id).first()
    if not row: raise HTTPException(404, "Reserva no encontrada")
    zone = db.query(models.ZonaComun).filter_by(id=row.zona_id).first()
    if is_admin(usuario_actual): require_admin_set(db, usuario_actual, zone.conjunto_id)
    elif row.solicitante_id != usuario_actual.id: raise HTTPException(403, "No puedes cancelar esta reserva")
    if row.estado not in ("pendiente", "aprobada"): raise HTTPException(409, "Solo puedes cancelar reservas pendientes o aprobadas")
    row.estado = "cancelada"; db.commit(); db.refresh(row); return row


@router.patch("/{reserva_id}/estado", response_model=schemas.ReservaResponse)
def cambiar_estado_reserva(reserva_id: int, datos: schemas.ReservaEstadoUpdate, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    if not is_admin(usuario_actual): raise HTTPException(403, "Solo administración puede aprobar o rechazar reservas")
    row = db.query(models.Reserva).filter_by(id=reserva_id).first()
    if not row: raise HTTPException(404, "Reserva no encontrada")
    zone = db.query(models.ZonaComun).filter_by(id=row.zona_id).first(); require_admin_set(db, usuario_actual, zone.conjunto_id)
    if datos.estado not in ("aprobada", "rechazada", "cancelada"): raise HTTPException(400, "Estado inválido")
    row.estado = datos.estado
    db.commit(); db.refresh(row)
    from app.routers.gestion import add_notification
    add_notification(db, row.solicitante_id, f"Reserva {datos.estado}", f"La administración cambió el estado de tu reserva #{row.id} a {datos.estado}.")
    db.commit()
    return row
