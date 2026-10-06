"""Control de visitantes: autorización desde portería, lista de invitados, placa,
registro de salida y alertas al residente."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.permissions import can_access_set, is_admin, require_admin_set, require_staff_set
from app.security_v3 import get_usuario_v3
from app.routers.v3_common import (
    admin_only, alcance, avisar_evento, conjunto_de, dt, etiqueta_unidad, localnow, model_data,
    notificar, tabla, workbook_response, unit_access, units_for_user,
)

router = APIRouter(prefix="/v3/visitantes", tags=["v3 · Visitantes"])

DIAS = {"lun": 1, "mar": 2, "mie": 3, "mié": 3, "jue": 4, "vie": 5, "sab": 6, "sáb": 6, "dom": 7}


def _normalizar_dias(valor) -> str | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, (list, tuple)):
        partes = [str(v).strip().lower() for v in valor]
    else:
        partes = [p.strip().lower() for p in str(valor).split(",") if p.strip()]
    numeros = sorted({str(DIAS.get(p, int(p) if str(p).isdigit() else 0)) for p in partes if str(p).isdigit() or p in DIAS})
    numeros = [n for n in numeros if n != "0"]
    return ",".join(numeros) or None


def _unidad_visible(db: Session, user: models.Usuario, unidad_id: int) -> models.Inmueble:
    if is_admin(user) or user.rol == "portero":
        unidad = db.query(models.Inmueble).filter_by(id=unidad_id).first()
        if not unidad:
            raise HTTPException(404, "Inmueble no encontrado")
        require_staff_set(db, user, unidad.conjunto_id)
        return unidad
    return unit_access(db, user, unidad_id)


def _autorizacion_valida(db: Session, autorizacion: models_v3.AutorizacionVisita) -> tuple[bool, str]:
    ahora = localnow()
    if autorizacion.estado != "activa":
        return False, f"La autorización está {autorizacion.estado}"
    if autorizacion.valido_desde and autorizacion.valido_desde > ahora:
        return False, "La autorización aún no está vigente"
    if autorizacion.valido_hasta and autorizacion.valido_hasta < ahora:
        autorizacion.estado = "expirada"
        return False, "La autorización venció"
    if autorizacion.usos_maximos is not None and autorizacion.usos_actuales >= autorizacion.usos_maximos:
        autorizacion.estado = "usada"
        return False, "La autorización agotó sus usos"
    if autorizacion.recurrente and autorizacion.dias_semana:
        permitidos = {int(x) for x in autorizacion.dias_semana.split(",") if x.strip().isdigit()}
        if permitidos and ahora.isoweekday() not in permitidos:
            return False, "La autorización recurrente no aplica para hoy"
    return True, "Autorización vigente"


# ---------------------------------------------------------------------------
# Directorio de visitantes y lista de invitados
# ---------------------------------------------------------------------------
@router.get("/directorio")
def directorio(inmueble_id: int | None = None, conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.Visitante)
    if is_admin(user) or user.rol == "portero":
        ids = [conjunto_id] if conjunto_id else alcance(db, user)
        if conjunto_id:
            require_staff_set(db, user, conjunto_id)
        q = q.filter(models_v3.Visitante.conjunto_id.in_(ids))
    else:
        unidades = [u.id for u in units_for_user(db, user)]
        q = q.filter(models_v3.Visitante.inmueble_id.in_(unidades))
    if inmueble_id:
        q = q.filter(models_v3.Visitante.inmueble_id == inmueble_id)
    return [model_data(v) for v in q.order_by(models_v3.Visitante.nombre).limit(500).all()]


@router.post("/directorio", status_code=201)
def crear_visitante(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    unidad = _unidad_visible(db, user, int(data.get("inmueble_id") or 0))
    nombre = str(data.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(422, "El nombre del visitante es obligatorio")
    fila = models_v3.Visitante(
        conjunto_id=unidad.conjunto_id, inmueble_id=unidad.id, nombre=nombre[:120],
        documento=str(data.get("documento") or "")[:30] or None, telefono=str(data.get("telefono") or "")[:30] or None,
        placa=(str(data.get("placa") or "").strip().upper() or None),
        tipo=str(data.get("tipo") or "visitante")[:20], empresa=str(data.get("empresa") or "")[:120] or None,
        notas=str(data.get("notas") or "")[:255] or None, creado_por=user.id,
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.get("/autorizaciones")
def listar_autorizaciones(inmueble_id: int | None = None, solo_activas: bool = False, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.AutorizacionVisita)
    if is_admin(user) or user.rol == "portero":
        q = q.filter(models_v3.AutorizacionVisita.conjunto_id.in_(alcance(db, user)))
    else:
        q = q.filter(models_v3.AutorizacionVisita.residente_id == user.id)
    if inmueble_id:
        q = q.filter(models_v3.AutorizacionVisita.inmueble_id == inmueble_id)
    if solo_activas:
        q = q.filter(models_v3.AutorizacionVisita.estado == "activa")
    salida = []
    for fila in q.order_by(models_v3.AutorizacionVisita.id.desc()).limit(300).all():
        datos = model_data(fila)
        visitante = db.query(models_v3.Visitante).filter_by(id=fila.visitante_id).first()
        datos["visitante"] = visitante.nombre if visitante else None
        datos["placa"] = visitante.placa if visitante else None
        datos["inmueble"] = etiqueta_unidad(db.query(models.Inmueble).filter_by(id=fila.inmueble_id).first())
        datos["vigente"] = _autorizacion_valida(db, fila)[0]
        salida.append(datos)
    return salida


@router.post("/autorizaciones", status_code=201)
def crear_autorizacion(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    """El residente autoriza una visita (desde la app o desde portería a su nombre)."""
    visitante_id = data.get("visitante_id")
    unidad_id = data.get("inmueble_id")
    if visitante_id:
        visitante = db.query(models_v3.Visitante).filter_by(id=int(visitante_id)).first()
        if not visitante:
            raise HTTPException(404, "Visitante no encontrado")
        unidad = db.query(models.Inmueble).filter_by(id=visitante.inmueble_id).first()
        if unidad is None:
            unidad = _unidad_visible(db, user, int(unidad_id or 0))
    else:
        unidad = _unidad_visible(db, user, int(unidad_id or 0))
        nombre = str(data.get("nombre") or "").strip()
        if not nombre:
            raise HTTPException(422, "Indica el visitante (visitante_id o nombre)")
        visitante = models_v3.Visitante(
            conjunto_id=unidad.conjunto_id, inmueble_id=unidad.id, nombre=nombre[:120],
            documento=str(data.get("documento") or "")[:30] or None, telefono=str(data.get("telefono") or "")[:30] or None,
            placa=(str(data.get("placa") or "").strip().upper() or None), tipo=str(data.get("tipo") or "visitante")[:20],
            notas=str(data.get("notas") or "")[:255] or None, creado_por=user.id,
        )
        db.add(visitante)
        db.flush()
    if not is_admin(user) and user.rol != "portero" and unidad.id not in [u.id for u in units_for_user(db, user)]:
        raise HTTPException(403, "No puedes autorizar visitas para ese inmueble")
    desde = dt(data["valido_desde"]) if data.get("valido_desde") else localnow()
    hasta = dt(data["valido_hasta"]) if data.get("valido_hasta") else None
    if hasta and hasta <= desde:
        raise HTTPException(422, "La vigencia final debe ser posterior al inicio")
    usos = data.get("usos_maximos")
    usos = int(usos) if usos not in (None, "") else None
    if usos is not None and usos <= 0:
        raise HTTPException(422, "Los usos máximos deben ser mayores que cero")
    fila = models_v3.AutorizacionVisita(
        conjunto_id=unidad.conjunto_id, inmueble_id=unidad.id, visitante_id=visitante.id,
        residente_id=user.id if not (is_admin(user) or user.rol == "portero") else int(data.get("residente_id") or (unidad.propietario_id or unidad.inquilino_id)),
        valido_desde=desde, valido_hasta=hasta, recurrente=bool(data.get("recurrente", False)),
        dias_semana=_normalizar_dias(data.get("dias_semana")), usos_maximos=usos,
        permite_vehiculo=bool(data.get("permite_vehiculo", bool(visitante.placa))),
        observacion=str(data.get("observacion") or "")[:255] or None,
    )
    if data.get("pin"):
        from app.services.crypto_v3 import hash_valor
        fila.pin_hash = hash_valor(str(data["pin"]))[:64]
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return {**model_data(fila), "visitante": visitante.nombre, "placa": visitante.placa}


@router.delete("/autorizaciones/{autorizacion_id}", status_code=204)
def cancelar_autorizacion(autorizacion_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.AutorizacionVisita).filter_by(id=autorizacion_id).first()
    if not fila:
        raise HTTPException(404, "Autorización no encontrada")
    if fila.residente_id != user.id:
        require_staff_set(db, user, fila.conjunto_id)
    fila.estado = "cancelada"
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Portería: ingreso y salida
# ---------------------------------------------------------------------------
@router.post("/accesos", status_code=201)
def registrar_ingreso(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    """Portería registra el ingreso, validando la autorización del residente."""
    if not (is_admin(user) or user.rol == "portero" or user.es_super_admin):
        raise HTTPException(403, "Solo portería o administración registran accesos")
    unidad = db.query(models.Inmueble).filter_by(id=int(data.get("inmueble_id") or 0)).first()
    if not unidad:
        raise HTTPException(404, "Inmueble no encontrado")
    require_staff_set(db, user, unidad.conjunto_id)
    nombre = str(data.get("nombre") or "").strip()
    autorizacion = None
    visitante = None
    if data.get("autorizacion_id"):
        autorizacion = db.query(models_v3.AutorizacionVisita).filter_by(id=int(data["autorizacion_id"]), inmueble_id=unidad.id).first()
        if not autorizacion:
            raise HTTPException(404, "Autorización no encontrada para este inmueble")
        visitante = db.query(models_v3.Visitante).filter_by(id=autorizacion.visitante_id).first()
    if not autorizacion and data.get("visitante_id"):
        visitante = db.query(models_v3.Visitante).filter_by(id=int(data["visitante_id"])).first()
        if visitante:
            autorizacion = db.query(models_v3.AutorizacionVisita).filter_by(
                visitante_id=visitante.id, estado="activa"
            ).order_by(models_v3.AutorizacionVisita.id.desc()).first()
    if not autorizacion and not data.get("autorizacion_manual"):
        candidatas = db.query(models_v3.AutorizacionVisita).filter_by(inmueble_id=unidad.id, estado="activa").all()
        for candidata in candidatas:
            vigente, _ = _autorizacion_valida(db, candidata)
            if vigente:
                visitante_candidato = db.query(models_v3.Visitante).filter_by(id=candidata.visitante_id).first()
                if visitante_candidato and (not nombre or visitante_candidato.nombre.lower() == nombre.lower()):
                    autorizacion, visitante = candidata, visitante_candidato
                    break

    autorizado = False
    detalle_autorizacion = "Ingreso sin autorización previa (registro manual del residente)"
    if autorizacion:
        vigente, motivo = _autorizacion_valida(db, autorizacion)
        if vigente:
            autorizado = True
            detalle_autorizacion = "Autorización vigente del residente"
            autorizacion.usos_actuales += 1
            if autorizacion.usos_maximos is not None and autorizacion.usos_actuales >= autorizacion.usos_maximos:
                autorizacion.estado = "usada"
        else:
            detalle_autorizacion = f"Autorización no vigente: {motivo}"

    if not nombre and visitante:
        nombre = visitante.nombre
    if not nombre:
        raise HTTPException(422, "Indica el nombre del visitante")

    placa = (str(data.get("placa") or (visitante.placa if visitante else "") or "").strip().upper() or None)
    if placa and autorizacion and not autorizacion.permite_vehiculo and not data.get("autorizacion_manual"):
        raise HTTPException(409, "La autorización no permite el ingreso de vehículo; activa la casilla de vehículo o registra una autorización manual de portería")

    fila = models_v3.RegistroAcceso(
        conjunto_id=unidad.conjunto_id, inmueble_id=unidad.id, visitante_id=visitante.id if visitante else None,
        autorizacion_id=autorizacion.id if autorizacion else None, nombre_visitante=nombre[:120],
        documento=str(data.get("documento") or (visitante.documento if visitante else "") or "")[:30] or None,
        placa=placa, tipo=str(data.get("tipo") or (visitante.tipo if visitante else "visitante"))[:20],
        registrado_por=user.id, autorizado_por_residente=autorizado,
        alerta_detalle=detalle_autorizacion[:255],
        observacion=str(data.get("observacion") or "")[:255] or None,
    )

    # Alerta al residente (in-app + WhatsApp/SMS si otorgó consentimiento)
    residentes = [x for x in {unidad.propietario_id, unidad.inquilino_id} - {None}]
    hora = localnow().strftime("%H:%M")
    for residente_id in residentes:
        notificar(db, residente_id, "Ingreso de visitante",
                  f"{nombre} ingresó a {etiqueta_unidad(unidad)} a las {hora}. Placa: {placa or 'no aplica'}. {detalle_autorizacion}")
        resultado = avisar_evento(db, residente_id, "visita", {
            "visitante": nombre, "inmueble": etiqueta_unidad(unidad), "hora": hora, "placa": placa or "no aplica",
            "mensaje": f"{nombre} ingresó a las {hora}. Placa: {placa or 'no aplica'}.",
        }, conjunto_id=unidad.conjunto_id)
        if resultado.get("enviado"):
            fila.alerta_enviada = True
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return {**model_data(fila), "inmueble": etiqueta_unidad(unidad), "autorizado": autorizado, "detalle_autorizacion": detalle_autorizacion}


@router.patch("/accesos/{acceso_id}/salida")
def registrar_salida(acceso_id: int, data: dict | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if not (is_admin(user) or user.rol == "portero" or user.es_super_admin):
        raise HTTPException(403, "Solo portería o administración registran salidas")
    fila = db.query(models_v3.RegistroAcceso).filter_by(id=acceso_id).first()
    if not fila:
        raise HTTPException(404, "Registro de acceso no encontrado")
    require_staff_set(db, user, fila.conjunto_id)
    if fila.salida_en:
        raise HTTPException(409, "La salida ya fue registrada")
    fila.salida_en = localnow()
    if (data or {}).get("observacion"):
        fila.observacion = str(data["observacion"])[:255]
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.get("/accesos")
def listar_accesos(conjunto_id: int | None = None, en_sitio: bool = False, desde: str | None = None, hasta: str | None = None,
                   inmueble_id: int | None = None, limit: int = 200, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.RegistroAcceso)
    if is_admin(user) or user.rol == "portero":
        ids = [conjunto_id] if conjunto_id else alcance(db, user)
        if conjunto_id:
            require_staff_set(db, user, conjunto_id)
        q = q.filter(models_v3.RegistroAcceso.conjunto_id.in_(ids))
    else:
        unidades = [u.id for u in units_for_user(db, user)]
        q = q.filter(models_v3.RegistroAcceso.inmueble_id.in_(unidades))
    if inmueble_id:
        q = q.filter(models_v3.RegistroAcceso.inmueble_id == inmueble_id)
    if en_sitio:
        q = q.filter(models_v3.RegistroAcceso.salida_en.is_(None))
    if desde:
        q = q.filter(models_v3.RegistroAcceso.ingreso_en >= dt(desde))
    if hasta:
        q = q.filter(models_v3.RegistroAcceso.ingreso_en <= dt(hasta))
    filas = q.order_by(models_v3.RegistroAcceso.id.desc()).limit(max(1, min(limit, 500))).all()
    salida = []
    for fila in filas:
        datos = model_data(fila)
        datos["inmueble"] = etiqueta_unidad(db.query(models.Inmueble).filter_by(id=fila.inmueble_id).first())
        datos["en_sitio"] = fila.salida_en is None
        datos["portero"] = db.query(models.Usuario.nombre_completo).filter_by(id=fila.registrado_por).scalar()
        salida.append(datos)
    return salida


@router.get("/en-sitio")
def en_sitio(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if not (is_admin(user) or user.rol == "portero" or user.es_super_admin):
        raise HTTPException(403, "Disponible para portería y administración")
    ids = [conjunto_id] if conjunto_id else alcance(db, user)
    if conjunto_id:
        require_staff_set(db, user, conjunto_id)
    filas = db.query(models_v3.RegistroAcceso).filter(
        models_v3.RegistroAcceso.conjunto_id.in_(ids),
        models_v3.RegistroAcceso.salida_en.is_(None),
    ).order_by(models_v3.RegistroAcceso.ingreso_en).all()
    salida = []
    for fila in filas:
        datos = model_data(fila)
        datos["inmueble"] = etiqueta_unidad(db.query(models.Inmueble).filter_by(id=fila.inmueble_id).first())
        datos["permanencia_minutos"] = int((localnow() - fila.ingreso_en).total_seconds() // 60)
        salida.append(datos)
    return salida


@router.get("/resumen")
def resumen(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if not (is_admin(user) or user.rol == "portero" or user.es_super_admin):
        raise HTTPException(403, "Disponible para portería y administración")
    ids = [conjunto_id] if conjunto_id else alcance(db, user)
    if conjunto_id:
        require_staff_set(db, user, conjunto_id)
    hoy = localnow().replace(hour=0, minute=0, second=0, microsecond=0)
    accesos_hoy = db.query(models_v3.RegistroAcceso).filter(
        models_v3.RegistroAcceso.conjunto_id.in_(ids), models_v3.RegistroAcceso.ingreso_en >= hoy
    ).all() if ids else []
    return {
        "accesos_hoy": len(accesos_hoy),
        "en_sitio": db.query(models_v3.RegistroAcceso).filter(models_v3.RegistroAcceso.conjunto_id.in_(ids), models_v3.RegistroAcceso.salida_en.is_(None)).count() if ids else 0,
        "sin_autorizacion_hoy": len([a for a in accesos_hoy if not a.autorizado_por_residente]),
        "con_vehiculo_hoy": len([a for a in accesos_hoy if a.placa]),
        "autorizaciones_activas": db.query(models_v3.AutorizacionVisita).filter(
            models_v3.AutorizacionVisita.conjunto_id.in_(ids), models_v3.AutorizacionVisita.estado == "activa"
        ).count() if ids else 0,
        "alertas_enviadas_hoy": len([a for a in accesos_hoy if a.alerta_enviada]),
    }


@router.get("/export.xlsx")
def exportar(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    admin_only(user)
    ids = [conjunto_id] if conjunto_id else alcance(db, user)
    filas = db.query(models_v3.RegistroAcceso).filter(models_v3.RegistroAcceso.conjunto_id.in_(ids)).order_by(models_v3.RegistroAcceso.id.desc()).limit(5000).all() if ids else []
    datos = [[f.id, f.conjunto_id, etiqueta_unidad(db.query(models.Inmueble).filter_by(id=f.inmueble_id).first()),
              f.nombre_visitante, f.documento, f.placa, f.tipo,
              f.ingreso_en.strftime("%Y-%m-%d %H:%M") if f.ingreso_en else "",
              f.salida_en.strftime("%Y-%m-%d %H:%M") if f.salida_en else "",
              "sí" if f.autorizado_por_residente else "no", "sí" if f.alerta_enviada else "no"] for f in filas]
    wb = tabla(["id", "conjunto_id", "inmueble", "visitante", "documento", "placa", "tipo", "ingreso", "salida", "autorizado", "alerta_enviada"], datos, "Visitantes")
    return workbook_response(wb, "iris-visitantes.xlsx")
