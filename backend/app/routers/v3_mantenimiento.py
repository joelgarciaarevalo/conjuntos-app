"""Seguimiento de mantenimiento: responsables, proveedores, cotizaciones, costos, fotos y fechas límite."""
from __future__ import annotations

import html as html_lib
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.permissions import can_access_set, is_admin, require_admin_set, require_staff_set
from app.security_v3 import dependencia_2fa, exigir_2fa_admin, get_usuario_v3
from app.routers.v3_common import (
    DOC_TYPES, IMAGE_TYPES, admin_only, alcance, avisar_evento, conjunto_de, dec, dt, etiqueta_unidad,
    guardar_archivo, archivo_local, localnow, model_data, money, notificar, tabla, workbook_response,
)

router = APIRouter(prefix="/v3/mantenimiento", tags=["v3 · Mantenimiento"])

ESTADOS = ("abierta", "asignada", "esperando_cotizacion", "en_ejecucion", "completada", "cancelada")
PRIORIDADES = ("baja", "media", "alta", "urgente")


def _orden_visible(db: Session, user: models.Usuario, orden: models_v3.OrdenMantenimiento) -> None:
    if user.es_super_admin:
        return
    if is_admin(user) or user.rol == "portero":
        if not can_access_set(db, user, orden.conjunto_id):
            raise HTTPException(403, "No tienes acceso a este conjunto")
        return
    if orden.responsable_id == user.id:
        return
    unidad = db.query(models.Inmueble).filter(
        (models.Inmueble.propietario_id == user.id) | (models.Inmueble.inquilino_id == user.id)
    ).filter_by(conjunto_id=orden.conjunto_id).first()
    if unidad and orden.inmueble_id in (None, unidad.id):
        return
    raise HTTPException(403, "Sin permiso sobre esta orden de mantenimiento")


# ---------------------------------------------------------------------------
# Proveedores
# ---------------------------------------------------------------------------
@router.get("/proveedores")
def listar_proveedores(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if not (is_admin(user) or user.rol == "portero"):
        raise HTTPException(403, "Catálogo de proveedores para administración y portería")
    ids = alcance(db, user)
    q = db.query(models_v3.Proveedor)
    q = q.filter(models_v3.Proveedor.conjunto_id == conjunto_id) if conjunto_id else q.filter(models_v3.Proveedor.conjunto_id.in_(ids))
    return [model_data(p) for p in q.order_by(models_v3.Proveedor.nombre).all()]


@router.post("/proveedores", status_code=201)
def crear_proveedor(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    conjunto_id = conjunto_de(db, user, data, staff=False)
    nombre = str(data.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(422, "El nombre del proveedor es obligatorio")
    calificacion = data.get("calificacion")
    if calificacion is not None and not 1 <= int(calificacion) <= 5:
        raise HTTPException(422, "La calificación debe estar entre 1 y 5")
    fila = models_v3.Proveedor(
        conjunto_id=conjunto_id, nombre=nombre[:140], nit=str(data.get("nit") or "")[:40] or None,
        especialidad=str(data.get("especialidad") or "")[:80] or None, contacto=str(data.get("contacto") or "")[:120] or None,
        telefono=str(data.get("telefono") or "")[:30] or None, email=str(data.get("email") or "")[:120] or None,
        calificacion=int(calificacion) if calificacion else None, activo=bool(data.get("activo", True)),
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.put("/proveedores/{proveedor_id}")
def actualizar_proveedor(proveedor_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Proveedor).filter_by(id=proveedor_id).first()
    if not fila:
        raise HTTPException(404, "Proveedor no encontrado")
    require_admin_set(db, user, fila.conjunto_id)
    for campo in ("nombre", "nit", "especialidad", "contacto", "telefono", "email"):
        if data.get(campo) is not None:
            setattr(fila, campo, str(data[campo])[:140] or None)
    if data.get("calificacion") is not None:
        valor = int(data["calificacion"])
        if not 1 <= valor <= 5:
            raise HTTPException(422, "La calificación debe estar entre 1 y 5")
        fila.calificacion = valor
    if data.get("activo") is not None:
        fila.activo = bool(data["activo"])
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.delete("/proveedores/{proveedor_id}", status_code=204)
def borrar_proveedor(proveedor_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Proveedor).filter_by(id=proveedor_id).first()
    if not fila:
        raise HTTPException(404, "Proveedor no encontrado")
    require_admin_set(db, user, fila.conjunto_id)
    if db.query(models_v3.OrdenMantenimiento).filter_by(proveedor_id=proveedor_id).first():
        fila.activo = False
        db.commit()
        return Response(status_code=204)
    db.delete(fila)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Órdenes de mantenimiento
# ---------------------------------------------------------------------------
def _orden_detalle(db: Session, orden: models_v3.OrdenMantenimiento) -> dict:
    datos = model_data(orden)
    datos["cotizaciones"] = [model_data(c) for c in db.query(models_v3.CotizacionMantenimiento).filter_by(orden_id=orden.id).order_by(models_v3.CotizacionMantenimiento.id).all()]
    datos["evidencias"] = [model_data(e) for e in db.query(models_v3.EvidenciaMantenimiento).filter_by(orden_id=orden.id).order_by(models_v3.EvidenciaMantenimiento.id).all()]
    datos["avances"] = [model_data(a) for a in db.query(models_v3.AvanceMantenimiento).filter_by(orden_id=orden.id).order_by(models_v3.AvanceMantenimiento.id).all()]
    datos["responsable"] = db.query(models.Usuario.nombre_completo).filter_by(id=orden.responsable_id).scalar() if orden.responsable_id else None
    datos["proveedor"] = db.query(models_v3.Proveedor.nombre).filter_by(id=orden.proveedor_id).scalar() if orden.proveedor_id else None
    datos["zona"] = db.query(models.ZonaComun.nombre).filter_by(id=orden.zona_id).scalar() if orden.zona_id else None
    datos["inmueble"] = etiqueta_unidad(db.query(models.Inmueble).filter_by(id=orden.inmueble_id).first()) if orden.inmueble_id else None
    datos["vencida"] = bool(orden.fecha_limite and orden.estado not in ("completada", "cancelada") and orden.fecha_limite < localnow())
    datos["dias_restantes"] = ((orden.fecha_limite - localnow()).days if orden.fecha_limite else None)
    return datos


@router.get("/ordenes")
def listar_ordenes(conjunto_id: int | None = None, estado: str | None = None, solo_vencidas: bool = False,
                   db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.OrdenMantenimiento)
    if user.es_super_admin:
        pass
    elif is_admin(user) or user.rol == "portero":
        ids = alcance(db, user)
        if conjunto_id:
            if conjunto_id not in ids:
                raise HTTPException(403, "No tienes acceso a este conjunto")
            ids = [conjunto_id]
        q = q.filter(models_v3.OrdenMantenimiento.conjunto_id.in_(ids))
    else:
        unidades = [u.id for u in db.query(models.Inmueble).filter((models.Inmueble.propietario_id == user.id) | (models.Inmueble.inquilino_id == user.id)).all()]
        q = q.filter((models_v3.OrdenMantenimiento.responsable_id == user.id) | (models_v3.OrdenMantenimiento.inmueble_id.in_(unidades)))
    if conjunto_id and (is_admin(user) or user.rol == "portero"):
        q = q.filter(models_v3.OrdenMantenimiento.conjunto_id == conjunto_id)
    if estado:
        if str(estado).lower() in ("undefined", "null", "none", ""):
            estado = None
    if estado:
        if estado not in ESTADOS:
            raise HTTPException(422, "Estado inválido")
        q = q.filter(models_v3.OrdenMantenimiento.estado == estado)
    if solo_vencidas:
        q = q.filter(models_v3.OrdenMantenimiento.fecha_limite.isnot(None),
                     models_v3.OrdenMantenimiento.fecha_limite < localnow(),
                     models_v3.OrdenMantenimiento.estado.notin_(("completada", "cancelada")))
    ordenes = q.order_by(models_v3.OrdenMantenimiento.id.desc()).limit(500).all()
    return [_orden_detalle(db, o) for o in ordenes]


@router.post("/ordenes", status_code=201)
def crear_orden(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    conjunto_id = conjunto_de(db, user, data)
    if not (is_admin(user) or user.es_super_admin or user.rol == "portero"):
        raise HTTPException(403, "Solo administración o portería crean órdenes; los residentes reportan incidentes")
    titulo = str(data.get("titulo") or "").strip()
    descripcion = str(data.get("descripcion") or "").strip()
    if not titulo or not descripcion:
        raise HTTPException(422, "Título y descripción son obligatorios")
    prioridad = str(data.get("prioridad") or "media")
    if prioridad not in PRIORIDADES:
        raise HTTPException(422, "Prioridad inválida")
    inmueble_id = data.get("inmueble_id") or None
    if inmueble_id and not db.query(models.Inmueble.id).filter_by(id=int(inmueble_id), conjunto_id=conjunto_id).first():
        raise HTTPException(422, "El inmueble no pertenece al conjunto")
    zona_id = data.get("zona_id") or None
    if zona_id and not db.query(models.ZonaComun.id).filter_by(id=int(zona_id), conjunto_id=conjunto_id).first():
        raise HTTPException(422, "La zona no pertenece al conjunto")
    responsable_id = data.get("responsable_id") or None
    proveedor_id = data.get("proveedor_id") or None
    fila = models_v3.OrdenMantenimiento(
        conjunto_id=conjunto_id, inmueble_id=int(inmueble_id) if inmueble_id else None,
        zona_id=int(zona_id) if zona_id else None, incidente_id=int(data["incidente_id"]) if data.get("incidente_id") else None,
        titulo=titulo[:160], descripcion=descripcion[:5000], categoria=str(data.get("categoria") or "mantenimiento")[:50],
        prioridad=prioridad, estado=str(data.get("estado") or ("asignada" if responsable_id else "abierta"))[:30],
        responsable_id=int(responsable_id) if responsable_id else None,
        proveedor_id=int(proveedor_id) if proveedor_id else None,
        fecha_limite=dt(data["fecha_limite"]) if data.get("fecha_limite") else None,
        costo_estimado=dec(data["costo_estimado"]) if data.get("costo_estimado") else None,
        creado_por=user.id,
    )
    if fila.estado not in ESTADOS:
        raise HTTPException(422, "Estado inválido")
    db.add(fila)
    db.flush()
    db.add(models_v3.AvanceMantenimiento(orden_id=fila.id, estado=fila.estado, nota=f"Orden creada por {user.nombre_completo}", usuario_id=user.id))
    if fila.responsable_id:
        notificar(db, fila.responsable_id, "Mantenimiento asignado", f"{fila.titulo} · fecha límite {fila.fecha_limite.date().isoformat() if fila.fecha_limite else 'sin definir'}")
        avisar_evento(db, fila.responsable_id, "mantenimiento", {
            "titulo": fila.titulo, "fecha_limite": fila.fecha_limite.date().isoformat() if fila.fecha_limite else "sin definir",
            "mensaje": f"Se te asignó: {fila.titulo}.",
        }, conjunto_id=conjunto_id)
    db.commit()
    db.refresh(fila)
    return _orden_detalle(db, fila)


@router.get("/ordenes/{orden_id}")
def detalle_orden(orden_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.OrdenMantenimiento).filter_by(id=orden_id).first()
    if not fila:
        raise HTTPException(404, "Orden no encontrada")
    _orden_visible(db, user, fila)
    return _orden_detalle(db, fila)


@router.patch("/ordenes/{orden_id}")
def actualizar_orden(orden_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.OrdenMantenimiento).filter_by(id=orden_id).first()
    if not fila:
        raise HTTPException(404, "Orden no encontrada")
    es_gestor = user.es_super_admin or (is_admin(user) and can_access_set(db, user, fila.conjunto_id))
    if not es_gestor and fila.responsable_id != user.id:
        raise HTTPException(403, "Solo administración o el responsable pueden actualizar la orden")
    if data.get("estado") is not None:
        if data["estado"] not in ESTADOS:
            raise HTTPException(422, "Estado inválido")
        fila.estado = data["estado"]
        if data["estado"] == "completada":
            fila.cerrada_en = localnow()
    if data.get("prioridad") is not None:
        if data["prioridad"] not in PRIORIDADES:
            raise HTTPException(422, "Prioridad inválida")
        fila.prioridad = data["prioridad"]
    if not es_gestor and any(k in data for k in ("responsable_id", "proveedor_id", "costo_final", "costo_estimado")):
        raise HTTPException(403, "Solo administración asigna responsables, proveedores y costos")
    if data.get("responsable_id") is not None:
        if data["responsable_id"] in ("", None):
            fila.responsable_id = None
        else:
            objetivo = db.query(models.Usuario).filter_by(id=int(data["responsable_id"])).first()
            if not objetivo:
                raise HTTPException(404, "Responsable no encontrado")
            fila.responsable_id = objetivo.id
            notificar(db, objetivo.id, "Mantenimiento asignado", fila.titulo)
    if data.get("proveedor_id") is not None:
        fila.proveedor_id = int(data["proveedor_id"]) if data["proveedor_id"] else None
    if data.get("fecha_limite") is not None:
        fila.fecha_limite = dt(data["fecha_limite"]) if data["fecha_limite"] else None
    if data.get("costo_estimado") is not None:
        fila.costo_estimado = dec(data["costo_estimado"]) if data["costo_estimado"] not in ("", None) else None
    if data.get("costo_final") is not None:
        fila.costo_final = dec(data["costo_final"]) if data["costo_final"] not in ("", None) else None
    if data.get("titulo"):
        fila.titulo = str(data["titulo"])[:160]
    if data.get("descripcion"):
        fila.descripcion = str(data["descripcion"])[:5000]
    fila.actualizado_en = localnow()
    if data.get("nota"):
        db.add(models_v3.AvanceMantenimiento(orden_id=fila.id, estado=fila.estado, nota=str(data["nota"])[:2000], usuario_id=user.id))
    db.commit()
    db.refresh(fila)
    return _orden_detalle(db, fila)


@router.post("/ordenes/{orden_id}/avances", status_code=201)
def agregar_avance(orden_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.OrdenMantenimiento).filter_by(id=orden_id).first()
    if not fila:
        raise HTTPException(404, "Orden no encontrada")
    _orden_visible(db, user, fila)
    nota = str(data.get("nota") or "").strip()
    if not nota:
        raise HTTPException(422, "La nota del avance es obligatoria")
    avance = models_v3.AvanceMantenimiento(orden_id=fila.id, estado=str(data.get("estado") or fila.estado)[:30], nota=nota[:2000], usuario_id=user.id)
    db.add(avance)
    if data.get("estado") and data["estado"] in ESTADOS:
        fila.estado = data["estado"]
    fila.actualizado_en = localnow()
    db.commit()
    db.refresh(avance)
    return model_data(avance)


# ---------------------------------------------------------------------------
# Cotizaciones
# ---------------------------------------------------------------------------
@router.post("/ordenes/{orden_id}/cotizaciones", status_code=201)
def crear_cotizacion(orden_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.OrdenMantenimiento).filter_by(id=orden_id).first()
    if not fila:
        raise HTTPException(404, "Orden no encontrada")
    require_admin_set(db, user, fila.conjunto_id)
    proveedor_id = data.get("proveedor_id") or None
    proveedor_nombre = str(data.get("proveedor_nombre") or "").strip() or None
    if proveedor_id:
        proveedor = db.query(models_v3.Proveedor).filter_by(id=int(proveedor_id)).first()
        if not proveedor:
            raise HTTPException(404, "Proveedor no encontrado")
        proveedor_nombre = proveedor_nombre or proveedor.nombre
    if not proveedor_nombre:
        raise HTTPException(422, "Indica el proveedor de la cotización")
    monto = dec(data.get("monto"))
    if monto <= 0:
        raise HTTPException(422, "El monto cotizado debe ser mayor que cero")
    cotizacion = models_v3.CotizacionMantenimiento(
        orden_id=fila.id, proveedor_id=int(proveedor_id) if proveedor_id else None, proveedor_nombre=proveedor_nombre[:140],
        monto=monto, descripcion=str(data.get("descripcion") or "")[:2000] or None,
        validez_hasta=datetime.fromisoformat(str(data["validez_hasta"])).date() if data.get("validez_hasta") else None,
        creado_por=user.id,
    )
    db.add(cotizacion)
    if fila.estado in ("abierta", "asignada"):
        fila.estado = "esperando_cotizacion"
    fila.actualizado_en = localnow()
    db.commit()
    db.refresh(cotizacion)
    return model_data(cotizacion)


@router.patch("/cotizaciones/{cotizacion_id}")
def decidir_cotizacion(cotizacion_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.CotizacionMantenimiento).filter_by(id=cotizacion_id).first()
    if not fila:
        raise HTTPException(404, "Cotización no encontrada")
    orden = db.query(models_v3.OrdenMantenimiento).filter_by(id=fila.orden_id).first()
    require_admin_set(db, user, orden.conjunto_id)
    accion = str(data.get("accion") or data.get("estado") or "").lower()
    if accion not in ("seleccionar", "seleccionada", "rechazar", "rechazada"):
        raise HTTPException(422, "Acción inválida: seleccionar o rechazar")
    if accion in ("seleccionar", "seleccionada"):
        if fila.aprobacion_estado != "aprobada":
            raise HTTPException(409, "Aprueba la cotización antes de seleccionarla")
        for otra in db.query(models_v3.CotizacionMantenimiento).filter_by(orden_id=fila.orden_id).all():
            if otra.id != fila.id and otra.estado == "seleccionada":
                otra.estado = "rechazada"
        fila.estado = "seleccionada"
        orden.costo_estimado = fila.monto
        orden.proveedor_id = fila.proveedor_id or orden.proveedor_id
        orden.estado = "en_ejecucion" if orden.estado != "completada" else orden.estado
    else:
        fila.estado = "rechazada"
    orden.actualizado_en = localnow()
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.patch("/cotizaciones/{cotizacion_id}/aprobacion")
def aprobar_gasto_cotizacion(cotizacion_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    """Registra una decisión de gasto independiente de la selección del proveedor."""
    fila = db.query(models_v3.CotizacionMantenimiento).filter_by(id=cotizacion_id).first()
    if not fila:
        raise HTTPException(404, "Cotización no encontrada")
    orden = db.query(models_v3.OrdenMantenimiento).filter_by(id=fila.orden_id).first()
    require_admin_set(db, user, orden.conjunto_id)
    decision = str(data.get("decision") or "").lower()
    if decision not in ("aprobada", "rechazada"):
        raise HTTPException(422, "La decisión debe ser aprobada o rechazada")
    if fila.estado == "seleccionada":
        raise HTTPException(409, "No se puede cambiar la aprobación de una cotización ya seleccionada")
    nota = str(data.get("nota") or "").strip()
    fila.aprobacion_estado = decision
    fila.aprobada_por = user.id
    fila.aprobada_en = localnow()
    fila.nota_aprobacion = nota[:2000] or None
    orden.actualizado_en = localnow()
    db.add(models_v3.AvanceMantenimiento(
        orden_id=orden.id, estado=orden.estado,
        nota=f"Cotización #{fila.id} {decision} por {user.nombre_completo}" + (f": {nota[:400]}" if nota else ""),
        usuario_id=user.id,
    ))
    db.commit()
    db.refresh(fila)
    return model_data(fila)


# ---------------------------------------------------------------------------
# Evidencias (fotos y soportes)
# ---------------------------------------------------------------------------
@router.post("/ordenes/{orden_id}/evidencias", status_code=201)
async def subir_evidencia(orden_id: int, file: UploadFile = File(...), descripcion: str | None = None,
                          db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.OrdenMantenimiento).filter_by(id=orden_id).first()
    if not fila:
        raise HTTPException(404, "Orden no encontrada")
    _orden_visible(db, user, fila)
    url = await guardar_archivo(file, IMAGE_TYPES)
    evidencia = models_v3.EvidenciaMantenimiento(orden_id=fila.id, url=url, tipo="foto", descripcion=(descripcion or "")[:255] or None, subido_por=user.id)
    db.add(evidencia)
    fila.actualizado_en = localnow()
    db.commit()
    db.refresh(evidencia)
    return model_data(evidencia)


@router.post("/ordenes/{orden_id}/soportes", status_code=201)
async def subir_soporte(orden_id: int, file: UploadFile = File(...), descripcion: str | None = None,
                        db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.OrdenMantenimiento).filter_by(id=orden_id).first()
    if not fila:
        raise HTTPException(404, "Orden no encontrada")
    require_admin_set(db, user, fila.conjunto_id)
    url = await guardar_archivo(file, DOC_TYPES)
    evidencia = models_v3.EvidenciaMantenimiento(orden_id=fila.id, url=url, tipo="soporte", descripcion=(descripcion or "")[:255] or None, subido_por=user.id)
    db.add(evidencia)
    db.commit()
    db.refresh(evidencia)
    return model_data(evidencia)


# ---------------------------------------------------------------------------
# Reportes
# ---------------------------------------------------------------------------
@router.get("/vencidas")
def ordenes_vencidas(db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if not (is_admin(user) or user.rol == "portero" or user.es_super_admin):
        raise HTTPException(403, "Disponible para administración y portería")
    ids = alcance(db, user)
    q = db.query(models_v3.OrdenMantenimiento).filter(
        models_v3.OrdenMantenimiento.conjunto_id.in_(ids),
        models_v3.OrdenMantenimiento.fecha_limite.isnot(None),
        models_v3.OrdenMantenimiento.fecha_limite < localnow(),
        models_v3.OrdenMantenimiento.estado.notin_(("completada", "cancelada")),
    )
    return [_orden_detalle(db, o) for o in q.order_by(models_v3.OrdenMantenimiento.fecha_limite).all()]


@router.get("/resumen")
def resumen(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if not (is_admin(user) or user.rol == "portero" or user.es_super_admin):
        raise HTTPException(403, "Disponible para administración y portería")
    ids = [conjunto_id] if conjunto_id else alcance(db, user)
    if conjunto_id:
        require_staff_set(db, user, conjunto_id)
    ordenes = db.query(models_v3.OrdenMantenimiento).filter(models_v3.OrdenMantenimiento.conjunto_id.in_(ids)).all() if ids else []
    ahora = localnow()
    return {
        "total": len(ordenes),
        "abiertas": len([o for o in ordenes if o.estado in ("abierta", "asignada", "esperando_cotizacion")]),
        "en_ejecucion": len([o for o in ordenes if o.estado == "en_ejecucion"]),
        "completadas": len([o for o in ordenes if o.estado == "completada"]),
        "vencidas": len([o for o in ordenes if o.fecha_limite and o.fecha_limite < ahora and o.estado not in ("completada", "cancelada")]),
        "costo_final_total": str(sum((dec(o.costo_final) for o in ordenes if o.costo_final), dec("0"))),
        "costo_estimado_total": str(sum((dec(o.costo_estimado) for o in ordenes if o.costo_estimado), dec("0"))),
        "proveedores_activos": db.query(models_v3.Proveedor).filter(models_v3.Proveedor.conjunto_id.in_(ids), models_v3.Proveedor.activo.is_(True)).count() if ids else 0,
    }


@router.get("/export.xlsx")
def exportar(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    admin_only(user)
    ids = [conjunto_id] if conjunto_id else alcance(db, user)
    ordenes = db.query(models_v3.OrdenMantenimiento).filter(models_v3.OrdenMantenimiento.conjunto_id.in_(ids)).order_by(models_v3.OrdenMantenimiento.id.desc()).all() if ids else []
    filas = []
    for o in ordenes:
        filas.append([o.id, o.conjunto_id, o.titulo, o.categoria, o.prioridad, o.estado,
                      db.query(models.Usuario.nombre_completo).filter_by(id=o.responsable_id).scalar() if o.responsable_id else "",
                      db.query(models_v3.Proveedor.nombre).filter_by(id=o.proveedor_id).scalar() if o.proveedor_id else "",
                      o.fecha_limite.strftime("%Y-%m-%d %H:%M") if o.fecha_limite else "",
                      str(o.costo_estimado or ""), str(o.costo_final or ""),
                      o.creado_en.strftime("%Y-%m-%d") if o.creado_en else ""])
    wb = tabla(["id", "conjunto_id", "titulo", "categoria", "prioridad", "estado", "responsable", "proveedor", "fecha_limite", "costo_estimado", "costo_final", "creado_en"], filas, "Mantenimiento")
    return workbook_response(wb, "iris-mantenimiento.xlsx")
