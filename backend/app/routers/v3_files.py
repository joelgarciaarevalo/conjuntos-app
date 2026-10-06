"""Entrega controlada de archivos cargados por los módulos de IRIS 3.0.

Ninguna URL de adjunto es pública: cada descarga valida la sesión y el permiso
sobre el recurso (orden de mantenimiento, egreso o cotización) antes de servir
el contenido.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.permissions import can_access_set, is_admin
from app.security_v3 import get_usuario_v3
from app.routers.v3_common import archivo_local
from app.routers.v3_mantenimiento import _orden_visible

router = APIRouter(prefix="/v3/files", tags=["v3 · Archivos"])


def _autorizado(db: Session, user: models.Usuario, url: str) -> bool:
    evidencia = db.query(models_v3.EvidenciaMantenimiento).filter_by(url=url).first()
    if evidencia:
        orden = db.query(models_v3.OrdenMantenimiento).filter_by(id=evidencia.orden_id).first()
        if orden:
            try:
                _orden_visible(db, user, orden)
                return True
            except HTTPException:
                return False

    cotizacion = db.query(models_v3.CotizacionMantenimiento).filter_by(archivo_url=url).first()
    if cotizacion:
        orden = db.query(models_v3.OrdenMantenimiento).filter_by(id=cotizacion.orden_id).first()
        if orden and (user.es_super_admin or (is_admin(user) and can_access_set(db, user, orden.conjunto_id))):
            return True

    egreso = db.query(models_v3.Egreso).filter_by(soporte_url=url).first()
    if egreso and is_admin(user) and can_access_set(db, user, egreso.conjunto_id):
        return True
    return False


@router.get("/{filename}")
def servir(filename: str, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    url = "/v3/files/" + filename
    if not _autorizado(db, user, url):
        raise HTTPException(404, "Archivo no encontrado")
    path = archivo_local(filename)
    return FileResponse(path, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})