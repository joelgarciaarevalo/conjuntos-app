"""Avisos por WhatsApp o SMS para aprobaciones, PQRS, paquetes y vencimientos.

Todo envío externo exige consentimiento vigente del residente y deja bitácora
con el teléfono enmascarado.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.permissions import can_access_set, is_admin, require_admin_set, require_staff_set
from app.security_v3 import dependencia_2fa, exigir_2fa_admin, get_usuario_v3, es_administracion
from app.services import messaging
from app.services.crypto_v3 import mask_phone
from app.routers.v3_common import (
    admin_only, alcance, avisar_evento, localnow, model_data, unit_access, units_for_user, usuario_visible,
)

router = APIRouter(prefix="/v3/avisos", tags=["v3 · Avisos WhatsApp/SMS"])

# Los avisos por WhatsApp/SMS sólo se envían a números en formato internacional.
TELEFONO_RE = re.compile(r"^\+[0-9]{8,15}$")

PLANTILLAS_SUGERIDAS = [
    ("aprobacion_reserva", "Reserva aprobada", "IRIS: {nombre}, tu reserva de {zona} para el {fecha} fue aprobada.", "whatsapp,sms"),
    ("rechazo_reserva", "Reserva no aprobada", "IRIS: {nombre}, tu reserva de {zona} para el {fecha} no fue aprobada. Motivo: {motivo}", "whatsapp,sms"),
    ("pqrs_respuesta", "Respuesta a tu PQRS", "IRIS: {nombre}, tu PQRS #{pqrs} cambió a {estado}. Respuesta: {respuesta}", "whatsapp,sms"),
    ("paquete_recibido", "Paquete recibido", "IRIS: {nombre}, recibimos un paquete en portería para {inmueble}: {descripcion}.", "whatsapp,sms"),
    ("cuota_vencimiento", "Vencimiento de cuota", "IRIS: {nombre}, tu {concepto} del periodo {periodo} vence el {fecha} por ${monto}.", "whatsapp,sms"),
    ("visita", "Visita en portería", "IRIS: {nombre}, {visitante} ingresó a {inmueble} a las {hora}. Placa: {placa}", "whatsapp,sms"),
    ("asamblea", "Convocatoria a asamblea", "IRIS: {nombre}, convocatoria a {titulo} el {fecha}. Lugar/enlace: {lugar}", "whatsapp,sms"),
    ("mantenimiento", "Mantenimiento programado", "IRIS: {nombre}, se programó {titulo} con fecha límite {fecha_limite}.", "whatsapp,sms"),
    ("pago_confirmado", "Pago confirmado", "IRIS: {nombre}, {mensaje}", "whatsapp,sms"),
]


@router.get("/proveedores")
def proveedores(user=Depends(get_usuario_v3)):
    return {
        "proveedores": messaging.PROVEEDORES,
        "proveedor_actual": messaging.proveedor_actual(),
        "canales_habilitados": messaging.canales_activos(),
        "max_avisos_dia": messaging.MAX_AVISOS_DIA,
    }


@router.get("/eventos")
def eventos(user=Depends(get_usuario_v3)):
    return {"eventos": messaging.EVENTOS}


# ---------------------------------------------------------------------------
# Consentimiento del residente
# ---------------------------------------------------------------------------
@router.get("/consentimientos")
def listar_consentimientos(usuario_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.ConsentimientoAviso)
    if usuario_id and usuario_id != user.id:
        if not is_admin(user):
            raise HTTPException(403, "Solo administración consulta consentimientos de terceros")
        objetivo = usuario_visible(db, user, usuario_id)
        if not objetivo:
            raise HTTPException(404, "Usuario fuera de tu alcance")
        q = q.filter(models_v3.ConsentimientoAviso.usuario_id == usuario_id)
    elif usuario_id:
        q = q.filter(models_v3.ConsentimientoAviso.usuario_id == user.id)
    elif is_admin(user):
        visibles = {u.id for u in db.query(models.Usuario).all()} if user.es_super_admin else None
        filas = q.order_by(models_v3.ConsentimientoAviso.usuario_id).all()
        return [model_data(f) for f in filas if visibles is None or f.usuario_id in visibles]
    else:
        q = q.filter(models_v3.ConsentimientoAviso.usuario_id == user.id)
    respuesta = []
    for fila in q.order_by(models_v3.ConsentimientoAviso.usuario_id, models_v3.ConsentimientoAviso.canal).all():
        datos = model_data(fila)
        datos["telefono_enmascarado"] = mask_phone(fila.telefono)
        datos["telefono"] = fila.telefono if (fila.usuario_id == user.id or is_admin(user)) else None
        respuesta.append(datos)
    return respuesta


@router.post("/consentimientos")
def otorgar_consentimiento(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    """El propio residente otorga o revoca su consentimiento para un canal."""
    canal = str(data.get("canal", "")).lower()
    if canal not in ("whatsapp", "sms"):
        raise HTTPException(422, "Canal inválido: usa whatsapp o sms")
    telefono = str(data.get("telefono") or "").strip()
    if not TELEFONO_RE.match(telefono):
        raise HTTPException(422, "Teléfono inválido. Usa formato internacional, por ejemplo +573001112233")
    otorgado = bool(data.get("otorgado", True))
    fila = db.query(models_v3.ConsentimientoAviso).filter_by(usuario_id=user.id, canal=canal).first()
    if not fila:
        fila = models_v3.ConsentimientoAviso(usuario_id=user.id, canal=canal, telefono=telefono)
        db.add(fila)
    fila.telefono = telefono
    fila.otorgado = otorgado
    fila.version_politica = str(data.get("version_politica") or "1.0")[:20]
    fila.evidencia = str(data.get("evidencia") or "Aceptación en la app IRIS")[:255]
    fila.otorgado_en = localnow() if otorgado else fila.otorgado_en
    fila.revocado_en = None if otorgado else localnow()
    if user.telefono != telefono:
        user.telefono = telefono[:20]
    db.commit()
    db.refresh(fila)
    return {**model_data(fila), "telefono_enmascarado": mask_phone(fila.telefono)}


@router.delete("/consentimientos/{consentimiento_id}", status_code=204)
def revocar_consentimiento(consentimiento_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.ConsentimientoAviso).filter_by(id=consentimiento_id).first()
    if not fila:
        raise HTTPException(404, "Consentimiento no encontrado")
    if fila.usuario_id != user.id and not is_admin(user):
        raise HTTPException(403, "Sin permiso")
    fila.otorgado = False
    fila.revocado_en = localnow()
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Plantillas por conjunto
# ---------------------------------------------------------------------------
@router.get("/plantillas")
def listar_plantillas(conjunto_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    require_staff_set(db, user, conjunto_id)
    return [model_data(f) for f in db.query(models_v3.PlantillaAviso).filter_by(conjunto_id=conjunto_id).order_by(models_v3.PlantillaAviso.evento).all()]


@router.get("/plantillas/sugeridas")
def plantillas_sugeridas(user=Depends(get_usuario_v3)):
    return [{"evento": e, "titulo": t, "cuerpo": c, "canales": k} for e, t, c, k in PLANTILLAS_SUGERIDAS]


@router.post("/plantillas", status_code=201)
def crear_plantilla(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    conjunto_id = int(data.get("conjunto_id") or 0)
    require_admin_set(db, user, conjunto_id)
    evento = str(data.get("evento", "")).strip()
    if evento not in messaging.EVENTOS:
        raise HTTPException(422, f"Evento no soportado. Opciones: {', '.join(messaging.EVENTOS)}")
    titulo = str(data.get("titulo", "")).strip()
    cuerpo = str(data.get("cuerpo", "")).strip()
    if not titulo or not cuerpo:
        raise HTTPException(422, "Título y cuerpo de la plantilla son obligatorios")
    fila = db.query(models_v3.PlantillaAviso).filter_by(conjunto_id=conjunto_id, evento=evento).first()
    if not fila:
        fila = models_v3.PlantillaAviso(conjunto_id=conjunto_id, evento=evento)
        db.add(fila)
    fila.titulo = titulo[:120]
    fila.cuerpo = cuerpo[:2000]
    fila.canales = ",".join([c.strip().lower() for c in str(data.get("canales", "whatsapp,sms")).split(",") if c.strip() in ("whatsapp", "sms")]) or "whatsapp,sms"
    fila.activo = bool(data.get("activo", True))
    fila.creado_por = fila.creado_por or user.id
    fila.actualizado_en = localnow()
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.put("/plantillas/{plantilla_id}")
def actualizar_plantilla(plantilla_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.PlantillaAviso).filter_by(id=plantilla_id).first()
    if not fila:
        raise HTTPException(404, "Plantilla no encontrada")
    require_admin_set(db, user, fila.conjunto_id)
    if data.get("titulo"):
        fila.titulo = str(data["titulo"])[:120]
    if data.get("cuerpo"):
        fila.cuerpo = str(data["cuerpo"])[:2000]
    if data.get("canales") is not None:
        fila.canales = ",".join([c.strip().lower() for c in str(data["canales"]).split(",") if c.strip() in ("whatsapp", "sms")]) or "whatsapp,sms"
    if data.get("activo") is not None:
        fila.activo = bool(data["activo"])
    fila.actualizado_en = localnow()
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.delete("/plantillas/{plantilla_id}", status_code=204)
def borrar_plantilla(plantilla_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.PlantillaAviso).filter_by(id=plantilla_id).first()
    if not fila:
        raise HTTPException(404, "Plantilla no encontrada")
    require_admin_set(db, user, fila.conjunto_id)
    db.delete(fila)
    db.commit()
    return Response(status_code=204)


@router.post("/plantillas/instalar-sugeridas")
def instalar_sugeridas(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    conjunto_id = int(data.get("conjunto_id") or 0)
    require_admin_set(db, user, conjunto_id)
    creadas = 0
    for evento, titulo, cuerpo, canales in PLANTILLAS_SUGERIDAS:
        fila = db.query(models_v3.PlantillaAviso).filter_by(conjunto_id=conjunto_id, evento=evento).first()
        if fila:
            continue
        db.add(models_v3.PlantillaAviso(conjunto_id=conjunto_id, evento=evento, titulo=titulo, cuerpo=cuerpo, canales=canales, creado_por=user.id))
        creadas += 1
    db.commit()
    return {"creadas": creadas}


# ---------------------------------------------------------------------------
# Envío y bitácora
# ---------------------------------------------------------------------------
@router.post("/enviar", status_code=201)
def enviar(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    admin_only(user)
    exigir_2fa_admin(db, user, otp)
    evento = str(data.get("evento") or "mantenimiento")
    if evento not in messaging.EVENTOS:
        raise HTTPException(422, f"Evento no soportado. Opciones: {', '.join(messaging.EVENTOS)}")
    canal = str(data.get("canal") or "").lower() or None
    if canal and canal not in ("whatsapp", "sms"):
        raise HTTPException(422, "Canal inválido")
    destinatarios: list[int] = []
    if data.get("usuario_id"):
        objetivo = usuario_visible(db, user, int(data["usuario_id"]))
        if not objetivo:
            raise HTTPException(404, "Usuario fuera de tu alcance")
        destinatarios = [objetivo.id]
    elif data.get("inmueble_id"):
        unidad = unit_access(db, user, int(data["inmueble_id"])) if not is_admin(user) else db.query(models.Inmueble).filter_by(id=int(data["inmueble_id"])).first()
        if not unidad:
            raise HTTPException(404, "Inmueble no encontrado")
        require_staff_set(db, user, unidad.conjunto_id)
        destinatarios = [x for x in {unidad.propietario_id, unidad.inquilino_id} if x]
    elif data.get("inmuebles"):
        for unidad_id in data["inmuebles"]:
            unidad = db.query(models.Inmueble).filter_by(id=int(unidad_id)).first()
            if unidad:
                require_staff_set(db, user, unidad.conjunto_id)
                destinatarios.extend([x for x in {unidad.propietario_id, unidad.inquilino_id} if x])
    else:
        raise HTTPException(422, "Indica usuario_id, inmueble_id o inmuebles")

    contexto = {"mensaje": str(data.get("mensaje") or "Tienes una novedad en tu conjunto.")[:500], **(data.get("contexto") or {})}
    resultados = []
    for usuario_id in sorted(set(destinatarios)):
        resultado = avisar_evento(db, usuario_id, evento, contexto, canal=canal)
        estado = resultado.get("estado")
        if not estado:
            estado = {"sin_consentimiento": "omitido_sin_consentimiento", "limite_diario": "omitido_limite_diario"}.get(
                resultado.get("motivo"), "enviado" if resultado.get("enviado") else "omitido"
            )
        resultados.append({
            "usuario_id": usuario_id,
            "enviado": bool(resultado.get("enviado")),
            "estado": estado,
            "canales": [fila.get("canal") for fila in (resultado.get("resultados") or [])],
            "motivo": resultado.get("motivo"),
            "mensaje": resultado.get("mensaje"),
        })
    db.commit()
    return {"destinatarios": len(resultados), "resultados": resultados}


@router.get("/bitacora")
def bitacora(conjunto_id: int | None = None, evento: str | None = None, limit: int = 100, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.AvisoEnviado)
    if is_admin(user):
        ids = [conjunto_id] if conjunto_id and can_access_set(db, user, conjunto_id) else alcance(db, user)
        q = q.filter(models_v3.AvisoEnviado.conjunto_id.in_(ids)) if ids else q.filter(models_v3.AvisoEnviado.conjunto_id.is_(None))
    else:
        q = q.filter(models_v3.AvisoEnviado.usuario_id == user.id)
    if evento:
        q = q.filter(models_v3.AvisoEnviado.evento == evento)
    filas = q.order_by(models_v3.AvisoEnviado.id.desc()).limit(max(1, min(limit, 500))).all()
    respuesta = []
    for fila in filas:
        datos = model_data(fila)
        datos["mensaje"] = (fila.mensaje or "")[:400]
        respuesta.append(datos)
    return respuesta


@router.get("/mis-avisos")
def mis_avisos(limit: int = 50, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    filas = db.query(models_v3.AvisoEnviado).filter_by(usuario_id=user.id).order_by(models_v3.AvisoEnviado.id.desc()).limit(max(1, min(limit, 200))).all()
    return [model_data(f) for f in filas]


@router.post("/vencimientos/ejecutar")
def ejecutar_vencimientos(data: dict | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    admin_only(user)
    exigir_2fa_admin(db, user, otp)
    dias = int((data or {}).get("dias_anticipacion") or 5)
    if not 1 <= dias <= 60:
        raise HTTPException(422, "dias_anticipacion debe estar entre 1 y 60")
    return messaging.aviso_vencimientos(db, dias)


@router.get("/estado-consentimientos")
def estado_consentimientos(conjunto_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    """Cobertura de consentimientos del conjunto (para saber a quién sí se puede avisar)."""
    require_admin_set(db, user, conjunto_id)
    unidades = db.query(models.Inmueble).filter_by(conjunto_id=conjunto_id).all()
    residentes = {uid for u in unidades for uid in (u.propietario_id, u.inquilino_id) if uid}
    con_whatsapp = db.query(models_v3.ConsentimientoAviso).filter(
        models_v3.ConsentimientoAviso.usuario_id.in_(residentes),
        models_v3.ConsentimientoAviso.canal == "whatsapp",
        models_v3.ConsentimientoAviso.otorgado.is_(True),
    ).count() if residentes else 0
    con_sms = db.query(models_v3.ConsentimientoAviso).filter(
        models_v3.ConsentimientoAviso.usuario_id.in_(residentes),
        models_v3.ConsentimientoAviso.canal == "sms",
        models_v3.ConsentimientoAviso.otorgado.is_(True),
    ).count() if residentes else 0
    return {"residentes": len(residentes), "con_whatsapp": con_whatsapp, "con_sms": con_sms,
            "sin_consentimiento": max(0, len(residentes) - max(con_whatsapp, con_sms))}
