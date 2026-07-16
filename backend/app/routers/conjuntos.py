from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.dependencies import get_usuario_actual 


router = APIRouter(prefix="/conjuntos", tags=["conjuntos"])

@router.post("/", response_model=schemas.ConjuntoResponse, status_code=201)
def crear_conjunto(
    datos: schemas.ConjuntoCreate,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    # Solo los super administradores pueden crear conjuntos
    if not usuario_actual.es_super_admin:
        raise HTTPException(status_code=403, detail="No tienes permiso para crear conjuntos")
    
    if db.query(models.Conjunto).filter(models.Conjunto.nit == datos.nit).first():
        raise HTTPException(status_code=400, detail="Ya existe un conjunto con ese NIT")
    
    nuevo = models.Conjunto(**datos.model_dump())
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo

@router.get("/", response_model=list[schemas.ConjuntoResponse])
def listar_conjuntos(
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    return db.query(models.Conjunto).all()


@router.get("/{conjunto_id}", response_model=schemas.ConjuntoResponse)
def obtener_conjunto(
    conjunto_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    conjunto = db.query(models.Conjunto).filter(models.Conjunto.id == conjunto_id).first()
    if not conjunto:
        raise HTTPException(status_code=404, detail="Conjunto no encontrado")
    return conjunto