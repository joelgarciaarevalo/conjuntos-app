"""Panel de indicadores: cartera vencida, tiempos de respuesta de PQRS,
uso de zonas y volumen de paquetes (más otros indicadores operativos)."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.permissions import can_access_set, is_admin, require_admin_set
from app.security_v3 import get_usuario_v3
from app.routers.v3_common import alcance, cartera_vencida, dec, etiqueta_unidad, localnow, tabla, workbook_response

router = APIRouter(prefix="/v3/indicadores", tags=["v3 · Indicadores"])

SLA_HORAS = {"peticion": 72, "queja": 120, "reclamo": 72, "sugerencia": 168}


def _rango(desde: str | None, hasta: str | None) -> tuple[datetime, datetime]:
    fin = datetime.fromisoformat(hasta) if hasta else localnow()
    inicio = datetime.fromisoformat(desde) if desde else fin - timedelta(days=90)
    if fin < inicio:
        raise HTTPException(422, "El rango de fechas es inválido")
    return inicio, fin


def _clave_periodo(momento: datetime) -> str:
    return momento.strftime("%Y-%m")


def _tid_pqrs(db: Session, pqrs: models.PQRS) -> datetime | None:
    fila = db.query(models.Auditoria.creado_en).filter(
        models.Auditoria.ruta.like(f"/pqrs/{pqrs.id}/responder%")
    ).order_by(models.Auditoria.creado_en).first()
    return fila[0] if fila else (pqrs.fecha_radicacion if getattr(pqrs.estado, "value", pqrs.estado) == "resuelto" else None)


@router.get("/panel")
def panel(conjunto_id: int | None = None, desde: str | None = None, hasta: str | None = None,
          db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    if not (is_admin(user) or user.rol == "portero" or user.es_super_admin):
        raise HTTPException(403, "El panel de indicadores es para administración y portería")
    ids = [conjunto_id] if conjunto_id else alcance(db, user)
    if conjunto_id:
        require_admin_set(db, user, conjunto_id)
    if not ids:
        return {"conjuntos": 0, "mensaje": "Sin conjuntos a tu cargo"}
    inicio, fin = _rango(desde, hasta)

    unidades = db.query(models.Inmueble).filter(models.Inmueble.conjunto_id.in_(ids)).all()
    unidades_ids = [u.id for u in unidades]
    mapa_unidades = {u.id: etiqueta_unidad(u) for u in unidades}

    # --- Cartera vencida ---
    cartera = cartera_vencida(db, ids)
    cargos = db.query(models_v3.CargoCartera).filter(
        models_v3.CargoCartera.conjunto_id.in_(ids), models_v3.CargoCartera.estado == "pendiente"
    ).all()
    cartera["cargos_monto"] = str(sum((dec(c.monto) for c in cargos), dec("0")))
    cartera["top_morosos"] = cartera["por_inmueble"][:5] if "por_inmueble" in cartera else []

    # --- Tiempos de respuesta de PQRS ---
    pqrs = db.query(models.PQRS).filter(models.PQRS.inmueble_id.in_(unidades_ids)).all() if unidades_ids else []
    pqrs_periodo = [p for p in pqrs if inicio <= p.fecha_radicacion <= fin]
    resueltas, pendientes, tiempos = 0, 0, []
    por_tipo: dict[str, dict] = {}
    cumplen, incumplen = 0, 0
    for registro in pqrs_periodo:
        tipo = getattr(registro.tipo, "value", registro.tipo)
        contador = por_tipo.setdefault(tipo, {"total": 0, "resueltas": 0, "horas_promedio": None, "_horas": []})
        contador["total"] += 1
        estado = getattr(registro.estado, "value", registro.estado)
        if estado == "radicado":
            pendientes += 1
        resolucion = _tid_pqrs(db, registro)
        if estado in ("resuelto", "en_proceso") and resolucion:
            horas = (resolucion - registro.fecha_radicacion).total_seconds() / 3600
            tiempos.append(horas)
            contador["_horas"].append(horas)
            contador["resueltas"] += 1
            if estado == "resuelto":
                resueltas += 1
                objetivo = SLA_HORAS.get(tipo, 72)
                cumplen += 1 if horas <= objetivo else 0
                incumplen += 0 if horas <= objetivo else 1
    for contador in por_tipo.values():
        horas = contador.pop("_horas")
        contador["horas_promedio"] = round(sum(horas) / len(horas), 2) if horas else None
    tiempo_promedio = round(sum(tiempos) / len(tiempos), 2) if tiempos else None
    total_evaluado = cumplen + incumplen

    # --- Uso de zonas ---
    zonas = db.query(models.ZonaComun).filter(models.ZonaComun.conjunto_id.in_(ids)).all()
    reservas = db.query(models.Reserva).filter(
        models.Reserva.zona_id.in_([z.id for z in zonas]),
        models.Reserva.fecha_inicio >= inicio, models.Reserva.fecha_inicio <= fin,
    ).all() if zonas else []
    uso_zonas = []
    for zona in zonas:
        propias = [r for r in reservas if r.zona_id == zona.id]
        canceladas = len([r for r in propias if getattr(r.estado, "value", r.estado) == "cancelada"])
        horas = sum(((r.fecha_fin - r.fecha_inicio).total_seconds() / 3600) for r in propias)
        regla = db.query(models_v3.ReglaZonaReserva).filter_by(zona_id=zona.id).first()
        dias = max(1, (fin - inicio).days)
        capacidad = (dias * 24 * 60) / max(15, regla.duracion_franja_minutos if regla else 60) * (regla.cupos_por_franja if regla else 1)
        reglas_dict = {
            "cupos_por_franja": regla.cupos_por_franja if regla else 1,
            "franja_minutos": regla.duracion_franja_minutos if regla else 60,
            "requiere_pago": bool(regla.requiere_pago) if regla else False,
            "tarifa": str(regla.tarifa_por_uso) if regla else "0",
        }
        uso_zonas.append({
            "zona_id": zona.id, "zona": zona.nombre, "reservas": len(propias), "canceladas": canceladas,
            "cancelacion_pct": round(canceladas / len(propias) * 100, 1) if propias else 0.0,
            "horas_reservadas": round(horas, 2),
            "ocupacion_estimada_pct": round(min(100.0, horas / (capacidad / 60) * 100), 1) if capacidad else 0.0,
            **reglas_dict,
        })
    uso_zonas.sort(key=lambda z: -z["reservas"])
    en_espera = db.query(models_v3.ListaEspera).filter(
        models_v3.ListaEspera.zona_id.in_([z.id for z in zonas]), models_v3.ListaEspera.estado == "esperando"
    ).count() if zonas else 0

    # --- Volumen de paquetes ---
    paquetes = db.query(models.Paquete).filter(
        models.Paquete.inmueble_id.in_(unidades_ids), models.Paquete.recibido_en >= inicio, models.Paquete.recibido_en <= fin
    ).all() if unidades_ids else []
    por_mes: dict[str, int] = {}
    for paquete in paquetes:
        por_mes[_clave_periodo(paquete.recibido_en)] = por_mes.get(_clave_periodo(paquete.recibido_en), 0) + 1
    retirados = len([p for p in paquetes if p.retirado])
    demoras = [(p.retirado_en - p.recibido_en).total_seconds() / 3600 for p in paquetes if p.retirado and p.retirado_en]
    paquetes_metricas = {
        "total_periodo": len(paquetes),
        "pendientes": len(paquetes) - retirados,
        "retirados": retirados,
        "tiempo_promedio_retiro_horas": round(sum(demoras) / len(demoras), 2) if demoras else None,
        "por_mes": dict(sorted(por_mes.items())),
        "top_inmuebles": sorted(
            [
                {"inmueble_id": uid, "inmueble": mapa_unidades.get(uid), "paquetes": len([p for p in paquetes if p.inmueble_id == uid])}
                for uid in {p.inmueble_id for p in paquetes}
            ],
            key=lambda x: -x["paquetes"],
        )[:5],
    }

    # --- Operación ---
    accesos = db.query(models_v3.RegistroAcceso).filter(
        models_v3.RegistroAcceso.conjunto_id.in_(ids),
        models_v3.RegistroAcceso.ingreso_en >= inicio, models_v3.RegistroAcceso.ingreso_en <= fin,
    ).all()
    ordenes = db.query(models_v3.OrdenMantenimiento).filter(
        models_v3.OrdenMantenimiento.conjunto_id.in_(ids),
        models_v3.OrdenMantenimiento.creado_en >= inicio, models_v3.OrdenMantenimiento.creado_en <= fin,
    ).all()
    vencidas = len([o for o in ordenes if o.fecha_limite and o.fecha_limite < localnow() and o.estado not in ("completada", "cancelada")])
    avisos = db.query(models_v3.AvisoEnviado).filter(
        models_v3.AvisoEnviado.conjunto_id.in_(ids),
        models_v3.AvisoEnviado.creado_en >= inicio, models_v3.AvisoEnviado.creado_en <= fin,
    ).all()

    return {
        "conjuntos": len(ids),
        "periodo": {"desde": inicio.date().isoformat(), "hasta": fin.date().isoformat()},
        "inmuebles": len(unidades),
        "cartera": {
            "total_pendiente": cartera["total_pendiente"], "total_vencido": cartera["total_vencido"],
            "rangos": cartera["rangos"], "cuotas_pendientes": cartera["cuotas_pendientes"],
            "cargos_monto": cartera["cargos_monto"], "top_morosos": cartera["top_morosos"],
            "indice_vencido_pct": round(
                float(dec(cartera["total_vencido"]) / (dec(cartera["total_pendiente"]) or Decimal("1")) * 100), 1
            ) if dec(cartera["total_pendiente"]) > 0 else 0.0,
        },
        "pqrs": {
            "total_periodo": len(pqrs_periodo), "resueltas": resueltas, "pendientes": pendientes,
            "tiempo_promedio_horas": tiempo_promedio,
            "sla_cumplimiento_pct": round(cumplen / total_evaluado * 100, 1) if total_evaluado else None,
            "por_tipo": por_tipo, "objetivos_sla_horas": SLA_HORAS,
        },
        "uso_zonas": uso_zonas,
        "reservas": {
            "total_periodo": len(reservas),
            "aprobadas": len([r for r in reservas if getattr(r.estado, "value", r.estado) == "aprobada"]),
            "pendientes": len([r for r in reservas if getattr(r.estado, "value", r.estado) == "pendiente"]),
            "canceladas": len([r for r in reservas if getattr(r.estado, "value", r.estado) == "cancelada"]),
            "en_lista_espera": en_espera,
        },
        "paquetes": paquetes_metricas,
        "visitantes": {
            "accesos_periodo": len(accesos),
            "en_sitio": len([a for a in accesos if a.salida_en is None]),
            "sin_autorizacion": len([a for a in accesos if not a.autorizado_por_residente]),
            "con_vehiculo": len([a for a in accesos if a.placa]),
            "promedio_permanencia_minutos": round(
                sum(((a.salida_en - a.ingreso_en).total_seconds() / 60) for a in accesos if a.salida_en) /
                max(1, len([a for a in accesos if a.salida_en])), 1
            ) if any(a.salida_en for a in accesos) else None,
        },
        "mantenimiento": {
            "total_periodo": len(ordenes),
            "abiertas": len([o for o in ordenes if o.estado in ("abierta", "asignada", "esperando_cotizacion")]),
            "en_ejecucion": len([o for o in ordenes if o.estado == "en_ejecucion"]),
            "completadas": len([o for o in ordenes if o.estado == "completada"]),
            "vencidas": vencidas,
            "costo_total": str(sum((dec(o.costo_final or o.costo_estimado or 0) for o in ordenes), dec("0"))),
        },
        "avisos": {
            "total_periodo": len(avisos),
            "enviados": len([a for a in avisos if a.estado == "enviado"]),
            "simulados": len([a for a in avisos if a.estado == "simulado"]),
            "omitidos_sin_consentimiento": len([a for a in avisos if a.estado == "omitido_sin_consentimiento"]),
            "fallidos": len([a for a in avisos if a.estado == "fallido"]),
        },
        "generado_en": localnow().isoformat(),
    }


@router.get("/export.xlsx")
def exportar(conjunto_id: int | None = None, desde: str | None = None, hasta: str | None = None,
             db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    datos = panel(conjunto_id=conjunto_id, desde=desde, hasta=hasta, db=db, user=user)
    filas = []
    cartera = datos["cartera"]
    filas.append(["Cartera", "Total pendiente", cartera["total_pendiente"]])
    filas.append(["Cartera", "Total vencido", cartera["total_vencido"]])
    for rango, monto in cartera["rangos"].items():
        filas.append(["Cartera", f"Rango {rango}", monto])
    filas.append(["PQRS", "Total del periodo", datos["pqrs"]["total_periodo"]])
    filas.append(["PQRS", "Tiempo promedio (h)", datos["pqrs"]["tiempo_promedio_horas"]])
    filas.append(["PQRS", "Cumplimiento SLA (%)", datos["pqrs"]["sla_cumplimiento_pct"]])
    for zona in datos["uso_zonas"]:
        filas.append(["Uso de zonas", zona["zona"], f"{zona['reservas']} reservas · {zona['horas_reservadas']} h · ocupación {zona['ocupacion_estimada_pct']}%"])
    filas.append(["Paquetes", "Total del periodo", datos["paquetes"]["total_periodo"]])
    filas.append(["Paquetes", "Pendientes de retiro", datos["paquetes"]["pendientes"]])
    for mes, total in datos["paquetes"]["por_mes"].items():
        filas.append(["Paquetes por mes", mes, total])
    filas.append(["Visitantes", "Accesos del periodo", datos["visitantes"]["accesos_periodo"]])
    filas.append(["Mantenimiento", "Órdenes del periodo", datos["mantenimiento"]["total_periodo"]])
    filas.append(["Mantenimiento", "Vencidas", datos["mantenimiento"]["vencidas"]])
    wb = tabla(["Indicador", "Detalle", "Valor"], filas, "Indicadores")
    return workbook_response(wb, "iris-indicadores.xlsx")


@router.get("/cartera-detalle")
def cartera_detalle(conjunto_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    require_admin_set(db, user, conjunto_id)
    base = cartera_vencida(db, [conjunto_id])
    base["por_inmueble"] = [
        {**registro, "etiqueta": etiqueta_unidad(db.query(models.Inmueble).filter_by(id=registro["inmueble_id"]).first())}
        for registro in base.get("por_inmueble", [])
    ]
    return base