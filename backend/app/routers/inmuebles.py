from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.dependencies import get_usuario_actual
from app.permissions import require_admin_set, require_access_set, require_finance_set
router = APIRouter(prefix="/conjuntos/{conjunto_id}/inmuebles", tags=["Inmuebles"])

def admin(u): return bool(u.es_super_admin or u.rol == "admin")

@router.post("/", response_model=schemas.InmuebleResponse, status_code=201)
def crear_inmueble(conjunto_id: int, datos: schemas.InmuebleCreate, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    require_admin_set(db, usuario_actual, conjunto_id)
    if not db.query(models.Conjunto).filter_by(id=conjunto_id).first(): raise HTTPException(404, "Conjunto no encontrado")
    if not db.query(models.Usuario).filter_by(id=datos.propietario_id).first(): raise HTTPException(404, "Propietario no encontrado")
    estado = str(datos.estado or "ocupado").lower()
    if estado not in {e.value for e in models.EstadoInmueble}: raise HTTPException(422, "Estado de inmueble inválido")
    payload = datos.model_dump(); payload["estado"] = estado
    nuevo = models.Inmueble(conjunto_id=conjunto_id, **payload)
    db.add(nuevo); db.commit(); db.refresh(nuevo); return nuevo

@router.get("/", response_model=list[schemas.InmuebleResponse])
def listar_inmuebles(conjunto_id: int, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    if not db.query(models.Conjunto).filter_by(id=conjunto_id).first(): raise HTTPException(404, "Conjunto no encontrado")
    if usuario_actual.rol == "contador": require_finance_set(db, usuario_actual, conjunto_id)
    else: require_access_set(db, usuario_actual, conjunto_id)
    consulta = db.query(models.Inmueble).filter_by(conjunto_id=conjunto_id)
    if not admin(usuario_actual) and usuario_actual.rol != "contador":
        consulta = consulta.filter((models.Inmueble.propietario_id == usuario_actual.id) | (models.Inmueble.inquilino_id == usuario_actual.id))
    return consulta.all()

@router.get("/{inmueble_id}", response_model=schemas.InmuebleResponse)
def obtener_inmueble(conjunto_id: int, inmueble_id: int, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    if usuario_actual.rol == "contador": require_finance_set(db, usuario_actual, conjunto_id)
    else: require_access_set(db, usuario_actual, conjunto_id)
    row = db.query(models.Inmueble).filter_by(id=inmueble_id, conjunto_id=conjunto_id).first()
    if not row: raise HTTPException(404, "Inmueble no encontrado")
    if not admin(usuario_actual) and usuario_actual.rol != "contador" and usuario_actual.id not in (row.propietario_id, row.inquilino_id): raise HTTPException(403, "Sin acceso al inmueble")
    return row
