from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.database import get_db
from app import models, schemas
from app.dependencies import get_usuario_actual

router = APIRouter(prefix="/reservas", tags=["Reservas"])

@router.post("/", response_model=schemas.ReservaResponse, status_code=201)
def crear_reserva(
    datos: schemas.ReservaCreate,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    # 1. Verificar que el inmueble existe
    inmueble = db.query(models.Inmueble).filter(models.Inmueble.id == datos.inmueble_id).first()
    if not inmueble:
        raise HTTPException(status_code=404, detail="Inmueble no encontrado")

    # 2. Verificar que la zona existe y pertenece al mismo conjunto que el inmueble
    zona = db.query(models.ZonaComun).filter(models.ZonaComun.id == datos.zona_id).first()
    if not zona:
        raise HTTPException(status_code=404, detail="Zona común no encontrada")
    if zona.conjunto_id != inmueble.conjunto_id:
        raise HTTPException(status_code=400, detail="La zona no pertenece al conjunto de este inmueble")

    # 3. LÓGICA CLAVE: el usuario debe ser propietario o inquilino del inmueble
    es_propietario = inmueble.propietario_id == usuario_actual.id
    es_inquilino = inmueble.inquilino_id == usuario_actual.id

    if not (es_propietario or es_inquilino):
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para reservar a nombre de este inmueble"
        )

    # 4. Validar que la fecha de fin sea posterior a la de inicio
    if datos.fecha_fin <= datos.fecha_inicio:
        raise HTTPException(status_code=400, detail="La fecha de fin debe ser posterior a la de inicio")

    # 5. LÓGICA CLAVE: verificar solapamiento de horarios en la misma zona
    # Dos rangos [A_inicio, A_fin] y [B_inicio, B_fin] se solapan si:
    # A_inicio < B_fin Y A_fin > B_inicio
    solapamiento = db.query(models.Reserva).filter(
        models.Reserva.zona_id == datos.zona_id,
        models.Reserva.estado.in_(["pendiente", "aprobada"]),
        models.Reserva.fecha_inicio < datos.fecha_fin,
        models.Reserva.fecha_fin > datos.fecha_inicio
    ).first()

    if solapamiento:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe una reserva para esa zona entre {solapamiento.fecha_inicio} y {solapamiento.fecha_fin}"
        )

    # 6. Si todo está bien, crear la reserva
    nueva_reserva = models.Reserva(
        zona_id=datos.zona_id,
        inmueble_id=datos.inmueble_id,
        solicitante_id=usuario_actual.id,
        fecha_inicio=datos.fecha_inicio,
        fecha_fin=datos.fecha_fin,
        estado="pendiente"
    )
    db.add(nueva_reserva)
    db.commit()
    db.refresh(nueva_reserva)
    return nueva_reserva


@router.get("/", response_model=list[schemas.ReservaResponse])
def listar_reservas(
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    # El super admin ve todas las reservas
    if usuario_actual.es_super_admin:
        return db.query(models.Reserva).all()
    # El residente solo ve las suyas
    return db.query(models.Reserva).filter(
        models.Reserva.solicitante_id == usuario_actual.id
    ).all()


@router.get("/{reserva_id}", response_model=schemas.ReservaResponse)
def obtener_reserva(
    reserva_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    reserva = db.query(models.Reserva).filter(models.Reserva.id == reserva_id).first()
    if not reserva:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    return reserva


@router.patch("/{reserva_id}/estado", response_model=schemas.ReservaResponse)
def cambiar_estado_reserva(
    reserva_id: int,
    datos: schemas.ReservaEstadoUpdate,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    # Solo el super admin puede aprobar/rechazar (más adelante puedes extender a admin de conjunto)
    if not usuario_actual.es_super_admin:
        raise HTTPException(status_code=403, detail="No tienes permiso para esto")

    reserva = db.query(models.Reserva).filter(models.Reserva.id == reserva_id).first()
    if not reserva:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")

    if datos.estado not in ["aprobada", "rechazada", "cancelada"]:
        raise HTTPException(status_code=400, detail="Estado inválido")

    reserva.estado = datos.estado
    db.commit()
    db.refresh(reserva)
    return reserva