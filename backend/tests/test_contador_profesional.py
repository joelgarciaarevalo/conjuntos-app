from datetime import date
import uuid

from test_integracion import auth, client
from app.database import SessionLocal
from app import models


def test_puc_asiento_balanceado_estado_y_exportacion():
    admin, _ = auth("admin@iris-demo.com", "Admin2026")
    accounts = client.get("/v3/contabilidad/profesional/puc", headers=admin, params={"conjunto_id": 1})
    assert accounts.status_code == 200, accounts.text
    codes = {x["codigo"] for x in accounts.json()}
    assert {"1110", "4170", "5195"} <= codes

    entry = client.post("/v3/contabilidad/profesional/asientos", headers=admin, json={
        "conjunto_id": 1, "fecha": date.today().isoformat(), "descripcion": "Asiento de prueba balanceado",
        "lineas": [
            {"codigo": "1110", "debito": 12500, "credito": 0},
            {"codigo": "4170", "debito": 0, "credito": 12500},
        ],
    })
    assert entry.status_code == 201, entry.text
    assert len(entry.json()["lineas"]) == 2

    unbalanced = client.post("/v3/contabilidad/profesional/asientos", headers=admin, json={
        "conjunto_id": 1, "descripcion": "Asiento descuadrado", "lineas": [
            {"codigo": "1110", "debito": 12500, "credito": 0},
            {"codigo": "4170", "debito": 0, "credito": 12000},
        ],
    })
    assert unbalanced.status_code == 422

    report = client.get("/v3/contabilidad/profesional/estados-financieros", headers=admin, params={"conjunto_id": 1})
    assert report.status_code == 200 and float(report.json()["total_debitos"]) == float(report.json()["total_creditos"])
    exported = client.get("/v3/contabilidad/profesional/exportar", headers=admin, params={"conjunto_id": 1, "tipo": "libro", "formato": "xlsx"})
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument")
    pdf = client.get("/v3/contabilidad/profesional/exportar", headers=admin, params={"conjunto_id": 1, "tipo": "balance_prueba", "formato": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_lote_idempotente_proveedor_fondo_y_dian_status():
    admin, _ = auth("admin@iris-demo.com", "Admin2026")
    period = f"2097-{uuid.uuid4().int % 12 + 1:02d}"
    payload = {"conjunto_id": 1, "periodo": period, "concepto": "Cuota masiva prueba", "monto": 85000, "fecha_vencimiento": f"{period}-28"}
    first = client.post("/v3/contabilidad/profesional/facturacion/lote", headers=admin, json=payload)
    second = client.post("/v3/contabilidad/profesional/facturacion/lote", headers=admin, json=payload)
    assert first.status_code == 200 and first.json()["cuentas_creadas"] > 0, first.text
    assert second.status_code == 200 and second.json()["cuentas_creadas"] == 0, second.text
    assert second.json()["omitidas_duplicadas"] == first.json()["cuentas_creadas"]

    bill = client.post("/v3/contabilidad/profesional/cuentas-por-pagar", headers=admin, json={
        "conjunto_id": 1, "proveedor": "Proveedor prueba", "documento": f"FC-{uuid.uuid4().hex[:8]}",
        "concepto": "Mantenimiento", "fecha_documento": date.today().isoformat(),
        "fecha_vencimiento": date.today().isoformat(), "monto": 15000,
    })
    assert bill.status_code == 201, bill.text
    paid = client.patch(f"/v3/contabilidad/profesional/cuentas-por-pagar/{bill.json()['id']}/pagar", headers=admin, json={})
    assert paid.status_code == 200 and paid.json()["estado"] == "pagada", paid.text
    assert paid.json()["asiento"]["origen"] == "cuenta_por_pagar"

    funds = client.get("/v3/contabilidad/profesional/fondos", headers=admin, params={"conjunto_id": 1})
    assert funds.status_code == 200 and funds.json()
    fund = funds.json()[0]
    transfer = client.post(f"/v3/contabilidad/profesional/fondos/{fund['id']}/causar", headers=admin, json={
        "periodo": "2096-01", "base_presupuestal": 1000000,
    })
    assert transfer.status_code == 200 and float(transfer.json()["traslado"]) >= 10000

    tax = client.get("/v3/contabilidad/profesional/tributario/estado", headers=admin, params={"conjunto_id": 1})
    assert tax.status_code == 200 and tax.json()["integracion_activa"] is False
    db = SessionLocal()
    try:
        db.query(models.Cuota).filter_by(periodo=period, concepto="Cuota masiva prueba").delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_modulos_financieros_denegados_a_residente():
    resident, _ = auth("residente@iris-demo.com", "Usuario2026")
    response = client.get("/v3/contabilidad/profesional/puc", headers=resident, params={"conjunto_id": 1})
    assert response.status_code == 403


def test_asiento_automatico_tras_pago_de_administracion():
    admin, _ = auth("admin@iris-demo.com", "Admin2026")
    unit = client.get("/conjuntos/1/inmuebles/", headers=admin).json()[0]
    period = f"2098-{uuid.uuid4().int % 12 + 1:02d}"
    fee = client.post("/cuotas/", headers=admin, json={
        "inmueble_id": unit["id"], "concepto": "Prueba auto-asiento", "periodo": period,
        "monto": 44500, "fecha_vencimiento": f"{period}-28",
    })
    assert fee.status_code == 201, fee.text
    paid = client.patch(f"/cuotas/{fee.json()['id']}/pago", headers=admin, json={"pagada": True})
    assert paid.status_code == 200, paid.text
    entries = client.get("/v3/contabilidad/profesional/asientos", headers=admin, params={"conjunto_id": 1})
    assert entries.status_code == 200
    assert any(x["origen"] == "cuota_pagada" and x["origen_id"] == str(fee.json()["id"]) for x in entries.json())
