from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.dependencies import get_usuario_actual

router = APIRouter(prefix="/conjuntos/{conjunto_id}/inmuebles", tags=["inmuebles"])

@router.post("/", response_model=schemas.InmuebleResponse, status_code=201)
def crear_inmueble(
    conjunto_id: int,
    datos: schemas.InmuebleCreate,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    # Verificar que el conjunto exista
    conjunto = db.query(models.Conjunto).filter(models.Conjunto.id == conjunto_id).first
    if not conjunto:
        raise HTTPException(status_code=404, detail="Conjunto no encontrado")
    
    # Verificar que el propetario exista
    propietario = db.query(models.Usuario).filter(models.Usuario.id == datos.propietario_id).first()
    if not propietario:
        raise HTTPException(status_code=404, detail="Propietario no encontrado")
    
    nuevo = models.Inmueble(conjunto_id=conjunto_id, **datos.model_dump())
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo

@router.get("/", response_model=list[schemas.InmuebleResponse])
def listar_inmuebles(
    conjunto_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    conjunto = db.query(models.Conjunto).filter(models.Conjunto.id == conjunto_id).first()
    if not conjunto:
        raise HTTPException(status_code=404, detail="Conjunto no encontrado")
    
    return db.query(models.Inmueble).filter(models.Inmueble.conjunto_id == conjunto_id).all()

@router.get("/{inmueble_id}", response_model=schemas.InmuebleResponse)
def obtener_inmueble(
    conjunto_id: int,
    inmueble_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    conjunto = db.query(models.Conjunto).filter(models.Conjunto.id == conjunto_id).first()
    if not conjunto:
        raise HTTPException(status_code=404, detail="Conjunto no encontrado")
    
    inmueble = db.query(models.Inmueble).filter(
        models.Inmueble.id == inmueble_id,
        models.Inmueble.conjunto_id == conjunto_id
    ).first()
    
    if not inmueble:
        raise HTTPException(status_code=404, detail="Inmueble no encontrado")
    
    return inmueble