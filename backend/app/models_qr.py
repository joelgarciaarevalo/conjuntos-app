from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey

from app.database import Base
from app import models  # noqa: F401  (garantiza que usuarios/inmuebles/reservas existan antes de crear las tablas)


def ahora_local():
    return datetime.now(ZoneInfo("America/Bogota")).replace(tzinfo=None)


class CodigoQR(Base):
    """Código QR dinámico: el contenido del QR es solo un token; la validez se decide en el servidor."""
    __tablename__ = "codigos_qr"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, index=True, nullable=False)
    tipo = Column(String(20), nullable=False)  # visita | reserva | residente
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=True)
    residente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    reserva_id = Column(Integer, ForeignKey("reservas.id"), nullable=True)
    visitante_nombre = Column(String(100), nullable=True)
    visitante_documento = Column(String(30), nullable=True)
    valido_desde = Column(DateTime, nullable=False)
    valido_hasta = Column(DateTime, nullable=True)   # None = sin vencimiento
    usos_maximos = Column(Integer, nullable=True)    # None = ilimitado
    usos_actuales = Column(Integer, nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class AccesoQR(Base):
    """Bitácora de cada intento de validación en portería."""
    __tablename__ = "accesos_qr"

    id = Column(Integer, primary_key=True, index=True)
    codigo_id = Column(Integer, ForeignKey("codigos_qr.id"), nullable=True)  # None = código no reconocido
    fecha = Column(DateTime, nullable=False, default=ahora_local)
    resultado = Column(String(20), nullable=False)  # permitido | denegado
    motivo = Column(String(255), nullable=False)
    validado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
