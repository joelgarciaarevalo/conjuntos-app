"""Modelos complementarios para el módulo profesional del contador.

Se añaden en tablas nuevas para mantener intacto el esquema financiero legado.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import Boolean, Column, Date, DateTime, DECIMAL, ForeignKey, Integer, String, Text, UniqueConstraint
from app.database import Base


def ahora_contable():
    return datetime.now(ZoneInfo("America/Bogota")).replace(tzinfo=None)


class CuentaPUC(Base):
    __tablename__ = "v3_contador_cuentas_puc"
    __table_args__ = (UniqueConstraint("conjunto_id", "codigo", name="uq_contador_puc_conjunto_codigo"),)
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    codigo = Column(String(20), nullable=False)
    nombre = Column(String(160), nullable=False)
    clase = Column(String(20), nullable=False)  # activo, pasivo, patrimonio, ingreso, gasto
    naturaleza = Column(String(10), nullable=False)  # debito | credito
    activa = Column(Boolean, nullable=False, default=True)
    creada_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creada_en = Column(DateTime, nullable=False, default=ahora_contable)


class AsientoContable(Base):
    __tablename__ = "v3_contador_asientos"
    __table_args__ = (UniqueConstraint("conjunto_id", "origen", "origen_id", name="uq_contador_asiento_origen"),)
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    numero = Column(String(40), nullable=False)
    fecha = Column(Date, nullable=False, index=True)
    descripcion = Column(String(255), nullable=False)
    origen = Column(String(40), nullable=False, default="manual")
    origen_id = Column(String(80), nullable=True)
    estado = Column(String(20), nullable=False, default="contabilizado")
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_contable)


class LineaAsientoContable(Base):
    __tablename__ = "v3_contador_lineas_asiento"
    id = Column(Integer, primary_key=True)
    asiento_id = Column(Integer, ForeignKey("v3_contador_asientos.id", ondelete="CASCADE"), nullable=False, index=True)
    cuenta_id = Column(Integer, ForeignKey("v3_contador_cuentas_puc.id"), nullable=False, index=True)
    descripcion = Column(String(255), nullable=True)
    debito = Column(DECIMAL(14, 2), nullable=False, default=0)
    credito = Column(DECIMAL(14, 2), nullable=False, default=0)


class CuentaPorPagar(Base):
    __tablename__ = "v3_contador_cuentas_por_pagar"
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    proveedor_id = Column(Integer, ForeignKey("v3_proveedores.id"), nullable=True, index=True)
    proveedor = Column(String(160), nullable=False)
    documento = Column(String(80), nullable=False)
    concepto = Column(String(255), nullable=False)
    fecha_documento = Column(Date, nullable=False)
    fecha_vencimiento = Column(Date, nullable=False, index=True)
    monto = Column(DECIMAL(14, 2), nullable=False)
    estado = Column(String(20), nullable=False, default="pendiente")  # pendiente | pagada | anulada
    pagada_en = Column(DateTime, nullable=True)
    notas = Column(Text, nullable=True)
    creada_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creada_en = Column(DateTime, nullable=False, default=ahora_contable)


class FondoReserva(Base):
    __tablename__ = "v3_contador_fondos_reserva"
    __table_args__ = (UniqueConstraint("conjunto_id", "nombre", name="uq_contador_fondo_conjunto_nombre"),)
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    nombre = Column(String(120), nullable=False)
    porcentaje = Column(DECIMAL(7, 4), nullable=False, default=1)
    saldo = Column(DECIMAL(14, 2), nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_contable, onupdate=ahora_contable)


class DocumentoContable(Base):
    __tablename__ = "v3_contador_documentos"
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    tipo = Column(String(50), nullable=False)
    numero = Column(String(100), nullable=False)
    fecha = Column(Date, nullable=False, index=True)
    tercero = Column(String(160), nullable=True)
    descripcion = Column(String(255), nullable=False)
    valor = Column(DECIMAL(14, 2), nullable=False, default=0)
    estado = Column(String(30), nullable=False, default="registrado")
    archivo_url = Column(String(500), nullable=True)
    metadatos = Column(Text, nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_contable)
