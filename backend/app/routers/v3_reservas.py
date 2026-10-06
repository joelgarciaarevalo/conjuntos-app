"""Reservas con reglas avanzadas: cupos por franja, listas de espera, cobros por uso,
penalizaciones por inasistencia y cierres por mantenimiento."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.permissions import can_access_set, is_admin, require_admin_set, require_staff_set
from app.security_v3 import dependencia_2fa, exigir_2fa_admin, get_usuario_v3
from app.routers.v3_common import (
    admin_only, alcance, avisar_evento, dec, dt, etiqueta_unidad, localnow, model_data, money,
    notificar, unit_access, units_for_user,
)

router = APIRouter(prefix="/v3/reservas", tags=["v3 · Reservas avanzadas"])


def _regla(db: Session, zona: models.ZonaComun) -> models_v3.ReglaZonaReserva:
    fila = db.query(models_v3.ReglaZonaReserva).filter_by(zona_id=zona.id).first()
    if not fila:
        fila = models_v3.ReglaZonaReserva(zona_id=zona.id)
        db.add(fila)
        db.commit()
        db.refresh(fila)
    return fila


def _zona(db: Session, user: models.Usuario, zona_id: int) -> models.ZonaComun:
    zona = db.query(models.ZonaComun).filter_by(id=zona_id).first()
    if not zona:
        raise HTTPException(404, "Zona no encontrada")
    if not can_access_set(db, user, zona.conjunto_id):
        raise HTTPException(403, "No tienes acceso a esta zona")
    return zona


def _reservas_solapadas(db: Session, zona_id: int, inicio: datetime, fin: datetime, excluir_id: int | None = None):
    q = db.query(models.Reserva).filter(
        models.Reserva.zona_id == zona_id,
        models.Reserva.estado.in_([models.EstadoReserva.pendiente, models.EstadoReserva.aprobada]),
        models.Reserva.fecha_inicio < fin,
        models.Reserva.fecha_fin > inicio,
    )
    if excluir_id:
        q = q.filter(models.Reserva.id != excluir_id)
    return q.all()


def _cierres_solapados(db: Session, zona_id: int, inicio: datetime, fin: datetime):
    return db.query(models_v3.CierreZona).filter(
        models_v3.CierreZona.zona_id == zona_id,
        models_v3.CierreZona.fecha_inicio < fin,
        models_v3.CierreZona.fecha_fin > inicio,
    ).all()


def _franjas(zona: models.ZonaComun, regla: models_v3.ReglaZonaReserva, dia: date) -> list[tuple[datetime, datetime]]:
    apertura = datetime.combine(dia, time.fromisoformat(zona.hora_apertura))
    cierre = datetime.combine(dia, time.fromisoformat(zona.hora_cierre))
    duracion = timedelta(minutes=max(15, regla.duracion_franja_minutos))
    salida = []
    cursor = apertura
    while cursor + duracion <= cierre:
        salida.append((cursor, cursor + duracion))
        cursor += duracion
    return salida


# ---------------------------------------------------------------------------
# Reglas por zona
# ---------------------------------------------------------------------------
@router.get("/reglas")
def listar_reglas(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if is_admin(user) or user.rol == "portero" or user.es_super_admin:
        ids = [conjunto_id] if conjunto_id else alcance(db, user)
        if conjunto_id:
            require_staff_set(db, user, conjunto_id)
    else:
        # Los residentes ven las reglas (cupos, horarios y tarifas) de las zonas de su conjunto.
        ids = sorted({u.conjunto_id for u in units_for_user(db, user)})
    zonas = db.query(models.ZonaComun).filter(models.ZonaComun.conjunto_id.in_(ids)).all() if ids else []
    return [model_data(_regla(db, z)) | {"zona": z.nombre, "conjunto_id": z.conjunto_id} for z in zonas]


@router.get("/reglas/{zona_id}")
def leer_regla(zona_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    zona = _zona(db, user, zona_id)
    return model_data(_regla(db, zona)) | {"zona": zona.nombre}


@router.put("/reglas/{zona_id}")
def guardar_regla(zona_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    zona = _zona(db, user, zona_id)
    require_admin_set(db, user, zona.conjunto_id)
    fila = _regla(db, zona)
    rangos = {
        "cupos_por_franja": (1, 50), "duracion_franja_minutos": (15, 720), "antelacion_minima_horas": (0, 720),
        "horas_limite_cancelacion": (0, 720), "cupos_lista_espera": (0, 50), "max_reservas_activas_inmueble": (1, 30),
    }
    for campo, (minimo, maximo) in rangos.items():
        if data.get(campo) is not None:
            valor = int(data[campo])
            if not minimo <= valor <= maximo:
                raise HTTPException(422, f"{campo} debe estar entre {minimo} y {maximo}")
            setattr(fila, campo, valor)
    for campo in ("requiere_pago", "lista_espera_activa"):
        if data.get(campo) is not None:
            setattr(fila, campo, bool(data[campo]))
    for campo in ("tarifa_por_uso", "penalizacion_inasistencia"):
        if data.get(campo) is not None:
            valor = dec(data[campo])
            if valor < 0:
                raise HTTPException(422, f"{campo} no puede ser negativo")
            setattr(fila, campo, valor)
    fila.actualizado_en = localnow()
    db.commit()
    db.refresh(fila)
    return model_data(fila)


# ---------------------------------------------------------------------------
# Disponibilidad
# ---------------------------------------------------------------------------
@router.get("/disponibilidad")
def disponibilidad(zona_id: int, fecha: str | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    zona = _zona(db, user, zona_id)
    regla = _regla(db, zona)
    try:
        dia = date.fromisoformat(fecha) if fecha else localnow().date()
    except ValueError:
        raise HTTPException(422, "Fecha inválida (usa AAAA-MM-DD)")
    franjas = []
    for inicio, fin in _franjas(zona, regla, dia):
        ocupacion = len(_reservas_solapadas(db, zona.id, inicio, fin))
        cierres = _cierres_solapados(db, zona.id, inicio, fin)
        disponibles = max(0, regla.cupos_por_franja - ocupacion)
        franjas.append({
            "inicio": inicio.isoformat(), "fin": fin.isoformat(),
            "cupos_totales": regla.cupos_por_franja, "ocupados": ocupacion, "disponibles": disponibles,
            "cerrado": bool(cierres), "motivo_cierre": cierres[0].motivo if cierres else None,
            "disponible": disponibles > 0 and not cierres,
            "espera": db.query(models_v3.ListaEspera).filter(
                models_v3.ListaEspera.zona_id == zona.id, models_v3.ListaEspera.estado == "esperando",
                models_v3.ListaEspera.fecha_inicio < fin, models_v3.ListaEspera.fecha_fin > inicio,
            ).count(),
        })
    return {
        "zona": {"id": zona.id, "nombre": zona.nombre, "hora_apertura": zona.hora_apertura, "hora_cierre": zona.hora_cierre,
                 "requiere_aprobacion": zona.requiere_aprobacion},
        "regla": model_data(regla), "fecha": dia.isoformat(), "franjas": franjas,
        "antelacion_minima_horas": regla.antelacion_minima_horas,
    }


# ---------------------------------------------------------------------------
# Solicitud de reserva
# ---------------------------------------------------------------------------
@router.post("/solicitar", status_code=201)
def solicitar(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    zona = _zona(db, user, int(data.get("zona_id") or 0))
    regla = _regla(db, zona)
    unidad = unit_access(db, user, int(data.get("inmueble_id") or 0))
    if unidad.conjunto_id != zona.conjunto_id:
        raise HTTPException(422, "El inmueble no pertenece al conjunto de la zona")
    if not data.get("fecha_inicio") or not data.get("fecha_fin"):
        raise HTTPException(422, "Indica el inicio y el fin de la reserva")
    inicio, fin = dt(data["fecha_inicio"]), dt(data["fecha_fin"])
    if fin <= inicio:
        raise HTTPException(422, "La fecha de fin debe ser posterior al inicio")
    if fin - inicio > timedelta(minutes=zona.duracion_max_minutos):
        raise HTTPException(422, f"La zona permite máximo {zona.duracion_max_minutos} minutos por reserva")
    ahora = localnow()
    if inicio < ahora - timedelta(minutes=1):
        raise HTTPException(422, "No se pueden reservar franjas en el pasado")
    if (inicio - ahora) < timedelta(hours=regla.antelacion_minima_horas):
        raise HTTPException(422, f"Esta zona exige {regla.antelacion_minima_horas} horas de anticipación")
    if (inicio.date() - ahora.date()).days > zona.max_dias_anticipacion:
        raise HTTPException(422, f"Solo se puede reservar con {zona.max_dias_anticipacion} días de anticipación")
    if not (time.fromisoformat(zona.hora_apertura) <= inicio.time() and fin.time() <= time.fromisoformat(zona.hora_cierre)):
        raise HTTPException(422, f"La zona opera entre {zona.hora_apertura} y {zona.hora_cierre}")
    cierres = _cierres_solapados(db, zona.id, inicio, fin)
    if cierres:
        raise HTTPException(409, f"La zona está cerrada por mantenimiento: {cierres[0].motivo}")

    activas = db.query(models.Reserva).filter(
        models.Reserva.inmueble_id == unidad.id,
        models.Reserva.estado.in_([models.EstadoReserva.pendiente, models.EstadoReserva.aprobada]),
        models.Reserva.fecha_fin > ahora,
    ).count()
    if activas >= regla.max_reservas_activas_inmueble:
        raise HTTPException(409, f"El inmueble ya tiene {activas} reservas activas (máximo {regla.max_reservas_activas_inmueble})")
    del_dia = db.query(models.Reserva).filter(
        models.Reserva.inmueble_id == unidad.id,
        models.Reserva.fecha_inicio >= datetime.combine(inicio.date(), time.min),
        models.Reserva.fecha_inicio <= datetime.combine(inicio.date(), time.max),
    ).count()
    if del_dia >= zona.max_reservas_dia_inmueble:
        raise HTTPException(409, f"El inmueble alcanzó el máximo de {zona.max_reservas_dia_inmueble} reservas para ese día")

    solapadas = _reservas_solapadas(db, zona.id, inicio, fin)
    if len(solapadas) >= regla.cupos_por_franja:
        raise HTTPException(409, "No hay cupos disponibles en esa franja. Puedes entrar a la lista de espera.")
    propias = [r for r in solapadas if r.inmueble_id == unidad.id]
    if propias:
        raise HTTPException(409, "Tu inmueble ya tiene una reserva en esa franja")

    estado = models.EstadoReserva.pendiente if zona.requiere_aprobacion else models.EstadoReserva.aprobada
    reserva = models.Reserva(zona_id=zona.id, inmueble_id=unidad.id, solicitante_id=user.id, fecha_inicio=inicio, fecha_fin=fin, estado=estado)
    db.add(reserva)
    db.flush()

    cargo = None
    if regla.requiere_pago and dec(regla.tarifa_por_uso) > 0:
        cargo = _aplicar_cargo(db, reserva, unidad, "cobro_uso", f"Uso de {zona.nombre}", dec(regla.tarifa_por_uso), user.id)
    db.commit()
    db.refresh(reserva)
    return {
        **model_data(reserva), "zona": zona.nombre,
        "inmueble": etiqueta_unidad(unidad), "estado": reserva.estado.value if hasattr(reserva.estado, "value") else reserva.estado,
        "requiere_pago": bool(regla.requiere_pago and dec(regla.tarifa_por_uso) > 0),
        "tarifa": money(regla.tarifa_por_uso), "cargo": model_data(cargo) if cargo else None,
        "cupos_restantes": max(0, regla.cupos_por_franja - len(solapadas) - 1),
    }


def _aplicar_cargo(db: Session, reserva: models.Reserva, unidad: models.Inmueble, tipo: str, concepto: str, monto: Decimal, usuario_id: int | None) -> models_v3.CargoReserva:
    cargo = models_v3.CargoReserva(reserva_id=reserva.id, inmueble_id=unidad.id, concepto=concepto[:160], tipo=tipo, monto=monto)
    db.add(cargo)
    db.flush()
    cartera = models_v3.CargoCartera(
        conjunto_id=unidad.conjunto_id, inmueble_id=unidad.id, reserva_id=reserva.id, tipo=tipo,
        concepto=concepto[:160], base=monto, monto=monto, periodo=reserva.fecha_inicio.strftime("%Y-%m"), creado_por=usuario_id,
    )
    db.add(cartera)
    db.flush()
    cargo.cargo_cartera_id = cartera.id
    for usuario_id_destino in {unidad.propietario_id, unidad.inquilino_id} - {None}:
        notificar(db, usuario_id_destino, "Cargo por reserva", f"{concepto}: ${money(monto)}")
    return cargo


@router.post("/{reserva_id}/cancelar")
def cancelar(reserva_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    reserva = db.query(models.Reserva).filter_by(id=reserva_id).first()
    if not reserva:
        raise HTTPException(404, "Reserva no encontrada")
    zona = db.query(models.ZonaComun).filter_by(id=reserva.zona_id).first()
    unidad = db.query(models.Inmueble).filter_by(id=reserva.inmueble_id).first()
    if not is_admin(user) and user.id not in (reserva.solicitante_id, unidad.propietario_id if unidad else None, unidad.inquilino_id if unidad else None):
        raise HTTPException(403, "Sin permiso para cancelar esta reserva")
    if is_admin(user):
        require_admin_set(db, user, zona.conjunto_id)
    if reserva.estado == models.EstadoReserva.cancelada:
        raise HTTPException(409, "La reserva ya estaba cancelada")
    regla = _regla(db, zona)
    horas_restantes = (reserva.fecha_inicio - localnow()).total_seconds() / 3600
    reserva.estado = models.EstadoReserva.cancelada
    db.flush()  # el cupo debe liberarse antes de promover la lista de espera
    penalizacion = None
    if not is_admin(user) and horas_restantes < regla.horas_limite_cancelacion and dec(regla.penalizacion_inasistencia) > 0:
        penalizacion = _aplicar_cargo(db, reserva, unidad, "penalizacion",
                                      f"Penalización por cancelación tardía de {zona.nombre}",
                                      dec(regla.penalizacion_inasistencia), user.id)
    promovida = _promover_lista_espera(db, zona, reserva.fecha_inicio, reserva.fecha_fin)
    db.commit()
    return {"reserva_id": reserva.id, "estado": "cancelada", "penalizacion": model_data(penalizacion) if penalizacion else None,
            "lista_espera_promovida": promovida}


def _promover_lista_espera(db: Session, zona: models.ZonaComun, inicio: datetime, fin: datetime) -> dict | None:
    regla = _regla(db, zona)
    if not regla.lista_espera_activa:
        return None
    if len(_reservas_solapadas(db, zona.id, inicio, fin)) >= regla.cupos_por_franja:
        return None
    candidatos = db.query(models_v3.ListaEspera).filter(
        models_v3.ListaEspera.zona_id == zona.id, models_v3.ListaEspera.estado == "esperando",
        models_v3.ListaEspera.fecha_inicio < fin, models_v3.ListaEspera.fecha_fin > inicio,
    ).order_by(models_v3.ListaEspera.posicion, models_v3.ListaEspera.id).all()
    if not candidatos:
        return None
    elegido = candidatos[0]
    if _cierres_solapados(db, zona.id, elegido.fecha_inicio, elegido.fecha_fin):
        elegido.estado = "expirada"
        return None
    estado = models.EstadoReserva.pendiente if zona.requiere_aprobacion else models.EstadoReserva.aprobada
    nueva = models.Reserva(zona_id=zona.id, inmueble_id=elegido.inmueble_id, solicitante_id=elegido.solicitante_id,
                           fecha_inicio=elegido.fecha_inicio, fecha_fin=elegido.fecha_fin, estado=estado)
    db.add(nueva)
    db.flush()
    elegido.estado = "promovida"
    elegido.reserva_id = nueva.id
    unidad = db.query(models.Inmueble).filter_by(id=elegido.inmueble_id).first()
    for usuario_id in ({unidad.propietario_id, unidad.inquilino_id} - {None} if unidad else set()):
        notificar(db, usuario_id, "Cupo liberado en lista de espera",
                  f"Se liberó un cupo para {zona.nombre} el {elegido.fecha_inicio.strftime('%Y-%m-%d %H:%M')}. Reserva #{nueva.id} creada.")
    from app.services.messaging import avisar
    try:
        avisar(db, elegido.solicitante_id, "aprobacion_reserva", {
            "zona": zona.nombre, "fecha": elegido.fecha_inicio.strftime("%Y-%m-%d %H:%M"),
            "mensaje": f"Se liberó un cupo en {zona.nombre} y tu reserva #{nueva.id} quedó creada.",
        }, conjunto_id=zona.conjunto_id)
    except Exception:
        pass
    return {"reserva_id": nueva.id, "inmueble": etiqueta_unidad(unidad), "lista_espera_id": elegido.id}


# ---------------------------------------------------------------------------
# Lista de espera
# ---------------------------------------------------------------------------
@router.get("/lista-espera")
def listar_espera(zona_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.ListaEspera)
    if is_admin(user) or user.rol == "portero":
        if zona_id:
            zona = _zona(db, user, zona_id)
            q = q.filter(models_v3.ListaEspera.zona_id == zona.id)
        else:
            zonas = [z.id for z in db.query(models.ZonaComun).filter(models.ZonaComun.conjunto_id.in_(alcance(db, user))).all()]
            q = q.filter(models_v3.ListaEspera.zona_id.in_(zonas))
    else:
        q = q.filter(models_v3.ListaEspera.solicitante_id == user.id)
        if zona_id:
            q = q.filter(models_v3.ListaEspera.zona_id == zona_id)
    salida = []
    for fila in q.order_by(models_v3.ListaEspera.zona_id, models_v3.ListaEspera.posicion).limit(300).all():
        zona = db.query(models.ZonaComun).filter_by(id=fila.zona_id).first()
        salida.append(model_data(fila) | {
            "zona": zona.nombre if zona else None,
            "inmueble": etiqueta_unidad(db.query(models.Inmueble).filter_by(id=fila.inmueble_id).first()),
        })
    return salida


@router.post("/lista-espera", status_code=201)
def entrar_espera(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    zona = _zona(db, user, int(data.get("zona_id") or 0))
    regla = _regla(db, zona)
    if not regla.lista_espera_activa:
        raise HTTPException(409, "Esta zona no tiene lista de espera habilitada")
    unidad = unit_access(db, user, int(data.get("inmueble_id") or 0))
    if unidad.conjunto_id != zona.conjunto_id:
        raise HTTPException(422, "El inmueble no pertenece al conjunto de la zona")
    inicio, fin = dt(data["fecha_inicio"]), dt(data["fecha_fin"])
    if fin <= inicio:
        raise HTTPException(422, "La fecha de fin debe ser posterior al inicio")
    if db.query(models_v3.ListaEspera).filter_by(zona_id=zona.id, inmueble_id=unidad.id, estado="esperando").count() >= 3:
        raise HTTPException(409, "Ya tienes varias solicitudes en espera para esta zona")
    posicion = db.query(models_v3.ListaEspera).filter_by(zona_id=zona.id, estado="esperando").count() + 1
    fila = models_v3.ListaEspera(zona_id=zona.id, inmueble_id=unidad.id, solicitante_id=user.id,
                                 fecha_inicio=inicio, fecha_fin=fin, posicion=posicion)
    if posicion > regla.cupos_lista_espera:
        raise HTTPException(409, f"La lista de espera admite {regla.cupos_lista_espera} solicitudes")
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return model_data(fila) | {"zona": zona.nombre, "posicion": posicion}


@router.delete("/lista-espera/{espera_id}", status_code=204)
def salir_espera(espera_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.ListaEspera).filter_by(id=espera_id).first()
    if not fila:
        raise HTTPException(404, "Registro de lista de espera no encontrado")
    if fila.solicitante_id != user.id and not is_admin(user):
        raise HTTPException(403, "Sin permiso")
    fila.estado = "cancelada"
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Cierres por mantenimiento
# ---------------------------------------------------------------------------
@router.get("/cierres")
def listar_cierres(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if is_admin(user) or user.rol == "portero" or user.es_super_admin:
        ids = [conjunto_id] if conjunto_id else alcance(db, user)
        if conjunto_id:
            require_staff_set(db, user, conjunto_id)
    else:
        ids = sorted({u.conjunto_id for u in units_for_user(db, user)})
    zonas = db.query(models.ZonaComun).filter(models.ZonaComun.conjunto_id.in_(ids)).all() if ids else []
    mapa = {z.id: z.nombre for z in zonas}
    if not mapa:
        return []
    filas = db.query(models_v3.CierreZona).filter(models_v3.CierreZona.zona_id.in_(list(mapa))).order_by(models_v3.CierreZona.fecha_inicio.desc()).limit(300).all()
    return [model_data(f) | {"zona": mapa.get(f.zona_id), "activo": bool(f.fecha_inicio <= localnow() <= f.fecha_fin)} for f in filas]


@router.post("/cierres", status_code=201)
def crear_cierre(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    zona = _zona(db, user, int(data.get("zona_id") or 0))
    require_admin_set(db, user, zona.conjunto_id)
    inicio, fin = dt(data["fecha_inicio"]), dt(data["fecha_fin"])
    if fin <= inicio:
        raise HTTPException(422, "La fecha de fin debe ser posterior al inicio")
    motivo = str(data.get("motivo") or "Mantenimiento").strip()
    cierre = models_v3.CierreZona(zona_id=zona.id, fecha_inicio=inicio, fecha_fin=fin, motivo=motivo[:255],
                                  orden_mantenimiento_id=int(data["orden_mantenimiento_id"]) if data.get("orden_mantenimiento_id") else None,
                                  creado_por=user.id)
    db.add(cierre)
    afectadas = _reservas_solapadas(db, zona.id, inicio, fin)
    canceladas = 0
    for reserva in afectadas:
        reserva.estado = models.EstadoReserva.cancelada
        unidad = db.query(models.Inmueble).filter_by(id=reserva.inmueble_id).first()
        for usuario_id in ({unidad.propietario_id, unidad.inquilino_id} - {None} if unidad else set()):
            notificar(db, usuario_id, "Reserva cancelada por mantenimiento",
                      f"{zona.nombre} estará cerrada del {inicio.strftime('%Y-%m-%d %H:%M')} al {fin.strftime('%Y-%m-%d %H:%M')}: {motivo}")
        canceladas += 1
    db.commit()
    db.refresh(cierre)
    return model_data(cierre) | {"zona": zona.nombre, "reservas_afectadas_canceladas": canceladas}


@router.delete("/cierres/{cierre_id}", status_code=204)
def borrar_cierre(cierre_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    cierre = db.query(models_v3.CierreZona).filter_by(id=cierre_id).first()
    if not cierre:
        raise HTTPException(404, "Cierre no encontrado")
    zona = db.query(models.ZonaComun).filter_by(id=cierre.zona_id).first()
    require_admin_set(db, user, zona.conjunto_id)
    exigir_2fa_admin(db, user, otp)
    db.delete(cierre)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Asistencia y penalizaciones
# ---------------------------------------------------------------------------
@router.post("/{reserva_id}/asistencia")
def registrar_asistencia(reserva_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    reserva = db.query(models.Reserva).filter_by(id=reserva_id).first()
    if not reserva:
        raise HTTPException(404, "Reserva no encontrada")
    zona = db.query(models.ZonaComun).filter_by(id=reserva.zona_id).first()
    if not (is_admin(user) or user.rol == "portero" or user.es_super_admin):
        raise HTTPException(403, "Solo portería o administración marcan la asistencia")
    require_staff_set(db, user, zona.conjunto_id)
    asistio = bool(data.get("asistio", True))
    fila = db.query(models_v3.AsistenciaReserva).filter_by(reserva_id=reserva.id).first()
    if fila:
        raise HTTPException(409, "La asistencia ya fue registrada")
    registro = models_v3.AsistenciaReserva(reserva_id=reserva.id, asistio=asistio,
                                           observacion=str(data.get("observacion") or "")[:255] or None, registrado_por=user.id)
    db.add(registro)
    penalizacion = None
    unidad = db.query(models.Inmueble).filter_by(id=reserva.inmueble_id).first()
    regla = _regla(db, zona)
    if not asistio:
        reserva.estado = models.EstadoReserva.cancelada
        db.flush()  # el cupo debe liberarse antes de promover la lista de espera
        if dec(regla.penalizacion_inasistencia) > 0:
            penalizacion = _aplicar_cargo(db, reserva, unidad, "penalizacion",
                                          f"Penalización por inasistencia a {zona.nombre}",
                                          dec(regla.penalizacion_inasistencia), user.id)
        for usuario_id in ({unidad.propietario_id, unidad.inquilino_id} - {None} if unidad else set()):
            notificar(db, usuario_id, "Inasistencia registrada",
                      f"No se registró asistencia a tu reserva de {zona.nombre} del {reserva.fecha_inicio.strftime('%Y-%m-%d %H:%M')}.")
        _promover_lista_espera(db, zona, reserva.fecha_inicio, reserva.fecha_fin)
    db.commit()
    return {"reserva_id": reserva.id, "asistio": asistio, "penalizacion": model_data(penalizacion) if penalizacion else None}


@router.get("/cargos")
def listar_cargos(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.CargoReserva)
    if is_admin(user):
        ids = [conjunto_id] if conjunto_id else alcance(db, user)
        unidades = [u.id for u in db.query(models.Inmueble).filter(models.Inmueble.conjunto_id.in_(ids)).all()] if ids else []
        q = q.filter(models_v3.CargoReserva.inmueble_id.in_(unidades)) if unidades else q.filter(models_v3.CargoReserva.id < 0)
    else:
        q = q.filter(models_v3.CargoReserva.inmueble_id.in_([u.id for u in units_for_user(db, user)]))
    salida = []
    for fila in q.order_by(models_v3.CargoReserva.id.desc()).limit(300).all():
        salida.append(model_data(fila) | {"inmueble": etiqueta_unidad(db.query(models.Inmueble).filter_by(id=fila.inmueble_id).first())})
    return salida


@router.get("/resumen")
def resumen(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if is_admin(user) or user.rol == "portero" or user.es_super_admin:
        ids = [conjunto_id] if conjunto_id else alcance(db, user)
        if conjunto_id:
            require_staff_set(db, user, conjunto_id)
    else:
        ids = sorted({u.conjunto_id for u in units_for_user(db, user)})
    zonas = db.query(models.ZonaComun).filter(models.ZonaComun.conjunto_id.in_(ids)).all() if ids else []
    reservas = db.query(models.Reserva).filter(models.Reserva.zona_id.in_([z.id for z in zonas])).all() if zonas else []
    ahora = localnow()
    return {
        "zonas": len(zonas),
        "reservas_totales": len(reservas),
        "pendientes": len([r for r in reservas if r.estado == models.EstadoReserva.pendiente]),
        "aprobadas_futuras": len([r for r in reservas if r.estado == models.EstadoReserva.aprobada and r.fecha_fin > ahora]),
        "canceladas": len([r for r in reservas if r.estado == models.EstadoReserva.cancelada]),
        "en_lista_espera": db.query(models_v3.ListaEspera).filter(models_v3.ListaEspera.zona_id.in_([z.id for z in zonas]), models_v3.ListaEspera.estado == "esperando").count() if zonas else 0,
        "cierres_activos": db.query(models_v3.CierreZona).filter(models_v3.CierreZona.zona_id.in_([z.id for z in zonas]), models_v3.CierreZona.fecha_inicio <= ahora, models_v3.CierreZona.fecha_fin >= ahora).count() if zonas else 0,
        "inasistencias": db.query(models_v3.AsistenciaReserva).filter(models_v3.AsistenciaReserva.asistio.is_(False)).count(),
        "cargos_pendientes": db.query(models_v3.CargoReserva).filter(models_v3.CargoReserva.estado == "pendiente").count(),
    }


@router.patch("/{reserva_id}/estado")
def cambiar_estado(reserva_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    reserva = db.query(models.Reserva).filter_by(id=reserva_id).first()
    if not reserva:
        raise HTTPException(404, "Reserva no encontrada")
    zona = db.query(models.ZonaComun).filter_by(id=reserva.zona_id).first()
    require_admin_set(db, user, zona.conjunto_id)
    estado = str(data.get("estado") or "")
    if estado not in ("aprobada", "rechazada", "cancelada", "pendiente"):
        raise HTTPException(422, "Estado inválido")
    reserva.estado = models.EstadoReserva(estado)
    unidad = db.query(models.Inmueble).filter_by(id=reserva.inmueble_id).first()
    db.flush()  # deja consistente el cupo antes de promover la lista de espera
    evento = "aprobacion_reserva" if estado == "aprobada" else "rechazo_reserva"
    for usuario_id in ({unidad.propietario_id, unidad.inquilino_id} - {None} if unidad else set()):
        notificar(db, usuario_id, f"Reserva {estado}", f"{zona.nombre} · {reserva.fecha_inicio.strftime('%Y-%m-%d %H:%M')}")
        avisar_evento(db, usuario_id, evento, {
            "zona": zona.nombre, "fecha": reserva.fecha_inicio.strftime("%Y-%m-%d %H:%M"),
            "motivo": str(data.get("motivo") or "sin observaciones"),
            "mensaje": f"Tu reserva de {zona.nombre} para el {reserva.fecha_inicio.strftime('%Y-%m-%d %H:%M')} quedó en estado {estado}.",
        }, conjunto_id=zona.conjunto_id)
    if estado in ("rechazada", "cancelada"):
        _promover_lista_espera(db, zona, reserva.fecha_inicio, reserva.fecha_fin)
    db.commit()
    db.refresh(reserva)
    return model_data(reserva)
