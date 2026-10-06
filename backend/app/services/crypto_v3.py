"""Cifrado de secretos (llaves de pasarela) y enmascarado de datos personales.

Las llaves privadas de la pasarela se cifran en reposo con Fernet usando una
clave derivada de SECRET_KEY. IRIS nunca devuelve el secreto completo.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re

from cryptography.fernet import Fernet, InvalidToken

from app.dependencies import SECRET_KEY

_fernet: Fernet | None = None


def _key() -> bytes:
    salt = os.getenv("IRIS_ENCRYPTION_SALT", "iris-v3-secretos")
    derived = hashlib.pbkdf2_hmac("sha256", SECRET_KEY.encode(), salt.encode(), 120_000, dklen=32)
    return base64.urlsafe_b64encode(derived)


def _cipher() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_key())
    return _fernet


def cifrar(valor: str | None) -> str | None:
    if valor is None or valor == "":
        return None
    return _cipher().encrypt(valor.encode()).decode()


def descifrar(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _cipher().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def enmascarar(valor: str | None) -> str | None:
    """Devuelve una vista segura de un secreto: 4 primeros + últimos 2."""
    if not valor:
        return None
    if len(valor) <= 8:
        return "*" * len(valor)
    return f"{valor[:4]}…{valor[-2:]}"


def mask_phone(phone: str | None) -> str | None:
    """Enmascara un teléfono conservando indicativo y últimos 2 dígitos."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 4:
        return "*" * len(digits)
    return f"{digits[:2]}{'*' * (len(digits) - 4)}{digits[-2:]}"


def hash_valor(valor: str) -> str:
    return hmac.new(SECRET_KEY.encode(), valor.encode(), hashlib.sha256).hexdigest()


PAN_PATTERN = re.compile(r"(?:\d[ -]?){12,19}")


def contiene_numero_tarjeta(payload) -> bool:
    """Detecta si un payload trae un PAN (número de tarjeta) para rechazarlo.

    IRIS nunca debe recibir ni almacenar números de tarjeta: el navegador los
    tokeniza directamente con la pasarela y sólo envía el token.
    """
    if payload is None:
        return False
    if isinstance(payload, dict):
        return any(contiene_numero_tarjeta(v) for v in payload.values())
    if isinstance(payload, (list, tuple)):
        return any(contiene_numero_tarjeta(v) for v in payload)
    if not isinstance(payload, str):
        return False
    if not PAN_PATTERN.fullmatch(payload.strip().replace(" ", "")):
        return False
    digits = re.sub(r"\D", "", payload)
    if not 13 <= len(digits) <= 19:
        return False
    # Validación Luhn: sólo se considera PAN si además cumple el algoritmo.
    total, par = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if par:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        par = not par
    return total % 10 == 0


CAMPOS_PROHIBIDOS = {"cvv", "cvc", "cvv2", "codigo_seguridad", "pin", "numero_tarjeta", "card_number", "pan", "track1", "track2"}


def detectar_campos_prohibidos(payload) -> list[str]:
    encontrados: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in CAMPOS_PROHIBIDOS:
                encontrados.append(str(key))
            encontrados.extend(detectar_campos_prohibidos(value))
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            encontrados.extend(detectar_campos_prohibidos(item))
    return sorted(set(encontrados))


def resumen_seguro(payload) -> str:
    """Resumen JSON sin datos sensibles para auditar una transacción."""
    def clean(value, depth=0):
        if depth > 6:
            return "…"
        if isinstance(value, dict):
            return {k: ("***" if str(k).lower() in CAMPOS_PROHIBIDOS else clean(v, depth + 1)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v, depth + 1) for v in value]
        if isinstance(value, str) and contiene_numero_tarjeta(value):
            return "***"
        return value

    return json.dumps(clean(payload), ensure_ascii=False)[:4000]