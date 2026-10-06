"""TOTP (RFC 6238) sin dependencias externas, para el segundo factor (2FA).

Implementación estándar HMAC-SHA1, ventana de 30 segundos, 6 dígitos y
tolerancia de ±1 intervalo para compensar relojes desfasados.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
PERIOD = 30
WINDOW = 1
ISSUER = "IRIS Conjuntos"


def generar_secreto(longitud: int = 20) -> str:
    """Secreto en base32 sin relleno (compatible con Google/Authy)."""
    raw = secrets.token_bytes(longitud)
    return base64.b32encode(raw).decode().rstrip("=")


def _normalizar(secreto: str) -> bytes:
    limpio = secreto.strip().replace(" ", "").upper()
    padding = (-len(limpio)) % 8
    return base64.b32decode(limpio + "=" * padding, casefold=True)


def codigo_en(secreto: str, momento: float | None = None, offset: int = 0) -> str:
    if not secreto:
        return ""
    contador = int((momento if momento is not None else time.time()) // PERIOD) + offset
    digest = hmac.new(_normalizar(secreto), struct.pack(">Q", contador), hashlib.sha1).digest()
    inicio = digest[-1] & 0x0F
    valor = struct.unpack(">I", digest[inicio:inicio + 4])[0] & 0x7FFFFFFF
    return str(valor % (10 ** DIGITS)).zfill(DIGITS)


def verificar(secreto: str, codigo: str, momento: float | None = None) -> bool:
    if not secreto:
        return False
    limpio = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    if len(limpio) != DIGITS:
        return False
    ahora = momento if momento is not None else time.time()
    return any(hmac.compare_digest(codigo_en(secreto, ahora, offset), limpio) for offset in range(-WINDOW, WINDOW + 1))


def uri_otpauth(secreto: str, email: str) -> str:
    label = quote(f"{ISSUER}:{email}")
    return f"otpauth://totp/{label}?secret={secreto}&issuer={quote(ISSUER)}&digits={DIGITS}&period={PERIOD}"


def generar_codigos_recuperacion(cantidad: int = 8) -> list[str]:
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(cantidad)]