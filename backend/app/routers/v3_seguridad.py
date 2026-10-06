"""Seguridad y protección de datos: segundo factor, límites de intentos,
registro de sesiones y políticas de retención y privacidad."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.dependencies import ALGORITHM, SECRET_KEY, verificar_password
from app.permissions import can_access_set, is_admin, require_admin_set
from app.security_v3 import (
    BLOQUEO_MINUTOS, MAX_INTENTOS, VENTANA_INTENTOS_MINUTOS, dependencia_2fa, emitir_token,
    es_administracion, estado_2fa, exigir_2fa_admin, get_usuario_v3, localnow,
)
from app.services import totp
from app.services.crypto_v3 import hash_valor
from app.routers.v3_common import admin_only, alcance, model_data, usuario_visible

router = APIRouter(prefix="/v3/seguridad", tags=["v3 · Seguridad y datos"])

TEXTO_PRIVACIDAD_DEFECTO = (
    "IRIS trata los datos personales de residentes, visitantes y proveedores con la finalidad de administrar "
    "la copropiedad: control de acceso, PQRS, cuotas, reservas, mantenimiento y comunicaciones. Los datos no se "
    "venden ni se comparten con terceros distintos de los proveedores necesarios (pasarela de pagos, mensajería y "
    "correo). Los números de tarjeta nunca se almacenan en IRIS. Puedes solicitar acceso, corrección, revocatoria "
    "del consentimiento de avisos y supresión de tus datos ante la administración del conjunto. Las bitácoras de "
    "auditoría, accesos y avisos se conservan según la política de retención configurada por la administración."
)


def _politica(db: Session, conjunto_id: int | None) -> models_v3.PoliticaDatos:
    fila = None
    if conjunto_id is not None:
        fila = db.query(models_v3.PoliticaDatos).filter_by(conjunto_id=conjunto_id).first()
    if not fila:
        fila = db.query(models_v3.PoliticaDatos).filter_by(conjunto_id=None).first()
    if not fila:
        fila = models_v3.PoliticaDatos(conjunto_id=None, texto_privacidad=TEXTO_PRIVACIDAD_DEFECTO)
        db.add(fila)
        db.commit()
        db.refresh(fila)
    return fila


# ---------------------------------------------------------------------------
# Estado y segundo factor
# ---------------------------------------------------------------------------
@router.get("/estado")
def estado(db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    sesiones = db.query(models_v3.SesionUsuario).filter(
        models_v3.SesionUsuario.usuario_id == user.id, models_v3.SesionUsuario.revocada_en.is_(None)
    ).count()
    ultimo = db.query(models_v3.IntentoAcceso).filter_by(email=user.email).order_by(models_v3.IntentoAcceso.id.desc()).first()
    return {
        **estado_2fa(db, user),
        "sesiones_activas": sesiones,
        "limite_intentos": MAX_INTENTOS,
        "ventana_intentos_minutos": VENTANA_INTENTOS_MINUTOS,
        "bloqueo_minutos": BLOQUEO_MINUTOS,
        "ultimo_intento": model_data(ultimo) if ultimo else None,
    }


@router.post("/2fa/iniciar", status_code=201)
def iniciar_2fa(db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if user.rol == "residente" and not user.es_super_admin:
        # El segundo factor está pensado para administración; los residentes
        # pueden activarlo también si lo desean.
        pass
    fila = db.query(models_v3.DosFactores).filter_by(usuario_id=user.id).first()
    secreto = totp.generar_secreto()
    if not fila:
        fila = models_v3.DosFactores(usuario_id=user.id, secreto=secreto, activo=False)
        db.add(fila)
    else:
        if fila.activo:
            raise HTTPException(409, "El segundo factor ya está activo. Desactívalo antes de generar un nuevo secreto.")
        fila.secreto = secreto
    db.commit()
    return {
        "secreto": secreto,
        "uri": totp.uri_otpauth(secreto, user.email),
        "emisor": totp.ISSUER,
        "digitos": totp.DIGITS,
        "periodo": totp.PERIOD,
        "instrucciones": "Escanea el URI en Google Authenticator, Authy o 1Password y confirma con un código de 6 dígitos.",
    }


@router.post("/2fa/confirmar")
def confirmar_2fa(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.DosFactores).filter_by(usuario_id=user.id).first()
    if not fila:
        raise HTTPException(409, "Primero inicia la configuración del segundo factor")
    if fila.activo:
        raise HTTPException(409, "El segundo factor ya está activo para tu cuenta")
    if not totp.verificar(fila.secreto, str(data.get("codigo") or "")):
        raise HTTPException(400, "Código inválido. Verifica la hora del dispositivo e inténtalo de nuevo.")
    fila.activo = True
    fila.confirmado_en = localnow()
    codigos = totp.generar_codigos_recuperacion()
    fila.codigos_recuperacion = json.dumps([hash_valor(c.lower()) for c in codigos])
    db.commit()
    return {
        "habilitado": True,
        "codigos_recuperacion": codigos,
        "aviso": "Guarda estos códigos en un lugar seguro: cada uno sirve una sola vez y no se volverán a mostrar.",
    }


@router.post("/2fa/verificar")
def verificar_2fa(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    from app.security_v3 import verificar_codigo_2fa
    if not verificar_codigo_2fa(db, user, str(data.get("codigo") or "")):
        raise HTTPException(400, "Código de segundo factor inválido")
    return {"valido": True}


@router.post("/2fa/login")
def login_2fa(data: dict, request: Request, db: Session = Depends(get_db)):
    """Segundo paso del inicio de sesión cuando el usuario tiene 2FA activo."""
    desafio = str(data.get("desafio") or "")
    try:
        payload = jwt.decode(desafio, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(401, "Desafío de segundo factor inválido o vencido")
    if payload.get("scope") != "2fa":
        raise HTTPException(401, "Desafío de segundo factor inválido")
    usuario = db.query(models.Usuario).filter_by(email=payload.get("sub")).first()
    if not usuario:
        raise HTTPException(401, "Usuario no encontrado")
    from app.security_v3 import registrar_intento, verificar_codigo_2fa
    if not verificar_codigo_2fa(db, usuario, str(data.get("codigo") or "")):
        registrar_intento(db, usuario.email, False, request, usuario.id, "2fa")
        raise HTTPException(401, "Código de segundo factor inválido")
    registrar_intento(db, usuario.email, True, request, usuario.id, "2fa")
    token = emitir_token(db, usuario, request, origen="login-2fa")
    return {
        "access_token": token, "token_type": "bearer", "nombre_completo": usuario.nombre_completo,
        "es_super_admin": usuario.es_super_admin, "rol": "admin" if usuario.es_super_admin else (usuario.rol or "residente"),
        "id": usuario.id, "cambio_password_requerido": bool(usuario.cambio_password_requerido),
    }


@router.delete("/2fa", status_code=204)
def desactivar_2fa(data: dict | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3),
                   otp: str | None = dependencia_2fa()):
    fila = db.query(models_v3.DosFactores).filter_by(usuario_id=user.id).first()
    if not fila or not fila.activo:
        raise HTTPException(409, "El segundo factor no está activo")
    exigir_2fa_admin(db, user, otp)
    if not otp:
        raise HTTPException(403, "Envía el código actual en el encabezado X-IRIS-OTP para desactivar el segundo factor")
    db.delete(fila)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Registro de sesiones
# ---------------------------------------------------------------------------
@router.get("/sesiones")
def sesiones(incluir_revocadas: bool = False, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.SesionUsuario).filter_by(usuario_id=user.id)
    if not incluir_revocadas:
        q = q.filter(models_v3.SesionUsuario.revocada_en.is_(None))
    filas = q.order_by(models_v3.SesionUsuario.id.desc()).limit(100).all()
    return [model_data(f) for f in filas]


@router.delete("/sesiones/{sesion_id}", status_code=204)
def revocar_sesion(sesion_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.SesionUsuario).filter_by(id=sesion_id).first()
    if not fila:
        raise HTTPException(404, "Sesión no encontrada")
    if fila.usuario_id != user.id:
        raise HTTPException(403, "No puedes cerrar sesiones de otros usuarios")
    fila.revocada_en = localnow()
    fila.motivo_revocacion = "Cierre manual desde el panel de seguridad"
    db.commit()
    return Response(status_code=204)


@router.delete("/sesiones", status_code=204)
def revocar_todas(request: Request, db: Session = Depends(get_db), user=Depends(get_usuario_v3),
                  otp: str | None = dependencia_2fa()):
    exigir_2fa_admin(db, user, otp)
    filas = db.query(models_v3.SesionUsuario).filter(
        models_v3.SesionUsuario.usuario_id == user.id, models_v3.SesionUsuario.revocada_en.is_(None)
    ).all()
    for fila in filas:
        fila.revocada_en = localnow()
        fila.motivo_revocacion = "Cierre masivo solicitado por el usuario"
    db.commit()
    return Response(status_code=204)


@router.get("/sesiones/conjunto")
def sesiones_del_conjunto(conjunto_id: int, limit: int = 100, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    """Registro de sesiones de las cuentas operativas del conjunto."""
    require_admin_set(db, user, conjunto_id)
    miembros = {r.usuario_id for r in db.query(models.ConjuntoMembership).filter_by(conjunto_id=conjunto_id).all()}
    unidades = db.query(models.Inmueble).filter_by(conjunto_id=conjunto_id).all()
    miembros |= {uid for u in unidades for uid in (u.propietario_id, u.inquilino_id) if uid}
    if not miembros:
        return []
    filas = db.query(models_v3.SesionUsuario).filter(
        models_v3.SesionUsuario.usuario_id.in_(miembros)
    ).order_by(models_v3.SesionUsuario.id.desc()).limit(max(1, min(limit, 500))).all()
    salida = []
    for fila in filas:
        datos = model_data(fila)
        datos["usuario"] = db.query(models.Usuario.nombre_completo).filter_by(id=fila.usuario_id).scalar()
        datos["email"] = db.query(models.Usuario.email).filter_by(id=fila.usuario_id).scalar()
        datos["activa"] = fila.revocada_en is None
        salida.append(datos)
    return salida


# ---------------------------------------------------------------------------
# Intentos de acceso
# ---------------------------------------------------------------------------
@router.get("/intentos")
def intentos(solo_fallidos: bool = True, limite: int = 100, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    admin_only(user)
    q = db.query(models_v3.IntentoAcceso)
    if solo_fallidos:
        q = q.filter(models_v3.IntentoAcceso.exito.is_(False))
    if not user.es_super_admin:
        ids = alcance(db, user)
        unidades = db.query(models.Inmueble).filter(models.Inmueble.conjunto_id.in_(ids)).all() if ids else []
        visibles = {uid for u in unidades for uid in (u.propietario_id, u.inquilino_id) if uid}
        visibles |= {r.usuario_id for r in db.query(models.ConjuntoMembership).filter(models.ConjuntoMembership.conjunto_id.in_(ids)).all()}
        filas = q.order_by(models_v3.IntentoAcceso.id.desc()).limit(max(1, min(limite, 500))).all()
        return [model_data(f) for f in filas if f.usuario_id in visibles or f.email in {db.query(models.Usuario.email).filter_by(id=uid).scalar() for uid in visibles}]
    return [model_data(f) for f in q.order_by(models_v3.IntentoAcceso.id.desc()).limit(max(1, min(limite, 500))).all()]


# ---------------------------------------------------------------------------
# Política de retención y privacidad
# ---------------------------------------------------------------------------
def _politica_publica(fila: models_v3.PoliticaDatos) -> dict:
    return model_data(fila)


@router.get("/politica")
def leer_politica(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if conjunto_id:
        if not can_access_set(db, user, conjunto_id):
            raise HTTPException(403, "No tienes acceso a este conjunto")
    elif not is_admin(user):
        unidades = db.query(models.Inmueble).filter((models.Inmueble.propietario_id == user.id) | (models.Inmueble.inquilino_id == user.id)).first()
        conjunto_id = unidades.conjunto_id if unidades else None
    return _politica_publica(_politica(db, conjunto_id))


@router.put("/politica")
def guardar_politica(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    conjunto_id = data.get("conjunto_id")
    conjunto_id = int(conjunto_id) if conjunto_id else None
    if conjunto_id is not None:
        require_admin_set(db, user, conjunto_id)
    else:
        if not user.es_super_admin:
            raise HTTPException(403, "Solo la superadministración define la política global")
    exigir_2fa_admin(db, user, otp)
    fila = db.query(models_v3.PoliticaDatos).filter_by(conjunto_id=conjunto_id).first()
    if not fila:
        fila = models_v3.PoliticaDatos(conjunto_id=conjunto_id, texto_privacidad=TEXTO_PRIVACIDAD_DEFECTO)
        db.add(fila)
    if data.get("texto_privacidad"):
        fila.texto_privacidad = str(data["texto_privacidad"])[:20000]
    if data.get("version"):
        fila.version = str(data["version"])[:20]
    for campo, minimo, maximo in (("dias_retencion_auditoria", 30, 3650), ("dias_retencion_accesos", 30, 3650),
                                  ("dias_retencion_avisos", 30, 3650), ("dias_retencion_intentos", 7, 3650),
                                  ("dias_retencion_sesiones", 7, 3650)):
        if data.get(campo) is not None:
            valor = int(data[campo])
            if not minimo <= valor <= maximo:
                raise HTTPException(422, f"{campo} debe estar entre {minimo} y {maximo} días")
            setattr(fila, campo, valor)
    if data.get("anonimizar_al_purgar") is not None:
        fila.anonimizar_al_purgar = bool(data["anonimizar_al_purgar"])
    fila.actualizado_en = localnow()
    db.commit()
    db.refresh(fila)
    return _politica_publica(fila)


@router.post("/politica/purgar")
def purgar(data: dict | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    """Aplica la política de retención: anonimiza o elimina datos vencidos."""
    data = data or {}
    conjunto_id = int(data["conjunto_id"]) if data.get("conjunto_id") else None
    if conjunto_id:
        require_admin_set(db, user, conjunto_id)
    else:
        admin_only(user)
    exigir_2fa_admin(db, user, otp)
    simulacion = bool(data.get("simulacion", True))
    politica = _politica(db, conjunto_id)
    ahora = localnow()
    corte_auditoria = ahora - timedelta(days=politica.dias_retencion_auditoria)
    corte_accesos = ahora - timedelta(days=politica.dias_retencion_accesos)
    corte_avisos = ahora - timedelta(days=politica.dias_retencion_avisos)
    corte_intentos = ahora - timedelta(days=politica.dias_retencion_intentos)
    corte_sesiones = ahora - timedelta(days=politica.dias_retencion_sesiones)

    q_auditoria = db.query(models.Auditoria).filter(models.Auditoria.creado_en < corte_auditoria)
    q_accesos = db.query(models_v3.RegistroAcceso).filter(models_v3.RegistroAcceso.ingreso_en < corte_accesos)
    q_avisos = db.query(models_v3.AvisoEnviado).filter(models_v3.AvisoEnviado.creado_en < corte_avisos)
    q_intentos = db.query(models_v3.IntentoAcceso).filter(models_v3.IntentoAcceso.creado_en < corte_intentos)
    q_sesiones = db.query(models_v3.SesionUsuario).filter(models_v3.SesionUsuario.creado_en < corte_sesiones)
    if conjunto_id:
        q_auditoria = q_auditoria.filter(models.Auditoria.conjunto_id == conjunto_id)
        q_accesos = q_accesos.filter(models_v3.RegistroAcceso.conjunto_id == conjunto_id)
        q_avisos = q_avisos.filter(models_v3.AvisoEnviado.conjunto_id == conjunto_id)

    resumen = {
        "simulacion": simulacion,
        "politica": {"conjunto_id": politica.conjunto_id, "version": politica.version, "anonimizar": politica.anonimizar_al_purgar},
        "auditoria": q_auditoria.count(),
        "accesos": q_accesos.count(),
        "avisos": q_avisos.count(),
        "intentos": q_intentos.count(),
        "sesiones": q_sesiones.count(),
    }
    if simulacion:
        return resumen

    if politica.anonimizar_al_purgar:
        for fila in q_auditoria.limit(5000).all():
            fila.email_usuario = None
            fila.ip = None
            fila.agente = None
        for fila in q_accesos.limit(5000).all():
            fila.nombre_visitante = "Visitante anonimizado"
            fila.documento = None
            fila.placa = None
            fila.observacion = None
        db.commit()
        resumen["anonimizados"] = {"auditoria": resumen["auditoria"], "accesos": resumen["accesos"]}
    else:
        q_auditoria.delete(synchronize_session=False)
        q_accesos.delete(synchronize_session=False)
        resumen["eliminados"] = {"auditoria": resumen["auditoria"], "accesos": resumen["accesos"]}
    q_avisos.delete(synchronize_session=False)
    q_intentos.delete(synchronize_session=False)
    q_sesiones.delete(synchronize_session=False)
    db.commit()
    resumen["ejecutado_en"] = ahora.isoformat()
    return resumen


@router.get("/privacidad")
def privacidad(db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    unidades = db.query(models.Inmueble).filter((models.Inmueble.propietario_id == user.id) | (models.Inmueble.inquilino_id == user.id)).first()
    politica = _politica(db, unidades.conjunto_id if unidades else None)
    consentimientos = db.query(models_v3.ConsentimientoAviso).filter_by(usuario_id=user.id).all()
    return {
        "version": politica.version,
        "texto": politica.texto_privacidad,
        "retencion": {
            "auditoria_dias": politica.dias_retencion_auditoria,
            "accesos_dias": politica.dias_retencion_accesos,
            "avisos_dias": politica.dias_retencion_avisos,
            "intentos_dias": politica.dias_retencion_intentos,
            "sesiones_dias": politica.dias_retencion_sesiones,
        },
        "mis_consentimientos": [model_data(c) for c in consentimientos],
        "derechos": ["Acceso", "Rectificación", "Revocatoria del consentimiento", "Supresión", "Queja ante la SIC"],
    }


@router.post("/privacidad/solicitud", status_code=201)
def solicitud_privacidad(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    """Registra una solicitud de habeas data dirigida a la administración."""
    tipo = str(data.get("tipo") or "acceso")
    if tipo not in ("acceso", "rectificacion", "revocatoria", "supresion", "queja"):
        raise HTTPException(422, "Tipo de solicitud inválido")
    detalle = str(data.get("detalle") or "").strip()
    if not detalle:
        raise HTTPException(422, "Describe tu solicitud")
    unidades = db.query(models.Inmueble).filter((models.Inmueble.propietario_id == user.id) | (models.Inmueble.inquilino_id == user.id)).first()
    if not unidades:
        raise HTTPException(403, "Solo residentes pueden radicar solicitudes de datos")
    cuota = models.PQRS(
        inmueble_id=unidades.id, solicitante_id=user.id, tipo=models.TipoPQRS.peticion,
        descripcion=f"[Habeas Data · {tipo}] {detalle}"[:5000], estado=models.EstadoPQRS.radicado,
        fecha_radicacion=localnow(),
    )
    db.add(cuota)
    db.flush()
    admins = db.query(models.Usuario).join(models.ConjuntoMembership, models.ConjuntoMembership.usuario_id == models.Usuario.id).filter(
        models.ConjuntoMembership.conjunto_id == unidades.conjunto_id, models.ConjuntoMembership.rol == "admin").all()
    for admin_user in admins:
        db.add(models.Notificacion(usuario_id=admin_user.id, titulo="Solicitud de protección de datos",
                                   mensaje=f"PQRS #{cuota.id} · {tipo}: {detalle[:200]}"))
    db.commit()
    return {"pqrs_id": cuota.id, "tipo": tipo, "estado": "radicado",
            "mensaje": "Tu solicitud quedó radicada como PQRS y será atendida por la administración en los términos legales."}
