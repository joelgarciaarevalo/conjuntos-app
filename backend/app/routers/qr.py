"""
Códigos QR dinámicos para IRIS.

- Cada QR contiene únicamente un token aleatorio (IRIS-QR:<token>).
- La vigencia, el número de usos y la revocación se controlan en el servidor,
  por eso el QR es "dinámico": se puede revocar o regenerar sin reimprimir datos sensibles.
- Tipos: residente (permanente), visita (temporal con usos limitados) y reserva (ligado a una reserva aprobada).
"""
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.dependencies import get_usuario_actual
from app.models_qr import AccesoQR, CodigoQR
from app.permissions import allowed_set_ids, require_admin_set, require_staff_set

router = APIRouter(prefix="/qr", tags=["Códigos QR"])
TZ = ZoneInfo("America/Bogota")
def ahora_local():
    return datetime.now(TZ).replace(tzinfo=None)

PREFIJO = "IRIS-QR:"


# ----------------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------------
class QRCreate(BaseModel):
    tipo: Literal["visita", "reserva", "residente"]
    inmueble_id: Optional[int] = None
    residente_id: Optional[int] = None
    reserva_id: Optional[int] = None
    visitante_nombre: Optional[str] = Field(default=None, max_length=100)
    visitante_documento: Optional[str] = Field(default=None, max_length=30)
    horas_validez: Optional[int] = Field(default=24, ge=1, le=720)
    usos_maximos: Optional[int] = Field(default=1, ge=1, le=100)


class QRResponse(BaseModel):
    id: int
    token: str
    tipo: str
    estado: str
    inmueble_id: Optional[int] = None
    inmueble_etiqueta: Optional[str] = None
    residente_id: Optional[int] = None
    residente_nombre: Optional[str] = None
    reserva_id: Optional[int] = None
    zona_nombre: Optional[str] = None
    visitante_nombre: Optional[str] = None
    visitante_documento: Optional[str] = None
    valido_desde: datetime
    valido_hasta: Optional[datetime] = None
    usos_maximos: Optional[int] = None
    usos_actuales: int
    activo: bool
    creado_en: datetime


class ValidarRequest(BaseModel):
    codigo: str
    registrar_ingreso: bool = True


class ValidacionResponse(BaseModel):
    valido: bool
    motivo: str
    estado: Optional[str] = None
    qr: Optional[QRResponse] = None


class AccesoResponse(BaseModel):
    id: int
    fecha: datetime
    resultado: str
    motivo: str
    descripcion: str
    validado_por: Optional[str] = None


class ResidenteOpcion(BaseModel):
    inmueble_id: int
    inmueble_etiqueta: str
    residente_id: int
    nombre: str
    rol: str
    tiene_qr: bool


class ReservaOpcion(BaseModel):
    id: int
    etiqueta: str
    inmueble_id: int
    fecha_inicio: datetime
    fecha_fin: datetime
    tiene_qr: bool


class CatalogoResponse(BaseModel):
    residentes: list[ResidenteOpcion]
    reservas: list[ReservaOpcion]


class LoteResponse(BaseModel):
    creados: int
    omitidos: int


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def _solo_admin(usuario: models.Usuario) -> None:
    if not (usuario.es_super_admin or usuario.rol == "admin"):
        raise HTTPException(status_code=403, detail="Solo la administración puede gestionar códigos QR")


def _solo_porteria_o_admin(usuario: models.Usuario) -> None:
    if not (usuario.es_super_admin or usuario.rol in ("admin", "portero")):
        raise HTTPException(status_code=403, detail="Solo portería o administración puede validar accesos")


def _valor(x) -> str:
    """Devuelve el texto de un Enum o de un string."""
    return str(getattr(x, "value", x))


def _etiqueta_inmueble(i: models.Inmueble) -> str:
    return f"{'Torre ' + i.torre + ' - ' if i.torre else ''}Apto {i.numero}"


def _nuevo_token(db: Session) -> str:
    while True:
        token = secrets.token_urlsafe(24)
        if not db.query(CodigoQR).filter(CodigoQR.token == token).first():
            return token


def _limpiar_codigo(codigo: str) -> str:
    texto = (codigo or "").strip()
    if texto.upper().startswith(PREFIJO):
        texto = texto[len(PREFIJO):]
    return texto.strip()


def _estado(qr: CodigoQR, ahora: datetime) -> str:
    if not qr.activo:
        return "revocado"
    if qr.usos_maximos is not None and qr.usos_actuales >= qr.usos_maximos:
        return "agotado"
    if qr.valido_desde and ahora < qr.valido_desde:
        return "programado"
    if qr.valido_hasta and ahora > qr.valido_hasta:
        return "vencido"
    return "activo"


_MOTIVOS = {
    "revocado": "Código revocado por la administración",
    "agotado": "Se alcanzó el número máximo de usos",
    "programado": "Aún no está vigente",
    "vencido": "Código vencido",
}


class _Mapas:
    """Carga una vez los nombres necesarios para armar respuestas legibles."""

    def __init__(self, db: Session):
        self.usuarios = {u.id: u.nombre_completo for u in db.query(models.Usuario).all()}
        self.inmuebles = {i.id: i for i in db.query(models.Inmueble).all()}
        self.zonas = {z.id: z.nombre for z in db.query(models.ZonaComun).all()}
        self.reservas = {r.id: r for r in db.query(models.Reserva).all()}


def _serializar(qr: CodigoQR, m: _Mapas, ahora: datetime) -> QRResponse:
    inmueble = m.inmuebles.get(qr.inmueble_id) if qr.inmueble_id else None
    reserva = m.reservas.get(qr.reserva_id) if qr.reserva_id else None
    return QRResponse(
        id=qr.id,
        token=qr.token,
        tipo=qr.tipo,
        estado=_estado(qr, ahora),
        inmueble_id=qr.inmueble_id,
        inmueble_etiqueta=_etiqueta_inmueble(inmueble) if inmueble else None,
        residente_id=qr.residente_id,
        residente_nombre=m.usuarios.get(qr.residente_id) if qr.residente_id else None,
        reserva_id=qr.reserva_id,
        zona_nombre=m.zonas.get(reserva.zona_id) if reserva else None,
        visitante_nombre=qr.visitante_nombre,
        visitante_documento=qr.visitante_documento,
        valido_desde=qr.valido_desde,
        valido_hasta=qr.valido_hasta,
        usos_maximos=qr.usos_maximos,
        usos_actuales=qr.usos_actuales or 0,
        activo=bool(qr.activo),
        creado_en=qr.creado_en,
    )


def _qr_o_404(db: Session, qr_id: int) -> CodigoQR:
    qr = db.query(CodigoQR).filter(CodigoQR.id == qr_id).first()
    if not qr:
        raise HTTPException(status_code=404, detail="Código QR no encontrado")
    return qr


def _validar_residente_inmueble(db: Session, inmueble_id: Optional[int], residente_id: Optional[int]) -> models.Inmueble:
    if inmueble_id is None or residente_id is None:
        raise HTTPException(status_code=400, detail="Selecciona el residente y su inmueble")
    inmueble = db.query(models.Inmueble).filter(models.Inmueble.id == inmueble_id).first()
    if not inmueble:
        raise HTTPException(status_code=404, detail="Inmueble no encontrado")
    if residente_id not in (inmueble.propietario_id, inmueble.inquilino_id):
        raise HTTPException(status_code=400, detail="El residente no pertenece a ese inmueble")
    return inmueble


def _qr_activo_existente(db: Session, **filtros) -> Optional[CodigoQR]:
    consulta = db.query(CodigoQR).filter(CodigoQR.activo.is_(True))
    for campo, valor in filtros.items():
        consulta = consulta.filter(getattr(CodigoQR, campo) == valor)
    return consulta.first()


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------
@router.get("/catalogo", response_model=CatalogoResponse)
def catalogo(
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual),
):
    """Opciones para los formularios: residentes por inmueble y reservas aprobadas vigentes."""
    _solo_admin(usuario_actual)
    ids = allowed_set_ids(db, usuario_actual)
    ahora = ahora_local()
    m = _Mapas(db)

    con_qr_residente = {
        (q.inmueble_id, q.residente_id)
        for q in db.query(CodigoQR).filter(CodigoQR.tipo == "residente", CodigoQR.activo.is_(True)).all()
    }
    con_qr_reserva = {
        q.reserva_id
        for q in db.query(CodigoQR).filter(CodigoQR.tipo == "reserva", CodigoQR.activo.is_(True)).all()
    }

    residentes: list[ResidenteOpcion] = []
    inmuebles = sorted((i for i in m.inmuebles.values() if i.conjunto_id in ids), key=lambda i: ((i.torre or ""), i.numero))
    for inm in inmuebles:
        personas = [(inm.propietario_id, "propietario")]
        if inm.inquilino_id and inm.inquilino_id != inm.propietario_id:
            personas.append((inm.inquilino_id, "inquilino"))
        for uid, rol in personas:
            residentes.append(ResidenteOpcion(
                inmueble_id=inm.id,
                inmueble_etiqueta=_etiqueta_inmueble(inm),
                residente_id=uid,
                nombre=m.usuarios.get(uid, f"Usuario #{uid}"),
                rol=rol,
                tiene_qr=(inm.id, uid) in con_qr_residente,
            ))

    reservas: list[ReservaOpcion] = []
    for r in sorted(m.reservas.values(), key=lambda x: x.fecha_inicio):
        z = db.query(models.ZonaComun).filter_by(id=r.zona_id).first()
        if not z or z.conjunto_id not in ids: continue
        if _valor(r.estado) != "aprobada" or r.fecha_fin < ahora:
            continue
        inm = m.inmuebles.get(r.inmueble_id)
        zona = m.zonas.get(r.zona_id, f"Zona #{r.zona_id}")
        etiqueta = (
            f"#{r.id} · {zona} · {_etiqueta_inmueble(inm) if inm else 'Inmueble #' + str(r.inmueble_id)}"
            f" · {r.fecha_inicio.strftime('%d/%m/%Y %H:%M')}"
        )
        reservas.append(ReservaOpcion(
            id=r.id,
            etiqueta=etiqueta,
            inmueble_id=r.inmueble_id,
            fecha_inicio=r.fecha_inicio,
            fecha_fin=r.fecha_fin,
            tiene_qr=r.id in con_qr_reserva,
        ))

    return CatalogoResponse(residentes=residentes, reservas=reservas)


@router.get("/", response_model=list[QRResponse])
def listar_qr(
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual),
):
    _solo_admin(usuario_actual)
    ahora = ahora_local()
    ids = allowed_set_ids(db, usuario_actual)
    consulta = db.query(CodigoQR).join(models.Inmueble, CodigoQR.inmueble_id == models.Inmueble.id).filter(models.Inmueble.conjunto_id.in_(ids))
    if tipo:
        consulta = consulta.filter(CodigoQR.tipo == tipo)
    codigos = consulta.order_by(CodigoQR.id.desc()).all()
    m = _Mapas(db)
    return [_serializar(q, m, ahora) for q in codigos]


@router.post("/", response_model=QRResponse, status_code=201)
def crear_qr(
    datos: QRCreate,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual),
):
    _solo_admin(usuario_actual)
    ahora = ahora_local()

    if datos.tipo == "reserva":
        if datos.reserva_id is None:
            raise HTTPException(status_code=400, detail="Selecciona la reserva")
        reserva = db.query(models.Reserva).filter(models.Reserva.id == datos.reserva_id).first()
        if not reserva:
            raise HTTPException(status_code=404, detail="Reserva no encontrada")
        zone = db.query(models.ZonaComun).filter_by(id=reserva.zona_id).first(); require_admin_set(db, usuario_actual, zone.conjunto_id)
        if _valor(reserva.estado) != "aprobada":
            raise HTTPException(status_code=400, detail="Solo se genera QR para reservas aprobadas")
        if reserva.fecha_fin < ahora:
            raise HTTPException(status_code=400, detail="La reserva ya terminó")
        if _qr_activo_existente(db, tipo="reserva", reserva_id=reserva.id):
            raise HTTPException(status_code=409, detail="Esta reserva ya tiene un QR activo. Usa «Regenerar» para cambiarlo.")
        qr = CodigoQR(
            token=_nuevo_token(db),
            tipo="reserva",
            inmueble_id=reserva.inmueble_id,
            residente_id=reserva.solicitante_id,
            reserva_id=reserva.id,
            valido_desde=reserva.fecha_inicio,
            valido_hasta=reserva.fecha_fin,
            usos_maximos=None,
            creado_por=usuario_actual.id,
            creado_en=ahora,
        )

    elif datos.tipo == "visita":
        inmueble = _validar_residente_inmueble(db, datos.inmueble_id, datos.residente_id)
        require_admin_set(db, usuario_actual, inmueble.conjunto_id)
        nombre = (datos.visitante_nombre or "").strip()
        if not nombre:
            raise HTTPException(status_code=400, detail="Escribe el nombre del visitante")
        horas = datos.horas_validez or 24
        qr = CodigoQR(
            token=_nuevo_token(db),
            tipo="visita",
            inmueble_id=inmueble.id,
            residente_id=datos.residente_id,
            visitante_nombre=nombre,
            visitante_documento=(datos.visitante_documento or "").strip() or None,
            valido_desde=ahora,
            valido_hasta=ahora + timedelta(hours=horas),
            usos_maximos=datos.usos_maximos or 1,
            creado_por=usuario_actual.id,
            creado_en=ahora,
        )

    else:  # residente
        inmueble = _validar_residente_inmueble(db, datos.inmueble_id, datos.residente_id)
        require_admin_set(db, usuario_actual, inmueble.conjunto_id)
        if _qr_activo_existente(db, tipo="residente", inmueble_id=inmueble.id, residente_id=datos.residente_id):
            raise HTTPException(status_code=409, detail="Este residente ya tiene un QR activo. Usa «Regenerar» para cambiarlo.")
        qr = CodigoQR(
            token=_nuevo_token(db),
            tipo="residente",
            inmueble_id=inmueble.id,
            residente_id=datos.residente_id,
            valido_desde=ahora,
            valido_hasta=None,
            usos_maximos=None,
            creado_por=usuario_actual.id,
            creado_en=ahora,
        )

    db.add(qr)
    db.commit()
    db.refresh(qr)
    return _serializar(qr, _Mapas(db), ahora)


@router.post("/lote-residentes", response_model=LoteResponse)
def generar_qr_para_todos_los_residentes(
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual),
):
    """Crea un QR permanente para cada propietario/inquilino que aún no tenga uno activo."""
    _solo_admin(usuario_actual)
    ahora = ahora_local()
    ids = allowed_set_ids(db, usuario_actual)
    existentes = {(q.inmueble_id, q.residente_id) for q in db.query(CodigoQR).join(models.Inmueble, CodigoQR.inmueble_id == models.Inmueble.id).filter(CodigoQR.tipo == "residente", CodigoQR.activo.is_(True), models.Inmueble.conjunto_id.in_(ids)).all()}
    creados = 0
    omitidos = 0
    for inm in db.query(models.Inmueble).filter(models.Inmueble.conjunto_id.in_(ids)).order_by(models.Inmueble.id).all():
        ids = [inm.propietario_id]
        if inm.inquilino_id and inm.inquilino_id != inm.propietario_id:
            ids.append(inm.inquilino_id)
        for uid in ids:
            if (inm.id, uid) in existentes:
                omitidos += 1
                continue
            db.add(CodigoQR(
                token=_nuevo_token(db),
                tipo="residente",
                inmueble_id=inm.id,
                residente_id=uid,
                valido_desde=ahora,
                valido_hasta=None,
                usos_maximos=None,
                creado_por=usuario_actual.id,
                creado_en=ahora,
            ))
            db.flush()  # asegura que _nuevo_token vea los tokens ya generados
            creados += 1
    db.commit()
    return LoteResponse(creados=creados, omitidos=omitidos)


@router.post("/{qr_id}/revocar", response_model=QRResponse)
def revocar_qr(
    qr_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual),
):
    _solo_admin(usuario_actual)
    qr = _qr_o_404(db, qr_id)
    unit = db.query(models.Inmueble).filter_by(id=qr.inmueble_id).first() if qr.inmueble_id else None
    if unit: require_admin_set(db, usuario_actual, unit.conjunto_id)
    qr.activo = False
    db.commit()
    db.refresh(qr)
    return _serializar(qr, _Mapas(db), ahora_local())


@router.post("/{qr_id}/regenerar", response_model=QRResponse)
def regenerar_qr(
    qr_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual),
):
    """Invalida el QR anterior (cambia el token), reinicia los usos y lo deja activo."""
    _solo_admin(usuario_actual)
    ahora = ahora_local()
    qr = _qr_o_404(db, qr_id)
    unit = db.query(models.Inmueble).filter_by(id=qr.inmueble_id).first() if qr.inmueble_id else None
    if unit: require_admin_set(db, usuario_actual, unit.conjunto_id)

    if qr.tipo == "reserva":
        reserva = db.query(models.Reserva).filter(models.Reserva.id == qr.reserva_id).first()
        if not reserva or _valor(reserva.estado) != "aprobada":
            raise HTTPException(status_code=400, detail="La reserva ya no está aprobada")
        if reserva.fecha_fin < ahora:
            raise HTTPException(status_code=400, detail="La reserva ya terminó")
    elif qr.tipo == "visita" and qr.valido_hasta:
        duracion = qr.valido_hasta - qr.valido_desde
        qr.valido_desde = ahora
        qr.valido_hasta = ahora + duracion

    qr.token = _nuevo_token(db)
    qr.usos_actuales = 0
    qr.activo = True
    db.commit()
    db.refresh(qr)
    return _serializar(qr, _Mapas(db), ahora)


@router.post("/validar", response_model=ValidacionResponse)
def validar_qr(
    datos: ValidarRequest,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual),
):
    """Portería: valida un código (pegado, tecleado o leído con un lector de QR)."""
    _solo_porteria_o_admin(usuario_actual)
    ahora = ahora_local()
    intentos = db.query(AccesoQR).filter(AccesoQR.validado_por == usuario_actual.id, AccesoQR.fecha >= ahora - timedelta(minutes=10)).count()
    if intentos >= 30: raise HTTPException(429, "Demasiados intentos de validación; espera 10 minutos")
    token = _limpiar_codigo(datos.codigo)
    qr = db.query(CodigoQR).filter(CodigoQR.token == token).first() if token else None

    if not qr:
        motivo = "Código no reconocido"
        if datos.registrar_ingreso:
            db.add(AccesoQR(codigo_id=None, fecha=ahora, resultado="denegado", motivo=motivo, validado_por=usuario_actual.id))
            db.commit()
        return ValidacionResponse(valido=False, motivo=motivo, estado=None, qr=None)

    if qr.inmueble_id:
        unit = db.query(models.Inmueble).filter_by(id=qr.inmueble_id).first()
        if unit: require_staff_set(db, usuario_actual, unit.conjunto_id)
    estado = _estado(qr, ahora)
    valido = estado == "activo"
    if valido:
        if datos.registrar_ingreso:
            qr.usos_actuales = (qr.usos_actuales or 0) + 1
            motivo = "Acceso autorizado"
        else:
            motivo = "Código válido (consulta: no se registró el ingreso)"
    else:
        motivo = _MOTIVOS.get(estado, "Código no válido")

    if datos.registrar_ingreso:
        db.add(AccesoQR(
            codigo_id=qr.id,
            fecha=ahora,
            resultado="permitido" if valido else "denegado",
            motivo=motivo,
            validado_por=usuario_actual.id,
        ))
    db.commit()
    db.refresh(qr)
    return ValidacionResponse(valido=valido, motivo=motivo, estado=estado, qr=_serializar(qr, _Mapas(db), ahora))


@router.get("/accesos/recientes", response_model=list[AccesoResponse])
def accesos_recientes(
    limite: int = 15,
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_usuario_actual),
):
    _solo_porteria_o_admin(usuario_actual)
    limite = max(1, min(limite, 100))
    ids = allowed_set_ids(db, usuario_actual)
    m = _Mapas(db)
    codigos = {q.id: q for q in db.query(CodigoQR).join(models.Inmueble, CodigoQR.inmueble_id == models.Inmueble.id).filter(models.Inmueble.conjunto_id.in_(ids)).all()}
    access_query = db.query(AccesoQR).join(CodigoQR, AccesoQR.codigo_id == CodigoQR.id).join(models.Inmueble, CodigoQR.inmueble_id == models.Inmueble.id).filter(models.Inmueble.conjunto_id.in_(ids))
    accesos = access_query.order_by(AccesoQR.id.desc()).limit(limite).all()

    salida: list[AccesoResponse] = []
    for a in accesos:
        qr = codigos.get(a.codigo_id) if a.codigo_id else None
        if qr is None:
            descripcion = "Código desconocido"
        else:
            inm = m.inmuebles.get(qr.inmueble_id) if qr.inmueble_id else None
            quien = qr.visitante_nombre if qr.tipo == "visita" else m.usuarios.get(qr.residente_id, "Residente")
            descripcion = f"{quien} · {_etiqueta_inmueble(inm)}" if inm else str(quien)
        salida.append(AccesoResponse(
            id=a.id,
            fecha=a.fecha,
            resultado=a.resultado,
            motivo=a.motivo,
            descripcion=descripcion,
            validado_por=m.usuarios.get(a.validado_por) if a.validado_por else None,
        ))
    return salida


@router.get("/mio", response_model=list[QRResponse])
def mis_codigos_qr(db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    """Lista únicamente los QR vinculados al usuario autenticado."""
    codigos = db.query(CodigoQR).filter(CodigoQR.residente_id == usuario_actual.id).order_by(CodigoQR.id.desc()).all()
    m = _Mapas(db)
    return [_serializar(q, m, ahora_local()) for q in codigos]


@router.post("/mio/residente", response_model=QRResponse, status_code=201)
def crear_mi_qr_residente(inmueble_id: int, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    inmueble = _validar_residente_inmueble(db, inmueble_id, usuario_actual.id)
    actual = _qr_activo_existente(db, tipo="residente", inmueble_id=inmueble.id, residente_id=usuario_actual.id)
    if actual:
        return _serializar(actual, _Mapas(db), ahora_local())
    ahora = ahora_local()
    qr = CodigoQR(token=_nuevo_token(db), tipo="residente", inmueble_id=inmueble.id, residente_id=usuario_actual.id,
                  valido_desde=ahora, valido_hasta=None, usos_maximos=None, creado_por=usuario_actual.id, creado_en=ahora)
    db.add(qr); db.commit(); db.refresh(qr)
    return _serializar(qr, _Mapas(db), ahora)


@router.post("/mio/visitas", response_model=QRResponse, status_code=201)
def crear_mi_qr_visita(datos: QRCreate, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    inmueble = _validar_residente_inmueble(db, datos.inmueble_id, usuario_actual.id)
    nombre = (datos.visitante_nombre or "").strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="Escribe el nombre del visitante")
    ahora = ahora_local()
    horas = datos.horas_validez or 24
    qr = CodigoQR(token=_nuevo_token(db), tipo="visita", inmueble_id=inmueble.id, residente_id=usuario_actual.id,
                  visitante_nombre=nombre, visitante_documento=(datos.visitante_documento or "").strip() or None,
                  valido_desde=ahora, valido_hasta=ahora + timedelta(hours=horas),
                  usos_maximos=datos.usos_maximos or 1, creado_por=usuario_actual.id, creado_en=ahora)
    db.add(qr); db.commit(); db.refresh(qr)
    return _serializar(qr, _Mapas(db), ahora)


@router.post("/mio/{qr_id}/revocar", response_model=QRResponse)
def revocar_mi_qr(qr_id: int, db: Session = Depends(get_db), usuario_actual: models.Usuario = Depends(get_usuario_actual)):
    qr = _qr_o_404(db, qr_id)
    if qr.residente_id != usuario_actual.id:
        raise HTTPException(status_code=403, detail="No puedes revocar un QR de otra persona")
    qr.activo = False; db.commit(); db.refresh(qr)
    return _serializar(qr, _Mapas(db), ahora_local())
