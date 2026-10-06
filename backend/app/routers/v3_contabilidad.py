"""Contabilidad y cartera: egresos, presupuestos, intereses y recargos configurables,
conciliación bancaria e informes por periodo."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.permissions import can_access_set, is_admin, require_admin_set, require_finance_set
from app.security_v3 import dependencia_2fa, exigir_2fa_admin, get_usuario_v3
from app.routers.v3_common import (
    admin_only, alcance, avisar_evento, cartera_vencida, conjunto_de, dec, etiqueta_unidad, json_dumps,
    localnow, model_data, money, notificar, tabla, workbook_response, csv_response, MAX_UPLOAD,
)

router = APIRouter(prefix="/v3/contabilidad", tags=["v3 · Contabilidad y cartera"])


def _config_cartera(db: Session, conjunto_id: int) -> models_v3.ConfigCartera:
    fila = db.query(models_v3.ConfigCartera).filter_by(conjunto_id=conjunto_id).first()
    if not fila:
        fila = models_v3.ConfigCartera(conjunto_id=conjunto_id)
        db.add(fila)
        db.commit()
        db.refresh(fila)
    return fila


def _finance_only(user: models.Usuario) -> None:
    if not is_admin(user) and user.rol != "contador":
        raise HTTPException(403, "Solo administración o contabilidad puede acceder a esta información")


def _finance_set(db: Session, user: models.Usuario, conjunto_id: int) -> None:
    if user.rol == "contador": require_finance_set(db, user, conjunto_id)
    else: require_admin_set(db, user, conjunto_id)


def _finance_set_from_data(db: Session, user: models.Usuario, data: dict) -> int:
    conjunto_id = int(data.get("conjunto_id") or 0)
    if not conjunto_id:
        ids = alcance(db, user)
        if len(ids) == 1: conjunto_id = ids[0]
        else: raise HTTPException(422, "Indica el conjunto")
    _finance_set(db, user, conjunto_id)
    return conjunto_id


# ---------------------------------------------------------------------------
# Egresos
# ---------------------------------------------------------------------------
@router.get("/egresos")
def listar_egresos(conjunto_id: int | None = None, desde: str | None = None, hasta: str | None = None,
                   categoria: str | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _finance_only(user)
    ids = [conjunto_id] if conjunto_id else alcance(db, user)
    if conjunto_id:
        _finance_set(db, user, conjunto_id)
    q = db.query(models_v3.Egreso).filter(models_v3.Egreso.conjunto_id.in_(ids)) if ids else db.query(models_v3.Egreso).filter(models_v3.Egreso.id < 0)
    if desde:
        q = q.filter(models_v3.Egreso.fecha >= date.fromisoformat(desde))
    if hasta:
        q = q.filter(models_v3.Egreso.fecha <= date.fromisoformat(hasta))
    if categoria:
        q = q.filter(models_v3.Egreso.categoria == categoria)
    filas = q.order_by(models_v3.Egreso.fecha.desc(), models_v3.Egreso.id.desc()).limit(500).all()
    salida = []
    for fila in filas:
        datos = model_data(fila)
        datos["proveedor"] = db.query(models_v3.Proveedor.nombre).filter_by(id=fila.proveedor_id).scalar()
        salida.append(datos)
    return salida


@router.post("/egresos", status_code=201)
def crear_egreso(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    conjunto_id = _finance_set_from_data(db, user, data)
    exigir_2fa_admin(db, user, otp)
    concepto = str(data.get("concepto") or "").strip()
    if not concepto:
        raise HTTPException(422, "El concepto es obligatorio")
    monto = dec(data.get("monto"))
    if monto <= 0:
        raise HTTPException(422, "El monto debe ser mayor que cero")
    try:
        fecha = date.fromisoformat(str(data.get("fecha") or date.today().isoformat()))
    except ValueError:
        raise HTTPException(422, "Fecha inválida (usa AAAA-MM-DD)")
    fila = models_v3.Egreso(
        conjunto_id=conjunto_id, concepto=concepto[:160], categoria=str(data.get("categoria") or "general")[:60],
        proveedor_id=int(data["proveedor_id"]) if data.get("proveedor_id") else None, monto=monto, fecha=fecha,
        soporte_url=str(data.get("soporte_url") or "")[:500] or None, notas=str(data.get("notas") or "")[:255] or None,
        creado_por=user.id,
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.patch("/egresos/{egreso_id}")
def actualizar_egreso(egreso_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Egreso).filter_by(id=egreso_id).first()
    if not fila:
        raise HTTPException(404, "Egreso no encontrado")
    _finance_set(db, user, fila.conjunto_id)
    if data.get("concepto"):
        fila.concepto = str(data["concepto"])[:160]
    if data.get("categoria"):
        fila.categoria = str(data["categoria"])[:60]
    if data.get("monto") is not None:
        fila.monto = dec(data["monto"])
    if data.get("fecha"):
        fila.fecha = date.fromisoformat(str(data["fecha"]))
    if data.get("notas") is not None:
        fila.notas = str(data["notas"])[:255] or None
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.delete("/egresos/{egreso_id}", status_code=204)
def borrar_egreso(egreso_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    fila = db.query(models_v3.Egreso).filter_by(id=egreso_id).first()
    if not fila:
        raise HTTPException(404, "Egreso no encontrado")
    _finance_set(db, user, fila.conjunto_id)
    exigir_2fa_admin(db, user, otp)
    db.delete(fila)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Presupuestos
# ---------------------------------------------------------------------------
@router.get("/presupuestos")
def listar_presupuestos(conjunto_id: int, periodo: str | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _finance_set(db, user, conjunto_id)
    q = db.query(models_v3.Presupuesto).filter_by(conjunto_id=conjunto_id)
    if periodo:
        q = q.filter(models_v3.Presupuesto.periodo == periodo)
    return [model_data(p) for p in q.order_by(models_v3.Presupuesto.periodo.desc()).all()]


@router.post("/presupuestos", status_code=201)
def guardar_presupuesto(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    conjunto_id = _finance_set_from_data(db, user, data)
    periodo = str(data.get("periodo") or "").strip()
    if not _periodo_valido(periodo):
        raise HTTPException(422, "Periodo inválido: usa AAAA-MM")
    categoria = str(data.get("categoria") or "general")[:60]
    monto = dec(data.get("monto_presupuestado"))
    if monto < 0:
        raise HTTPException(422, "El monto presupuestado no puede ser negativo")
    fila = db.query(models_v3.Presupuesto).filter_by(conjunto_id=conjunto_id, periodo=periodo, categoria=categoria).first()
    if not fila:
        fila = models_v3.Presupuesto(conjunto_id=conjunto_id, periodo=periodo, categoria=categoria)
        db.add(fila)
    fila.monto_presupuestado = monto
    fila.notas = str(data.get("notas") or "")[:255] or None
    fila.creado_por = fila.creado_por or user.id
    db.commit()
    db.refresh(fila)
    return model_data(fila)


def _periodo_valido(periodo: str) -> bool:
    try:
        datetime.strptime(periodo, "%Y-%m")
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Configuración de cartera y cálculo de mora
# ---------------------------------------------------------------------------
@router.get("/config-cartera")
def leer_config_cartera(conjunto_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    require_admin_set(db, user, conjunto_id)
    return model_data(_config_cartera(db, conjunto_id))


@router.put("/config-cartera")
def guardar_config_cartera(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    conjunto_id = conjunto_de(db, user, data, staff=False)
    exigir_2fa_admin(db, user, otp)
    fila = _config_cartera(db, conjunto_id)
    if data.get("tasa_mora_mensual") is not None:
        valor = dec(data["tasa_mora_mensual"])
        if valor < 0 or valor > 1:
            raise HTTPException(422, "La tasa de mora mensual debe estar entre 0 y 1 (por ejemplo 0.02 = 2 %)")
        fila.tasa_mora_mensual = valor
    if data.get("interes_moratorio_diario") is not None:
        valor = dec(data["interes_moratorio_diario"])
        if valor < 0 or valor > 1:
            raise HTTPException(422, "El interés diario debe estar entre 0 y 1")
        fila.interes_moratorio_diario = valor
    if data.get("recargo_fijo") is not None:
        fila.recargo_fijo = dec(data["recargo_fijo"])
    if data.get("dias_gracia") is not None:
        valor = int(data["dias_gracia"])
        if not 0 <= valor <= 60:
            raise HTTPException(422, "Los días de gracia deben estar entre 0 y 60")
        fila.dias_gracia = valor
    if data.get("activo") is not None:
        fila.activo = bool(data["activo"])
    fila.actualizado_en = localnow()
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.post("/cartera/calcular-mora")
def calcular_mora(data: dict | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    """Aplica intereses y recargos configurables a las cuotas vencidas (idempotente por cuota y día)."""
    data = data or {}
    conjunto_id = conjunto_de(db, user, data, staff=False)
    exigir_2fa_admin(db, user, otp)
    config = _config_cartera(db, conjunto_id)
    if not config.activo:
        raise HTTPException(409, "Activa la configuración de cartera antes de calcular intereses")
    hoy = localnow().date()
    cuotas = db.query(models.Cuota).join(models.Inmueble).filter(
        models.Inmueble.conjunto_id == conjunto_id, models.Cuota.estado == "pendiente",
        models.Cuota.fecha_vencimiento < hoy,
    ).all()
    aplicados, omitidos = [], 0
    for cuota in cuotas:
        dias_mora = (hoy - cuota.fecha_vencimiento).days
        if dias_mora <= config.dias_gracia:
            omitidos += 1
            continue
        marca = f"{cuota.id}:{hoy.isoformat()}"
        existente = db.query(models_v3.CargoCartera).filter(
            models_v3.CargoCartera.cuota_id == cuota.id, models_v3.CargoCartera.tipo == "interes_mora",
            models_v3.CargoCartera.concepto.like(f"%{marca}%"),
        ).first()
        if existente:
            omitidos += 1
            continue
        base = dec(cuota.monto)
        interes = (base * config.interes_moratorio_diario * Decimal(dias_mora)).quantize(Decimal("0.01"))
        if config.tasa_mora_mensual > 0 and interes == 0:
            meses = Decimal(dias_mora) / Decimal(30)
            interes = (base * config.tasa_mora_mensual * meses).quantize(Decimal("0.01"))
        total = interes + dec(config.recargo_fijo)
        if total <= 0:
            omitidos += 1
            continue
        cargo = models_v3.CargoCartera(
            conjunto_id=conjunto_id, inmueble_id=cuota.inmueble_id, cuota_id=cuota.id, tipo="interes_mora",
            concepto=f"Interés de mora {dias_mora} días ({marca})", base=base,
            tasa_aplicada=config.interes_moratorio_diario or config.tasa_mora_mensual, dias_mora=dias_mora,
            monto=total, periodo=cuota.periodo, creado_por=user.id,
        )
        db.add(cargo)
        aplicados.append({"cuota_id": cuota.id, "inmueble_id": cuota.inmueble_id, "dias_mora": dias_mora, "monto": str(total)})
        unidad = db.query(models.Inmueble).filter_by(id=cuota.inmueble_id).first()
        for usuario_id in ({unidad.propietario_id, unidad.inquilino_id} - {None} if unidad else set()):
            notificar(db, usuario_id, "Interés de mora aplicado",
                      f"Cuota #{cuota.id} ({cuota.concepto}) con {dias_mora} días de mora: ${money(total)}")
            avisar_evento(db, usuario_id, "cuota_vencimiento", {
                "concepto": cuota.concepto, "periodo": cuota.periodo, "monto": money(total),
                "fecha": hoy.isoformat(), "inmueble": etiqueta_unidad(unidad),
                "mensaje": f"Se aplicó interés de mora por ${money(total)} a tu cuota {cuota.concepto} ({dias_mora} días).",
            }, conjunto_id=conjunto_id)
    db.commit()
    return {"cuotas_vencidas": len(cuotas), "cargos_aplicados": len(aplicados), "omitidos": omitidos, "detalle": aplicados}


@router.get("/cartera")
def reporte_cartera(conjunto_id: int | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _finance_only(user)
    ids = [conjunto_id] if conjunto_id else alcance(db, user)
    if conjunto_id:
        _finance_set(db, user, conjunto_id)
    base = cartera_vencida(db, ids)
    cargos = db.query(models_v3.CargoCartera).filter(
        models_v3.CargoCartera.conjunto_id.in_(ids), models_v3.CargoCartera.estado == "pendiente"
    ).all() if ids else []
    base["cargos_pendientes"] = len(cargos)
    base["cargos_monto"] = str(sum((dec(c.monto) for c in cargos), dec("0")))
    por_inmueble: dict[int, dict] = {}
    for item in base["detalle"]:
        registro = por_inmueble.setdefault(item["inmueble_id"], {
            "inmueble_id": item["inmueble_id"],
            "etiqueta": etiqueta_unidad(db.query(models.Inmueble).filter_by(id=item["inmueble_id"]).first()),
            "Cuotas": "0", "monto": Decimal("0"), "dias_mora_max": 0,
        })
        registro["Cuotas"] = str(int(registro["Cuotas"]) + 1)
        registro["monto"] += dec(item["monto"])
        registro["dias_mora_max"] = max(registro["dias_mora_max"], item["dias_mora"])
    for registro in por_inmueble.values():
        registro["monto"] = str(registro["monto"])
    base["por_inmueble"] = sorted(por_inmueble.values(), key=lambda r: -r["dias_mora_max"])
    return base


# ---------------------------------------------------------------------------
# Extracto bancario y conciliación
# ---------------------------------------------------------------------------
def _leer_filas_archivo(raw: bytes, filename: str) -> list[dict]:
    nombre = (filename or "").lower()
    if nombre.endswith(".csv"):
        texto = raw.decode("utf-8-sig", errors="replace")
        lector = csv.DictReader(io.StringIO(texto), delimiter=";" if texto.count(";") > texto.count(",") else ",")
        return [{str(k).strip().lower(): v for k, v in fila.items() if k} for fila in lector]
    if nombre.endswith(".xlsx"):
        hoja = load_workbook(io.BytesIO(raw), read_only=True, data_only=True).active
        iterador = hoja.iter_rows(values_only=True)
        encabezados = [str(x or "").strip().lower() for x in next(iterador)]
        return [dict(zip(encabezados, valores)) for valores in iterador if any(v is not None for v in valores)]
    raise HTTPException(415, "Sube un extracto .csv o .xlsx")


@router.post("/extracto/importar", status_code=201)
async def importar_extracto(conjunto_id: int, file: UploadFile = File(...), banco: str | None = None,
                            cuenta: str | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    require_admin_set(db, user, conjunto_id)
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "El archivo excede 10 MB")
    filas = _leer_filas_archivo(raw, file.filename or "")
    creados, errores = 0, []
    for indice, fila in enumerate(filas, start=2):
        try:
            fecha_cruda = fila.get("fecha") or fila.get("date") or fila.get("fecha movimiento")
            if not fecha_cruda:
                raise ValueError("sin fecha")
            if isinstance(fecha_cruda, datetime):
                fecha = fecha_cruda.date()
            elif isinstance(fecha_cruda, date):
                fecha = fecha_cruda
            else:
                texto = str(fecha_cruda).strip().replace("/", "-")
                fecha = None
                for formato in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
                    try:
                        fecha = datetime.strptime(texto, formato).date()
                        break
                    except ValueError:
                        continue
                if fecha is None:
                    raise ValueError("fecha no reconocida")
            descripcion = str(fila.get("descripcion") or fila.get("detalle") or fila.get("concepto") or "Movimiento")[:255]
            referencia = str(fila.get("referencia") or fila.get("ref") or fila.get("documento") or "")[:120] or None
            debito = dec(fila.get("debito") or fila.get("débito") or fila.get("cargo") or 0)
            credito = dec(fila.get("credito") or fila.get("crédito") or fila.get("abono") or fila.get("valor") or 0)
            if credito < 0:
                debito, credito = abs(credito), Decimal("0")
            duplicado = db.query(models_v3.MovimientoBancario).filter_by(
                conjunto_id=conjunto_id, fecha=fecha, descripcion=descripcion, referencia=referencia
            ).first()
            if duplicado:
                errores.append({"fila": indice, "detalle": "movimiento duplicado"})
                continue
            db.add(models_v3.MovimientoBancario(
                conjunto_id=conjunto_id, banco=(banco or "")[:80] or None, cuenta=(cuenta or "")[:60] or None,
                fecha=fecha, descripcion=descripcion, referencia=referencia, debito=debito, credito=credito,
            ))
            creados += 1
        except Exception as exc:
            errores.append({"fila": indice, "detalle": str(exc)[:160]})
    db.commit()
    return {"movimientos_creados": creados, "errores": errores[:50]}


@router.get("/movimientos")
def listar_movimientos(conjunto_id: int, conciliado: bool | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    require_admin_set(db, user, conjunto_id)
    q = db.query(models_v3.MovimientoBancario).filter_by(conjunto_id=conjunto_id)
    if conciliado is not None:
        q = q.filter(models_v3.MovimientoBancario.conciliado.is_(conciliado))
    return [model_data(m) for m in q.order_by(models_v3.MovimientoBancario.fecha.desc(), models_v3.MovimientoBancario.id.desc()).limit(500).all()]


@router.post("/conciliar-bancaria")
def conciliar_bancaria(data: dict | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    """Concilia automáticamente los créditos del extracto con cuotas, pagos y transacciones aprobadas."""
    data = data or {}
    conjunto_id = conjunto_de(db, user, data, staff=False)
    exigir_2fa_admin(db, user, otp)
    dias_tolerancia = int(data.get("dias_tolerancia") or 5)
    movimientos = db.query(models_v3.MovimientoBancario).filter(
        models_v3.MovimientoBancario.conjunto_id == conjunto_id,
        models_v3.MovimientoBancario.conciliado.is_(False),
        models_v3.MovimientoBancario.credito > 0,
    ).order_by(models_v3.MovimientoBancario.fecha).all()
    conciliados, sin_match = [], []
    for movimiento in movimientos:
        unidades = [u.id for u in db.query(models.Inmueble).filter_by(conjunto_id=conjunto_id).all()]
        candidatas = db.query(models.Cuota).filter(
            models.Cuota.inmueble_id.in_(unidades), models.Cuota.estado == "pendiente",
            models.Cuota.monto == movimiento.credito,
            models.Cuota.fecha_vencimiento.between(movimiento.fecha - timedelta(days=dias_tolerancia), movimiento.fecha + timedelta(days=dias_tolerancia)),
        ).all() if unidades else []
        if len(candidatas) == 1:
            cuota = candidatas[0]
            pago = models.Pago(
                cuota_id=cuota.id, inmueble_id=cuota.inmueble_id, solicitado_por=user.id, verificado_por=user.id,
                monto=movimiento.credito, metodo="conciliacion_bancaria",
                referencia=movimiento.referencia or f"MOV-{movimiento.id}", estado="verificado",
                notas=f"Conciliación bancaria automática del movimiento #{movimiento.id}", verificado_en=localnow(),
            )
            db.add(pago)
            db.flush()
            cuota.estado = "pagada"
            cuota.pagada_en = pago.verificado_en
            movimiento.conciliado = True
            movimiento.conciliado_en = localnow()
            movimiento.cuota_id = cuota.id
            db.add(models_v3.ConciliacionPago(
                conjunto_id=conjunto_id, transaccion_id=None, cuota_id=cuota.id, pago_id=pago.id,
                movimiento_id=movimiento.id, origen="bancaria", monto=movimiento.credito,
                observacion=f"Coincidencia exacta de valor y fecha (±{dias_tolerancia} días)",
            ))
            conciliados.append({"movimiento_id": movimiento.id, "cuota_id": cuota.id, "pago_id": pago.id, "monto": str(movimiento.credito)})
        else:
            sin_match.append({"movimiento_id": movimiento.id, "monto": str(movimiento.credito), "candidatas": len(candidatas)})
    db.commit()
    return {"movimientos_revisados": len(movimientos), "conciliados": conciliados, "sin_coincidencia": sin_match}


@router.post("/movimientos/{movimiento_id}/conciliar")
def conciliar_movimiento_manual(movimiento_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3), otp: str | None = dependencia_2fa()):
    movimiento = db.query(models_v3.MovimientoBancario).filter_by(id=movimiento_id).first()
    if not movimiento:
        raise HTTPException(404, "Movimiento no encontrado")
    require_admin_set(db, user, movimiento.conjunto_id)
    exigir_2fa_admin(db, user, otp)
    if movimiento.conciliado:
        raise HTTPException(409, "El movimiento ya está conciliado")
    cuota = db.query(models.Cuota).filter_by(id=int(data.get("cuota_id") or 0)).first()
    if not cuota:
        raise HTTPException(404, "Cuota no encontrada")
    unidad = db.query(models.Inmueble).filter_by(id=cuota.inmueble_id).first()
    if not unidad or unidad.conjunto_id != movimiento.conjunto_id:
        raise HTTPException(422, "La cuota no pertenece al conjunto del extracto")
    monto = dec(data.get("monto") or movimiento.credito)
    pago = models.Pago(
        cuota_id=cuota.id, inmueble_id=cuota.inmueble_id, solicitado_por=user.id, verificado_por=user.id,
        monto=monto, metodo="conciliacion_bancaria", referencia=movimiento.referencia or f"MOV-{movimiento.id}",
        estado="verificado", notas=f"Conciliación manual del movimiento #{movimiento.id}", verificado_en=localnow(),
    )
    db.add(pago)
    db.flush()
    if monto >= dec(cuota.monto):
        cuota.estado = "pagada"
        cuota.pagada_en = pago.verificado_en
    movimiento.conciliado = True
    movimiento.conciliado_en = localnow()
    movimiento.cuota_id = cuota.id
    db.add(models_v3.ConciliacionPago(
        conjunto_id=movimiento.conjunto_id, cuota_id=cuota.id, pago_id=pago.id, movimiento_id=movimiento.id,
        origen="manual", monto=monto, diferencia=max(Decimal("0"), dec(cuota.monto) - monto),
        observacion="Conciliación bancaria manual", creado_por=user.id,
    ))
    for usuario_id in {unidad.propietario_id, unidad.inquilino_id} - {None}:
        notificar(db, usuario_id, "Pago conciliado", f"Se concilió tu pago de ${money(monto)} para {cuota.concepto}")
    db.commit()
    return {"conciliado": True, "pago_id": pago.id, "cuota_id": cuota.id}


# ---------------------------------------------------------------------------
# Informes por periodo
# ---------------------------------------------------------------------------
@router.get("/informes/periodo")
def informe_periodo(conjunto_id: int, desde: str, hasta: str, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _finance_set(db, user, conjunto_id)
    try:
        inicio, fin = date.fromisoformat(desde), date.fromisoformat(hasta)
    except ValueError:
        raise HTTPException(422, "Fechas inválidas: usa AAAA-MM-DD")
    if fin < inicio:
        raise HTTPException(422, "El rango es inválido")
    unidades = [u.id for u in db.query(models.Inmueble).filter_by(conjunto_id=conjunto_id).all()]
    cuotas = db.query(models.Cuota).filter(
        models.Cuota.inmueble_id.in_(unidades), models.Cuota.fecha_vencimiento.between(inicio, fin)
    ).all() if unidades else []
    egresos = db.query(models_v3.Egreso).filter(
        models_v3.Egreso.conjunto_id == conjunto_id, models_v3.Egreso.fecha.between(inicio, fin)
    ).all()
    cargos = db.query(models_v3.CargoCartera).filter(
        models_v3.CargoCartera.conjunto_id == conjunto_id, models_v3.CargoCartera.creado_en >= datetime.combine(inicio, datetime.min.time()),
        models_v3.CargoCartera.creado_en <= datetime.combine(fin, datetime.max.time()),
    ).all()
    facturado = sum((dec(c.monto) for c in cuotas), dec("0"))
    recaudado = sum((dec(c.monto) for c in cuotas if c.estado == "pagada"), dec("0"))
    egresos_total = sum((dec(e.monto) for e in egresos), dec("0"))
    por_categoria: dict[str, str] = {}
    for egreso in egresos:
        por_categoria[egreso.categoria] = str(dec(por_categoria.get(egreso.categoria, "0")) + dec(egreso.monto))
    presupuesto_total = sum((dec(p.monto_presupuestado) for p in db.query(models_v3.Presupuesto).filter_by(conjunto_id=conjunto_id).all()
                             if inicio.strftime("%Y-%m") <= p.periodo <= fin.strftime("%Y-%m")), dec("0"))
    return {
        "conjunto_id": conjunto_id, "desde": inicio.isoformat(), "hasta": fin.isoformat(),
        "facturado": str(facturado), "recaudado": str(recaudado),
        "cartera_generada": str(facturado - recaudado),
        "egresos": str(egresos_total), "egresos_por_categoria": por_categoria,
        "presupuesto_periodo": str(presupuesto_total),
        "desviacion_presupuesto": str(egresos_total - presupuesto_total),
        "intereses_y_recargos": str(sum((dec(c.monto) for c in cargos), dec("0"))),
        "resultado": str(recaudado - egresos_total),
        "cuotas": {"total": len(cuotas), "pagadas": len([c for c in cuotas if c.estado == "pagada"]),
                   "pendientes": len([c for c in cuotas if c.estado != "pagada"])},
    }


@router.get("/export/cartera.xlsx")
def exportar_cartera(conjunto_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _finance_set(db, user, conjunto_id)
    base = cartera_vencida(db, [conjunto_id])
    filas = [[d["cuota_id"], d["inmueble_id"], etiqueta_unidad(db.query(models.Inmueble).filter_by(id=d["inmueble_id"]).first()),
              d["monto"], d["dias_mora"], d["rango"]] for d in base["detalle"]]
    wb = tabla(["cuota_id", "inmueble_id", "inmueble", "monto", "dias_mora", "rango"], filas, "Cartera")
    return workbook_response(wb, "iris-cartera.xlsx")


@router.get("/export/egresos.xlsx")
def exportar_egresos(conjunto_id: int, desde: str | None = None, hasta: str | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _finance_set(db, user, conjunto_id)
    q = db.query(models_v3.Egreso).filter_by(conjunto_id=conjunto_id)
    if desde:
        q = q.filter(models_v3.Egreso.fecha >= date.fromisoformat(desde))
    if hasta:
        q = q.filter(models_v3.Egreso.fecha <= date.fromisoformat(hasta))
    filas = [[e.id, e.fecha.isoformat(), e.concepto, e.categoria,
              db.query(models_v3.Proveedor.nombre).filter_by(id=e.proveedor_id).scalar() or "", str(e.monto), e.notas or ""]
             for e in q.order_by(models_v3.Egreso.fecha).all()]
    wb = tabla(["id", "fecha", "concepto", "categoria", "proveedor", "monto", "notas"], filas, "Egresos")
    return workbook_response(wb, "iris-egresos.xlsx")


@router.get("/export/conciliaciones.csv")
def exportar_conciliaciones(conjunto_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    require_admin_set(db, user, conjunto_id)
    filas = db.query(models_v3.ConciliacionPago).filter_by(conjunto_id=conjunto_id).order_by(models_v3.ConciliacionPago.id.desc()).limit(5000).all()
    datos = [[c.id, c.origen, c.transaccion_id or "", c.cuota_id or "", c.pago_id or "", c.movimiento_id or "",
              str(c.monto), str(c.diferencia), c.creado_en.strftime("%Y-%m-%d %H:%M") if c.creado_en else ""] for c in filas]
    return csv_response(datos, ["id", "origen", "transaccion_id", "cuota_id", "pago_id", "movimiento_id", "monto", "diferencia", "creado_en"], "iris-conciliaciones.csv")
