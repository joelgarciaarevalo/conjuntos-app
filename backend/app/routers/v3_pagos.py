"""Pagos en línea con pasarela colombiana y conciliación automática.

Principios:
- IRIS nunca captura ni almacena números de tarjeta: el navegador tokeniza con
  el proveedor y sólo se guarda el token de un solo uso, la marca y los últimos
  cuatro dígitos (más información NO sensible).
- La conciliación es automática al recibir el webhook del proveedor y también
  puede ejecutarse manualmente o en lote.
"""
from __future__ import annotations

import secrets
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.permissions import can_access_set, is_admin, require_admin_set
from app.security_v3 import dependencia_2fa, exigir_2fa_admin, get_usuario_v3
from app.services import payments_gateway as gw
from app.services.crypto_v3 import cifrar, descifrar, enmascarar, hash_valor, resumen_seguro
from app.routers.v3_common import (
    admin_only, avisar_evento, dec, localnow, model_data, money, notificar, payload_sin_tarjetas,
    resumen_conjunto, unit_access, units_for_user,
)

router = APIRouter(prefix="/v3/pagos", tags=["v3 · Pagos en línea"])


# ---------------------------------------------------------------------------
# Configuración de la pasarela
# ---------------------------------------------------------------------------
@router.get("/proveedores")
def listar_proveedores(user=Depends(get_usuario_v3)):
    return gw.proveedores_disponibles()


def _config_publica(fila: models_v3.ConfigPasarela | None, conjunto_id: int) -> dict:
    if not fila:
        return {
            "conjunto_id": conjunto_id, "proveedor": "simulado", "modo": "sandbox", "moneda": "COP",
            "public_key": None, "private_key": None, "events_secret": None, "integrity_secret": None,
            "merchant_id": None, "configurada": False, "activo": False,
            "permite_tarjeta": True, "permite_pse": True, "permite_nequi": True,
            "conciliacion_automatica": True,
        }
    return {
        "conjunto_id": fila.conjunto_id, "proveedor": fila.proveedor, "modo": fila.modo, "moneda": fila.moneda,
        "public_key": fila.public_key,
        "private_key": enmascarar(descifrar(fila.private_key_cifrada)),
        "events_secret": enmascarar(descifrar(fila.events_secret_cifrado)),
        "integrity_secret": enmascarar(descifrar(fila.integrity_secret_cifrado)),
        "merchant_id": fila.merchant_id, "configurada": bool(fila.public_key and fila.private_key_cifrada),
        "activo": fila.activo, "permite_tarjeta": fila.permite_tarjeta, "permite_pse": fila.permite_pse,
        "permite_nequi": fila.permite_nequi, "conciliacion_automatica": fila.conciliacion_automatica,
        "actualizado_en": fila.actualizado_en.isoformat() if fila.actualizado_en else None,
        "tokenizacion": gw.PROVEEDORES.get(fila.proveedor, {}).get("tokenizacion"),
    }


@router.get("/config")
def leer_config(conjunto_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    require_admin_set(db, user, conjunto_id)
    return _config_publica(db.query(models_v3.ConfigPasarela).filter_by(conjunto_id=conjunto_id).first(), conjunto_id)


def _config_para_cobro(db: Session, conjunto_id: int) -> dict:
    fila = db.query(models_v3.ConfigPasarela).filter_by(conjunto_id=conjunto_id).first()
    if not fila:
        # Sin configuración explícita se usa la pasarela simulada en sandbox.
        return {"conjunto_id": conjunto_id, "proveedor": "simulado", "modo": "sandbox", "moneda": "COP"}
    return {
        "conjunto_id": conjunto_id, "proveedor": fila.proveedor, "modo": fila.modo, "moneda": fila.moneda,
        "public_key": fila.public_key, "private_key": descifrar(fila.private_key_cifrada),
        "events_secret": descifrar(fila.events_secret_cifrado), "integrity_secret": descifrar(fila.integrity_secret_cifrado),
        "merchant_id": fila.merchant_id,
    }


@router.put("/config")
def guardar_config(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3),
                   otp: str | None = dependencia_2fa()):
    conjunto_id = int(data.get("conjunto_id") or 0)
    require_admin_set(db, user, conjunto_id)
    exigir_2fa_admin(db, user, otp)
    proveedor = str(data.get("proveedor", "simulado")).lower()
    if proveedor not in gw.PROVEEDORES:
        raise HTTPException(422, f"Proveedor no soportado. Opciones: {', '.join(gw.PROVEEDORES)}")
    modo = str(data.get("modo", "sandbox")).lower()
    if modo not in ("sandbox", "produccion"):
        raise HTTPException(422, "El modo debe ser sandbox o produccion")
    fila = db.query(models_v3.ConfigPasarela).filter_by(conjunto_id=conjunto_id).first()
    if not fila:
        fila = models_v3.ConfigPasarela(conjunto_id=conjunto_id, proveedor=proveedor)
        db.add(fila)
    fila.proveedor = proveedor
    fila.modo = modo
    fila.moneda = str(data.get("moneda", "COP"))[:3].upper()
    if data.get("public_key") is not None:
        fila.public_key = str(data["public_key"])[:255] or None
    if data.get("private_key"):
        fila.private_key_cifrada = cifrar(str(data["private_key"]))
    if data.get("events_secret"):
        fila.events_secret_cifrado = cifrar(str(data["events_secret"]))
    if data.get("integrity_secret"):
        fila.integrity_secret_cifrado = cifrar(str(data["integrity_secret"]))
    if data.get("merchant_id") is not None:
        fila.merchant_id = str(data["merchant_id"])[:120] or None
    for campo in ("permite_tarjeta", "permite_pse", "permite_nequi", "conciliacion_automatica", "activo"):
        if campo in data:
            setattr(fila, campo, bool(data[campo]))
    fila.actualizado_en = localnow()
    db.commit()
    db.refresh(fila)
    return _config_publica(fila, conjunto_id)


# ---------------------------------------------------------------------------
# Checkout y cobro
# ---------------------------------------------------------------------------
@router.get("/metodos")
def metodos_disponibles(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if conjunto_id is None:
        unidad = units_for_user(db, user)
        if not unidad and not (is_admin(user) or user.es_super_admin):
            raise HTTPException(422, "No se pudo determinar el conjunto del usuario")
        conjunto_id = unidad[0].conjunto_id if unidad else None
        if conjunto_id is None:
            raise HTTPException(422, "Indica el conjunto")
    if not can_access_set(db, user, conjunto_id):
        raise HTTPException(403, "No tienes acceso a este conjunto")
    config = _config_publica(db.query(models_v3.ConfigPasarela).filter_by(conjunto_id=conjunto_id).first(), conjunto_id)
    permitidos = []
    if config.get("permite_tarjeta"): permitidos.append("tarjeta")
    if config.get("permite_pse"): permitidos.append("pse")
    if config.get("permite_nequi"): permitidos.append("nequi")
    meta = gw.PROVEEDORES.get(config.get("proveedor") or "simulado", gw.PROVEEDORES["simulado"])
    return {
        "proveedor": config.get("proveedor"), "modo": config.get("modo"),
        "public_key": config.get("public_key") or ("pk_test_simulado" if (config.get("proveedor") or "simulado") == "simulado" else None),
        "tokenizacion": meta.get("tokenizacion"),
        "metodos": [m for m in permitidos if m in meta["metodos"]],
        "moneda": config.get("moneda") or "COP",
    }


@router.post("/checkout", status_code=201)
def iniciar_checkout(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    """Crea la intención de pago y devuelve los datos para tokenizar en el navegador."""
    payload_sin_tarjetas(data)
    cuota = db.query(models.Cuota).filter_by(id=int(data.get("cuota_id") or 0)).first()
    if not cuota:
        raise HTTPException(404, "Cuota no encontrada")
    unit = unit_access(db, user, cuota.inmueble_id)
    if is_admin(user):
        raise HTTPException(400, "La administración registra los pagos desde el módulo de contabilidad")
    if cuota.estado == "pagada":
        raise HTTPException(409, "La cuota ya figura pagada")
    metodo = str(data.get("metodo", "tarjeta")).lower()
    config = _config_para_cobro(db, unit.conjunto_id)
    if metodo not in gw.PROVEEDORES.get(config["proveedor"], gw.PROVEEDORES["simulado"])["metodos"]:
        raise HTTPException(422, f"El proveedor configurado no admite el método {metodo}")
    monto = dec(data.get("monto") or cuota.monto)
    if monto <= 0 or monto > dec(cuota.monto):
        raise HTTPException(422, "El monto debe ser mayor que cero y no superar el valor de la cuota")

    referencia = f"IRIS-{unit.conjunto_id}-{cuota.id}-{secrets.token_hex(4).upper()}"
    idempotencia = f"{user.id}:{cuota.id}:{metodo}:{secrets.token_hex(6)}"
    fila = models_v3.TransaccionPago(
        conjunto_id=unit.conjunto_id, inmueble_id=unit.id, cuota_id=cuota.id, usuario_id=user.id,
        proveedor=config["proveedor"], metodo=metodo, monto=monto, moneda=config.get("moneda", "COP"),
        referencia=referencia, idempotencia=idempotencia, estado="iniciada",
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    respuesta = {
        "transaccion_id": fila.id, "referencia": fila.referencia, "monto": money(fila.monto),
        "moneda": fila.moneda, "proveedor": fila.proveedor, "metodo": metodo, "estado": fila.estado,
        "cuota": {"id": cuota.id, "concepto": cuota.concepto, "periodo": cuota.periodo},
        "inmueble": {"id": unit.id, "etiqueta": f"{(unit.torre or '')} {unit.numero}".strip()},
        "public_key": config.get("public_key") or ("pk_test_simulado" if config["proveedor"] == "simulado" else None),
        "tokenizacion": gw.PROVEEDORES.get(config["proveedor"], {}).get("tokenizacion"),
        "instrucciones": "Tokeniza la tarjeta con el SDK del proveedor y envía el token a POST /v3/pagos/cobrar. IRIS no recibe datos de la tarjeta.",
    }
    if config["proveedor"] == "simulado":
        respuesta["tokens_demo"] = {
            "aprobado": "tok_visa_aprobado", "rechazado": "tok_visa_rechaza", "pendiente": "tok_visa_pendiente",
        }
    return respuesta


def _actualizar_desde_resultado(db: Session, fila: models_v3.TransaccionPago, resultado: dict) -> None:
    fila.estado = gw.normalizar_estado(resultado.get("estado_proveedor"))
    fila.referencia_proveedor = (resultado.get("referencia_proveedor") or fila.referencia)[:120]
    fila.mensaje = str(resultado.get("mensaje") or "")[:255]
    fila.marca_tarjeta = (resultado.get("marca_tarjeta") or None)[:30] if resultado.get("marca_tarjeta") else None
    fila.ultimos_cuatro = (resultado.get("ultimos_cuatro") or None)
    fila.payload_resumen = resumen_seguro(resultado.get("payload") or {})
    fila.actualizado_en = localnow()


def conciliar(db: Session, fila: models_v3.TransaccionPago, origen: str = "automatica", usuario_id: int | None = None) -> dict:
    """Concilia una transacción aprobada con su cuota: marca pagada y genera recibo."""
    if fila.estado != "aprobada":
        return {"conciliada": False, "motivo": "La transacción no está aprobada"}
    if fila.conciliado:
        return {"conciliada": True, "motivo": "Ya estaba conciliada", "pago_id": fila.pago_id}
    cuota = db.query(models.Cuota).filter_by(id=fila.cuota_id).first() if fila.cuota_id else None
    pago = models.Pago(
        cuota_id=cuota.id if cuota else fila.cuota_id, inmueble_id=fila.inmueble_id, solicitado_por=fila.usuario_id,
        verificado_por=None, monto=fila.monto, metodo=f"pasarela_{fila.proveedor}_{fila.metodo}",
        referencia=fila.referencia_proveedor or fila.referencia, estado="verificado",
        notas=f"Conciliación {origen} de la pasarela {fila.proveedor}. Transacción IRIS #{fila.id}.",
        verificado_en=localnow(),
    )
    db.add(pago)
    db.flush()
    diferencia = Decimal("0")
    if cuota:
        diferencia = dec(cuota.monto) - dec(fila.monto)
        if dec(fila.monto) >= dec(cuota.monto):
            cuota.estado = "pagada"
            cuota.pagada_en = pago.verificado_en
    fila.conciliado = True
    fila.conciliado_en = localnow()
    fila.pago_id = pago.id
    registro = models_v3.ConciliacionPago(
        conjunto_id=fila.conjunto_id, transaccion_id=fila.id, cuota_id=fila.cuota_id, pago_id=pago.id,
        origen=origen, monto=fila.monto, diferencia=diferencia if diferencia > 0 else Decimal("0"),
        observacion=(f"Faltante de {money(diferencia)}" if diferencia > 0 else "Conciliado por el valor exacto de la cuota"),
        creado_por=usuario_id,
    )
    db.add(registro)
    unidad = db.query(models.Inmueble).filter_by(id=fila.inmueble_id).first()
    grupo = resumen_conjunto(db, fila.conjunto_id)
    for usuario_id_destino in ({unidad.propietario_id, unidad.inquilino_id} - {None} if unidad else set()):
        notificar(db, usuario_id_destino, "Pago confirmado", f"Pago aprobado por ${money(fila.monto)} para {grupo['nombre']}. Recibo #{pago.id}.")
        avisar_evento(db, usuario_id_destino, "pago_confirmado", {
            "monto": money(fila.monto), "conjunto": grupo["nombre"], "recibo": pago.id,
            "mensaje": f"Pago aprobado por ${money(fila.monto)}. Recibo #{pago.id}.",
        }, conjunto_id=fila.conjunto_id)
    db.commit()
    return {"conciliada": True, "pago_id": pago.id, "conciliacion_id": registro.id, "diferencia": money(diferencia)}


def _buscar_transaccion(db: Session, referencia: str | None, referencia_proveedor: str | None) -> models_v3.TransaccionPago | None:
    if referencia:
        fila = db.query(models_v3.TransaccionPago).filter_by(referencia=referencia).first()
        if fila:
            return fila
    if referencia_proveedor:
        return db.query(models_v3.TransaccionPago).filter_by(referencia_proveedor=referencia_proveedor).first()
    return None


@router.post("/cobrar")
def cobrar(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    """Cobra con el token generado por la pasarela en el navegador."""
    payload_sin_tarjetas(data)
    fila = None
    if data.get("transaccion_id"):
        fila = db.query(models_v3.TransaccionPago).filter_by(id=int(data["transaccion_id"]), usuario_id=user.id).first()
    if not fila and data.get("referencia"):
        fila = db.query(models_v3.TransaccionPago).filter_by(referencia=str(data["referencia"]), usuario_id=user.id).first()
    if not fila:
        raise HTTPException(404, "Transacción no encontrada")
    if fila.estado in ("aprobada", "declinada", "anulada", "expirada"):
        raise HTTPException(409, f"La transacción ya finalizó con estado {fila.estado}")
    token = str(data.get("token") or "").strip()
    if not token or len(token) > 255:
        raise HTTPException(422, "Falta el token de pago generado por la pasarela")
    config = _config_para_cobro(db, fila.conjunto_id)
    unidad = db.query(models.Inmueble).filter_by(id=fila.inmueble_id).first()
    try:
        resultado = gw.cobrar(
            config, referencia=fila.referencia, monto=fila.monto, metodo=fila.metodo, token=token,
            correo=user.email, descripcion=f"IRIS cuota {fila.cuota_id}", documento=str(data.get("documento") or ""),
            tipo_persona=str(data.get("tipo_persona") or "0"), banco=str(data.get("banco") or ""),
            telefono=str(data.get("telefono") or ""), cuotas=int(data.get("cuotas") or 1),
        )
    except gw.GatewayError as exc:
        fila.estado = "error"
        fila.mensaje = str(exc)[:255]
        fila.actualizado_en = localnow()
        db.commit()
        raise HTTPException(502, str(exc))
    fila.token_proveedor = hash_valor(token)[:64]  # sólo hash del token de un solo uso
    if data.get("titular"):
        fila.titular_hash = hash_valor(str(data["titular"]).lower())[:64]
    _actualizar_desde_resultado(db, fila, resultado)
    db.commit()
    detalle = {"transaccion_id": fila.id, "estado": fila.estado, "mensaje": fila.mensaje,
               "referencia": fila.referencia, "referencia_proveedor": fila.referencia_proveedor,
               "marca_tarjeta": fila.marca_tarjeta, "ultimos_cuatro": fila.ultimos_cuatro}
    if fila.estado == "aprobada":
        detalle["conciliacion"] = conciliar(db, fila, origen="automatica")
    elif fila.estado in ("declinada", "error"):
        notificar(db, fila.usuario_id, "Pago no aprobado", f"La transacción {fila.referencia} terminó en estado {fila.estado}: {fila.mensaje or ''}")
        db.commit()
    return detalle


@router.post("/webhook/{proveedor}")
async def webhook(proveedor: str, request: Request, db: Session = Depends(get_db),
                  x_iris_firma: str | None = Header(default=None, alias="X-IRIS-Firma")):
    """Notificación del proveedor. Verifica firma y concilia automáticamente."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Payload JSON inválido")
    proveedor = proveedor.lower()
    referencia = None
    evento_nombre = "transaction.updated"
    if proveedor == "wompi":
        datos = payload.get("data") or {}
        transaccion = datos.get("transaction") or {}
        referencia = transaccion.get("reference")
        evento_nombre = str(payload.get("event") or evento_nombre)
    else:
        referencia = payload.get("reference") or (payload.get("data") or {}).get("reference")
        evento_nombre = str(payload.get("event") or evento_nombre)

    fila = db.query(models_v3.TransaccionPago).filter_by(referencia=str(referencia)).first() if referencia else None
    config = _config_para_cobro(db, fila.conjunto_id) if fila else {"proveedor": proveedor, "events_secret": None}
    secreto = config.get("events_secret")

    firma_valida = False
    if proveedor == "wompi":
        firma_valida = bool(secreto) and gw.verificar_evento_wompi(secreto, payload)
    elif proveedor == "simulado":
        checksum = str(payload.get("checksum") or x_iris_firma or "")
        esperado = gw.firma_evento(secreto or "simulado", {
            "reference": str(payload.get("reference") or ""),
            "status": str(payload.get("status") or ""),
        }, ["reference", "status"])
        firma_valida = bool(checksum) and checksum.lower() == esperado.lower()
    else:
        checksum = str(payload.get("checksum") or x_iris_firma or "")
        calculado = gw.firma_integridad(secreto or "", str(referencia or ""), int(payload.get("amount_in_cents") or 0), str(payload.get("currency") or "COP"))
        firma_valida = bool(checksum) and checksum.lower() == calculado.lower()

    evento = models_v3.EventoPasarela(
        conjunto_id=fila.conjunto_id if fila else None, transaccion_id=fila.id if fila else None,
        proveedor=proveedor, evento=evento_nombre[:60], firma_valida=firma_valida,
        estado_proveedor=str((payload.get("data") or {}).get("transaction", {}).get("status") or payload.get("status") or "")[:30],
        resumen=resumen_seguro(payload), ip=(request.client.host if request.client else None),
    )
    db.add(evento)
    if not firma_valida:
        db.commit()
        raise HTTPException(401, "Firma del webhook inválida")
    if not fila:
        db.commit()
        return {"recibido": True, "conciliada": False, "motivo": "Transacción no reconocida"}

    estado_proveedor = evento.estado_proveedor
    if proveedor != "wompi":
        estado_proveedor = str(payload.get("status") or estado_proveedor)
    fila.estado = gw.normalizar_estado(estado_proveedor)
    fila.mensaje = str((payload.get("data") or {}).get("transaction", {}).get("status_message") or payload.get("message") or fila.mensaje or "")[:255]
    fila.actualizado_en = localnow()
    db.commit()

    conciliacion = {"conciliada": False}
    if fila.estado == "aprobada":
        conciliacion = conciliar(db, fila, origen="webhook")
    elif fila.estado in ("declinada", "error"):
        notificar(db, fila.usuario_id, "Pago no aprobado", f"La transacción {fila.referencia} fue {fila.estado}.")
        db.commit()
    return {"recibido": True, "estado": fila.estado, **conciliacion}


@router.get("/transacciones")
def listar_transacciones(estado: str | None = None, conjunto_id: int | None = None, page: int = 1, size: int = 50,
                         db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.TransaccionPago)
    if is_admin(user):
        ids = [c for c in ([conjunto_id] if conjunto_id else []) if can_access_set(db, user, c)] or sorted(
            {row[0] for row in db.query(models.ConjuntoMembership.conjunto_id).filter_by(usuario_id=user.id, rol="admin").all()} | ({c.id for c in db.query(models.Conjunto.id).all()} if user.es_super_admin else set())
        )
        if not ids:
            return {"total": 0, "page": page, "size": size, "items": []}
        q = q.filter(models_v3.TransaccionPago.conjunto_id.in_(ids))
    else:
        q = q.filter(models_v3.TransaccionPago.usuario_id == user.id)
    if estado:
        q = q.filter(models_v3.TransaccionPago.estado == estado)
    total = q.count()
    filas = q.order_by(models_v3.TransaccionPago.id.desc()).offset((max(1, page) - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": [model_data(f) for f in filas]}


@router.post("/transacciones/{transaccion_id}/conciliar")
def conciliar_manual(transaccion_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3),
                     otp: str | None = dependencia_2fa()):
    fila = db.query(models_v3.TransaccionPago).filter_by(id=transaccion_id).first()
    if not fila:
        raise HTTPException(404, "Transacción no encontrada")
    require_admin_set(db, user, fila.conjunto_id)
    exigir_2fa_admin(db, user, otp)
    if fila.estado != "aprobada":
        try:
            config = _config_para_cobro(db, fila.conjunto_id)
            resultado = gw.consultar(config, fila.referencia_proveedor or fila.referencia)
            _actualizar_desde_resultado(db, fila, resultado)
            db.commit()
        except Exception as exc:
            raise HTTPException(409, f"La transacción no está aprobada y no se pudo consultar al proveedor: {exc}")
    return conciliar(db, fila, origen="manual", usuario_id=user.id)


@router.post("/conciliacion/ejecutar")
def ejecutar_conciliacion(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3),
                          otp: str | None = dependencia_2fa()):
    """Conciliación automática en lote: aprobadas sin recibo y webhooks pendientes."""
    ids = sorted({row[0] for row in db.query(models.ConjuntoMembership.conjunto_id).filter_by(usuario_id=user.id, rol="admin").all()})
    if user.es_super_admin:
        ids = [c.id for c in db.query(models.Conjunto.id).all()]
    if conjunto_id:
        require_admin_set(db, user, conjunto_id)
        ids = [conjunto_id]
    if not ids:
        raise HTTPException(403, "No administras ningún conjunto")
    exigir_2fa_admin(db, user, otp)
    pendientes = db.query(models_v3.TransaccionPago).filter(
        models_v3.TransaccionPago.conjunto_id.in_(ids),
        models_v3.TransaccionPago.conciliado.is_(False),
    ).all()
    conciliadas, revisadas, errores = [], 0, []
    for fila in pendientes:
        if fila.estado in ("iniciada", "pendiente"):
            revisadas += 1
            try:
                config = _config_para_cobro(db, fila.conjunto_id)
                resultado = gw.consultar(config, fila.referencia_proveedor or fila.referencia)
                _actualizar_desde_resultado(db, fila, resultado)
                db.commit()
            except Exception as exc:
                errores.append({"transaccion_id": fila.id, "detalle": str(exc)[:160]})
                continue
        if fila.estado == "aprobada":
            resultado = conciliar(db, fila, origen="automatica")
            if resultado.get("conciliada"):
                conciliadas.append({"transaccion_id": fila.id, "pago_id": resultado.get("pago_id")})
    return {"transacciones_revisadas": revisadas, "conciliadas": conciliadas, "total_conciliadas": len(conciliadas), "errores": errores}


@router.get("/transacciones/{transaccion_id}/comprobante", response_class=HTMLResponse)
def comprobante(transaccion_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    import html as html_lib
    fila = db.query(models_v3.TransaccionPago).filter_by(id=transaccion_id).first()
    if not fila:
        raise HTTPException(404, "Transacción no encontrada")
    unidad = unit_access(db, user, fila.inmueble_id)
    if fila.estado != "aprobada":
        raise HTTPException(409, "El comprobante se habilita cuando el pago está aprobado")
    grupo = resumen_conjunto(db, fila.conjunto_id)
    cuota = db.query(models.Cuota).filter_by(id=fila.cuota_id).first() if fila.cuota_id else None
    contenido = f"""<!doctype html><html lang="es"><meta charset="utf-8"><title>Comprobante IRIS #{fila.id}</title>
<style>body{{font:16px Arial;max-width:720px;margin:48px auto;color:#0c3b45}}header,footer{{border-bottom:2px solid #21666b;padding:12px}}table{{width:100%;border-collapse:collapse}}td{{padding:10px;border-bottom:1px solid #dbe7ea}}button{{padding:10px 18px;background:#21666b;color:#fff;border:0;cursor:pointer}}@media print{{button{{display:none}}}}</style>
<header><h1>Comprobante de pago en línea</h1><b>{html_lib.escape(grupo['nombre'] or 'IRIS')}</b></header>
<p>Transacción #{fila.id} · {fila.creado_en.strftime('%Y-%m-%d %H:%M')}</p>
<table>
<tr><td>Inmueble</td><td>{html_lib.escape(((unidad.torre or '') + ' ' + unidad.numero).strip())}</td></tr>
<tr><td>Concepto</td><td>{html_lib.escape(cuota.concepto if cuota else 'Pago')}</td></tr>
<tr><td>Periodo</td><td>{html_lib.escape(cuota.periodo if cuota else '—')}</td></tr>
<tr><td>Monto</td><td>${money(fila.monto)} {html_lib.escape(fila.moneda)}</td></tr>
<tr><td>Pasarela</td><td>{html_lib.escape(fila.proveedor)} · {html_lib.escape(fila.metodo)}</td></tr>
<tr><td>Referencia</td><td>{html_lib.escape(fila.referencia)}</td></tr>
<tr><td>ID proveedor</td><td>{html_lib.escape(fila.referencia_proveedor or '—')}</td></tr>
<tr><td>Tarjeta</td><td>{html_lib.escape((fila.marca_tarjeta or '') + ' •••• ' + (fila.ultimos_cuatro or '')) if fila.marca_tarjeta else 'No aplica'}</td></tr>
<tr><td>Estado</td><td>APROBADO · conciliado {'sí' if fila.conciliado else 'no'}</td></tr>
</table><footer>Comprobante generado por IRIS. IRIS no almacena datos completos de la tarjeta. <button onclick="window.print()">Imprimir / Guardar PDF</button></footer></html>"""
    return HTMLResponse(contenido)


@router.get("/resumen")
def resumen_pagos(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    admin_only(user)
    ids = [conjunto_id] if conjunto_id and can_access_set(db, user, conjunto_id) else sorted(
        {row[0] for row in db.query(models.ConjuntoMembership.conjunto_id).filter_by(usuario_id=user.id, rol="admin").all()} | ({c.id for c in db.query(models.Conjunto.id).all()} if user.es_super_admin else set())
    )
    if not ids:
        return {"aprobadas": 0, "aprobadas_monto": "0.00", "pendientes": 0, "declinadas": 0, "sin_conciliar": 0, "proveedor": None}
    filas = db.query(models_v3.TransaccionPago).filter(models_v3.TransaccionPago.conjunto_id.in_(ids)).all()
    aprobadas = [f for f in filas if f.estado == "aprobada"]
    config = _config_publica(db.query(models_v3.ConfigPasarela).filter_by(conjunto_id=ids[0]).first(), ids[0])
    return {
        "aprobadas": len(aprobadas),
        "aprobadas_monto": str(sum((dec(f.monto) for f in aprobadas), Decimal("0"))),
        "pendientes": len([f for f in filas if f.estado in ("iniciada", "pendiente")]),
        "declinadas": len([f for f in filas if f.estado in ("declinada", "error")]),
        "sin_conciliar": len([f for f in aprobadas if not f.conciliado]),
        "proveedor": config.get("proveedor"),
        "configurada": config.get("configurada"),
    }


@router.get("/eventos")
def listar_eventos(conjunto_id: int, limit: int = 50, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    require_admin_set(db, user, conjunto_id)
    filas = db.query(models_v3.EventoPasarela).filter_by(conjunto_id=conjunto_id).order_by(models_v3.EventoPasarela.id.desc()).limit(max(1, min(limit, 200))).all()
    return [model_data(f) for f in filas]


@router.delete("/config/{conjunto_id}", status_code=204)
def borrar_config(conjunto_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    require_admin_set(db, user, conjunto_id)
    exigir_2fa_admin(db, user, otp)
    fila = db.query(models_v3.ConfigPasarela).filter_by(conjunto_id=conjunto_id).first()
    if fila:
        db.delete(fila)
        db.commit()
    return Response(status_code=204)
