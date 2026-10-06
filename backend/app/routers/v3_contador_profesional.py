"""Capa contable profesional aditiva: libros, PUC, documentos, fondos y cierres.

La emisión DIAN real exige habilitación y credenciales del facturador electrónico;
este módulo no simula una transmisión tributaria ni marca documentos como emitidos.
"""
from __future__ import annotations
import json
import io
from html import escape
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app import models, models_v3, models_contador as mc
from app.database import get_db
from app.permissions import require_finance_set
from app.security_v3 import get_usuario_v3
from app.routers.v3_common import localnow, model_data, tabla, workbook_response, csv_response

router = APIRouter(prefix="/v3/contabilidad/profesional", tags=["v3 · Contabilidad profesional"])
CENT = Decimal("0.01")
PUC_BASE = [
    ("1105", "Caja", "activo", "debito"),
    ("1110", "Bancos", "activo", "debito"),
    ("1305", "Cuentas comerciales por cobrar", "activo", "debito"),
    ("2335", "Costos y gastos por pagar", "pasivo", "credito"),
    ("3105", "Capital / aportes sociales", "patrimonio", "credito"),
    ("3305", "Reservas obligatorias y fondos", "patrimonio", "credito"),
    ("4170", "Ingresos por cuotas y servicios comunes", "ingreso", "credito"),
    ("5105", "Gastos de personal", "gasto", "debito"),
    ("5135", "Servicios y mantenimiento", "gasto", "debito"),
    ("5195", "Otros gastos de administración", "gasto", "debito"),
]
CLASES = {"activo", "pasivo", "patrimonio", "ingreso", "gasto"}


def _auth_set(db: Session, user, conjunto_id: int):
    require_finance_set(db, user, conjunto_id)


def _required_set(data: dict, db: Session, user) -> int:
    try:
        cid = int(data.get("conjunto_id") or 0)
    except (TypeError, ValueError):
        cid = 0
    if not cid:
        from app.routers.v3_common import alcance
        ids = alcance(db, user)
        if len(ids) != 1:
            raise HTTPException(422, "Indica el conjunto")
        cid = ids[0]
    _auth_set(db, user, cid)
    return cid


def _dec(value, label="valor") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(422, f"{label} no es válido")
    if not result.is_finite():
        raise HTTPException(422, f"{label} no es válido")
    return result.quantize(CENT, rounding=ROUND_HALF_UP)


def _puc(db: Session, conjunto_id: int):
    rows = db.query(mc.CuentaPUC).filter_by(conjunto_id=conjunto_id).all()
    existing_codes = {row.codigo for row in rows}
    for codigo, nombre, clase, naturaleza in PUC_BASE:
        if codigo not in existing_codes:
            db.add(mc.CuentaPUC(conjunto_id=conjunto_id, codigo=codigo, nombre=nombre, clase=clase, naturaleza=naturaleza, activa=True))
    db.flush()
    rows = db.query(mc.CuentaPUC).filter_by(conjunto_id=conjunto_id).all()
    return {row.codigo: row for row in rows if row.activa}


def _serial_account(row):
    return {"id": row.id, "conjunto_id": row.conjunto_id, "codigo": row.codigo, "nombre": row.nombre,
            "clase": row.clase, "naturaleza": row.naturaleza, "activa": row.activa}


def _make_entry(db: Session, *, conjunto_id: int, fecha: date, descripcion: str, origen: str,
                origen_id: str | int | None, lineas: list[dict], usuario_id: int | None):
    if origen_id is not None:
        existing = db.query(mc.AsientoContable).filter_by(conjunto_id=conjunto_id, origen=origen, origen_id=str(origen_id)).first()
        if existing:
            return existing, False
    accounts = _puc(db, conjunto_id)
    total_debito = Decimal("0.00")
    total_credito = Decimal("0.00")
    normalized = []
    for line in lineas:
        account = accounts.get(str(line.get("codigo") or ""))
        if not account:
            raise HTTPException(422, f"La cuenta {line.get('codigo')} no existe o está inactiva en el PUC")
        deb = _dec(line.get("debito", 0), "Débito")
        cre = _dec(line.get("credito", 0), "Crédito")
        if deb < 0 or cre < 0 or (deb > 0 and cre > 0) or (deb == 0 and cre == 0):
            raise HTTPException(422, "Cada línea debe tener débito o crédito positivo, nunca ambos")
        total_debito += deb
        total_credito += cre
        normalized.append((account, deb, cre, str(line.get("descripcion") or "")[:255] or None))
    if len(normalized) < 2 or total_debito <= 0 or total_debito != total_credito:
        raise HTTPException(422, "El asiento debe tener al menos dos líneas y quedar balanceado")
    numero = f"{conjunto_id}-{fecha:%Y%m%d}-{int(datetime.now().timestamp() * 1000) % 100000000:08d}"
    row = mc.AsientoContable(conjunto_id=conjunto_id, numero=numero, fecha=fecha, descripcion=descripcion[:255],
                             origen=origen[:40], origen_id=str(origen_id) if origen_id is not None else None,
                             estado="contabilizado", creado_por=usuario_id)
    db.add(row)
    db.flush()
    for account, deb, cre, desc in normalized:
        db.add(mc.LineaAsientoContable(asiento_id=row.id, cuenta_id=account.id, descripcion=desc, debito=deb, credito=cre))
    db.flush()
    return row, True


def _entry_dict(db: Session, row):
    lines = db.query(mc.LineaAsientoContable, mc.CuentaPUC).join(mc.CuentaPUC, mc.CuentaPUC.id == mc.LineaAsientoContable.cuenta_id).filter(mc.LineaAsientoContable.asiento_id == row.id).all()
    return {"id": row.id, "numero": row.numero, "conjunto_id": row.conjunto_id, "fecha": row.fecha.isoformat(),
            "descripcion": row.descripcion, "origen": row.origen, "origen_id": row.origen_id, "estado": row.estado,
            "creado_por": row.creado_por, "creado_en": row.creado_en.isoformat() if row.creado_en else None,
            "lineas": [{"cuenta": c.codigo, "nombre": c.nombre, "descripcion": l.descripcion,
                        "debito": str(l.debito), "credito": str(l.credito)} for l, c in lines]}


@router.get("/puc")
def listar_puc(conjunto_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _auth_set(db, user, conjunto_id)
    rows = _puc(db, conjunto_id)
    db.commit()
    return sorted((_serial_account(x) for x in rows.values()), key=lambda x: x["codigo"])


@router.post("/puc", status_code=201)
def crear_cuenta_puc(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    cid = _required_set(data, db, user)
    codigo = str(data.get("codigo") or "").strip()
    nombre = str(data.get("nombre") or "").strip()
    clase = str(data.get("clase") or "").lower()
    naturaleza = str(data.get("naturaleza") or "").lower()
    if not codigo.isdigit() or not (2 <= len(codigo) <= 8) or not nombre or clase not in CLASES or naturaleza not in {"debito", "credito"}:
        raise HTTPException(422, "Código, nombre, clase y naturaleza PUC son obligatorios y deben ser válidos")
    if db.query(mc.CuentaPUC).filter_by(conjunto_id=cid, codigo=codigo).first():
        raise HTTPException(409, "Ese código PUC ya está registrado")
    row = mc.CuentaPUC(conjunto_id=cid, codigo=codigo, nombre=nombre[:160], clase=clase, naturaleza=naturaleza, creada_por=user.id)
    db.add(row); db.commit(); db.refresh(row)
    return _serial_account(row)


@router.get("/asientos")
def listar_asientos(conjunto_id: int, desde: date | None = None, hasta: date | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _auth_set(db, user, conjunto_id)
    q = db.query(mc.AsientoContable).filter_by(conjunto_id=conjunto_id)
    if desde: q = q.filter(mc.AsientoContable.fecha >= desde)
    if hasta: q = q.filter(mc.AsientoContable.fecha <= hasta)
    return [_entry_dict(db, row) for row in q.order_by(mc.AsientoContable.fecha.desc(), mc.AsientoContable.id.desc()).limit(500).all()]


@router.post("/asientos", status_code=201)
def crear_asiento(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    cid = _required_set(data, db, user)
    try: fecha = date.fromisoformat(str(data.get("fecha") or date.today().isoformat()))
    except ValueError: raise HTTPException(422, "Fecha inválida (AAAA-MM-DD)")
    descripcion = str(data.get("descripcion") or "").strip()
    if not descripcion: raise HTTPException(422, "La descripción es obligatoria")
    try:
        row, created = _make_entry(db, conjunto_id=cid, fecha=fecha, descripcion=descripcion, origen="manual",
                                   origen_id=None, lineas=data.get("lineas") or [], usuario_id=user.id)
        db.commit(); db.refresh(row)
        return _entry_dict(db, row)
    except Exception:
        db.rollback(); raise


def sincronizar_asientos(db: Session, conjunto_id: int, usuario_id: int | None = None) -> dict:
    """Causación idempotente para cuotas pagadas y cobros efectivamente generados de reservas."""
    accounts = _puc(db, conjunto_id)
    made = 0
    cuotas = (db.query(models.Cuota).join(models.Inmueble, models.Inmueble.id == models.Cuota.inmueble_id)
              .filter(models.Inmueble.conjunto_id == conjunto_id).all())
    for fee in cuotas:
        invoice = db.query(mc.AsientoContable).filter_by(conjunto_id=conjunto_id, origen="cuota_emitida", origen_id=str(fee.id)).first()
        if not invoice:
            invoice, is_new = _make_entry(db, conjunto_id=conjunto_id, fecha=fee.fecha_vencimiento,
                descripcion=f"Causación de cuota #{fee.id}: {fee.concepto}", origen="cuota_emitida", origen_id=fee.id,
                lineas=[{"codigo": "1305", "debito": fee.monto, "credito": 0}, {"codigo": "4170", "debito": 0, "credito": fee.monto}], usuario_id=usuario_id or fee.creado_por)
            made += int(is_new)
        if fee.estado == "pagada":
            _, is_new = _make_entry(db, conjunto_id=conjunto_id, fecha=(fee.pagada_en.date() if fee.pagada_en else date.today()),
                descripcion=f"Recaudo de cuota #{fee.id}: {fee.concepto}", origen="cuota_pagada", origen_id=fee.id,
                lineas=[{"codigo": "1110", "debito": fee.monto, "credito": 0}, {"codigo": "1305", "debito": 0, "credito": fee.monto}], usuario_id=usuario_id or fee.creado_por)
            made += int(is_new)
    # Un cargo positivo de reserva representa un uso facturable (no toda reserva sin costo).
    cargos = (db.query(models_v3.CargoReserva, models.Reserva, models.Inmueble)
              .join(models.Reserva, models.Reserva.id == models_v3.CargoReserva.reserva_id)
              .join(models.Inmueble, models.Inmueble.id == models.Reserva.inmueble_id)
              .filter(models.Inmueble.conjunto_id == conjunto_id, models_v3.CargoReserva.monto > 0,
                      models_v3.CargoReserva.estado != "anulado").all())
    for charge, booking, unit in cargos:
        made_entry, is_new = _make_entry(db, conjunto_id=conjunto_id, fecha=charge.creado_en.date() if charge.creado_en else date.today(),
            descripcion=f"Cobro por uso de zona común · reserva #{booking.id}", origen="cargo_reserva", origen_id=charge.id,
            lineas=[{"codigo": "1305", "debito": charge.monto, "credito": 0}, {"codigo": "4170", "debito": 0, "credito": charge.monto}], usuario_id=usuario_id)
        made += int(is_new)
    cartera = db.query(models_v3.CargoCartera).filter_by(conjunto_id=conjunto_id, estado="pendiente").all()
    for charge in cartera:
        entry, is_new = _make_entry(db, conjunto_id=conjunto_id,
            fecha=charge.creado_en.date() if charge.creado_en else date.today(),
            descripcion=f"Causación de cartera: {charge.concepto}", origen="cargo_cartera", origen_id=charge.id,
            lineas=[{"codigo": "1305", "debito": charge.monto, "credito": 0}, {"codigo": "4170", "debito": 0, "credito": charge.monto}], usuario_id=usuario_id or charge.creado_por)
        made += int(is_new)
    db.commit()
    return {"asientos_creados": made, "cuotas_revisadas": len(cuotas), "cargos_reserva_revisados": len(cargos), "cargos_cartera_revisados": len(cartera)}


@router.post("/asientos/sincronizar")
def ejecutar_sincronizacion(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    cid = _required_set(data, db, user)
    return sincronizar_asientos(db, cid, user.id)


@router.post("/cartera/calcular-mora")
def calcular_mora_contador(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    cid = _required_set(data, db, user)
    config = db.query(models_v3.ConfigCartera).filter_by(conjunto_id=cid).first()
    if not config or not config.activo:
        raise HTTPException(409, "La administración debe activar y configurar las tasas de cartera antes de liquidar mora")
    hoy = localnow().date()
    cuotas = (db.query(models.Cuota).join(models.Inmueble, models.Inmueble.id == models.Cuota.inmueble_id)
              .filter(models.Inmueble.conjunto_id == cid, models.Cuota.estado == "pendiente", models.Cuota.fecha_vencimiento < hoy).all())
    applied, skipped = [], 0
    for fee in cuotas:
        days = (hoy - fee.fecha_vencimiento).days
        if days <= config.dias_gracia:
            skipped += 1; continue
        marker = f"{fee.id}:{hoy.isoformat()}"
        exists = db.query(models_v3.CargoCartera.id).filter(
            models_v3.CargoCartera.cuota_id == fee.id, models_v3.CargoCartera.tipo == "interes_mora",
            models_v3.CargoCartera.concepto.like(f"%{marker}%")).first()
        if exists:
            skipped += 1; continue
        base = _dec(fee.monto)
        rate = _dec(config.interes_moratorio_diario or 0)
        interest = (base * rate * Decimal(days)).quantize(CENT, rounding=ROUND_HALF_UP)
        if config.tasa_mora_mensual and interest == 0:
            interest = (base * _dec(config.tasa_mora_mensual) * Decimal(days) / Decimal("30")).quantize(CENT, rounding=ROUND_HALF_UP)
        amount = interest + _dec(config.recargo_fijo or 0)
        if amount <= 0:
            skipped += 1; continue
        db.add(models_v3.CargoCartera(conjunto_id=cid, inmueble_id=fee.inmueble_id, cuota_id=fee.id,
            tipo="interes_mora", concepto=f"Interés de mora {days} días ({marker})", base=base,
            tasa_aplicada=rate or config.tasa_mora_mensual, dias_mora=days, monto=amount,
            periodo=fee.periodo, estado="pendiente", creado_por=user.id))
        applied.append({"cuota_id": fee.id, "dias_mora": days, "monto": str(amount)})
    db.commit()
    auto = sincronizar_asientos(db, cid, user.id)
    return {"cuotas_vencidas": len(cuotas), "cargos_aplicados": len(applied), "omitidos": skipped,
            "detalle": applied, "asientos_generados": auto["asientos_creados"]}


@router.get("/estados-financieros")
def estados_financieros(conjunto_id: int, desde: date | None = None, hasta: date | None = None,
                       db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _auth_set(db, user, conjunto_id)
    q = db.query(mc.AsientoContable).filter_by(conjunto_id=conjunto_id, estado="contabilizado")
    if desde: q = q.filter(mc.AsientoContable.fecha >= desde)
    if hasta: q = q.filter(mc.AsientoContable.fecha <= hasta)
    entries = q.all()
    ids = [e.id for e in entries]
    result = {"conjunto_id": conjunto_id, "desde": desde.isoformat() if desde else None, "hasta": hasta.isoformat() if hasta else None,
              "activos": "0.00", "pasivos": "0.00", "patrimonio": "0.00", "ingresos": "0.00", "gastos": "0.00",
              "utilidad_periodo": "0.00", "balance_prueba": [], "total_debitos": "0.00", "total_creditos": "0.00"}
    if not ids: return result
    rows = (db.query(mc.CuentaPUC, mc.LineaAsientoContable)
            .join(mc.LineaAsientoContable, mc.LineaAsientoContable.cuenta_id == mc.CuentaPUC.id)
            .filter(mc.CuentaPUC.conjunto_id == conjunto_id, mc.LineaAsientoContable.asiento_id.in_(ids)).all())
    totals = {key: Decimal("0.00") for key in ["activos", "pasivos", "patrimonio", "ingresos", "gastos", "total_debitos", "total_creditos"]}
    clase_a_total = {"activo": "activos", "pasivo": "pasivos", "patrimonio": "patrimonio", "ingreso": "ingresos", "gasto": "gastos"}
    by_code = {}
    for account, line in rows:
        deb, cre = _dec(line.debito), _dec(line.credito)
        totals["total_debitos"] += deb; totals["total_creditos"] += cre
        # Saldo presentado con signo normal de la clase contable.
        val = deb - cre if account.naturaleza == "debito" else cre - deb
        totals[clase_a_total[account.clase]] += val
        slot = by_code.setdefault(account.codigo, {"codigo": account.codigo, "cuenta": account.nombre, "clase": account.clase, "debito": Decimal("0.00"), "credito": Decimal("0.00")})
        slot["debito"] += deb; slot["credito"] += cre
    for key, value in totals.items(): result[key] = str(value.quantize(CENT))
    result["utilidad_periodo"] = str((totals["ingresos"] - totals["gastos"]).quantize(CENT))
    result["balance_prueba"] = [{**v, "debito": str(v["debito"]), "credito": str(v["credito"])} for v in sorted(by_code.values(), key=lambda x: x["codigo"])]
    return result


@router.get("/exportar")
def exportar_libros(conjunto_id: int, tipo: str = "libro", formato: str = "xlsx", desde: date | None = None,
                    hasta: date | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _auth_set(db, user, conjunto_id)
    if tipo not in {"libro", "balance_prueba", "cartera"} or formato not in {"xlsx", "csv", "pdf"}:
        raise HTTPException(422, "Tipo o formato de exportación no soportado")
    if tipo == "cartera":
        q = (db.query(models.Cuota, models.Inmueble).join(models.Inmueble, models.Inmueble.id == models.Cuota.inmueble_id)
             .filter(models.Inmueble.conjunto_id == conjunto_id))
        rows = [[c.id, u.torre or "", u.numero, c.concepto, c.periodo, c.monto, c.fecha_vencimiento, c.estado] for c, u in q.order_by(models.Cuota.fecha_vencimiento).all()]
        headers = ["Cuota", "Torre", "Inmueble", "Concepto", "Periodo", "Valor COP", "Vencimiento", "Estado"]
    elif tipo == "balance_prueba":
        state = estados_financieros(conjunto_id, desde, hasta, db, user)
        rows = [[x["codigo"], x["cuenta"], x["clase"], x["debito"], x["credito"]] for x in state["balance_prueba"]]
        headers = ["Código PUC", "Cuenta", "Clase", "Débitos COP", "Créditos COP"]
    else:
        q = db.query(mc.AsientoContable).filter_by(conjunto_id=conjunto_id)
        if desde: q = q.filter(mc.AsientoContable.fecha >= desde)
        if hasta: q = q.filter(mc.AsientoContable.fecha <= hasta)
        rows, headers = [], ["Asiento", "Fecha", "Descripción", "Origen", "Cuenta", "Nombre", "Débito", "Crédito"]
        for entry in q.order_by(mc.AsientoContable.fecha, mc.AsientoContable.id).all():
            for line, account in db.query(mc.LineaAsientoContable, mc.CuentaPUC).join(mc.CuentaPUC).filter(mc.LineaAsientoContable.asiento_id == entry.id).all():
                rows.append([entry.numero, entry.fecha, entry.descripcion, entry.origen, account.codigo, account.nombre, line.debito, line.credito])
    name = f"iris-{tipo}-{conjunto_id}.{formato}"
    if formato == "csv": return csv_response(rows, headers, name)
    if formato == "pdf":
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        stream = io.BytesIO()
        doc = SimpleDocTemplate(stream, pagesize=landscape(letter), rightMargin=12*mm, leftMargin=12*mm, topMargin=12*mm, bottomMargin=12*mm)
        styles = getSampleStyleSheet()
        data_table = [[Paragraph(escape(str(cell)), styles["BodyText"]) for cell in headers]]
        data_table += [[Paragraph(escape(str(cell if cell is not None else "")), styles["BodyText"]) for cell in row] for row in rows]
        widths = [doc.width / max(1, len(headers))] * len(headers)
        table = Table(data_table, colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#176d69")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#cbded9")),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f4fbf8")]),
            ("FONTSIZE", (0,0), (-1,-1), 7),
            ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ]))
        story = [Paragraph(f"IRIS · {tipo.replace('_', ' ').title()} · Conjunto {conjunto_id}", styles["Title"]),
                 Paragraph(f"Generado {date.today().isoformat()} · Periodo {desde or '—'} a {hasta or '—'}", styles["BodyText"]), Spacer(1, 8), table]
        doc.build(story)
        stream.seek(0)
        return Response(stream.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return workbook_response(tabla(headers, rows, tipo[:31]), name)


@router.post("/facturacion/lote")
def facturacion_masiva(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    cid = _required_set(data, db, user)
    periodo = str(data.get("periodo") or "")
    try: datetime.strptime(periodo, "%Y-%m")
    except ValueError: raise HTTPException(422, "Periodo inválido; usa AAAA-MM")
    concepto = str(data.get("concepto") or f"Administración {periodo}").strip()[:160]
    monto = _dec(data.get("monto"), "Monto")
    if monto <= 0: raise HTTPException(422, "El valor de facturación debe ser mayor que cero")
    try: vencimiento = date.fromisoformat(str(data.get("fecha_vencimiento") or ""))
    except ValueError: raise HTTPException(422, "La fecha de vencimiento es obligatoria (AAAA-MM-DD)")
    units = db.query(models.Inmueble).filter_by(conjunto_id=cid).order_by(models.Inmueble.id).all()
    created = skipped = 0
    for unit in units:
        exists = db.query(models.Cuota.id).filter_by(inmueble_id=unit.id, periodo=periodo, concepto=concepto).first()
        if exists:
            skipped += 1; continue
        db.add(models.Cuota(inmueble_id=unit.id, concepto=concepto, periodo=periodo, monto=monto,
                            fecha_vencimiento=vencimiento, estado="pendiente", creado_por=user.id))
        created += 1
    db.commit()
    sync_result = sincronizar_asientos(db, cid, user.id)
    return {"conjunto_id": cid, "periodo": periodo, "inmuebles": len(units), "cuentas_creadas": created,
            "omitidas_duplicadas": skipped, "asientos_generados": sync_result["asientos_creados"]}


@router.get("/cuentas-por-pagar")
def listar_cxp(conjunto_id: int, estado: str | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _auth_set(db, user, conjunto_id)
    q = db.query(mc.CuentaPorPagar).filter_by(conjunto_id=conjunto_id)
    if estado: q = q.filter_by(estado=estado)
    return [model_data(x) for x in q.order_by(mc.CuentaPorPagar.fecha_vencimiento).limit(500).all()]


@router.post("/cuentas-por-pagar", status_code=201)
def crear_cxp(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    cid = _required_set(data, db, user)
    proveedor = str(data.get("proveedor") or "").strip(); doc = str(data.get("documento") or "").strip(); concepto = str(data.get("concepto") or "").strip()
    if not proveedor or not doc or not concepto: raise HTTPException(422, "Proveedor, documento y concepto son obligatorios")
    try:
        fecha_doc = date.fromisoformat(str(data.get("fecha_documento")))
        fecha_ven = date.fromisoformat(str(data.get("fecha_vencimiento")))
    except ValueError: raise HTTPException(422, "Fechas inválidas (AAAA-MM-DD)")
    monto = _dec(data.get("monto"), "Monto")
    if monto <= 0: raise HTTPException(422, "El monto debe ser positivo")
    proveedor_id = int(data["proveedor_id"]) if data.get("proveedor_id") else None
    if proveedor_id and not db.query(models_v3.Proveedor.id).filter_by(id=proveedor_id, conjunto_id=cid).first():
        raise HTTPException(422, "El proveedor no pertenece a este conjunto")
    row = mc.CuentaPorPagar(conjunto_id=cid, proveedor_id=proveedor_id, proveedor=proveedor[:160], documento=doc[:80],
        concepto=concepto[:255], fecha_documento=fecha_doc, fecha_vencimiento=fecha_ven, monto=monto, notas=data.get("notas"), creada_por=user.id)
    db.add(row); db.flush()
    _make_entry(db, conjunto_id=cid, fecha=fecha_doc, descripcion=f"Causación factura {doc} · {proveedor}",
        origen="cuenta_por_pagar_causacion", origen_id=row.id,
        lineas=[{"codigo": "5135", "debito": monto, "credito": 0}, {"codigo": "2335", "debito": 0, "credito": monto}], usuario_id=user.id)
    db.commit(); db.refresh(row)
    return model_data(row)


@router.patch("/cuentas-por-pagar/{cuenta_id}/pagar")
def pagar_cxp(cuenta_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    row = db.query(mc.CuentaPorPagar).filter_by(id=cuenta_id).first()
    if not row: raise HTTPException(404, "Cuenta por pagar no encontrada")
    _auth_set(db, user, row.conjunto_id)
    if row.estado == "pagada": return {**model_data(row), "asiento_reutilizado": True}
    if row.estado != "pendiente": raise HTTPException(409, "Solo pueden pagarse cuentas pendientes")
    try: fecha = date.fromisoformat(str(data.get("fecha") or date.today().isoformat()))
    except ValueError: raise HTTPException(422, "Fecha de pago inválida")
    accounts = _puc(db, row.conjunto_id)
    expense_code = str(data.get("cuenta_gasto") or "5135")
    if expense_code not in accounts: raise HTTPException(422, "La cuenta de gasto no existe en el PUC")
    asiento, _ = _make_entry(db, conjunto_id=row.conjunto_id, fecha=fecha, descripcion=f"Pago proveedor {row.proveedor}: {row.concepto}",
        origen="cuenta_por_pagar", origen_id=row.id,
        lineas=[{"codigo": "2335", "debito": row.monto, "credito": 0}, {"codigo": "1110", "debito": 0, "credito": row.monto}], usuario_id=user.id)
    row.estado="pagada"; row.pagada_en=localnow(); db.commit(); db.refresh(row)
    return {**model_data(row), "asiento": _entry_dict(db, asiento)}


@router.get("/ejecucion-presupuestal")
def ejecucion_presupuestal(conjunto_id: int, periodo: str, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _auth_set(db, user, conjunto_id)
    budgets = db.query(models_v3.Presupuesto).filter_by(conjunto_id=conjunto_id, periodo=periodo).all()
    result=[]
    for b in budgets:
        try: year, month = map(int, periodo.split("-")); start=date(year, month, 1); end=date(year+1,1,1) if month==12 else date(year,month+1,1)
        except Exception: raise HTTPException(422, "Periodo inválido; usa AAAA-MM")
        actual = sum((_dec(x.monto) for x in db.query(models_v3.Egreso).filter(models_v3.Egreso.conjunto_id==conjunto_id, models_v3.Egreso.categoria==b.categoria, models_v3.Egreso.fecha>=start, models_v3.Egreso.fecha<end).all()), Decimal("0"))
        result.append({"periodo":periodo,"categoria":b.categoria,"presupuestado":str(_dec(b.monto_presupuestado)),"ejecutado":str(actual),"disponible":str(_dec(b.monto_presupuestado)-actual),"porcentaje_ejecucion":str((actual/_dec(b.monto_presupuestado)*100).quantize(CENT) if _dec(b.monto_presupuestado) else Decimal("0"))})
    return result


@router.get("/fondos")
def listar_fondos(conjunto_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    _auth_set(db,user,conjunto_id)
    row=db.query(mc.FondoReserva).filter_by(conjunto_id=conjunto_id,nombre="Fondo de Imprevistos").first()
    if not row:
        row=mc.FondoReserva(conjunto_id=conjunto_id,nombre="Fondo de Imprevistos",porcentaje=1,saldo=0,activo=True);db.add(row);db.commit();db.refresh(row)
    return [model_data(x) for x in db.query(mc.FondoReserva).filter_by(conjunto_id=conjunto_id).order_by(mc.FondoReserva.id).all()]


@router.put("/fondos/{fondo_id}")
def configurar_fondo(fondo_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    row=db.query(mc.FondoReserva).filter_by(id=fondo_id).first()
    if not row: raise HTTPException(404,"Fondo no encontrado")
    _auth_set(db,user,row.conjunto_id)
    if data.get("porcentaje") is not None:
        pct=_dec(data["porcentaje"],"Porcentaje")
        if pct < 1 or pct > 100: raise HTTPException(422,"El fondo de imprevistos debe ser mínimo 1 % y máximo 100 %")
        row.porcentaje=pct
    if data.get("activo") is not None: row.activo=bool(data["activo"])
    db.commit();db.refresh(row);return model_data(row)


@router.post("/fondos/{fondo_id}/causar")
def causar_fondo(fondo_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    row=db.query(mc.FondoReserva).filter_by(id=fondo_id).first()
    if not row: raise HTTPException(404,"Fondo no encontrado")
    _auth_set(db,user,row.conjunto_id)
    if not row.activo: raise HTTPException(409,"El fondo está inactivo")
    periodo=str(data.get("periodo") or "")
    try: datetime.strptime(periodo,"%Y-%m"); fecha=date.fromisoformat(str(data.get("fecha") or f"{periodo}-01"))
    except ValueError: raise HTTPException(422,"Periodo AAAA-MM y fecha válidos son obligatorios")
    base=_dec(data.get("base_presupuestal"),"Base presupuestal")
    if base <= 0: raise HTTPException(422,"La base presupuestal debe ser positiva")
    amount=(base*_dec(row.porcentaje)/Decimal("100")).quantize(CENT,rounding=ROUND_HALF_UP)
    asiento,created=_make_entry(db,conjunto_id=row.conjunto_id,fecha=fecha,descripcion=f"Traslado al {row.nombre} {periodo}",origen="fondo_reserva",origen_id=f"{row.id}:{periodo}",
        lineas=[{"codigo":"5195","debito":amount,"credito":0},{"codigo":"3305","debito":0,"credito":amount}],usuario_id=user.id)
    if created: row.saldo=_dec(row.saldo)+amount
    db.commit();db.refresh(row)
    return {"fondo":model_data(row),"periodo":periodo,"base_presupuestal":str(base),"porcentaje":str(row.porcentaje),"traslado":str(amount),"asiento":_entry_dict(db,asiento),"nuevo":created}


@router.get("/documentos")
def listar_documentos(conjunto_id: int, db: Session=Depends(get_db),user=Depends(get_usuario_v3)):
    _auth_set(db,user,conjunto_id)
    return [model_data(x) for x in db.query(mc.DocumentoContable).filter_by(conjunto_id=conjunto_id).order_by(mc.DocumentoContable.fecha.desc(),mc.DocumentoContable.id.desc()).limit(500).all()]


@router.post("/documentos",status_code=201)
def registrar_documento(data:dict,db:Session=Depends(get_db),user=Depends(get_usuario_v3)):
    cid=_required_set(data,db,user)
    tipo=str(data.get("tipo") or "").strip(); numero=str(data.get("numero") or "").strip(); descripcion=str(data.get("descripcion") or "").strip()
    if not tipo or not numero or not descripcion: raise HTTPException(422,"Tipo, número y descripción son obligatorios")
    try: fecha=date.fromisoformat(str(data.get("fecha") or date.today().isoformat()))
    except ValueError: raise HTTPException(422,"Fecha inválida")
    monto=_dec(data.get("valor",0),"Valor")
    if monto<0: raise HTTPException(422,"El valor no puede ser negativo")
    metadata=data.get("metadatos")
    row=mc.DocumentoContable(conjunto_id=cid,tipo=tipo[:50],numero=numero[:100],fecha=fecha,tercero=str(data.get("tercero") or "")[:160] or None,
        descripcion=descripcion[:255],valor=monto,estado=str(data.get("estado") or "registrado")[:30],archivo_url=str(data.get("archivo_url") or "")[:500] or None,
        metadatos=json.dumps(metadata,ensure_ascii=False) if isinstance(metadata,(dict,list)) else None,creado_por=user.id)
    db.add(row);db.commit();db.refresh(row);return model_data(row)


@router.get("/auditoria")
def auditar_finanzas(conjunto_id:int,desde:datetime|None=None,hasta:datetime|None=None,db:Session=Depends(get_db),user=Depends(get_usuario_v3)):
    _auth_set(db,user,conjunto_id)
    q=db.query(models.Auditoria).filter_by(conjunto_id=conjunto_id)
    # Todos los cambios quedan en la bitácora global; aquí se exponen los caminos contables y de recaudo.
    q=q.filter(models.Auditoria.ruta.like("%contabilidad%") | models.Auditoria.ruta.like("%payments%") | models.Auditoria.ruta.like("%cuotas%") | models.Auditoria.ruta.like("%reservas%"))
    if desde:q=q.filter(models.Auditoria.creado_en>=desde)
    if hasta:q=q.filter(models.Auditoria.creado_en<=hasta)
    return [{"id":x.id,"fecha_hora":x.creado_en.isoformat() if x.creado_en else None,"usuario":x.email_usuario,"accion":x.accion,"ruta":x.ruta,"codigo_http":x.codigo_http,"ip":x.ip} for x in q.order_by(models.Auditoria.creado_en.desc()).limit(500).all()]


@router.get("/tributario/estado")
def estado_tributario(conjunto_id:int,db:Session=Depends(get_db),user=Depends(get_usuario_v3)):
    _auth_set(db,user,conjunto_id)
    return {"conjunto_id":conjunto_id,"pais":"CO","estado":"requiere_configuracion_dian","integracion_activa":False,
            "mensaje":"La emisión/transmisión electrónica requiere habilitación DIAN, certificado digital, resolución de numeración y credenciales del proveedor tecnológico. No se marcarán documentos como emitidos sin acuse válido.",
            "resumen_disponible":True,"documentos_registrados":db.query(mc.DocumentoContable).filter_by(conjunto_id=conjunto_id).count()}


@router.get("/tributario/resumen")
def resumen_tributario(conjunto_id:int,periodo:str,db:Session=Depends(get_db),user=Depends(get_usuario_v3)):
    _auth_set(db,user,conjunto_id)
    try: year,month=map(int,periodo.split("-"));start=date(year,month,1);end=date(year+1,1,1) if month==12 else date(year,month+1,1)
    except Exception: raise HTTPException(422,"Periodo inválido; usa AAAA-MM")
    income=sum((_dec(x.valor) for x in db.query(mc.DocumentoContable).filter(mc.DocumentoContable.conjunto_id==conjunto_id,mc.DocumentoContable.fecha>=start,mc.DocumentoContable.fecha<end,mc.DocumentoContable.tipo.in_(["factura_venta","documento_equivalente","ingreso"])).all()),Decimal("0"))
    expense=sum((_dec(x.valor) for x in db.query(mc.DocumentoContable).filter(mc.DocumentoContable.conjunto_id==conjunto_id,mc.DocumentoContable.fecha>=start,mc.DocumentoContable.fecha<end,mc.DocumentoContable.tipo.in_(["factura_compra","soporte_gasto","egreso"])).all()),Decimal("0"))
    return {"periodo":periodo,"ingresos_registrados":str(income),"egresos_registrados":str(expense),"impuestos":[],"nota":"Resumen de trabajo, no sustituye la liquidación ni presentación tributaria profesional."}


@router.get("/certificacion",response_class=HTMLResponse)
def certificacion(conjunto_id:int,fecha_corte:date|None=None,db:Session=Depends(get_db),user=Depends(get_usuario_v3)):
    _auth_set(db,user,conjunto_id)
    cutoff=fecha_corte or date.today()
    conjunto=db.query(models.Conjunto).filter_by(id=conjunto_id).first()
    state=estados_financieros(conjunto_id,None,cutoff,db,user)
    nombre_conjunto = escape(conjunto.nombre if conjunto else str(conjunto_id))
    nit_conjunto = escape(conjunto.nit if conjunto else "—")
    html=f"""<!doctype html><html lang='es'><meta charset='utf-8'><title>Certificación contable · {nombre_conjunto}</title>
    <style>body{{font:15px Arial,sans-serif;color:#173d44;max-width:820px;margin:48px auto;line-height:1.6}}h1{{font-size:24px}}.note{{background:#fff6df;padding:14px;border-left:4px solid #c58b1b}}.sign{{margin-top:90px;border-top:1px solid #555;width:320px;padding-top:8px}}@media print{{button{{display:none}}}}</style>
    <button onclick='window.print()'>Imprimir / Guardar PDF</button><h1>Certificación de información contable — borrador</h1>
    <p>Conjunto: <b>{nombre_conjunto}</b> · NIT: {nit_conjunto}</p><p>Fecha de corte: {cutoff.isoformat()}</p>
    <p>Este documento presenta un resumen de información registrada en IRIS a la fecha de corte. Requiere verificación y firma del contador responsable antes de su uso como certificación oficial.</p>
    <ul><li>Activos: COP {state['activos']}</li><li>Pasivos: COP {state['pasivos']}</li><li>Patrimonio: COP {state['patrimonio']}</li><li>Ingresos: COP {state['ingresos']}</li><li>Gastos: COP {state['gastos']}</li></ul>
    <p class='note'>Borrador generado automáticamente; no es una firma digital ni una certificación legal hasta su revisión y suscripción por profesional autorizado.</p>
    <div class='sign'>Contador responsable · Nombre y tarjeta profesional</div></html>"""
    return HTMLResponse(html,headers={"Content-Disposition":f'inline; filename="certificacion-contable-{conjunto_id}-{cutoff}.html"'})
