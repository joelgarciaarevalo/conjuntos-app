import uuid

from test_integracion import auth, client


def test_admin_crea_cuenta_contador_separada_y_restringida_al_conjunto():
    admin, _ = auth("admin@iris-demo.com", "Admin2026")
    suffix = uuid.uuid4().hex[:10]
    email = f"contadora-{suffix}@example.com"
    password = "ContadoraSegura2026!"
    response = client.post("/gestion/conjuntos/1/contadores", headers=admin, json={
        "nombre_completo": "Contadora Independiente",
        "cedula": f"CNT-{suffix}",
        "email": email,
        "telefono": "3001234567",
        "password": password,
    })
    assert response.status_code == 201, response.text
    assert response.json()["rol"] == "contador"
    assert response.json()["conjunto_id"] == 1
    assert response.json()["cambio_password_requerido"] is True

    accountant, user = auth(email, password)
    assert user["rol"] == "contador"
    assert user["cambio_password_requerido"] is True
    assert [row["id"] for row in client.get("/conjuntos/", headers=accountant).json()] == [1]
    assert client.get("/gestion/usuarios", headers=accountant).status_code == 403
    assert client.get("/v3/contabilidad/profesional/puc", headers=accountant, params={"conjunto_id": 1}).status_code == 200


def test_residente_no_puede_crear_una_cuenta_contador():
    resident, _ = auth("residente@iris-demo.com", "Usuario2026")
    response = client.post("/gestion/conjuntos/1/contadores", headers=resident, json={
        "nombre_completo": "No autorizado", "cedula": "CNT-UNAUTH", "email": "not-allowed@example.com",
        "password": "ContadoraSegura2026!",
    })
    assert response.status_code == 403


def test_cuenta_demo_contador_inicia_en_el_rol_correcto():
    accountant, user = auth("contador@iris-demo.com", "Contador2026!")
    assert user["rol"] == "contador"
    assert user["cambio_password_requerido"] is False
    assert client.get("/v3/contabilidad/profesional/puc", headers=accountant, params={"conjunto_id": 1}).status_code == 200
    assert client.get("/gestion/usuarios", headers=accountant).status_code == 403
