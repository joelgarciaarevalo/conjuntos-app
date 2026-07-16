from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app import schemas, models
from app.dependencies import get_usuario_actual

router = APIRouter(prefix="/pqrs", tags=["PQRS"])


@router.post("/", response_model=schemas.PQRSResponse, status_code=201)
def create_pqrs(datos: schemas.PQRSCreate, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    inmueble = db.query(models.Inmueble).filter(models.Inmueble.id == datos.inmueble_id).first()
    if not inmueble:
        raise HTTPException(status_code=404, detail="Inmueble no encontrado")
    
    es_propietario = inmueble.propietario_id == usuario_actual.id
    es_inquilino = inmueble.inquilino_id == usuario_actual.id

    if not (es_propietario or es_inquilino):
        raise HTTPException(status_code=403, detail="No tiene permiso para crear PQRS para este inmueble")
    
    tipos_validos = ["queja", "peticion", "reclamo", "sugerencia"]
    if datos.tipo not in tipos_validos:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Usa uno de: {tipos_validos}")
    
    nuevo_pqrs = models.PQRS(
        inmueble_id=datos.inmueble_id,
        solicitante_id=usuario_actual.id,
        tipo=datos.tipo,
        descripcion=datos.descripcion,
        estado="radicado",
        fecha_radicacion=datetime.utcnow()
    )
    db.add(nuevo_pqrs)
    db.commit()
    db.refresh(nuevo_pqrs)
    return nuevo_pqrs

@router.get("/", response_model=list[schemas.PQRSResponse])
def listar_pqrs(
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    if usuario_actual.es_super_admin:
        return db.query(models.PQRS).all()
    return db.query(models.PQRS).filter(
        models.PQRS.solicitante_id == usuario_actual.id
    ).all()

@router.get("/{pqrs_id}", response_model=schemas.PQRSResponse)
def obtener_pqrs(
    pqrs_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    pqrs = db.query(models.PQRS).filter(models.PQRS.id == pqrs_id).first()
    if not pqrs:
        raise HTTPException(status_code=404, detail="PQRS no encontrada")

    # Solo el dueño de la PQRS o el super admin pueden verla
    if not usuario_actual.es_super_admin and pqrs.solicitante_id != usuario_actual.id:
        raise HTTPException(status_code=403, detail="No tienes permiso para ver esta PQRS")

    return pqrs

@router.patch("/{pqrs_id}/responder", response_model=schemas.PQRSResponse)
def responder_pqrs(
    pqrs_id: int,
    datos: schemas.PQRSRespuestaUpdate,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    if not usuario_actual.es_super_admin:
        raise HTTPException(status_code=403, detail="No tienes permiso para responder PQRS")
    
    pqrs = db.query(models.PQRS).filter(models.PQRS.id == pqrs_id).first()
    if not pqrs:
        raise HTTPException(status_code=404, detail="PQRS no encontrada")
    
    pqrs.respuesta_admin = datos.respuesta_admin
    pqrs.estado = datos.estado
    db.commit()
    db.refresh(pqrs)
    return pqrs