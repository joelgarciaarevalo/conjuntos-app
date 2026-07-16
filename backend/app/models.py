from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, Text, Enum, ForeignKey, DECIMAL
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class EstadoInmueble(str, enum.Enum):
    ocupado = "ocupado"
    desocupado = "desocupado"
    en_venta = "en_venta"

class EstadoReserva(str, enum.Enum):
    pendiente = "pendiente"
    aprobada = "aprobada"
    rechazada = "rechazada"
    cancelada = "cancelada"

class EstadoPQRS(str, enum.Enum):
    radicado = "radicado"
    en_proceso = "en_proceso"
    resuelto = "resuelto"

class TipoPQRS(str, enum.Enum):
    peticion = "peticion"
    queja = "queja"
    reclamo = "reclamo"
    sugerencia = "sugerencia"

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombre_completo = Column(String(100), nullable=False)
    cedula = Column(String(20), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    telefono = Column(String(20), nullable=True)
    es_super_admin = Column(Boolean, default=False)

class Conjunto(Base):
    __tablename__ = "conjuntos"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    nit = Column(String(100), nullable=False)
    direccion = Column(String(255), nullable=False)

    inmuebles = relationship("Inmueble", back_populates="conjunto")
    zonas_comunes = relationship("ZonaComun", back_populates="conjunto")

class AdministradorConjunto(Base):
    __tablename__ = "administradores_conjunto"
    id = Column(Integer, primary_key=True, index=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_nombramiento = Column(Date, nullable=False)

class Inmueble(Base):
    __tablename__ = "inmuebles"
    id = Column(Integer, primary_key=True, index=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False)
    torre = Column(String(50), nullable=True)
    numero = Column(String(20), nullable=False)
    propietario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    inquilino_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    estado = Column(Enum(EstadoInmueble), default=EstadoInmueble.desocupado)

    conjunto = relationship("Conjunto", back_populates="inmuebles")
    propietario = relationship("Usuario", foreign_keys=[propietario_id])
    inquilino = relationship("Usuario", foreign_keys=[inquilino_id])

class ZonaComun(Base):
    __tablename__ = "zonas_comunes"
    id = Column(Integer, primary_key=True, index=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False)
    nombre = Column(String(100), nullable=False)
    requiere_aprobacion = Column(Boolean, default=True)

    conjunto = relationship("Conjunto", back_populates="zonas_comunes")

class Reserva(Base):
    __tablename__ = "reservas"
    id = Column(Integer, primary_key=True, index=True)
    zona_id = Column(Integer, ForeignKey("zonas_comunes.id"), nullable=False)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False)
    solicitante_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_inicio = Column(DateTime, nullable=False)
    fecha_fin = Column(DateTime, nullable=False)
    estado = Column(Enum(EstadoReserva), default=EstadoReserva.pendiente)

class PQRS(Base):
    __tablename__ = "pqrs"
    id = Column(Integer, primary_key=True, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False)
    solicitante_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tipo = Column(Enum(TipoPQRS), nullable=False)
    descripcion = Column(Text, nullable=False)
    estado = Column(Enum(EstadoPQRS), default=EstadoPQRS.radicado)
    fecha_radicacion = Column(DateTime, nullable=False)
    respuesta_admin = Column(Text, nullable=True)