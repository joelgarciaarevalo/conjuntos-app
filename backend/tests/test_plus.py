from datetime import date, timedelta
from io import BytesIO
import time

from openpyxl import Workbook

from test_integracion import client, auth


def test_plus_roles_incidents_payments_private_files_and_recovery():
    admin, _ = auth("admin@iris-demo.com", "Admin2026")
    resident, resident_user = auth("residente@iris-demo.com", "Usuario2026")
    porter, porter_user = auth("portero@iris-demo.com", "Portero2026")

    units = client.get("/v2/my-units", headers=resident)
    assert units.status_code == 200 and units.json()
    unit = units.json()[0]
    operational = client.get("/v2/operational-units", headers=porter)
    assert operational.status_code == 200 and any(x["id"] == unit["id"] for x in operational.json())
    assert client.get("/v2/memberships", headers=resident).status_code == 403

    incident = client.post("/v2/incidents", headers=resident, json={
        "inmueble_id": unit["id"], "titulo": "Prueba de servicio", "descripcion": "Incidente automatizado", "categoria": "mantenimiento"
    })
    assert incident.status_code == 201 and "id" in incident.json(), incident.text
    updated = client.patch(f"/v2/incidents/{incident.json()['id']}", headers=admin, json={"estado": "en_proceso", "prioridad": "alta"})
    assert updated.status_code == 200 and updated.json()["estado"] == "en_proceso"
    assert any(n["titulo"] == "Actualización de incidente" for n in client.get("/notificaciones/", headers=resident).json())

    announcement = client.post("/comunicados/", headers=admin, json={"conjunto_id": unit["conjunto_id"], "titulo": "Archivo privado de prueba", "contenido": "Adjunto de prueba"})
    assert announcement.status_code == 201, announcement.text
    pdf = b"%PDF-1.4\n%IRIS test\n%%EOF"
    attachment = client.post(f"/v2/announcements/{announcement.json()['id']}/attachment", headers=admin, files={"file": ("aviso.pdf", pdf, "application/pdf")})
    assert attachment.status_code == 200, attachment.text
    private_file = client.get(attachment.json()["adjunto_url"], headers=resident)
    assert private_file.status_code == 200 and private_file.content.startswith(b"%PDF")
    assert client.get(attachment.json()["adjunto_url"]).status_code in (401, 403)

    contact = client.post("/v2/emergency-contacts", headers=resident, json={
        "inmueble_id": unit["id"], "nombre": "Contacto prueba", "telefono": "+573001112233", "visible": True
    })
    assert contact.status_code == 201, contact.text
    assert any(x["id"] == contact.json()["id"] for x in client.get("/v2/emergency-contacts", headers=porter).json())
    assert client.delete(f"/v2/emergency-contacts/{contact.json()['id']}", headers=resident).status_code == 204
    unsafe_push = client.post("/v2/push/subscriptions", headers=resident, json={"endpoint": "https://127.0.0.1/admin", "keys": {"p256dh": "abc", "auth": "def"}})
    assert unsafe_push.status_code == 422

    fee = client.post("/cuotas/", headers=admin, json={
        "inmueble_id": unit["id"], "concepto": "Cuota de prueba Plus", "periodo": f"plus-{int(time.time())}",
        "monto": 125000, "fecha_vencimiento": (date.today() + timedelta(days=20)).isoformat()
    })
    assert fee.status_code == 201, fee.text
    payment = client.post("/v2/payments", headers=resident, json={"cuota_id": fee.json()["id"], "metodo": "transferencia", "referencia": "TRX-TEST"})
    assert payment.status_code == 201, payment.text
    verified = client.patch(f"/v2/payments/{payment.json()['id']}", headers=admin, json={"estado": "verificado", "notas": "Conciliado"})
    assert verified.status_code == 200 and verified.json()["estado"] == "verificado"
    receipt = client.get(f"/v2/payments/{payment.json()['id']}/receipt", headers=resident)
    assert receipt.status_code == 200 and b"Recibo de pago" in receipt.content

    manual_fee = client.post("/cuotas/", headers=admin, json={
        "inmueble_id": unit["id"], "concepto": "Pago en caja", "periodo": f"caja-{int(time.time())}",
        "monto": 45000, "fecha_vencimiento": (date.today() + timedelta(days=20)).isoformat()
    })
    assert manual_fee.status_code == 201
    manual = client.post("/v2/payments/manual", headers=admin, json={"cuota_id": manual_fee.json()["id"], "metodo": "efectivo"})
    assert manual.status_code == 201 and manual.json()["estado"] == "verificado"
    for existing_fee in client.get("/cuotas/", headers=resident).json():
        if existing_fee["inmueble_id"] == unit["id"] and existing_fee["estado"] == "pendiente":
            assert client.patch(f"/cuotas/{existing_fee['id']}/pago", headers=admin, json={"pagada": True}).status_code == 200
    assert client.get(f"/cuotas/paz-y-salvo/{unit['id']}", headers=resident).json()["paz_y_salvo"] is True

    template = client.get("/v2/import/template/residents", headers=admin)
    assert template.status_code == 200 and template.content.startswith(b"PK")
    assert client.get("/v2/audit?limit=50", headers=admin).status_code == 200

    suffix = str(int(time.time()))
    created = client.post("/auth/registro", json={"nombre_completo": "Cuenta recuperable", "cedula": "RESET-" + suffix, "email": f"reset-{suffix}@example.com", "password": "TemporalPass2026"})
    assert created.status_code == 201, created.text
    reset_request = client.post("/auth/forgot-password", json={"email": f"reset-{suffix}@example.com"})
    token = reset_request.json().get("debug_token")
    assert token
    reset = client.post("/auth/reset-password", json={"token": token, "password": "NuevaPassword2026"})
    assert reset.status_code == 200, reset.text
    assert client.post("/auth/login", json={"email": f"reset-{suffix}@example.com", "password": "NuevaPassword2026"}).status_code == 200

    new_guard = client.post("/auth/registro", json={"nombre_completo": "Portero temporal", "cedula": "PORT-" + suffix, "email": f"porter-{suffix}@example.com", "password": "TemporalPass2026"})
    assert new_guard.status_code == 201, new_guard.text
    member = client.post("/v2/memberships", headers=admin, json={"usuario_id": new_guard.json()["id"], "conjunto_id": unit["conjunto_id"], "rol": "portero"})
    assert member.status_code == 201, member.text
    assert client.delete(f"/v2/memberships/{member.json()['id']}", headers=admin).status_code == 204
    _, reverted = auth(f"porter-{suffix}@example.com", "TemporalPass2026")
    assert reverted["rol"] == "residente"
