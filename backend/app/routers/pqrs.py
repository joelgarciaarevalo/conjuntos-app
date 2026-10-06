from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from zoneinfo import ZoneInfo
from app.database import get_db
from app import schemas, models
from app.dependencies import get_usuario_actual
from app.routers.gestion import add_notification
from app.permissions import allowed_set_ids, require_admin_set

router = APIRouter(prefix="/pqrs", tags=["PQRS"])


def is_admin(user): return bool(user.es_super_admin or user.rol == "admin")


@router.post("/", response_model=schemas.PQRSResponse, status_code=201)
def create_pqrs(datos: schemas.PQRSCreate, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    inmueble = db.query(models.Inmueble).filter_by(id=datos.inmueble_id).first()
    if not inmueble: raise HTTPException(404, "Inmueble no encontrado")
    if usuario_actual.id not in (inmueble.propietario_id, inmueble.inquilino_id): raise HTTPException(403, "No tiene permiso para crear PQRS para este inmueble")
    if datos.tipo not in {"queja", "peticion", "reclamo", "sugerencia"}: raise HTTPException(400, "Tipo de PQRS inválido")
    row = models.PQRS(inmueble_id=datos.inmueble_id, solicitante_id=usuario_actual.id, tipo=datos.tipo,
                      descripcion=datos.descripcion, estado="radicado", fecha_radicacion=datetime.now(ZoneInfo("America/Bogota")).replace(tzinfo=None))
    db.add(row); db.commit(); db.refresh(row)
    admins = db.query(models.Usuario).filter(models.Usuario.es_super_admin.is_(True)).all() + db.query(models.Usuario).join(models.ConjuntoMembership, models.ConjuntoMembership.usuario_id == models.Usuario.id).filter(models.ConjuntoMembership.conjunto_id == inmueble.conjunto_id, models.ConjuntoMembership.rol == "admin").all()
    for admin_user in {x.id: x for x in admins}.values(): add_notification(db, admin_user.id, "Nueva PQRS", f"Solicitud #{row.id} recibida")
    db.commit(); return row


@router.get("/", response_model=list[schemas.PQRSResponse])
def listar_pqrs(db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    if is_admin(usuario_actual):
        ids = allowed_set_ids(db, usuario_actual)
        return db.query(models.PQRS).join(models.Inmueble).filter(models.Inmueble.conjunto_id.in_(ids)).order_by(models.PQRS.fecha_radicacion.desc()).all()
    return db.query(models.PQRS).filter_by(solicitante_id=usuario_actual.id).order_by(models.PQRS.fecha_radicacion.desc()).all()


@router.get("/{pqrs_id}", response_model=schemas.PQRSResponse)
def obtener_pqrs(pqrs_id: int, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    row = db.query(models.PQRS).filter_by(id=pqrs_id).first()
    if not row: raise HTTPException(404, "PQRS no encontrada")
    unit = db.query(models.Inmueble).filter_by(id=row.inmueble_id).first()
    if is_admin(usuario_actual): require_admin_set(db, usuario_actual, unit.conjunto_id)
    elif row.solicitante_id != usuario_actual.id: raise HTTPException(403, "No tienes permiso para ver esta PQRS")
    return row


@router.patch("/{pqrs_id}/responder", response_model=schemas.PQRSResponse)
def responder_pqrs(pqrs_id: int, datos: schemas.PQRSRespuestaUpdate, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    if not is_admin(usuario_actual): raise HTTPException(403, "No tienes permiso para responder PQRS")
    if datos.estado not in ("radicado", "en_proceso", "resuelto"): raise HTTPException(422, "Estado de PQRS inválido")
    row = db.query(models.PQRS).filter_by(id=pqrs_id).first()
    if not row: raise HTTPException(404, "PQRS no encontrada")
    unit = db.query(models.Inmueble).filter_by(id=row.inmueble_id).first(); require_admin_set(db, usuario_actual, unit.conjunto_id)
    row.respuesta_admin = datos.respuesta_admin.strip()
    row.estado = datos.estado
    db.commit(); db.refresh(row)
    add_notification(db, row.solicitante_id, "Respuesta a tu PQRS", f"La administración respondió tu solicitud #{row.id} y su estado es {datos.estado}.")
    db.commit()
    return row
