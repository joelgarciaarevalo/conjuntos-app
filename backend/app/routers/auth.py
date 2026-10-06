import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import jwt
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas, models_v3
from app.dependencies import verificar_password, hashear_password, crear_token, get_usuario_actual, ALGORITHM, SECRET_KEY
from app.security_tokens import issue_token, consume_token
from app.services.notifications import deliver_external
from app.security_v3 import (
    bloqueo_activo, emitir_token, es_administracion, intentos_fallidos, localnow, registrar_intento,
)

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/registro", response_model=schemas.UsuarioResponse, status_code=201)
def registrar_usuario(datos: schemas.UsuarioCreate, db: Session = Depends(get_db)):
    if len(datos.password) < 12: raise HTTPException(422, "La contraseña debe tener 12 caracteres o más")
    if db.query(models.Usuario).filter(models.Usuario.email == datos.email).first(): raise HTTPException(400, "El email ya está registrado")
    if db.query(models.Usuario).filter(models.Usuario.cedula == datos.cedula).first(): raise HTTPException(400, "La cédula ya está registrada")
    production = os.getenv("APP_ENV", "development").lower() == "production"
    row = models.Usuario(nombre_completo=datos.nombre_completo, cedula=datos.cedula, email=datos.email, password_hash=hashear_password(datos.password), telefono=datos.telefono, email_verificado=not production)
    db.add(row); db.commit(); db.refresh(row)
    if production:
        token = issue_token(db, row, "verify", 24 * 60); db.commit()
        link = f"{os.getenv('API_PUBLIC_URL', 'http://localhost:8000')}/auth/verify-email?token={quote(token)}"
        deliver_external(db, row.id, "Verifica tu correo IRIS", f"Abre este enlace para activar tu cuenta: {link}", allow_unverified=True)
    return row


@router.post("/login")
def login(datos: schemas.LoginData, request: Request, db: Session = Depends(get_db)):
    usuario = db.query(models.Usuario).filter(models.Usuario.email == datos.email).first()
    desbloqueo = bloqueo_activo(db, datos.email)
    if desbloqueo:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos fallidos. Vuelve a intentarlo después de {desbloqueo.strftime('%Y-%m-%d %H:%M')}.",
        )
    if not usuario or not verificar_password(datos.password, usuario.password_hash):
        registrar_intento(db, datos.email, False, request, usuario.id if usuario else None, "credenciales")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email o contraseña incorrectos")
    if not usuario.email_verificado:
        raise HTTPException(403, "Verifica tu correo electrónico antes de iniciar sesión")

    doble_factor = db.query(models_v3.DosFactores).filter_by(usuario_id=usuario.id, activo=True).first()
    if doble_factor:
        desafio = jwt.encode(
            {"sub": usuario.email, "scope": "2fa", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            SECRET_KEY, algorithm=ALGORITHM,
        )
        return {
            "requiere_2fa": True,
            "desafio": desafio,
            "mensaje": "Ingresa el código de tu aplicación de autenticación (o un código de recuperación).",
            "metodo": "POST /v3/seguridad/2fa/login con {desafio, codigo}",
        }

    registrar_intento(db, datos.email, True, request, usuario.id, "login")
    token = emitir_token(db, usuario, request, origen="login")
    return {"access_token": token, "token_type": "bearer", "nombre_completo": usuario.nombre_completo, "es_super_admin": usuario.es_super_admin,
            "rol": "admin" if usuario.es_super_admin else (usuario.rol or "residente"), "id": usuario.id,
            "cambio_password_requerido": bool(usuario.cambio_password_requerido),
            "requiere_2fa": False,
            "seguridad": {
                "limite_intentos": intentos_fallidos(db, datos.email),
                "segundo_factor": bool(doble_factor),
                "obligatorio_para_administracion": es_administracion(usuario),
            }}


@router.post("/forgot-password")
def forgot_password(data: dict, db: Session = Depends(get_db)):
    email = str(data.get("email", "")).strip().lower()
    user = db.query(models.Usuario).filter(models.Usuario.email == email).first()
    response = {"ok": True, "mensaje": "Si la cuenta existe, recibirás instrucciones en tu correo."}
    if user:
        token = issue_token(db, user, "reset", 30); db.commit()
        link = f"{os.getenv('FRONTEND_BASE_URL', 'http://localhost:4200')}/reset-password?token={quote(token)}"
        deliver_external(db, user.id, "Restablece tu contraseña de IRIS", f"El enlace vence en 30 minutos. Para continuar abre: {link}", allow_unverified=True)
        if os.getenv("APP_ENV", "development").lower() != "production": response["debug_token"] = token
    return response


@router.post("/reset-password")
def reset_password(data: dict, db: Session = Depends(get_db)):
    password = str(data.get("password", ""))
    if len(password) < 12: raise HTTPException(422, "La nueva contraseña debe tener al menos 12 caracteres")
    user = consume_token(db, str(data.get("token", "")), "reset")
    if not user: raise HTTPException(400, "Enlace inválido, vencido o ya usado")
    user.password_hash = hashear_password(password); user.cambio_password_requerido = False
    db.commit(); return {"ok": True, "mensaje": "Contraseña actualizada"}


@router.get("/verify-email", response_class=HTMLResponse)
def verify_email(token: str, db: Session = Depends(get_db)):
    user = consume_token(db, token, "verify")
    if not user:
        return HTMLResponse("<h1>Enlace inválido o vencido</h1><p>Solicita una nueva verificación a administración.</p>", status_code=400)
    user.email_verificado = True; db.commit()
    frontend = os.getenv("FRONTEND_BASE_URL", "http://localhost:4200")
    return HTMLResponse(f"<!doctype html><html lang='es'><meta charset='utf-8'><title>Correo verificado</title><h1>Correo verificado</h1><p>Tu cuenta IRIS ya está activa.</p><a href='{frontend}/login'>Ir a iniciar sesión</a></html>")


@router.post("/change-password")
def change_password(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_actual)):
    current = str(data.get("current_password", "")); new = str(data.get("new_password", ""))
    if len(new) < 12: raise HTTPException(422, "La nueva contraseña debe tener al menos 12 caracteres")
    if not verificar_password(current, user.password_hash): raise HTTPException(403, "La contraseña actual no coincide")
    user.password_hash = hashear_password(new); user.cambio_password_requerido = False
    db.commit(); return {"ok": True, "mensaje": "Contraseña actualizada"}
