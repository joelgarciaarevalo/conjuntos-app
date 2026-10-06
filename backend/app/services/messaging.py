"""Avisos externos por WhatsApp y SMS.

Reglas:
- Nunca se envía un aviso externo sin consentimiento vigente del residente.
- El teléfono se guarda/enmascara y no se expone completo en bitácoras.
- Proveedores: ``simulado`` (bitácora local, no usa red), ``meta`` (WhatsApp
  Cloud API oficial) y ``twilio`` (WhatsApp y SMS). Cualquier proveedor puede
  sustituirse por un webhook REST con ``IRIS_AVISOS_WEBHOOK``.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app import models, models_v3
from app.services.crypto_v3 import mask_phone

log = logging.getLogger("iris.avisos")

PROVEEDORES = [
    {"codigo": "simulado", "nombre": "Bitácora simulada (sin envío real)"},
    {"codigo": "meta", "nombre": "WhatsApp Cloud API (Meta)"},
    {"codigo": "twilio", "nombre": "Twilio (WhatsApp y SMS)"},
    {"codigo": "webhook", "nombre": "Webhook REST personalizado"},
]

EVENTOS = [
    "aprobacion_reserva", "rechazo_reserva", "pqrs_respuesta", "paquete_recibido",
    "cuota_vencimiento", "visita", "asamblea", "mantenimiento", "pago_confirmado",
]

MAX_AVISOS_DIA = int(os.getenv("IRIS_AVISOS_MAX_DIA", "12"))


def proveedor_actual() -> str:
    return os.getenv("IRIS_AVISOS_PROVEEDOR", "simulado").lower()


def canales_activos() -> list[str]:
    crudo = os.getenv("IRIS_AVISOS_CANALES", "whatsapp,sms")
    return [c.strip().lower() for c in crudo.split(",") if c.strip()]


def _http_post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 15) -> dict:
    data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode() or "{}")


def renderizar(plantilla: str, contexto: dict) -> str:
    texto = plantilla or ""
    for clave, valor in (contexto or {}).items():
        texto = texto.replace("{" + str(clave) + "}", str(valor if valor is not None else ""))
    return texto


def consentimiento_vigente(db: Session, usuario_id: int, canal: str) -> models_v3.ConsentimientoAviso | None:
    fila = db.query(models_v3.ConsentimientoAviso).filter_by(usuario_id=usuario_id, canal=canal).first()
    if not fila or not fila.otorgado or not fila.telefono:
        return None
    return fila


def canales_permitidos(db: Session, usuario_id: int) -> list[str]:
    disponibles = []
    for canal in canales_activos():
        if consentimiento_vigente(db, usuario_id, canal):
            disponibles.append(canal)
    return disponibles


def _enviar_proveedor(canal: str, telefono: str, mensaje: str) -> dict:
    """Entrega al proveedor configurado. Devuelve estado + referencia."""
    proveedor = proveedor_actual()
    if proveedor == "simulado":
        return {"estado": "simulado", "proveedor": "simulado", "referencia": f"SIM-{datetime.now().timestamp():.0f}", "detalle": "Aviso registrado sin envío real (modo simulado)"}

    if proveedor == "webhook":
        url = os.getenv("IRIS_AVISOS_WEBHOOK", "")
        if not url:
            return {"estado": "fallido", "proveedor": "webhook", "detalle": "Falta IRIS_AVISOS_WEBHOOK"}
        try:
            respuesta = _http_post_json(url, {"canal": canal, "to": telefono, "mensaje": mensaje}, headers={"Authorization": f"Bearer {os.getenv('IRIS_AVISOS_TOKEN', '')}"})
            return {"estado": "enviado", "proveedor": "webhook", "referencia": str(respuesta.get("id", "")), "detalle": None}
        except Exception as exc:  # pragma: no cover - depende de red
            return {"estado": "fallido", "proveedor": "webhook", "detalle": str(exc)[:200]}

    if proveedor == "meta":
        token = os.getenv("IRIS_META_TOKEN", "")
        phone_id = os.getenv("IRIS_META_PHONE_ID", "")
        if not token or not phone_id:
            return {"estado": "fallido", "proveedor": "meta", "detalle": "Faltan IRIS_META_TOKEN / IRIS_META_PHONE_ID"}
        try:
            respuesta = _http_post_json(
                f"https://graph.facebook.com/v20.0/{phone_id}/messages",
                {"messaging_product": "whatsapp", "to": telefono, "type": "text", "text": {"preview_url": False, "body": mensaje}},
                headers={"Authorization": f"Bearer {token}"},
            )
            return {"estado": "enviado", "proveedor": "meta", "referencia": str((respuesta.get("messages") or [{}])[0].get("id", "")), "detalle": None}
        except Exception as exc:  # pragma: no cover
            return {"estado": "fallido", "proveedor": "meta", "detalle": str(exc)[:200]}

    if proveedor == "twilio":
        sid = os.getenv("IRIS_TWILIO_SID", "")
        token = os.getenv("IRIS_TWILIO_TOKEN", "")
        origen = os.getenv("IRIS_TWILIO_FROM", "")
        if not sid or not token or not origen:
            return {"estado": "fallido", "proveedor": "twilio", "detalle": "Faltan IRIS_TWILIO_SID / IRIS_TWILIO_TOKEN / IRIS_TWILIO_FROM"}
        from_field = f"whatsapp:{origen}" if canal == "whatsapp" else origen
        to_field = f"whatsapp:{telefono}" if canal == "whatsapp" else telefono
        data = urllib.parse.urlencode({"From": from_field, "To": to_field, "Body": mensaje}).encode()
        request = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        import base64
        request.add_header("Authorization", "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode())
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                respuesta = json.loads(response.read().decode() or "{}")
            return {"estado": "enviado", "proveedor": "twilio", "referencia": str(respuesta.get("sid", "")), "detalle": None}
        except urllib.error.HTTPError as exc:  # pragma: no cover
            return {"estado": "fallido", "proveedor": "twilio", "detalle": exc.read().decode(errors="replace")[:200]}
        except Exception as exc:  # pragma: no cover
            return {"estado": "fallido", "proveedor": "twilio", "detalle": str(exc)[:200]}

    return {"estado": "fallido", "proveedor": proveedor, "detalle": "Proveedor de avisos no reconocido"}


def avisos_enviados_hoy(db: Session, usuario_id: int) -> int:
    desde = datetime.now(ZoneInfo("America/Bogota")).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.query(models_v3.AvisoEnviado).filter(
        models_v3.AvisoEnviado.usuario_id == usuario_id,
        models_v3.AvisoEnviado.creado_en >= desde,
        models_v3.AvisoEnviado.estado.in_(("enviado", "simulado")),
    ).count()


def plantilla_para(db: Session, conjunto_id: int | None, evento: str) -> models_v3.PlantillaAviso | None:
    if conjunto_id is None:
        return None
    return db.query(models_v3.PlantillaAviso).filter_by(conjunto_id=conjunto_id, evento=evento, activo=True).first()


def avisar(db: Session, usuario_id: int, evento: str, contexto: dict | None = None, conjunto_id: int | None = None, canal: str | None = None) -> dict:
    """Envía un aviso externo respetando el consentimiento del residente.

    Devuelve un resumen del resultado y siempre deja registro en la bitácora.
    """
    contexto = contexto or {}
    usuario = db.query(models.Usuario).filter_by(id=usuario_id).first()
    if not usuario:
        return {"enviado": False, "motivo": "usuario_inexistente"}

    if conjunto_id is None:
        unidad = db.query(models.Inmueble).filter((models.Inmueble.propietario_id == usuario_id) | (models.Inmueble.inquilino_id == usuario_id)).first()
        conjunto_id = unidad.conjunto_id if unidad else None

    plantilla = plantilla_para(db, conjunto_id, evento)
    titulo = plantilla.titulo if plantilla else evento.replace("_", " ").capitalize()
    cuerpo_base = plantilla.cuerpo if plantilla else "IRIS: {mensaje}"
    mensaje = renderizar(cuerpo_base, {**contexto, "nombre": usuario.nombre_completo, "titulo": titulo})
    canales_preferidos = ([canal] if canal else [c for c in (plantilla.canales.split(",") if plantilla else canales_activos()) if c.strip()])
    canales_preferidos = [c.strip().lower() for c in canales_preferidos if c.strip()]

    permitidos = canales_permitidos(db, usuario_id)
    elegidos = [c for c in canales_preferidos if c in permitidos]
    if not elegidos:
        db.add(models_v3.AvisoEnviado(
            conjunto_id=conjunto_id, usuario_id=usuario_id, evento=evento, canal=canales_preferidos[0] if canales_preferidos else "sms",
            telefono_enmascarado=None, mensaje=mensaje, estado="omitido_sin_consentimiento",
            proveedor=None, detalle="El residente no tiene consentimiento vigente para avisos externos",
        ))
        db.flush()
        return {"enviado": False, "motivo": "sin_consentimiento", "mensaje": mensaje}

    if avisos_enviados_hoy(db, usuario_id) >= MAX_AVISOS_DIA:
        db.add(models_v3.AvisoEnviado(conjunto_id=conjunto_id, usuario_id=usuario_id, evento=evento, canal=elegidos[0],
                                      mensaje=mensaje, estado="omitido_sin_consentimiento", detalle="Límite diario de avisos alcanzado"))
        db.flush()
        return {"enviado": False, "motivo": "limite_diario", "mensaje": mensaje}

    resultados = []
    ultimo = None
    for canal_elegido in elegidos:
        consentimiento = consentimiento_vigente(db, usuario_id, canal_elegido)
        telefono = consentimiento.telefono if consentimiento else None
        if not telefono:
            continue
        resultado = _enviar_proveedor(canal_elegido, telefono, mensaje)
        fila = models_v3.AvisoEnviado(
            conjunto_id=conjunto_id, usuario_id=usuario_id, evento=evento, canal=canal_elegido,
            telefono_enmascarado=mask_phone(telefono), mensaje=mensaje,
            estado=resultado["estado"], proveedor=resultado.get("proveedor"), referencia=resultado.get("referencia"),
            detalle=resultado.get("detalle"),
        )
        db.add(fila); db.flush()
        ultimo = resultado
        resultados.append({"canal": canal_elegido, **resultado})

    db.add(models.Notificacion(usuario_id=usuario_id, titulo=titulo, mensaje=mensaje[:500]))
    db.flush()
    return {"enviado": bool(resultados), "resultados": resultados, "mensaje": mensaje, "estado": (ultimo or {}).get("estado")}


def aviso_vencimientos(db: Session, dias_anticipacion: int = 5) -> dict:
    """Recorre las cuotas próximas a vencer y avisa una sola vez por cuota y periodo."""
    hoy = datetime.now(ZoneInfo("America/Bogota")).replace(tzinfo=None).date()
    limite = hoy + timedelta(days=dias_anticipacion)
    cuotas = db.query(models.Cuota).filter(
        models.Cuota.estado == "pendiente",
        models.Cuota.fecha_vencimiento <= limite,
    ).all()
    enviados, omitidos = 0, 0
    for cuota in cuotas:
        unidad = db.query(models.Inmueble).filter_by(id=cuota.inmueble_id).first()
        if not unidad:
            continue
        for usuario_id in {unidad.propietario_id, unidad.inquilino_id} - {None}:
            marca = f"cuota_vencimiento:{cuota.id}:{hoy.isoformat()}"
            ya = db.query(models_v3.AvisoEnviado).filter(
                models_v3.AvisoEnviado.usuario_id == usuario_id,
                models_v3.AvisoEnviado.evento == "cuota_vencimiento",
                models_v3.AvisoEnviado.detalle == marca,
            ).first()
            if ya:
                continue
            resultado = avisar(db, usuario_id, "cuota_vencimiento", {
                "concepto": cuota.concepto, "periodo": cuota.periodo, "monto": f"{cuota.monto:,.0f}",
                "fecha": cuota.fecha_vencimiento.isoformat(), "inmueble": f"{(unidad.torre or '')} {unidad.numero}".strip(),
                "mensaje": f"Tu {cuota.concepto} del periodo {cuota.periodo} vence el {cuota.fecha_vencimiento.isoformat()} por ${cuota.monto:,.0f}.",
            }, conjunto_id=unidad.conjunto_id)
            if resultado.get("enviado"):
                enviados += 1
                if resultado.get("resultados"):
                    ultima = db.query(models_v3.AvisoEnviado).filter_by(usuario_id=usuario_id, evento="cuota_vencimiento").order_by(models_v3.AvisoEnviado.id.desc()).first()
                    if ultima:
                        ultima.detalle = marca
            else:
                omitidos += 1
    db.commit()
    return {"cuotas_revisadas": len(cuotas), "avisos_enviados": enviados, "omitidos_sin_consentimiento": omitidos}