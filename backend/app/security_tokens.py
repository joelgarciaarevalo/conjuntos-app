import hashlib
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from app import models

def localnow():
    return datetime.now(ZoneInfo("America/Bogota")).replace(tzinfo=None)


def issue_token(db: Session, user: models.Usuario, purpose: str, minutes: int = 30) -> str:
    raw = secrets.token_urlsafe(36)
    db.add(models.PasswordToken(usuario_id=user.id, token_hash=hashlib.sha256(raw.encode()).hexdigest(), proposito=purpose, expira_en=localnow() + timedelta(minutes=minutes)))
    return raw


def consume_token(db: Session, raw: str, purpose: str):
    if not raw or len(raw) > 200:
        return None
    digest = hashlib.sha256(raw.encode()).hexdigest()
    row = db.query(models.PasswordToken).filter_by(token_hash=digest, proposito=purpose, consumido_en=None).first()
    if not row or row.expira_en < localnow():
        return None
    row.consumido_en = localnow()
    return db.query(models.Usuario).filter_by(id=row.usuario_id).first()
