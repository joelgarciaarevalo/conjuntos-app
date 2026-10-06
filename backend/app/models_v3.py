"""Modelos de datos de IRIS 3.0.

Amplía el modelo original (models.py) SIN modificarlo. Todas las tablas son
nuevas y aditivas, de modo que una instalación previa puede migrarse sin
pérdida de datos (ver app/migrate_v3.py).

Convenios:
- Las tarjetas NUNCA se almacenan en IRIS: solo se guardan los últimos cuatro
  dígitos, la marca y las referencias/token del proveedor de pagos.
- Los campos tipo "lista/objeto" se guardan como texto JSON para mantener
  portabilidad entre SQLite, PostgreSQL y MySQL.
- Las marcas de tiempo de negocio usan America/Bogota (ahora_local).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    DECIMAL,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.database import Base
from app import models  # noqa: F401  garantiza el orden de creación de tablas


def ahora_local():
    return datetime.now(ZoneInfo("America/Bogota")).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# 1. Pagos en línea con pasarela colombiana + conciliación automática
# ---------------------------------------------------------------------------
class ConfigPasarela(Base):
    """Credenciales por conjunto del proveedor de pagos (Wompi, PayU, ePayco, Mercado Pago o simulado).

    Las llaves privadas se guardan cifradas con la clave de la aplicación y
    nunca se devuelven completas por la API.
    """

    __tablename__ = "v3_pasarela_config"
    __table_args__ = (UniqueConstraint("conjunto_id", name="uq_pasarela_conjunto"),)

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    proveedor = Column(String(30), nullable=False, default="simulado")  # simulado | wompi | payu | epayco | mercadopago
    public_key = Column(String(255), nullable=True)
    private_key_cifrada = Column(Text, nullable=True)
    events_secret_cifrado = Column(Text, nullable=True)
    integrity_secret_cifrado = Column(Text, nullable=True)
    merchant_id = Column(String(120), nullable=True)
    modo = Column(String(20), nullable=False, default="sandbox")  # sandbox | produccion
    moneda = Column(String(3), nullable=False, default="COP")
    permite_tarjeta = Column(Boolean, nullable=False, default=True)
    permite_pse = Column(Boolean, nullable=False, default=True)
    permite_nequi = Column(Boolean, nullable=False, default=True)
    activo = Column(Boolean, nullable=False, default=False)
    conciliacion_automatica = Column(Boolean, nullable=False, default=True)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_local, onupdate=ahora_local)


class TransaccionPago(Base):
    """Intento de pago en línea. Reemplaza la captura manual de tarjetas.

    IRIS solo conserva: referencia interna, referencia del proveedor, estado,
    monto y metadatos NO sensibles de la tarjeta (marca y últimos 4 dígitos).
    """

    __tablename__ = "v3_transacciones_pago"

    id = Column(Integer, primary_key=True, index=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False, index=True)
    cuota_id = Column(Integer, ForeignKey("cuotas.id"), nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    proveedor = Column(String(30), nullable=False, default="simulado")
    metodo = Column(String(20), nullable=False, default="tarjeta")  # tarjeta | pse | nequi | bancolombia
    monto = Column(DECIMAL(12, 2), nullable=False)
    moneda = Column(String(3), nullable=False, default="COP")
    referencia = Column(String(64), nullable=False, unique=True, index=True)
    idempotencia = Column(String(64), nullable=False, unique=True, index=True)
    referencia_proveedor = Column(String(120), nullable=True, index=True)
    token_proveedor = Column(String(255), nullable=True)
    estado = Column(String(20), nullable=False, default="iniciada")  # iniciada | pendiente | aprobada | declinada | error | expirada | anulada
    marca_tarjeta = Column(String(30), nullable=True)
    ultimos_cuatro = Column(String(4), nullable=True)
    titular_hash = Column(String(64), nullable=True)
    mensaje = Column(String(255), nullable=True)
    payload_resumen = Column(Text, nullable=True)  # JSON saneado, sin PAN ni CVV
    conciliado = Column(Boolean, nullable=False, default=False)
    conciliado_en = Column(DateTime, nullable=True)
    pago_id = Column(Integer, ForeignKey("pagos.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_local, onupdate=ahora_local)


class EventoPasarela(Base):
    """Bitácora de webhooks/notificaciones recibidas del proveedor."""

    __tablename__ = "v3_eventos_pasarela"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=True, index=True)
    transaccion_id = Column(Integer, ForeignKey("v3_transacciones_pago.id"), nullable=True)
    proveedor = Column(String(30), nullable=False)
    evento = Column(String(60), nullable=False)
    firma_valida = Column(Boolean, nullable=False, default=False)
    estado_proveedor = Column(String(30), nullable=True)
    resumen = Column(Text, nullable=True)
    ip = Column(String(64), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)


class ConciliacionPago(Base):
    """Resultado de la conciliación entre una transacción aprobada y una cuota/recibo."""

    __tablename__ = "v3_conciliaciones_pago"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    # Puede provenir de una transacción de pasarela o de un movimiento bancario conciliado.
    transaccion_id = Column(Integer, ForeignKey("v3_transacciones_pago.id"), nullable=True, index=True)
    cuota_id = Column(Integer, ForeignKey("cuotas.id"), nullable=True)
    pago_id = Column(Integer, ForeignKey("pagos.id"), nullable=True)
    movimiento_id = Column(Integer, ForeignKey("v3_movimientos_bancarios.id"), nullable=True)
    origen = Column(String(20), nullable=False, default="automatica")  # automatica | manual | webhook
    monto = Column(DECIMAL(12, 2), nullable=False)
    diferencia = Column(DECIMAL(12, 2), nullable=False, default=0)
    observacion = Column(String(255), nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)


# ---------------------------------------------------------------------------
# 2. Avisos por WhatsApp / SMS con consentimiento del residente
# ---------------------------------------------------------------------------
class ConsentimientoAviso(Base):
    """Consentimiento explícito del residente para recibir avisos por WhatsApp o SMS."""

    __tablename__ = "v3_consentimientos_aviso"
    __table_args__ = (UniqueConstraint("usuario_id", "canal", name="uq_consentimiento_usuario_canal"),)

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    canal = Column(String(20), nullable=False)  # whatsapp | sms
    telefono = Column(String(30), nullable=False)
    otorgado = Column(Boolean, nullable=False, default=False)
    version_politica = Column(String(20), nullable=False, default="1.0")
    evidencia = Column(String(255), nullable=True)  # texto aceptado / IP / canal de captura
    otorgado_en = Column(DateTime, nullable=True)
    revocado_en = Column(DateTime, nullable=True)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_local, onupdate=ahora_local)


class PlantillaAviso(Base):
    """Plantilla por conjunto y evento para avisos externos."""

    __tablename__ = "v3_plantillas_aviso"
    __table_args__ = (UniqueConstraint("conjunto_id", "evento", name="uq_plantilla_evento"),)

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    evento = Column(String(40), nullable=False)  # aprobacion_reserva | pqrs_respuesta | paquete_recibido | cuota_vencimiento | visita | asamblea | mantenimiento
    titulo = Column(String(120), nullable=False)
    cuerpo = Column(Text, nullable=False)
    canales = Column(String(60), nullable=False, default="whatsapp,sms")
    activo = Column(Boolean, nullable=False, default=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_local, onupdate=ahora_local)


class AvisoEnviado(Base):
    """Bitácora de avisos externos (WhatsApp/SMS) con el teléfono enmascarado."""

    __tablename__ = "v3_avisos_enviados"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    evento = Column(String(40), nullable=False, index=True)
    canal = Column(String(20), nullable=False)
    telefono_enmascarado = Column(String(30), nullable=True)
    mensaje = Column(Text, nullable=True)
    estado = Column(String(30), nullable=False, default="enviado")  # enviado | simulado | fallido | omitido_sin_consentimiento
    proveedor = Column(String(30), nullable=True)
    referencia = Column(String(120), nullable=True)
    detalle = Column(String(255), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)


# ---------------------------------------------------------------------------
# 3. Seguimiento de mantenimiento
# ---------------------------------------------------------------------------
class Proveedor(Base):
    __tablename__ = "v3_proveedores"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    nombre = Column(String(140), nullable=False)
    nit = Column(String(40), nullable=True)
    especialidad = Column(String(80), nullable=True)
    contacto = Column(String(120), nullable=True)
    telefono = Column(String(30), nullable=True)
    email = Column(String(120), nullable=True)
    calificacion = Column(Integer, nullable=True)  # 1..5
    activo = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class OrdenMantenimiento(Base):
    __tablename__ = "v3_ordenes_mantenimiento"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=True, index=True)
    zona_id = Column(Integer, ForeignKey("zonas_comunes.id"), nullable=True)
    incidente_id = Column(Integer, ForeignKey("incidentes.id"), nullable=True)
    titulo = Column(String(160), nullable=False)
    descripcion = Column(Text, nullable=False)
    categoria = Column(String(50), nullable=False, default="mantenimiento")
    prioridad = Column(String(20), nullable=False, default="media")
    estado = Column(String(30), nullable=False, default="abierta")  # abierta | asignada | esperando_cotizacion | en_ejecucion | completada | cancelada
    responsable_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    proveedor_id = Column(Integer, ForeignKey("v3_proveedores.id"), nullable=True)
    fecha_limite = Column(DateTime, nullable=True)
    costo_estimado = Column(DECIMAL(12, 2), nullable=True)
    costo_final = Column(DECIMAL(12, 2), nullable=True)
    cerrada_en = Column(DateTime, nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_local, onupdate=ahora_local)


class CotizacionMantenimiento(Base):
    __tablename__ = "v3_cotizaciones_mantenimiento"

    id = Column(Integer, primary_key=True)
    orden_id = Column(Integer, ForeignKey("v3_ordenes_mantenimiento.id"), nullable=False, index=True)
    proveedor_id = Column(Integer, ForeignKey("v3_proveedores.id"), nullable=True)
    proveedor_nombre = Column(String(140), nullable=True)
    monto = Column(DECIMAL(12, 2), nullable=False)
    descripcion = Column(Text, nullable=True)
    archivo_url = Column(String(500), nullable=True)
    validez_hasta = Column(Date, nullable=True)
    estado = Column(String(20), nullable=False, default="recibida")  # recibida | seleccionada | rechazada
    aprobacion_estado = Column(String(20), nullable=False, default="pendiente")  # pendiente | aprobada | rechazada
    aprobada_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    aprobada_en = Column(DateTime, nullable=True)
    nota_aprobacion = Column(Text, nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class EvidenciaMantenimiento(Base):
    __tablename__ = "v3_evidencias_mantenimiento"

    id = Column(Integer, primary_key=True)
    orden_id = Column(Integer, ForeignKey("v3_ordenes_mantenimiento.id"), nullable=False, index=True)
    url = Column(String(500), nullable=False)
    tipo = Column(String(20), nullable=False, default="foto")  # foto | soporte
    descripcion = Column(String(255), nullable=True)
    subido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class AvanceMantenimiento(Base):
    __tablename__ = "v3_avances_mantenimiento"

    id = Column(Integer, primary_key=True)
    orden_id = Column(Integer, ForeignKey("v3_ordenes_mantenimiento.id"), nullable=False, index=True)
    estado = Column(String(30), nullable=True)
    nota = Column(Text, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


# ---------------------------------------------------------------------------
# 4. Control de visitantes
# ---------------------------------------------------------------------------
class Visitante(Base):
    __tablename__ = "v3_visitantes"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=True, index=True)
    nombre = Column(String(120), nullable=False)
    documento = Column(String(30), nullable=True)
    telefono = Column(String(30), nullable=True)
    placa = Column(String(20), nullable=True)
    tipo = Column(String(20), nullable=False, default="visitante")  # visitante | domiciliario | contratista | familiar
    empresa = Column(String(120), nullable=True)
    notas = Column(String(255), nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class AutorizacionVisita(Base):
    """Autorización previa emitida por el residente (lista de invitados)."""

    __tablename__ = "v3_autorizaciones_visita"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False, index=True)
    visitante_id = Column(Integer, ForeignKey("v3_visitantes.id"), nullable=False, index=True)
    residente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    valido_desde = Column(DateTime, nullable=False)
    valido_hasta = Column(DateTime, nullable=True)
    recurrente = Column(Boolean, nullable=False, default=False)
    dias_semana = Column(String(30), nullable=True)  # "1,2,3" (lun..dom)
    usos_maximos = Column(Integer, nullable=True)
    usos_actuales = Column(Integer, nullable=False, default=0)
    permite_vehiculo = Column(Boolean, nullable=False, default=False)
    estado = Column(String(20), nullable=False, default="activa")  # activa | usada | expirada | cancelada
    pin_hash = Column(String(64), nullable=True)
    observacion = Column(String(255), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class RegistroAcceso(Base):
    """Ingreso/salida de visitantes registrado en portería (autorización desde portería)."""

    __tablename__ = "v3_registros_acceso"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=True, index=True)
    visitante_id = Column(Integer, ForeignKey("v3_visitantes.id"), nullable=True)
    autorizacion_id = Column(Integer, ForeignKey("v3_autorizaciones_visita.id"), nullable=True)
    nombre_visitante = Column(String(120), nullable=False)
    documento = Column(String(30), nullable=True)
    placa = Column(String(20), nullable=True)
    tipo = Column(String(20), nullable=False, default="visitante")
    ingreso_en = Column(DateTime, nullable=False, default=ahora_local, index=True)
    salida_en = Column(DateTime, nullable=True)
    registrado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    autorizado_por_residente = Column(Boolean, nullable=False, default=False)
    alerta_enviada = Column(Boolean, nullable=False, default=False)
    alerta_detalle = Column(String(255), nullable=True)
    observacion = Column(String(255), nullable=True)


# ---------------------------------------------------------------------------
# 5. Seguridad y protección de datos
# ---------------------------------------------------------------------------
class DosFactores(Base):
    __tablename__ = "v3_dos_factores"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, unique=True, index=True)
    secreto = Column(String(64), nullable=False)
    activo = Column(Boolean, nullable=False, default=False)
    confirmado_en = Column(DateTime, nullable=True)
    codigos_recuperacion = Column(Text, nullable=True)  # JSON con hashes de códigos de un solo uso
    ultimo_uso = Column(DateTime, nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class SesionUsuario(Base):
    """Registro de sesiones emitidas (token identificado por jti)."""

    __tablename__ = "v3_sesiones_usuario"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    ip = Column(String(64), nullable=True)
    agente = Column(String(255), nullable=True)
    origen = Column(String(30), nullable=False, default="web")
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)
    ultima_actividad = Column(DateTime, nullable=False, default=ahora_local)
    expira_en = Column(DateTime, nullable=False)
    revocada_en = Column(DateTime, nullable=True)
    motivo_revocacion = Column(String(120), nullable=True)


class IntentoAcceso(Base):
    __tablename__ = "v3_intentos_acceso"

    id = Column(Integer, primary_key=True)
    email = Column(String(120), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    ip = Column(String(64), nullable=True)
    exito = Column(Boolean, nullable=False, default=False)
    motivo = Column(String(80), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)


class PoliticaDatos(Base):
    """Política de retención y privacidad por conjunto (o global si conjunto_id es NULL)."""

    __tablename__ = "v3_politicas_datos"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=True, index=True)
    version = Column(String(20), nullable=False, default="1.0")
    texto_privacidad = Column(Text, nullable=False)
    dias_retencion_auditoria = Column(Integer, nullable=False, default=365)
    dias_retencion_accesos = Column(Integer, nullable=False, default=365)
    dias_retencion_avisos = Column(Integer, nullable=False, default=180)
    dias_retencion_intentos = Column(Integer, nullable=False, default=90)
    dias_retencion_sesiones = Column(Integer, nullable=False, default=30)
    anonimizar_al_purgar = Column(Boolean, nullable=False, default=True)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_local, onupdate=ahora_local)


# ---------------------------------------------------------------------------
# 6. Contabilidad y cartera
# ---------------------------------------------------------------------------
class Egreso(Base):
    __tablename__ = "v3_egresos"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    concepto = Column(String(160), nullable=False)
    categoria = Column(String(60), nullable=False, default="general")
    proveedor_id = Column(Integer, ForeignKey("v3_proveedores.id"), nullable=True)
    monto = Column(DECIMAL(12, 2), nullable=False)
    fecha = Column(Date, nullable=False, index=True)
    soporte_url = Column(String(500), nullable=True)
    notas = Column(String(255), nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class Presupuesto(Base):
    __tablename__ = "v3_presupuestos"
    __table_args__ = (UniqueConstraint("conjunto_id", "periodo", "categoria", name="uq_presupuesto_periodo_categoria"),)

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    periodo = Column(String(20), nullable=False)  # YYYY-MM
    categoria = Column(String(60), nullable=False, default="general")
    monto_presupuestado = Column(DECIMAL(12, 2), nullable=False)
    notas = Column(String(255), nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class ConfigCartera(Base):
    __tablename__ = "v3_config_cartera"
    __table_args__ = (UniqueConstraint("conjunto_id", name="uq_cartera_conjunto"),)

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    tasa_mora_mensual = Column(DECIMAL(6, 4), nullable=False, default=0)     # porcentaje mensual, ej 0.0200 = 2 %
    interes_moratorio_diario = Column(DECIMAL(6, 4), nullable=False, default=0)  # porcentaje diario
    recargo_fijo = Column(DECIMAL(12, 2), nullable=False, default=0)
    dias_gracia = Column(Integer, nullable=False, default=5)
    activo = Column(Boolean, nullable=False, default=False)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_local, onupdate=ahora_local)


class CargoCartera(Base):
    """Intereses, recargos y cobros por uso aplicados a una cuota o reserva."""

    __tablename__ = "v3_cargos_cartera"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False, index=True)
    cuota_id = Column(Integer, ForeignKey("cuotas.id"), nullable=True, index=True)
    reserva_id = Column(Integer, ForeignKey("reservas.id"), nullable=True)
    tipo = Column(String(30), nullable=False, default="interes_mora")  # interes_mora | recargo | cobro_uso | penalizacion
    concepto = Column(String(160), nullable=False)
    base = Column(DECIMAL(12, 2), nullable=False, default=0)
    tasa_aplicada = Column(DECIMAL(6, 4), nullable=True)
    dias_mora = Column(Integer, nullable=True)
    monto = Column(DECIMAL(12, 2), nullable=False)
    periodo = Column(String(20), nullable=True)
    estado = Column(String(20), nullable=False, default="pendiente")  # pendiente | pagado | anulado
    pagado_en = Column(DateTime, nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)


class MovimientoBancario(Base):
    """Extracto bancario importado para conciliación bancaria."""

    __tablename__ = "v3_movimientos_bancarios"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    banco = Column(String(80), nullable=True)
    cuenta = Column(String(60), nullable=True)
    fecha = Column(Date, nullable=False, index=True)
    descripcion = Column(String(255), nullable=False)
    referencia = Column(String(120), nullable=True, index=True)
    debito = Column(DECIMAL(12, 2), nullable=False, default=0)
    credito = Column(DECIMAL(12, 2), nullable=False, default=0)
    conciliado = Column(Boolean, nullable=False, default=False)
    conciliado_en = Column(DateTime, nullable=True)
    cuota_id = Column(Integer, ForeignKey("cuotas.id"), nullable=True)
    transaccion_id = Column(Integer, ForeignKey("v3_transacciones_pago.id"), nullable=True)
    observacion = Column(String(255), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


# ---------------------------------------------------------------------------
# 7. Votaciones y asambleas
# ---------------------------------------------------------------------------
class Asamblea(Base):
    __tablename__ = "v3_asambleas"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=False, index=True)
    titulo = Column(String(160), nullable=False)
    tipo = Column(String(20), nullable=False, default="ordinaria")  # ordinaria | extraordinaria
    modalidad = Column(String(20), nullable=False, default="virtual")  # presencial | virtual | mixta
    lugar = Column(String(255), nullable=True)
    enlace = Column(String(500), nullable=True)
    fecha_convocatoria = Column(DateTime, nullable=False, default=ahora_local)
    fecha_inicio = Column(DateTime, nullable=False)
    fecha_fin = Column(DateTime, nullable=False)
    quorum_requerido = Column(DECIMAL(5, 2), nullable=False, default=50.00)  # porcentaje de unidades
    estado = Column(String(20), nullable=False, default="convocada")  # convocada | en_curso | cerrada | cancelada
    acta = Column(Text, nullable=True)
    acta_generada_en = Column(DateTime, nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class AsistenciaAsamblea(Base):
    __tablename__ = "v3_asistencia_asamblea"
    __table_args__ = (UniqueConstraint("asamblea_id", "inmueble_id", name="uq_asistencia_asamblea_inmueble"),)

    id = Column(Integer, primary_key=True)
    asamblea_id = Column(Integer, ForeignKey("v3_asambleas.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    representado_por = Column(String(120), nullable=True)
    poder = Column(Boolean, nullable=False, default=False)
    registrado_en = Column(DateTime, nullable=False, default=ahora_local)


class Votacion(Base):
    __tablename__ = "v3_votaciones"

    id = Column(Integer, primary_key=True)
    asamblea_id = Column(Integer, ForeignKey("v3_asambleas.id"), nullable=False, index=True)
    titulo = Column(String(200), nullable=False)
    descripcion = Column(Text, nullable=True)
    tipo = Column(String(20), nullable=False, default="si_no")  # si_no | opciones | eleccion
    opciones = Column(Text, nullable=True)  # JSON con lista de opciones
    permite_abstencion = Column(Boolean, nullable=False, default=True)
    mayoria = Column(String(20), nullable=False, default="simple")  # simple | absoluta | calificada
    orden = Column(Integer, nullable=False, default=1)
    estado = Column(String(20), nullable=False, default="abierta")  # abierta | cerrada
    ganador = Column(String(120), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class Voto(Base):
    __tablename__ = "v3_votos"
    __table_args__ = (UniqueConstraint("votacion_id", "inmueble_id", name="uq_voto_votacion_inmueble"),)

    id = Column(Integer, primary_key=True)
    votacion_id = Column(Integer, ForeignKey("v3_votaciones.id"), nullable=False, index=True)
    asamblea_id = Column(Integer, ForeignKey("v3_asambleas.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    opcion = Column(String(120), nullable=False)  # si | no | abstencion | opción elegida
    peso = Column(DECIMAL(10, 4), nullable=False, default=1)
    hash_validacion = Column(String(64), nullable=False)
    emitido_en = Column(DateTime, nullable=False, default=ahora_local)


# ---------------------------------------------------------------------------
# 8. Reservas con reglas avanzadas
# ---------------------------------------------------------------------------
class ReglaZonaReserva(Base):
    __tablename__ = "v3_reglas_zona"
    __table_args__ = (UniqueConstraint("zona_id", name="uq_regla_zona"),)

    id = Column(Integer, primary_key=True)
    zona_id = Column(Integer, ForeignKey("zonas_comunes.id"), nullable=False, index=True)
    cupos_por_franja = Column(Integer, nullable=False, default=1)
    duracion_franja_minutos = Column(Integer, nullable=False, default=60)
    antelacion_minima_horas = Column(Integer, nullable=False, default=0)
    horas_limite_cancelacion = Column(Integer, nullable=False, default=12)
    requiere_pago = Column(Boolean, nullable=False, default=False)
    tarifa_por_uso = Column(DECIMAL(12, 2), nullable=False, default=0)
    lista_espera_activa = Column(Boolean, nullable=False, default=True)
    cupos_lista_espera = Column(Integer, nullable=False, default=5)
    penalizacion_inasistencia = Column(DECIMAL(12, 2), nullable=False, default=0)
    max_reservas_activas_inmueble = Column(Integer, nullable=False, default=3)
    actualizado_en = Column(DateTime, nullable=False, default=ahora_local, onupdate=ahora_local)


class ListaEspera(Base):
    __tablename__ = "v3_lista_espera"

    id = Column(Integer, primary_key=True)
    zona_id = Column(Integer, ForeignKey("zonas_comunes.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False)
    solicitante_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_inicio = Column(DateTime, nullable=False)
    fecha_fin = Column(DateTime, nullable=False)
    posicion = Column(Integer, nullable=False, default=1)
    estado = Column(String(20), nullable=False, default="esperando")  # esperando | promovida | expirada | cancelada
    reserva_id = Column(Integer, ForeignKey("reservas.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)


class CierreZona(Base):
    """Cierre de zona por mantenimiento (bloquea reservas y promueve lista de espera al liberar)."""

    __tablename__ = "v3_cierres_zona"

    id = Column(Integer, primary_key=True)
    zona_id = Column(Integer, ForeignKey("zonas_comunes.id"), nullable=False, index=True)
    orden_mantenimiento_id = Column(Integer, ForeignKey("v3_ordenes_mantenimiento.id"), nullable=True)
    fecha_inicio = Column(DateTime, nullable=False)
    fecha_fin = Column(DateTime, nullable=False)
    motivo = Column(String(255), nullable=False)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


class AsistenciaReserva(Base):
    __tablename__ = "v3_asistencia_reserva"
    __table_args__ = (UniqueConstraint("reserva_id", name="uq_asistencia_reserva"),)

    id = Column(Integer, primary_key=True)
    reserva_id = Column(Integer, ForeignKey("reservas.id"), nullable=False, index=True)
    asistio = Column(Boolean, nullable=False)
    registrado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    observacion = Column(String(255), nullable=True)
    registrado_en = Column(DateTime, nullable=False, default=ahora_local)


class CargoReserva(Base):
    __tablename__ = "v3_cargos_reserva"

    id = Column(Integer, primary_key=True)
    reserva_id = Column(Integer, ForeignKey("reservas.id"), nullable=False, index=True)
    inmueble_id = Column(Integer, ForeignKey("inmuebles.id"), nullable=False)
    concepto = Column(String(160), nullable=False)
    tipo = Column(String(30), nullable=False, default="cobro_uso")  # cobro_uso | penalizacion
    monto = Column(DECIMAL(12, 2), nullable=False)
    estado = Column(String(20), nullable=False, default="pendiente")
    cargo_cartera_id = Column(Integer, ForeignKey("v3_cargos_cartera.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local)


Index("ix_v3_tx_estado_conjunto", TransaccionPago.conjunto_id, TransaccionPago.estado)
Index("ix_v3_orden_estado", OrdenMantenimiento.conjunto_id, OrdenMantenimiento.estado)
Index("ix_v3_acceso_conjunto_salida", RegistroAcceso.conjunto_id, RegistroAcceso.salida_en)


# ---------------------------------------------------------------------------
# 10. Operación: respaldos con prueba de restauración
# ---------------------------------------------------------------------------
class Respaldo(Base):
    __tablename__ = "v3_respaldos"

    id = Column(Integer, primary_key=True)
    conjunto_id = Column(Integer, ForeignKey("conjuntos.id"), nullable=True, index=True)
    tipo = Column(String(20), nullable=False, default="postgres")  # postgres | sqlite | completo
    archivo = Column(String(255), nullable=False)
    tamano_bytes = Column(Integer, nullable=False, default=0)
    checksum = Column(String(64), nullable=True)
    motor = Column(String(30), nullable=False, default="postgresql")
    estado_prueba = Column(String(20), nullable=False, default="pendiente")  # pendiente | ok | fallido
    detalle_prueba = Column(Text, nullable=True)
    tablas_verificadas = Column(Text, nullable=True)  # JSON
    filas_verificadas = Column(Integer, nullable=False, default=0)
    duracion_prueba_ms = Column(Integer, nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, default=ahora_local, index=True)
    probado_en = Column(DateTime, nullable=True)
