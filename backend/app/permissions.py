from fastapi import HTTPException
from sqlalchemy.orm import Session
from app import models


def is_admin(user: models.Usuario) -> bool:
    return bool(user.es_super_admin or user.rol == "admin")


def allowed_set_ids(db: Session, user: models.Usuario) -> set[int]:
    if user.es_super_admin:
        return {row.id for row in db.query(models.Conjunto.id).all()}
    if user.rol in ("admin", "portero", "contador"):
        return {row.conjunto_id for row in db.query(models.ConjuntoMembership.conjunto_id).filter_by(usuario_id=user.id, rol=user.rol).all()}
    return {row.conjunto_id for row in db.query(models.Inmueble.conjunto_id).filter((models.Inmueble.propietario_id == user.id) | (models.Inmueble.inquilino_id == user.id)).all()}


def can_access_set(db: Session, user: models.Usuario, conjunto_id: int) -> bool:
    if user.es_super_admin:
        return True
    if user.rol in ("admin", "portero"):
        return db.query(models.ConjuntoMembership.id).filter_by(usuario_id=user.id, conjunto_id=conjunto_id, rol=user.rol).first() is not None
    return db.query(models.Inmueble.id).filter_by(conjunto_id=conjunto_id).filter((models.Inmueble.propietario_id == user.id) | (models.Inmueble.inquilino_id == user.id)).first() is not None


def require_access_set(db: Session, user: models.Usuario, conjunto_id: int) -> None:
    if not can_access_set(db, user, conjunto_id):
        raise HTTPException(403, "No tienes acceso a este conjunto")


def require_admin_set(db: Session, user: models.Usuario, conjunto_id: int) -> None:
    if user.es_super_admin:
        return
    if user.rol != "admin" or not db.query(models.ConjuntoMembership.id).filter_by(usuario_id=user.id, conjunto_id=conjunto_id, rol="admin").first():
        raise HTTPException(403, "No eres administrador de este conjunto")


def require_finance_set(db: Session, user: models.Usuario, conjunto_id: int) -> None:
    if user.es_super_admin:
        return
    if user.rol not in ("admin", "contador") or not db.query(models.ConjuntoMembership.id).filter_by(
        usuario_id=user.id, conjunto_id=conjunto_id, rol=user.rol
    ).first():
        raise HTTPException(403, "No tienes acceso financiero a este conjunto")


def require_staff_set(db: Session, user: models.Usuario, conjunto_id: int) -> None:
    if user.es_super_admin:
        return
    if user.rol not in ("admin", "portero") or not db.query(models.ConjuntoMembership.id).filter_by(usuario_id=user.id, conjunto_id=conjunto_id, rol=user.rol).first():
        raise HTTPException(403, "No tienes acceso de portería o administración a este conjunto")
