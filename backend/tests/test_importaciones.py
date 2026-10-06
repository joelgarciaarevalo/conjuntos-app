from io import BytesIO
import time
from openpyxl import Workbook

from test_integracion import client, auth


def test_xlsx_resident_import_and_forced_password_change():
    admin, _ = auth("admin@iris-demo.com", "Admin2026")
    suffix = str(int(time.time()))
    workbook = Workbook(); sheet = workbook.active
    sheet.append(["nombre_completo", "cedula", "email", "telefono", "password", "inmueble_torre", "inmueble_numero", "estado_inmueble"])
    sheet.append(["Residente importado", "XLSX-" + suffix, f"importado-{suffix}@example.com", "3001112233", "Temporal2026", "88", "8801", "ocupado"])
    stream = BytesIO(); workbook.save(stream); stream.seek(0)
    response = client.post("/v2/import/residents?conjunto_id=1", headers=admin, files={"file": ("residentes.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["creados"] == 1 and not result["errores"], result
    headers, profile = auth(f"importado-{suffix}@example.com", "Temporal2026")
    assert profile["cambio_password_requerido"] is True
    units = client.get("/v2/my-units", headers=headers)
    assert units.status_code == 200 and any(x["numero"] == "8801" for x in units.json())
    change = client.post("/auth/change-password", headers=headers, json={"current_password": "Temporal2026", "new_password": "ResidenteNuevo2026"})
    assert change.status_code == 200, change.text
    assert client.post("/auth/login", json={"email": f"importado-{suffix}@example.com", "password": "ResidenteNuevo2026"}).status_code == 200
