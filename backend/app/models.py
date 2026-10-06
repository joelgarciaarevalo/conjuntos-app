from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, Text, Enum, ForeignKey, DECIMAL, Time, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.database import Base
import enum
from datetime import datetime
from zoneinfo import ZoneInfo


def ahora_local():
    return datetime.now(ZoneInfo("America/Bogota")).replace(tzinfo=None)


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
    rol = Column(String(20), nullable=False, default="residente")  # residente | portero | admin | contador
    email_verificado = Column(Boolean, nullable=False, default=True)
    cambio_password_requerido = Column(Boolean, nullable=False, default=False)


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
    inquilino_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
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
    hora_apertura = Column(String(5), nullable=False, default="06:00")
    hora_cierre = Column(String(5), nullable=False, default="22:00")
    duracion_max_minutos = Column(Integer, nullable=False, default=240)
    max_dias_anticipacion = Column(Integer, nullable=False, default=30)
    max_reservas_dia_inmueble = Column(Integer, nullable=False, default=2)
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


class Notificacion(Base):
    __tablename__ = "notificaciones"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    titulo = Column(String(160), nullable=False)
    mensaje = Column(Text, nullable=False)
    leida = Column(Boolean, nullable=False, default=False)
    creada_en = Column(DateTime, nullable=False, default=ahora_local)


class Comunicado(Base):
    __tablename__ = "comunicados"
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    titulo = Column(String(160), nullable=False)
    contenido = Column(Text, nullable=False)
    publicado = Column(Boolean, nullable=False, default=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)
    adjunto_url = Column(String(500), nullable=True)


class Cuota(Base):
    __tablename__ = "cuotas"
    id = Column(Integer, primary_key=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False, index=True)
    concepto = Column(String(160), nullable=False)
    periodo = Column(String(20), nullable=False)
    monto = Column(DECIMAL(12, 2), nullable=False)
    fecha_vencimiento = Column(Date, nullable=False)
    estado = Column(String(20), nullable=False, default="pendiente")  # pendiente | pagada
    pagada_en = Column(DateTime, nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)


class Paquete(Base):
    __tablename__ = "paquetes"
    id = Column(Integer, primary_key=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False, index=True)
    transportadora = Column(String(100), nullable=True)
    descripcion = Column(String(255), nullable=False)
    recibido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    recibido_en = Column(DateTime, nullable=False, default=ahora_local)
    retirado = Column(Boolean, nullable=False, default=False)
    retirado_por = Column(String(120), nullable=True)
    retirado_en = Column(DateTime, nullable=True)
    foto_url = Column(String(500), nullable=True)
    codigo_retiro_hash = Column(String(64), nullable=True)


class Parqueadero(Base):
    __tablename__ = "parqueaderos"
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=True, index=True)
    identificador = Column(String(40), nullable=False)
    tipo = Column(String(30), nullable=False, default="privado")
    placa = Column(String(20), nullable=True)
    tarifa_mensual = Column(DECIMAL(12, 2), nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True)


class ConjuntoMembership(Base):
    __tablename__ = "conjunto_memberships"
    __table_args__ = (UniqueConstraint("conjunto_id", "usuario_id", "rol", name="uq_membership_set_user_role"),)
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    rol = Column(String(20), nullable=False)  # admin | portero | contador
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class PasswordToken(Base):
    __tablename__ = "password_tokens"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    proposito = Column(String(20), nullable=False)  # reset | verify
    expira_en = Column(DateTime, nullable=False)
    consumido_en = Column(DateTime, nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    endpoint = Column(Text, nullable=False, unique=True)
    p256dh = Column(String(300), nullable=False)
    auth = Column(String(100), nullable=False)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class Pago(Base):
    __tablename__ = "pagos"
    id = Column(Integer, primary_key=True)
    cuota_id = Column(Integer, ForeignKey("cuotas.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False, index=True)
    solicitado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    verificado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    monto = Column(DECIMAL(12, 2), nullable=False)
    metodo = Column(String(30), nullable=False, default="transferencia")
    referencia = Column(String(120), nullable=True)
    estado = Column(String(20), nullable=False, default="pendiente")  # pendiente | verificado | rechazado
    notas = Column(Text, nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)
    verificado_en = Column(DateTime, nullable=True)


class Incidente(Base):
    __tablename__ = "incidentes"
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=True, index=True)
    solicitante_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    asignado_a = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    categoria = Column(String(50), nullable=False, default="mantenimiento")
    titulo = Column(String(160), nullable=False)
    descripcion = Column(Text, nullable=False)
    prioridad = Column(String(20), nullable=False, default="media")
    estado = Column(String(20), nullable=False, default="abierto")
    foto_url = Column(String(500), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_local, onupdate=ahora_local)


class ContactoEmergencia(Base):
    __tablename__ = "contactos_emergencia"
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    nombre = Column(String(120), nullable=False)
    telefono = Column(String(30), nullable=False)
    parentesco = Column(String(60), nullable=True)
    visible = Column(Boolean, nullable=False, default=False)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class ComunicadoLectura(Base):
    __tablename__ = "comunicado_lecturas"
    id = Column(Integer, primary_key=True)
    comunicado_id = Column(Integer, ForeignKey("comunicados.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    leido_en = Column(DateTime, nullable=False, default=ahora_local)
    __table_args__ = (UniqueConstraint("comunicado_id", "usuario_id", name="uq_comunicado_lectura"),)


class BloqueoReserva(Base):
    __tablename__ = "bloqueos_reserva"
    id = Column(Integer, primary_key=True)
    zona_id = Column(Integer, ForeignKey("zonas_comunes.id"), nullable=False, index=True)
    fecha_inicio = Column(DateTime, nullable=False)
    fecha_fin = Column(DateTime, nullable=False)
    motivo = Column(String(255), nullable=False)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class Auditoria(Base):
    __tablename__ = "auditoria"
    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    email_usuario = Column(String(120), nullable=True)
    accion = Column(String(20), nullable=False)
    ruta = Column(String(255), nullable=False)
    metodo = Column(String(10), nullable=False)
    codigo_http = Column(Integer, nullable=False)
    ip = Column(String(64), nullable=True)
    agente = Column(String(255), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)


Index("ix_incidente_set_status", Incidente.conjunto_id, Incidente.estado)
