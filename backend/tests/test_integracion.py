import os
import tempfile
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_DB = tempfile.NamedTemporaryFile(prefix="iris-test-", suffix=".db", delete=False)
_DB.close()
os.environ["APP_ENV"] = "development"
os.environ["DATABASE_URL"] = "sqlite:///" + _DB.name
os.environ["SECRET_KEY"] = "pytest-secret-not-for-production"
os.environ["CORS_ORIGINS"] = "http://localhost:4200"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def auth(email, password):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}, response.json()


def test_resident_qr_porter_reservations_pqrs_and_reports():
    admin, _ = auth("admin@iris-demo.com", "Admin2026")
    resident, resident_user = auth("residente@iris-demo.com", "Usuario2026")
    porter, porter_user = auth("portero@iris-demo.com", "Portero2026")
    assert porter_user["rol"] == "portero"

    unit = client.get("/conjuntos/1/inmuebles/", headers=resident).json()[0]
    resident_qr = client.post("/qr/mio/residente", params={"inmueble_id": unit["id"]}, headers=resident)
    assert resident_qr.status_code == 201, resident_qr.text
    assert resident_qr.json()["tipo"] == "residente"

    visit = client.post("/qr/mio/visitas", headers=resident, json={
        "tipo": "visita", "inmueble_id": unit["id"], "visitante_nombre": "Persona de prueba",
        "horas_validez": 24, "usos_maximos": 2,
    })
    assert visit.status_code == 201, visit.text
    checked = client.post("/qr/validar", headers=porter, json={"codigo": "IRIS-QR:" + visit.json()["token"], "registrar_ingreso": True})
    assert checked.status_code == 200 and checked.json()["valido"]
    assert checked.json()["qr"]["usos_actuales"] == 1
    assert client.get("/qr/", headers=porter).status_code == 403

    zone = client.get("/conjuntos/1/zonas-comunes/", headers=admin).json()[0]
    zone_update = client.patch(f"/conjuntos/1/zonas-comunes/{zone['id']}", headers=admin, json={
        "requiere_aprobacion": False, "hora_apertura": "08:00", "hora_cierre": "18:00", "duracion_max_minutos": 120,
    })
    assert zone_update.status_code == 200, zone_update.text
    start = (datetime.now(ZoneInfo("America/Bogota")) + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    body = {"zona_id": zone["id"], "inmueble_id": unit["id"], "fecha_inicio": start.replace(tzinfo=None).isoformat(), "fecha_fin": (start + timedelta(hours=1)).replace(tzinfo=None).isoformat()}
    reservation = client.post("/reservas/", headers=resident, json=body)
    assert reservation.status_code == 201 and reservation.json()["estado"] == "aprobada"
    reservation_id = reservation.json()["id"]
    assert client.post(f"/reservas/{reservation_id}/cancelar", headers=resident).status_code == 200

    texto_largo = "Descripción completa para validar que la PQRS no trunca ni limita a 200 caracteres. " * 8
    pqrs = client.post("/pqrs/", headers=resident, json={"inmueble_id": unit["id"], "tipo": "queja", "descripcion": texto_largo})
    assert pqrs.status_code == 201, pqrs.text
    assert pqrs.json()["descripcion"] == texto_largo
    respuesta_larga = ("Respuesta detallada de administración sin tope de 200 caracteres. " * 8).strip()
    answered = client.patch(f"/pqrs/{pqrs.json()['id']}/responder", headers=admin, json={"respuesta_admin": respuesta_larga, "estado": "resuelto"})
    assert answered.status_code == 200 and answered.json()["estado"] == "resuelto"
    assert answered.json()["respuesta_admin"] == respuesta_larga
    assert any(x["titulo"] == "Respuesta a tu PQRS" for x in client.get("/notificaciones/", headers=resident).json())

    unit_created = client.post("/conjuntos/1/inmuebles", headers=admin, json={"numero": "TEST-01", "torre": "TEST", "propietario_id": resident_user["id"]})
    assert unit_created.status_code == 201 and str(unit_created.json()["estado"]).lower() == "ocupado"
    assert client.post("/conjuntos/1/zonas-comunes/", headers=resident, json={"nombre": "No autorizado"}).status_code == 403

    announcement = client.post("/comunicados/", headers=admin, json={"conjunto_id": 1, "titulo": "Aviso de prueba", "contenido": "Mensaje a residentes"})
    assert announcement.status_code == 201, announcement.text
    assert any(x["titulo"] == "Nuevo comunicado" for x in client.get("/notificaciones/", headers=resident).json())

    fee = client.post("/cuotas/", headers=admin, json={"inmueble_id": unit["id"], "concepto": "Administración", "periodo": "2026-10", "monto": 150000, "fecha_vencimiento": "2026-10-31"})
    assert fee.status_code == 201, fee.text
    assert client.get(f"/cuotas/paz-y-salvo/{unit['id']}", headers=resident).json()["paz_y_salvo"] is False
    assert client.patch(f"/cuotas/{fee.json()['id']}/pago", headers=admin, json={"pagada": True}).status_code == 200
    assert client.get(f"/cuotas/paz-y-salvo/{unit['id']}", headers=resident).json()["paz_y_salvo"] is True

    package = client.post("/paquetes/", headers=porter, json={"inmueble_id": unit["id"], "transportadora": "Prueba", "descripcion": "Caja pequeña"})
    assert package.status_code == 201, package.text
    assert any(p["id"] == package.json()["id"] for p in client.get("/paquetes/", headers=resident).json())
    assert client.patch(f"/paquetes/{package.json()['id']}/retirar", headers=resident, json={"retirado_por": "Residente"}).status_code == 200

    parking = client.post("/parqueaderos/", headers=admin, json={"conjunto_id": 1, "inmueble_id": unit["id"], "identificador": "P-TEST", "tipo": "privado", "placa": "ABC123", "tarifa_mensual": 45000})
    assert parking.status_code == 201, parking.text
    assert any(p["identificador"] == "P-TEST" for p in client.get("/parqueaderos/", headers=resident).json())
    unassigned = client.patch(f"/parqueaderos/{parking.json()['id']}", headers=admin, json={"inmueble_id": None})
    assert unassigned.status_code == 200 and unassigned.json()["inmueble_id"] is None
    assert not any(p["identificador"] == "P-TEST" for p in client.get("/parqueaderos/", headers=resident).json())
    reassigned = client.patch(f"/parqueaderos/{parking.json()['id']}", headers=admin, json={"inmueble_id": unit["id"], "tarifa_mensual": 45000})
    assert reassigned.status_code == 200 and reassigned.json()["inmueble_id"] == unit["id"]
    cobro_parqueadero = {"conjunto_id": 1, "periodo": "2099-01", "fecha_vencimiento": "2099-01-31"}
    first_charge = client.post("/parqueaderos/generar-cobros", headers=admin, json=cobro_parqueadero)
    assert first_charge.status_code == 200 and first_charge.json()["creados"] == 1, first_charge.text
    duplicate_charge = client.post("/parqueaderos/generar-cobros", headers=admin, json=cobro_parqueadero)
    assert duplicate_charge.status_code == 200 and duplicate_charge.json()["creados"] == 0 and duplicate_charge.json()["omitidos"] == 1
    assert any(f["concepto"] == "Parqueadero P-TEST" and float(f["monto"]) == 45000 for f in client.get("/cuotas/", headers=resident).json())
    xlsx = client.get("/reportes/reservas.xlsx", headers=admin)
    assert xlsx.status_code == 200 and xlsx.content.startswith(b"PK")
    assert client.get("/reportes/reservas.xlsx", headers=resident).status_code == 403
