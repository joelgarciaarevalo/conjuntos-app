from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.dependencies import get_usuario_actual
from app.permissions import require_access_set, require_admin_set
router = APIRouter(prefix="/conjuntos/{conjunto_id}/zonas-comunes", tags=["Zonas Comunes"])

def admin(u): return bool(u.es_super_admin or u.rol == "admin")

@router.post("/", response_model=schemas.ZonaComunResponse, status_code=201)
def crear_zona(conjunto_id: int, datos: schemas.ZonaComunCreate, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    require_admin_set(db, usuario_actual, conjunto_id)
    if not db.query(models.Conjunto).filter_by(id=conjunto_id).first(): raise HTTPException(404, "Conjunto no encontrado")
    try:
        apertura = datetime.strptime(datos.hora_apertura, "%H:%M").time(); cierre = datetime.strptime(datos.hora_cierre, "%H:%M").time()
    except ValueError: raise HTTPException(422, "Horario debe tener formato HH:MM")
    if apertura >= cierre: raise HTTPException(422, "La hora de cierre debe ser posterior a apertura")
    if not 1 <= datos.max_dias_anticipacion <= 365 or not 1 <= datos.max_reservas_dia_inmueble <= 20: raise HTTPException(422, "Límites de reserva inválidos")
    row = models.ZonaComun(**datos.model_dump(), conjunto_id=conjunto_id)
    db.add(row); db.commit(); db.refresh(row); return row

@router.get("/", response_model=list[schemas.ZonaComunResponse])
def listar_zonas(conjunto_id: int, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    if not db.query(models.Conjunto).filter_by(id=conjunto_id).first(): raise HTTPException(404, "Conjunto no encontrado")
    require_access_set(db, usuario_actual, conjunto_id)
    return db.query(models.ZonaComun).filter_by(conjunto_id=conjunto_id).all()

@router.get("/{zona_id}", response_model=schemas.ZonaComunResponse)
def obtener_zona(conjunto_id: int, zona_id: int, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    require_access_set(db, usuario_actual, conjunto_id)
    row = db.query(models.ZonaComun).filter_by(id=zona_id, conjunto_id=conjunto_id).first()
    if not row: raise HTTPException(404, "Zona no encontrada")
    return row
