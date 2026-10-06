import uuid
from datetime import date, timedelta

from test_integracion import auth, client
from app.database import SessionLocal
from app import models


def test_contador_operativo_login_alcance_y_modulos_financieros():
    admin, _ = auth("admin@iris-demo.com", "Admin2026")
    residente, residente_user = auth("residente@iris-demo.com", "Usuario2026")
    suffix = uuid.uuid4().hex[:10]
    email = f"contador-{suffix}@example.com"
    password = "ContadorPrueba2026"

    registered = client.post("/auth/registro", json={
        "nombre_completo": "Contador de prueba", "cedula": f"CNT-{suffix}",
        "email": email, "password": password,
    })
    assert registered.status_code == 201, registered.text
    member = client.post("/v2/memberships", headers=admin, json={
        "usuario_id": registered.json()["id"], "conjunto_id": 1, "rol": "contador",
    })
    assert member.status_code == 201, member.text

    contador, user = auth(email, password)
    assert user["rol"] == "contador"
    conjuntos = client.get("/conjuntos/", headers=contador)
    assert conjuntos.status_code == 200, conjuntos.text
    assert [row["id"] for row in conjuntos.json()] == [1]
    units = client.get("/conjuntos/1/inmuebles/", headers=contador)
    assert units.status_code == 200 and units.json()
    unit_id = units.json()[0]["id"]

    fee = client.post("/cuotas/", headers=contador, json={
        "inmueble_id": unit_id, "concepto": "Cuota creada por contador", "periodo": date.today().strftime("%Y-%m"),
        "monto": 120000, "fecha_vencimiento": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert fee.status_code == 201, fee.text

    reported = client.post("/v2/payments", headers=residente, json={
        "cuota_id": fee.json()["id"], "metodo": "transferencia", "referencia": f"REF-{suffix}",
    })
    assert reported.status_code == 201, reported.text
    pending = client.get("/v2/payments", headers=contador)
    assert pending.status_code == 200 and any(row["id"] == reported.json()["id"] for row in pending.json())
    assert client.patch(f"/v2/payments/{reported.json()['id']}", headers=contador, json={
        "estado": "verificado", "notas": "Conciliación de prueba",
    }).status_code == 200
    paid_fee = client.get("/cuotas/", headers=contador)
    assert any(row["id"] == fee.json()["id"] and row["estado"] == "pagada" for row in paid_fee.json())
    assert any(row["titulo"] == "Pago por verificar" for row in client.get("/notificaciones/", headers=contador).json())

    manual_fee = client.post("/cuotas/", headers=contador, json={
        "inmueble_id": unit_id, "concepto": "Pago manual por contador", "periodo": "2099-12",
        "monto": 35000, "fecha_vencimiento": "2099-12-31",
    })
    assert manual_fee.status_code == 201, manual_fee.text
    manual = client.post("/v2/payments/manual", headers=contador, json={
        "cuota_id": manual_fee.json()["id"], "metodo": "efectivo", "referencia": f"REC-{suffix}",
    })
    assert manual.status_code == 201 and manual.json()["estado"] == "verificado", manual.text

    expense = client.post("/v3/contabilidad/egresos", headers=contador, json={
        "conjunto_id": 1, "concepto": "Reparación de prueba", "categoria": "mantenimiento",
        "monto": 42000, "fecha": date.today().isoformat(),
    })
    assert expense.status_code == 201, expense.text
    expense_id = expense.json()["id"]
    assert client.get("/v3/contabilidad/egresos?conjunto_id=1", headers=contador).status_code == 200
    changed = client.patch(f"/v3/contabilidad/egresos/{expense_id}", headers=contador, json={"monto": 43000})
    assert changed.status_code == 200 and float(changed.json()["monto"]) == 43000

    budget = client.post("/v3/contabilidad/presupuestos", headers=contador, json={
        "conjunto_id": 1, "periodo": date.today().strftime("%Y-%m"), "categoria": "mantenimiento",
        "monto_presupuestado": 200000,
    })
    assert budget.status_code == 201, budget.text
    budgets = client.get("/v3/contabilidad/presupuestos", headers=contador, params={"conjunto_id": 1})
    assert budgets.status_code == 200 and any(row["id"] == budget.json()["id"] for row in budgets.json())
    report = client.get("/v3/contabilidad/informes/periodo", headers=contador, params={
        "conjunto_id": 1, "desde": date.today().replace(day=1).isoformat(), "hasta": date.today().isoformat(),
    })
    assert report.status_code == 200 and "recaudado" in report.json()

    # Sigue sin ser un perfil general de administración ni de portería.
    assert client.get("/gestion/usuarios", headers=contador).status_code == 403
    assert client.get("/v2/memberships", headers=contador).status_code == 403
    assert client.get("/v3/contabilidad/config-cartera", headers=contador, params={"conjunto_id": 1}).status_code == 403
    assert client.post("/comunicados/", headers=contador, json={
        "conjunto_id": 1, "titulo": "No permitido", "contenido": "Prueba",
    }).status_code == 403

    other = client.post("/conjuntos/", headers=admin, json={
        "nombre": f"Conjunto aislado {suffix}", "nit": str(700000000 + int(suffix[:8], 16) % 99999999),
        "direccion": "Bogotá, Colombia",
    })
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]
    assert client.get(f"/conjuntos/{other_id}/inmuebles/", headers=contador).status_code == 403
    assert client.get("/v3/contabilidad/egresos", headers=contador, params={"conjunto_id": other_id}).status_code == 403
    assert client.delete(f"/v3/contabilidad/egresos/{expense_id}", headers=contador).status_code == 204
    db = SessionLocal()
    try:
        db.query(models.Cuota).filter(models.Cuota.creado_por == user["id"], models.Cuota.concepto.in_(
            ["Cuota creada por contador", "Pago manual por contador"])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
