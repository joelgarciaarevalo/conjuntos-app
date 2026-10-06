"""Pasarela de pagos para Colombia.

Proveedores soportados:
- ``simulado`` : pasarela local determinista. Permite operar y probar todo el
  flujo (tokenización, cobro, webhook y conciliación) sin credenciales reales.
- ``wompi``    : pasarela colombiana (tarjetas tokenizadas, PSE y Nequi).
- ``personalizado`` : REST genérico configurable para otros proveedores.

Regla de oro: el número de tarjeta y el CVV se capturan y tokenizan en el
navegador con el SDK del proveedor; IRIS sólo recibe el token de un solo uso y
guarda marca + últimos cuatro dígitos.
"""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_HALF_UP

log = logging.getLogger("iris.pagos")

PROVEEDORES = {
    "simulado": {
        "nombre": "Pasarela simulada (sandbox local)",
        "pais": "CO",
        "metodos": ["tarjeta", "pse", "nequi"],
        "sandbox": "https://sandbox.local/iris/pagos",
        "produccion": "https://api.local/iris/pagos",
        "tokenizacion": "local",
    },
    "wompi": {
        "nombre": "Wompi (Bancolombia)",
        "pais": "CO",
        "metodos": ["tarjeta", "pse", "nequi", "bancolombia"],
        "sandbox": "https://sandbox.wompi.co/v1",
        "produccion": "https://production.wompi.co/v1",
        "tokenizacion": "https://checkout.wompi.co/widget.js",
    },
    "personalizado": {
        "nombre": "Pasarela REST personalizada",
        "pais": "CO",
        "metodos": ["tarjeta"],
        "sandbox": "",
        "produccion": "",
        "tokenizacion": "manual",
    },
}

METODOS_MAP = {
    "tarjeta": "CARD",
    "pse": "PSE",
    "nequi": "NEQUI",
    "bancolombia": "BANCOLOMBIA_TRANSFER",
}


def proveedores_disponibles() -> list[dict]:
    return [{"codigo": code, **meta} for code, meta in PROVEEDORES.items()]


def base_url(proveedor: str, modo: str) -> str:
    meta = PROVEEDORES.get(proveedor) or PROVEEDORES["simulado"]
    return meta["produccion"] if modo == "produccion" else meta["sandbox"]


def centavos(monto) -> int:
    return int((Decimal(str(monto)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def firma_integridad(secreto: str, referencia: str, monto_centavos: int, moneda: str = "COP", expiracion: str | None = None, timestamp: str | None = None) -> str:
    """Firma de integridad: SHA256 de la concatenación de valores + secreto."""
    partes = [referencia, str(monto_centavos), moneda]
    if expiracion:
        partes.append(str(expiracion))
    if timestamp:
        partes.append(str(timestamp))
    partes.append(secreto or "")
    return hashlib.sha256("".join(partes).encode()).hexdigest()


def firma_evento(secreto: str, propiedades: dict, propiedades_orden: list[str]) -> str:
    """Checksum de un evento/webhook: SHA256 de los valores en orden + secreto de eventos."""
    partes = [str(propiedades.get(prop, "")) for prop in propiedades_orden]
    partes.append(secreto or "")
    return hashlib.sha256("".join(partes).encode()).hexdigest()


def verificar_checksum(recibido: str | None, esperado: str) -> bool:
    if not recibido:
        return False
    return hashlib.sha256(str(recibido).lower().encode()).hexdigest() != "" and str(recibido).lower() == esperado.lower()


def _http_json(url: str, payload: dict | None = None, headers: dict | None = None, method: str = "POST", timeout: int = 20) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:  # pragma: no cover - depende de red real
        detalle = exc.read().decode(errors="replace")[:500]
        raise GatewayError(f"El proveedor respondió HTTP {exc.code}: {detalle}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover
        raise GatewayError(f"No fue posible contactar la pasarela: {exc.reason}") from exc


class GatewayError(RuntimeError):
    pass


def _token_simulado(token: str) -> tuple[str, str]:
    """Deriva marca y últimos cuatro dígitos de un token simulado."""
    marca = "VISA" if token.lower().startswith("tok_visa") else "MASTERCARD" if token.lower().startswith("tok_mc") else "TARJETA"
    digitos = "".join(ch for ch in token if ch.isdigit())
    ultimos = (digitos[-4:] if len(digitos) >= 4 else "4242")
    return marca, ultimos


def cobrar(config: dict, *, referencia: str, monto, metodo: str, token: str | None = None,
           correo: str | None = None, descripcion: str | None = None,
           documento: str | None = None, tipo_persona: str | None = None,
           banco: str | None = None, telefono: str | None = None,
           cuotas: int = 1, expiracion: str | None = None) -> dict:
    """Ejecuta el cobro en el proveedor. Devuelve un resultado normalizado."""
    proveedor = (config or {}).get("proveedor", "simulado")
    modo = (config or {}).get("modo", "sandbox")
    monto_centavos = centavos(monto)
    moneda = (config or {}).get("moneda", "COP")

    if metodo not in PROVEEDORES.get(proveedor, PROVEEDORES["simulado"])["metodos"]:
        raise GatewayError(f"El proveedor {proveedor} no admite el método {metodo}")

    if proveedor == "simulado":
        return _cobro_simulado(referencia, monto_centavos, metodo, token, expiracion)

    if proveedor == "wompi":
        return _cobro_wompi(config, referencia, monto_centavos, moneda, metodo, token, correo, descripcion, documento, tipo_persona, banco, telefono, cuotas, expiracion)

    return _cobro_generico(config, referencia, monto_centavos, moneda, metodo, token, correo, descripcion)


def _cobro_simulado(referencia: str, monto_centavos: int, metodo: str, token: str | None, expiracion: str | None) -> dict:
    """Pasarela local: aprueba salvo tokens de prueba explícitos.

    Reglas deterministas para poder probar todos los caminos:
    - token que contiene 'rechaza' -> DECLINED
    - token que contiene 'error'   -> ERROR
    - token que contiene 'pendiente'-> PENDING
    - cualquier otro               -> APPROVED
    """
    if not token:
        raise GatewayError("Falta el token de pago generado por la pasarela")
    marca, ultimos = _token_simulado(token)
    estado = "APPROVED"
    mensaje = "Pago aprobado (pasarela simulada)"
    if "rechaza" in token.lower():
        estado, mensaje = "DECLINED", "Fondos insuficientes (simulado)"
    elif "error" in token.lower():
        estado, mensaje = "ERROR", "Error del proveedor (simulado)"
    elif "pendiente" in token.lower():
        estado, mensaje = "PENDING", "Pago en estudio (simulado)"
    if metodo != "tarjeta":
        marca, ultimos = None, None
    return {
        "estado_proveedor": estado,
        "referencia_proveedor": f"SIM-{referencia}",
        "mensaje": mensaje,
        "marca_tarjeta": marca,
        "ultimos_cuatro": ultimos,
        "payload": {"proveedor": "simulado", "metodo": metodo, "estado": estado, "referencia": referencia},
        "simulado": True,
    }


def _cobro_wompi(config, referencia, monto_centavos, moneda, metodo, token, correo, descripcion, documento, tipo_persona, banco, telefono, cuotas, expiracion) -> dict:
    privada = config.get("private_key")
    publica = config.get("public_key")
    if not privada or not publica:
        raise GatewayError("Configura la llave pública y privada de Wompi antes de cobrar")
    acceptance = _http_json(f"{base_url('wompi', config.get('modo', 'sandbox'))}/merchants/{publica}", method="GET")
    acceptance_token = (((acceptance or {}).get("data") or {}).get("presigned_acceptance") or {}).get("acceptance_token")
    if not acceptance_token:
        raise GatewayError("No se obtuvo el token de aceptación de Wompi")

    metodo_wompi = METODOS_MAP.get(metodo, "CARD")
    payment_method: dict = {"type": metodo_wompi}
    if metodo == "tarjeta":
        payment_method.update({"token": token, "installments": max(1, int(cuotas or 1))})
    elif metodo == "pse":
        payment_method.update({"user_type": (tipo_persona or "0"), "user_legal_id_type": "CC", "user_legal_id": documento or "", "financial_institution_code": banco or "", "payment_description": descripcion or referencia})
    elif metodo == "nequi":
        payment_method.update({"phone_number": telefono or ""})
    elif metodo == "bancolombia":
        payment_method.update({"user_type": (tipo_persona or "0"), "user_legal_id_type": "CC", "user_legal_id": documento or ""})

    body = {
        "acceptance_token": acceptance_token,
        "amount_in_cents": monto_centavos,
        "currency": moneda,
        "customer_email": correo or "sin-correo@iris.local",
        "reference": referencia,
        "payment_method": payment_method,
        "redirect_url": config.get("redirect_url"),
    }
    integridad = config.get("integrity_secret")
    if integridad:
        body["signature"] = {
            "properties": ["reference", "amount_in_cents", "currency", "expiration_time"],
            "checksum": firma_integridad(integridad, referencia, monto_centavos, moneda, expiracion),
        }
    if expiracion:
        body["expiration_time"] = expiracion

    respuesta = _http_json(f"{base_url('wompi', config.get('modo', 'sandbox'))}/transactions", body, headers={"Authorization": f"Bearer {privada}"})
    data = (respuesta or {}).get("data") or {}
    estado = (data.get("status") or "PENDING").upper()
    extra = data.get("payment_method") or {}
    return {
        "estado_proveedor": estado,
        "referencia_proveedor": data.get("id") or referencia,
        "mensaje": data.get("status_message") or estado,
        "marca_tarjeta": (extra.get("extra") or {}).get("brand") or extra.get("brand"),
        "ultimos_cuatro": str((extra.get("extra") or {}).get("last_four") or extra.get("last_four") or "")[-4:] or None,
        "payload": {k: v for k, v in data.items() if k not in ("payment_method",)},
        "simulado": False,
    }


def _cobro_generico(config, referencia, monto_centavos, moneda, metodo, token, correo, descripcion) -> dict:
    url = config.get("url_transaccion")
    if not url:
        raise GatewayError("Configura la URL de transacción del proveedor personalizado")
    respuesta = _http_json(url, {
        "reference": referencia, "amount_in_cents": monto_centavos, "currency": moneda,
        "payment_method": {"type": METODOS_MAP.get(metodo, "CARD"), "token": token},
        "customer_email": correo, "description": descripcion,
    }, headers={"Authorization": f"Bearer {config.get('private_key') or ''}"})
    estado = str(respuesta.get("status") or respuesta.get("estado") or "PENDING").upper()
    return {
        "estado_proveedor": estado,
        "referencia_proveedor": str(respuesta.get("id") or respuesta.get("transaction_id") or referencia),
        "mensaje": str(respuesta.get("message") or estado),
        "marca_tarjeta": respuesta.get("brand"),
        "ultimos_cuatro": str(respuesta.get("last_four") or "")[-4:] or None,
        "payload": respuesta,
        "simulado": False,
    }


def consultar(config: dict, referencia_proveedor: str) -> dict:
    proveedor = (config or {}).get("proveedor", "simulado")
    if proveedor == "simulado":
        return {"estado_proveedor": "APPROVED", "mensaje": "Consulta simulada", "payload": {"id": referencia_proveedor}}
    if proveedor == "wompi":
        data = _http_json(f"{base_url('wompi', config.get('modo', 'sandbox'))}/transactions/{urllib.parse.quote(referencia_proveedor)}",
                          headers={"Authorization": f"Bearer {config.get('private_key') or ''}"}, method="GET")
        registro = (data or {}).get("data") or {}
        return {"estado_proveedor": (registro.get("status") or "PENDING").upper(), "mensaje": registro.get("status_message"), "payload": registro}
    raise GatewayError("El proveedor configurado no permite consultar transacciones")


def normalizar_estado(estado_proveedor: str | None) -> str:
    """Traduce el estado del proveedor al estado interno de IRIS."""
    valor = (estado_proveedor or "").upper()
    if valor in ("APPROVED", "APROBADA", "SUCCESS", "SUCCEEDED", "PAID"):
        return "aprobada"
    if valor in ("DECLINED", "DECLINADA", "REJECTED", "FAILED", "VOIDED", "ANULADA"):
        return "declinada"
    if valor in ("ERROR", "ERROR_PAYMENT"):
        return "error"
    if valor in ("EXPIRED", "EXPIRADA"):
        return "expirada"
    return "pendiente"


def propiedades_evento_wompi() -> list[str]:
    """Orden documentado de propiedades para firmar eventos de Wompi."""
    return ["transaction.id", "transaction.status", "transaction.amount_in_cents"]


def resolver_propiedades(payload: dict, propiedades: list[str]):
    actual = payload
    for parte in propiedades:
        if isinstance(actual, dict):
            actual = actual.get(parte)
        else:
            return None
    return actual


def verificar_evento_wompi(secreto: str, payload: dict) -> bool:
    """Verifica el checksum de un evento de Wompi.

    Se aceptan los dos órdenes documentados por Wompi para el arreglo
    ``signature.properties`` del evento.
    """
    signature = (payload or {}).get("signature") or {}
    checksum = signature.get("checksum")
    propiedades = signature.get("properties") or propiedades_evento_wompi()
    if not checksum:
        return False
    valores = [resolver_propiedades(payload, prop) for prop in propiedades]
    calculado = hashlib.sha256(("".join(str(v or "") for v in valores) + (secreto or "")).encode()).hexdigest()
    return calculado.lower() == str(checksum).lower()