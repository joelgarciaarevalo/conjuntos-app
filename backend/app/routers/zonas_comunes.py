from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.dependencies import get_usuario_actual

router = APIRouter(prefix="/conjuntos/{conjunto_id}/zonas-comunes", tags=["Zonas Comunes"])


@router.post("/", response_model=schemas.ZonaComunResponse, status_code=201)
def crear_zona(
    conjunto_id: int,
    datos: schemas.ZonaComunCreate,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    conjunto = db.query(models.Conjunto).filter(models.Conjunto.id == conjunto_id).first()
    if not conjunto:
        raise HTTPException(status_code=404, detail="Conjunto no encontrado")

    nueva = models.ZonaComun(**datos.model_dump(), conjunto_id=conjunto_id)
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return nueva


@router.get("/", response_model=list[schemas.ZonaComunResponse])
def listar_zonas(
    conjunto_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    conjunto = db.query(models.Conjunto).filter(models.Conjunto.id == conjunto_id).first()
    if not conjunto:
        raise HTTPException(status_code=404, detail="Conjunto no encontrado")

    return db.query(models.ZonaComun).filter(models.ZonaComun.conjunto_id == conjunto_id).all()


@router.get("/{zona_id}", response_model=schemas.ZonaComunResponse)
def obtener_zona(
    conjunto_id: int,
    zona_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual)
):
    zona = db.query(models.ZonaComun).filter(
        models.ZonaComun.id == zona_id,
        models.ZonaComun.conjunto_id == conjunto_id
    ).first()
    if not zona:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    return zona