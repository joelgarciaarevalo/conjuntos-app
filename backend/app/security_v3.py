"""Seguridad de IRIS 3.0: sesiones registradas, límite de intentos y 2FA.

No reemplaza `app/dependencies.py` (se mantiene intacto): añade una capa v3 que
- identifica cada token emitido en la tabla de sesiones y respeta revocaciones;
- limita los intentos de acceso fallidos;
- exige el segundo factor a la administración en operaciones sensibles.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.dependencies import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY
from app.services.crypto_v3 import hash_valor
from app.services import totp

bearer = HTTPBearer(auto_error=False)

MAX_INTENTOS = int(os.getenv("IRIS_MAX_INTENTOS", "5"))
VENTANA_INTENTOS_MINUTOS = int(os.getenv("IRIS_VENTANA_INTENTOS_MINUTOS", "15"))
BLOQUEO_MINUTOS = int(os.getenv("IRIS_BLOQUEO_MINUTOS", "15"))


def localnow() -> datetime:
    return datetime.now(ZoneInfo("America/Bogota")).replace(tzinfo=None)


def emitir_token(db: Session, usuario: models.Usuario, request: Request | None = None, origen: str = "web", extra: dict | None = None) -> str:
    """Crea un token JWT identificado con `jti` y registra la sesión."""
    jti = secrets.token_urlsafe(24)
    expira = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": usuario.email, "jti": jti, **(extra or {})}
    token = jwt.encode({**payload, "exp": expira}, SECRET_KEY, algorithm=ALGORITHM)
    db.add(models_v3.SesionUsuario(
        usuario_id=usuario.id, jti=jti,
        ip=(request.client.host if request and request.client else None),
        agente=(request.headers.get("user-agent", "")[:255] if request else None),
        origen=origen, expira_en=expira.replace(tzinfo=None),
    ))
    db.commit()
    return token


def _sesion_activa(db: Session, jti: str | None) -> models_v3.SesionUsuario | None:
    if not jti:
        return None
    return db.query(models_v3.SesionUsuario).filter_by(jti=jti).first()


def get_usuario_v3(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.Usuario:
    """Usuario autenticado con validación de sesión (revocable)."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No se pudo validar el token", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No se pudo validar el token", headers={"WWW-Authenticate": "Bearer"})
    usuario = db.query(models.Usuario).filter(models.Usuario.email == email).first() if email else None
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No se pudo validar el token", headers={"WWW-Authenticate": "Bearer"})
    sesion = _sesion_activa(db, payload.get("jti"))
    if sesion:
        if sesion.revocada_en is not None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesión fue cerrada. Inicia sesión de nuevo.")
        if sesion.expira_en and sesion.expira_en < localnow():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesión expiró. Inicia sesión de nuevo.")
        ahora = localnow()
        if not sesion.ultima_actividad or (ahora - sesion.ultima_actividad).total_seconds() > 60:
            sesion.ultima_actividad = ahora
            db.commit()
    return usuario


# ---------------------------------------------------------------------------
# Segundo factor para administración
# ---------------------------------------------------------------------------
def _doble_factor(db: Session, usuario_id: int) -> models_v3.DosFactores | None:
    return db.query(models_v3.DosFactores).filter_by(usuario_id=usuario_id).first()


def es_administracion(usuario: models.Usuario) -> bool:
    return bool(usuario.es_super_admin or usuario.rol == "admin")


def estado_2fa(db: Session, usuario: models.Usuario) -> dict:
    fila = _doble_factor(db, usuario.id)
    return {
        "habilitado": bool(fila and fila.activo),
        "confirmado_en": fila.confirmado_en.isoformat() if fila and fila.confirmado_en else None,
        "obligatorio_para_administracion": es_administracion(usuario),
        "codigos_recuperacion_restantes": _codigos_restantes(fila),
    }


def _codigos_restantes(fila: models_v3.DosFactores | None) -> int:
    if not fila or not fila.codigos_recuperacion:
        return 0
    import json
    try:
        return len(json.loads(fila.codigos_recuperacion))
    except Exception:
        return 0


def verificar_codigo_2fa(db: Session, usuario: models.Usuario, codigo: str) -> bool:
    fila = _doble_factor(db, usuario.id)
    if not fila or not fila.activo:
        return False
    if totp.verificar(fila.secreto, codigo):
        fila.ultimo_uso = localnow()
        db.commit()
        return True
    return consumir_codigo_recuperacion(db, usuario, codigo)


def consumir_codigo_recuperacion(db: Session, usuario: models.Usuario, codigo: str) -> bool:
    import json
    fila = _doble_factor(db, usuario.id)
    if not fila or not fila.codigos_recuperacion:
        return False
    try:
        hashes = json.loads(fila.codigos_recuperacion)
    except Exception:
        return False
    objetivo = hash_valor(str(codigo).strip().lower())
    if objetivo in hashes:
        hashes = [h for h in hashes if h != objetivo]
        fila.codigos_recuperacion = json.dumps(hashes)
        fila.ultimo_uso = localnow()
        db.commit()
        return True
    return False


def exigir_2fa_admin(db: Session, usuario: models.Usuario, codigo: str | None) -> None:
    """Obliga a la administración con 2FA activo a enviar un código válido."""
    if not es_administracion(usuario):
        return
    fila = _doble_factor(db, usuario.id)
    if not fila or not fila.activo:
        return
    if verificar_codigo_2fa(db, usuario, codigo or ""):
        return
    raise HTTPException(status_code=403, detail={"codigo": "2fa_requerido", "mensaje": "Esta operación de administración requiere el código de segundo factor (encabezado X-IRIS-OTP)."})


def dependencia_2fa(opcional: bool = True):
    """Dependencia de FastAPI que entrega el encabezado X-IRIS-OTP."""
    def _leer(x_iris_otp: str | None = Header(default=None, alias="X-IRIS-OTP")) -> str | None:
        return x_iris_otp
    return Depends(_leer)


# ---------------------------------------------------------------------------
# Límite de intentos de acceso
# ---------------------------------------------------------------------------
def intentos_fallidos(db: Session, email: str) -> int:
    desde = localnow() - timedelta(minutes=VENTANA_INTENTOS_MINUTOS)
    return db.query(models_v3.IntentoAcceso).filter(
        models_v3.IntentoAcceso.email == email,
        models_v3.IntentoAcceso.exito.is_(False),
        models_v3.IntentoAcceso.creado_en >= desde,
    ).count()


def bloqueo_activo(db: Session, email: str) -> datetime | None:
    if MAX_INTENTOS <= 0:
        return None
    desde = localnow() - timedelta(minutes=VENTANA_INTENTOS_MINUTOS)
    filas = db.query(models_v3.IntentoAcceso).filter(
        models_v3.IntentoAcceso.email == email,
        models_v3.IntentoAcceso.exito.is_(False),
        models_v3.IntentoAcceso.creado_en >= desde,
    ).order_by(models_v3.IntentoAcceso.id.desc()).all()
    if len(filas) < MAX_INTENTOS:
        return None
    ultimo = filas[0].creado_en
    desbloqueo = ultimo + timedelta(minutes=BLOQUEO_MINUTOS)
    return desbloqueo if desbloqueo > localnow() else None


def registrar_intento(db: Session, email: str, exito: bool, request: Request | None = None, usuario_id: int | None = None, motivo: str | None = None) -> None:
    db.add(models_v3.IntentoAcceso(
        email=email[:120], usuario_id=usuario_id, exito=exito, motivo=(motivo or "")[:80],
        ip=(request.client.host if request and request.client else None),
    ))
    db.commit()
    if exito:
        # Un acceso correcto limpia el contador de intentos fallidos
        db.query(models_v3.IntentoAcceso).filter(
            models_v3.IntentoAcceso.email == email,
            models_v3.IntentoAcceso.exito.is_(False),
        ).delete()
        db.commit()