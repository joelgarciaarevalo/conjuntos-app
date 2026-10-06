"""Pruebas de extremo a extremo de los módulos de IRIS 3.0."""
import time
import uuid
from datetime import date, datetime, timedelta

# test_integracion prepara el entorno (base temporal, SECRET_KEY) y expone el cliente.
from test_integracion import auth, client

from jose import jwt as jose_jwt

from app.dependencies import ALGORITHM, SECRET_KEY
from app.services import payments_gateway as gw
from app.services import totp

EJEMPLO_PNG = b"\x89PNG\r\n\x1a\n" + b"IRIS" * 40


def _contexto():
    admin, _ = auth("admin@iris-demo.com", "Admin2026")
    residente, usuario = auth("residente@iris-demo.com", "Usuario2026")
    portero, _ = auth("portero@iris-demo.com", "Portero2026")
    unidad = client.get("/v2/my-units", headers=residente).json()[0]
    return admin, residente, portero, usuario, unidad


def _cuota(admin, unidad, monto, vencimiento, concepto="Cuota v3"):
    respuesta = client.post("/cuotas/", headers=admin, json={
        "inmueble_id": unidad["id"], "concepto": concepto, "periodo": f"v3-{uuid.uuid4().hex[:8]}",
        "monto": monto, "fecha_vencimiento": vencimiento.isoformat(),
    })
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_alta_conjunto_y_zona_solo_superadmin():
    admin, residente, _, _, _ = _contexto()
    nit = str(900000000 + (uuid.uuid4().int % 99999999))
    creado = client.post("/conjuntos/", headers=admin, json={
        "nombre": f"Conjunto de prueba {uuid.uuid4().hex[:6]}", "nit": nit, "direccion": "Bogotá, Colombia",
    })
    assert creado.status_code == 201, creado.text
    conjunto_id = creado.json()["id"]
    zona = client.post(f"/conjuntos/{conjunto_id}/zonas-comunes", headers=admin, json={
        "nombre": "Zona de prueba", "hora_apertura": "06:00", "hora_cierre": "22:00",
        "duracion_max_minutos": 240, "max_dias_anticipacion": 30, "max_reservas_dia_inmueble": 2,
    })
    assert zona.status_code == 201 and zona.json()["conjunto_id"] == conjunto_id
    no_autorizado = client.post("/conjuntos/", headers=residente, json={
        "nombre": "No autorizado", "nit": str(uuid.uuid4().int % 999999999), "direccion": "Bogotá",
    })
    assert no_autorizado.status_code == 403


# ---------------------------------------------------------------------------
# Seguridad: sesiones, intentos y protección de datos
# ---------------------------------------------------------------------------
def test_v3_seguridad_sesiones_intentos_politicas_y_privacidad():
    admin, residente, _, usuario, unidad = _contexto()

    estado = client.get("/v3/seguridad/estado", headers=residente)
    assert estado.status_code == 200, estado.text
    cuerpo = estado.json()
    assert cuerpo["habilitado"] is False and cuerpo["limite_intentos"] == 5 and cuerpo["sesiones_activas"] >= 1

    # Cada inicio de sesión queda registrado y se puede revocar individualmente
    primero, _ = auth("residente@iris-demo.com", "Usuario2026")
    segundo, _ = auth("residente@iris-demo.com", "Usuario2026")
    sesiones = client.get("/v3/seguridad/sesiones", headers=primero).json()
    assert sesiones and all("jti" in s and "ip" in s for s in sesiones)
    jti = jose_jwt.decode(primero["Authorization"].split(" ", 1)[1], SECRET_KEY, algorithms=[ALGORITHM])["jti"]
    objetivo = next(s for s in sesiones if s["jti"] == jti)
    assert client.delete(f"/v3/seguridad/sesiones/{objetivo['id']}", headers=primero).status_code == 204
    assert client.get("/v3/seguridad/sesiones", headers=primero).status_code == 401
    assert client.get("/v3/seguridad/sesiones", headers=segundo).status_code == 200

    # Límite de intentos: al sexto intento fallido la cuenta se bloquea temporalmente
    intruso = f"intruso-{int(time.time())}@example.com"
    for _ in range(5):
        assert client.post("/auth/login", json={"email": intruso, "password": "NoEsLaClave"}).status_code == 401
    bloqueado = client.post("/auth/login", json={"email": intruso, "password": "NoEsLaClave"})
    assert bloqueado.status_code == 429 and "Demasiados intentos" in bloqueado.json()["detail"]
    assert client.get("/v3/seguridad/intentos", headers=admin).status_code == 200
    assert client.get("/v3/seguridad/intentos", headers=residente).status_code == 403

    politica = client.get(f"/v3/seguridad/politica?conjunto_id={unidad['conjunto_id']}", headers=admin)
    assert politica.status_code == 200 and politica.json()["texto_privacidad"]
    assert client.put("/v3/seguridad/politica", headers=residente, json={
        "conjunto_id": unidad["conjunto_id"], "dias_retencion_accesos": 365,
    }).status_code == 403
    guardada = client.put("/v3/seguridad/politica", headers=admin, json={
        "conjunto_id": unidad["conjunto_id"], "texto_privacidad": "Política de tratamiento de datos de prueba.",
        "dias_retencion_accesos": 365, "dias_retencion_auditoria": 730, "anonimizar_al_purgar": True,
    })
    assert guardada.status_code == 200 and guardada.json()["dias_retencion_accesos"] == 365

    simulacion = client.post("/v3/seguridad/politica/purgar", headers=admin, json={
        "conjunto_id": unidad["conjunto_id"], "simulacion": True,
    })
    assert simulacion.status_code == 200 and simulacion.json()["simulacion"] is True

    privacidad = client.get("/v3/seguridad/privacidad", headers=residente)
    assert privacidad.status_code == 200 and privacidad.json()["retencion"]["accesos_dias"] == 365
    assert privacidad.json()["mis_consentimientos"]
    solicitud = client.post("/v3/seguridad/privacidad/solicitud", headers=residente,
                            json={"tipo": "acceso", "detalle": "Solicito copia de mis datos tratados por IRIS."})
    assert solicitud.status_code == 201 and solicitud.json()["pqrs_id"]


# ---------------------------------------------------------------------------
# Pagos en línea y conciliación automática
# ---------------------------------------------------------------------------
def test_v3_pagos_checkout_webhook_y_conciliacion():
    admin, residente, _, usuario, unidad = _contexto()
    cuota = _cuota(admin, unidad, 250000, date.today() + timedelta(days=10))

    assert client.get("/v3/pagos/proveedores", headers=admin).status_code == 200
    metodos = client.get(f"/v3/pagos/metodos?conjunto_id={unidad['conjunto_id']}", headers=residente)
    assert metodos.status_code == 200 and "tarjeta" in metodos.json()["metodos"]

    # IRIS nunca recibe datos de tarjeta
    rechazo = client.post("/v3/pagos/checkout", headers=residente,
                          json={"cuota_id": cuota["id"], "metodo": "tarjeta", "numero_tarjeta": "4111111111111111"})
    assert rechazo.status_code == 422 and "tarjeta" in rechazo.text.lower()

    checkout = client.post("/v3/pagos/checkout", headers=residente, json={"cuota_id": cuota["id"], "metodo": "tarjeta"})
    assert checkout.status_code == 201, checkout.text
    datos = checkout.json()
    assert datos["tokens_demo"]["aprobado"] and datos["monto"].replace(",", "") == "250000.00"

    cobro = client.post("/v3/pagos/cobrar", headers=residente,
                        json={"transaccion_id": datos["transaccion_id"], "token": datos["tokens_demo"]["aprobado"]})
    assert cobro.status_code == 200, cobro.text
    assert cobro.json()["estado"] == "aprobada" and cobro.json()["conciliacion"]["conciliada"] is True

    pendientes = [c for c in client.get("/cuotas/", headers=residente).json() if c["id"] == cuota["id"]]
    assert pendientes[0]["estado"] == "pagada"
    assert client.get(f"/v3/pagos/transacciones/{datos['transaccion_id']}/comprobante", headers=residente).status_code == 200
    assert client.get(f"/v3/pagos/transacciones/{datos['transaccion_id']}/comprobante").status_code in (401, 403)

    # Webhook firmado: concilia sin intervención humana
    cuota_dos = _cuota(admin, unidad, 99000, date.today() + timedelta(days=10), concepto="Cuota webhook")
    checkout_dos = client.post("/v3/pagos/checkout", headers=residente, json={"cuota_id": cuota_dos["id"], "metodo": "pse"})
    assert checkout_dos.status_code == 201, checkout_dos.text
    referencia = checkout_dos.json()["referencia"]
    firma = gw.firma_evento("simulado", {"reference": referencia, "status": "APPROVED"}, ["reference", "status"])
    webhook = client.post("/v3/pagos/webhook/simulado", json={"reference": referencia, "status": "APPROVED", "checksum": firma})
    assert webhook.status_code == 200 and webhook.json()["conciliada"] is True, webhook.text
    assert client.post("/v3/pagos/webhook/simulado", json={"reference": referencia, "status": "APPROVED", "checksum": "falsa"}).status_code == 401
    assert client.get(f"/v3/pagos/eventos?conjunto_id={unidad['conjunto_id']}", headers=admin).status_code == 200

    # Conciliación en lote
    lote = client.post("/v3/pagos/conciliacion/ejecutar", headers=admin, json={"conjunto_id": unidad["conjunto_id"]})
    assert lote.status_code == 200, lote.text
    resumen = client.get(f"/v3/pagos/resumen?conjunto_id={unidad['conjunto_id']}", headers=admin).json()
    assert resumen["aprobadas"] >= 2 and resumen["sin_conciliar"] == 0

    config = client.put("/v3/pagos/config", headers=admin, json={
        "conjunto_id": unidad["conjunto_id"], "proveedor": "wompi", "modo": "sandbox", "moneda": "COP",
        "public_key": "pub_test_iris", "private_key": "prv_test_iris_secreto", "events_secret": "evt_test_iris",
        "permite_tarjeta": True, "permite_pse": True, "permite_nequi": True, "activo": True,
    })
    assert config.status_code == 200, config.text
    assert "prv_test_iris_secreto" not in config.text
    assert config.json()["private_key"] not in (None, "", "prv_test_iris_secreto")
    assert config.json()["events_secret"] not in (None, "", "evt_test_iris")
    assert client.get(f"/v3/pagos/config?conjunto_id={unidad['conjunto_id']}", headers=residente).status_code == 403


# ---------------------------------------------------------------------------
# Avisos por WhatsApp / SMS con consentimiento
# ---------------------------------------------------------------------------
def test_v3_avisos_consentimiento_bitacora_y_vencimientos():
    admin, residente, _, usuario, unidad = _contexto()

    consentimientos = client.get("/v3/avisos/consentimientos", headers=residente)
    assert consentimientos.status_code == 200 and consentimientos.json()
    assert consentimientos.json()[0]["telefono_enmascarado"].count("*") > 0

    otorgado = client.post("/v3/avisos/consentimientos", headers=residente,
                           json={"canal": "sms", "telefono": "+573001112233", "otorgado": True})
    assert otorgado.status_code == 200 and otorgado.json()["otorgado"] is True
    assert client.post("/v3/avisos/consentimientos", headers=residente,
                       json={"canal": "sms", "telefono": "3001112233"}).status_code == 422

    assert client.post("/v3/avisos/plantillas/instalar-sugeridas", headers=admin,
                       json={"conjunto_id": unidad["conjunto_id"]}).status_code == 200
    assert client.get(f"/v3/avisos/plantillas?conjunto_id={unidad['conjunto_id']}", headers=admin).status_code == 200

    enviado = client.post("/v3/avisos/enviar", headers=admin, json={
        "conjunto_id": unidad["conjunto_id"], "inmueble_id": unidad["id"], "evento": "paquete_recibido",
        "mensaje": "Tienes un paquete en portería.", "contexto": {"descripcion": "Caja mediana"},
    })
    assert enviado.status_code == 201, enviado.text
    assert enviado.json()["resultados"]
    assert set(enviado.json()["resultados"][0]["canales"]) & {"whatsapp", "sms"}
    assert enviado.json()["resultados"][0]["estado"] in ("enviado", "simulado")

    bitacora = client.get(f"/v3/avisos/bitacora?conjunto_id={unidad['conjunto_id']}", headers=admin)
    assert bitacora.status_code == 200 and bitacora.json()
    assert client.get("/v3/avisos/mis-avisos", headers=residente).status_code == 200

    _cuota(admin, unidad, 180000, date.today() + timedelta(days=2), concepto="Administración")
    vencimientos = client.post("/v3/avisos/vencimientos/ejecutar", headers=admin,
                               json={"conjunto_id": unidad["conjunto_id"], "dias_anticipacion": 5})
    assert vencimientos.status_code == 200 and vencimientos.json()["avisos_enviados"] >= 1
    assert client.get(f"/v3/avisos/estado-consentimientos?conjunto_id={unidad['conjunto_id']}", headers=admin).status_code == 200

    # Al revocar el consentimiento, los avisos externos se omiten (nunca se envían sin permiso)
    sms = [c for c in client.get("/v3/avisos/consentimientos", headers=residente).json() if c["canal"] == "sms"][0]
    assert client.delete(f"/v3/avisos/consentimientos/{sms['id']}", headers=residente).status_code == 204
    omitido = client.post("/v3/avisos/enviar", headers=admin, json={
        "conjunto_id": unidad["conjunto_id"], "inmueble_id": unidad["id"], "evento": "paquete_recibido",
        "canal": "sms", "mensaje": "Aviso sin consentimiento",
    })
    assert omitido.status_code == 201 and omitido.json()["resultados"][0]["estado"] == "omitido_sin_consentimiento"


# ---------------------------------------------------------------------------
# Mantenimiento: responsables, proveedores, cotizaciones, fotos y vencimientos
# ---------------------------------------------------------------------------
def test_v3_mantenimiento_proveedores_cotizaciones_evidencias_y_vencimientos():
    admin, residente, portero, usuario, unidad = _contexto()
    conjunto_id = unidad["conjunto_id"]
    # La orden se abre en un inmueble ajeno al residente para comprobar el control de acceso.
    ajeno = next(u["id"] for u in client.get(f"/conjuntos/{conjunto_id}/inmuebles/", headers=admin).json()
                 if u["id"] != unidad["id"])

    proveedor = client.post("/v3/mantenimiento/proveedores", headers=admin, json={
        "conjunto_id": conjunto_id, "nombre": f"Plomería Andina {uuid.uuid4().hex[:4]}", "nit": "900555111-2",
        "especialidad": "Hidráulico", "telefono": "+573005554433", "calificacion": 5,
    })
    assert proveedor.status_code == 201, proveedor.text
    assert client.post("/v3/mantenimiento/proveedores", headers=residente,
                       json={"conjunto_id": conjunto_id, "nombre": "No autorizado"}).status_code == 403

    orden = client.post("/v3/mantenimiento/ordenes", headers=admin, json={
        "conjunto_id": conjunto_id, "titulo": f"Filtración en parqueadero {uuid.uuid4().hex[:4]}",
        "descripcion": "Se detectó humedad en el muro norte.", "prioridad": "urgente",
        "inmueble_id": ajeno, "proveedor_id": proveedor.json()["id"],
        "fecha_limite": (datetime.now() - timedelta(days=2)).isoformat(), "costo_estimado": 400000,
    })
    assert orden.status_code == 201, orden.text
    orden_id = orden.json()["id"]
    assert orden.json()["vencida"] is True and orden.json()["avances"]

    cotizacion_a = client.post(f"/v3/mantenimiento/ordenes/{orden_id}/cotizaciones", headers=admin, json={
        "proveedor_id": proveedor.json()["id"], "monto": 520000, "descripcion": "Incluye materiales",
    })
    cotizacion_b = client.post(f"/v3/mantenimiento/ordenes/{orden_id}/cotizaciones", headers=admin, json={
        "proveedor_nombre": "Obras del Norte", "monto": 480000, "descripcion": "Solo mano de obra",
    })
    assert cotizacion_a.status_code == 201 and cotizacion_b.status_code == 201
    pendiente = client.patch(f"/v3/mantenimiento/cotizaciones/{cotizacion_b.json()['id']}", headers=admin,
                             json={"accion": "seleccionar"})
    assert pendiente.status_code == 409
    rechazada_por_no_admin = client.patch(f"/v3/mantenimiento/cotizaciones/{cotizacion_b.json()['id']}/aprobacion",
                                          headers=residente, json={"decision": "aprobada"})
    assert rechazada_por_no_admin.status_code == 403
    aprobacion = client.patch(f"/v3/mantenimiento/cotizaciones/{cotizacion_b.json()['id']}/aprobacion", headers=admin,
                              json={"decision": "aprobada", "nota": "Dentro del presupuesto aprobado"})
    assert aprobacion.status_code == 200 and aprobacion.json()["aprobacion_estado"] == "aprobada"
    assert aprobacion.json()["aprobada_por"]
    elegida = client.patch(f"/v3/mantenimiento/cotizaciones/{cotizacion_b.json()['id']}", headers=admin,
                           json={"accion": "seleccionar"})
    assert elegida.status_code == 200 and elegida.json()["estado"] == "seleccionada"
    detalle = client.get(f"/v3/mantenimiento/ordenes/{orden_id}", headers=admin).json()
    assert detalle["estado"] == "en_ejecucion" and detalle["costo_estimado"] == "480000.00"
    assert len(detalle["cotizaciones"]) == 2

    evidencia = client.post(f"/v3/mantenimiento/ordenes/{orden_id}/evidencias", headers=admin,
                            files={"file": ("foto.png", EJEMPLO_PNG, "image/png")})
    assert evidencia.status_code == 201, evidencia.text
    url = evidencia.json()["url"]
    assert url.startswith("/v3/files/")
    assert client.get(url, headers=admin).status_code == 200
    assert client.get(url).status_code in (401, 403)
    assert client.get(url, headers=residente).status_code == 404
    assert client.post(f"/v3/mantenimiento/ordenes/{orden_id}/evidencias", headers=admin,
                       files={"file": ("notas.txt", b"texto", "text/plain")}).status_code == 415
    assert client.post(f"/v3/mantenimiento/ordenes/{orden_id}/soportes", headers=admin,
                       files={"file": ("factura.pdf", b"%PDF-1.4 IRIS", "application/pdf")}).status_code == 201

    avance = client.post(f"/v3/mantenimiento/ordenes/{orden_id}/avances", headers=admin,
                         json={"nota": "Se reparó la filtración y se selló el muro.", "estado": "completada"})
    assert avance.status_code == 201
    final = client.patch(f"/v3/mantenimiento/ordenes/{orden_id}", headers=admin,
                         json={"estado": "completada", "costo_final": 480000, "nota": "Cierre con factura del proveedor"})
    assert final.status_code == 200 and final.json()["estado"] == "completada" and final.json()["cerrada_en"]

    vegadas = client.get("/v3/mantenimiento/vencidas", headers=admin)
    assert vegadas.status_code == 200 and all(o["id"] != orden_id for o in vegadas.json())
    resumen = client.get(f"/v3/mantenimiento/resumen?conjunto_id={conjunto_id}", headers=admin).json()
    assert resumen["total"] >= 1 and resumen["completadas"] >= 1
    exportado = client.get(f"/v3/mantenimiento/export.xlsx?conjunto_id={conjunto_id}", headers=admin)
    assert exportado.status_code == 200 and exportado.content.startswith(b"PK")
    assert client.get(f"/v3/mantenimiento/ordenes?conjunto_id={conjunto_id}", headers=portero).status_code == 200
    assert client.get("/v3/mantenimiento/ordenes", headers=residente).status_code == 200


# ---------------------------------------------------------------------------
# Visitantes: autorización, ingreso, placa, salida y alertas
# ---------------------------------------------------------------------------
def test_v3_visitantes_autorizacion_ingreso_salida_y_alertas():
    admin, residente, portero, usuario, unidad = _contexto()
    conjunto_id = unidad["conjunto_id"]

    autorizacion = client.post("/v3/visitantes/autorizaciones", headers=residente, json={
        "inmueble_id": unidad["id"], "nombre": f"Carlos Visitante {uuid.uuid4().hex[:4]}",
        "documento": "1099887766", "placa": "XYZ789", "tipo": "visitante",
        "usos_maximos": 3, "valido_hasta": (datetime.now() + timedelta(days=2)).isoformat(),
    })
    assert autorizacion.status_code == 201, autorizacion.text
    assert autorizacion.json()["permite_vehiculo"] is True
    autorizacion_id = autorizacion.json()["id"]
    listado = client.get("/v3/visitantes/autorizaciones", headers=residente).json()
    assert any(a["id"] == autorizacion_id and a["vigente"] is True for a in listado)

    assert client.post("/v3/visitantes/accesos", headers=residente,
                       json={"inmueble_id": unidad["id"], "nombre": "Intruso"}).status_code == 403

    ingreso = client.post("/v3/visitantes/accesos", headers=portero, json={
        "inmueble_id": unidad["id"], "autorizacion_id": autorizacion_id, "placa": "XYZ789",
    })
    assert ingreso.status_code == 201, ingreso.text
    assert ingreso.json()["autorizado"] is True and ingreso.json()["placa"] == "XYZ789"
    acceso_id = ingreso.json()["id"]

    en_sitio = client.get(f"/v3/visitantes/en-sitio?conjunto_id={conjunto_id}", headers=portero)
    assert en_sitio.status_code == 200 and any(v["id"] == acceso_id for v in en_sitio.json())
    salida = client.patch(f"/v3/visitantes/accesos/{acceso_id}/salida", headers=portero, json={"observacion": "Salió a las 18:00"})
    assert salida.status_code == 200 and salida.json()["salida_en"]
    assert client.patch(f"/v3/visitantes/accesos/{acceso_id}/salida", headers=portero).status_code == 409

    manual = client.post("/v3/visitantes/accesos", headers=portero, json={
        "inmueble_id": unidad["id"], "nombre": "Domiciliario sin autorización",
    })
    assert manual.status_code == 201 and manual.json()["autorizado"] is False

    assert client.get(f"/v3/visitantes/accesos?inmueble_id={unidad['id']}", headers=residente).status_code == 200
    assert client.get("/v3/visitantes/directorio", headers=residente).status_code == 200
    resumen = client.get(f"/v3/visitantes/resumen?conjunto_id={conjunto_id}", headers=admin).json()
    assert resumen["accesos_hoy"] >= 2 and resumen["sin_autorizacion_hoy"] >= 1
    assert client.get(f"/v3/visitantes/export.xlsx?conjunto_id={conjunto_id}", headers=admin).content.startswith(b"PK")
    assert client.delete(f"/v3/visitantes/autorizaciones/{autorizacion_id}", headers=residente).status_code == 204


# ---------------------------------------------------------------------------
# Contabilidad y cartera
# ---------------------------------------------------------------------------
def test_v3_contabilidad_egresos_cartera_conciliacion_e_informes():
    admin, residente, _, usuario, unidad = _contexto()
    conjunto_id = unidad["conjunto_id"]

    egreso = client.post("/v3/contabilidad/egresos", headers=admin, json={
        "conjunto_id": conjunto_id, "concepto": f"Aseo zonas comunes {uuid.uuid4().hex[:4]}",
        "categoria": "aseo", "monto": 1200000, "fecha": date.today().isoformat(),
    })
    assert egreso.status_code == 201, egreso.text
    assert client.get(f"/v3/contabilidad/egresos?conjunto_id={conjunto_id}", headers=admin).json()
    assert client.post("/v3/contabilidad/egresos", headers=residente,
                       json={"conjunto_id": conjunto_id, "concepto": "No autorizado", "monto": 1}).status_code == 403

    presupuesto = client.post("/v3/contabilidad/presupuestos", headers=admin, json={
        "conjunto_id": conjunto_id, "periodo": date.today().strftime("%Y-%m"), "categoria": "aseo",
        "monto_presupuestado": 1500000,
    })
    assert presupuesto.status_code == 201 and client.get(
        f"/v3/contabilidad/presupuestos?conjunto_id={conjunto_id}", headers=admin).json()

    config = client.put("/v3/contabilidad/config-cartera", headers=admin, json={
        "conjunto_id": conjunto_id, "interes_moratorio_diario": "0.002", "recargo_fijo": 5000,
        "dias_gracia": 0, "activo": True,
    })
    assert config.status_code == 200 and config.json()["activo"] is True
    assert client.put("/v3/contabilidad/config-cartera", headers=admin, json={
        "conjunto_id": conjunto_id, "interes_moratorio_diario": "3"}).status_code == 422

    vencida = _cuota(admin, unidad, 300000, date.today() - timedelta(days=20), concepto="Administración vencida")
    primera = client.post("/v3/contabilidad/cartera/calcular-mora", headers=admin, json={"conjunto_id": conjunto_id})
    assert primera.status_code == 200 and primera.json()["cargos_aplicados"] >= 1, primera.text
    segunda = client.post("/v3/contabilidad/cartera/calcular-mora", headers=admin, json={"conjunto_id": conjunto_id})
    assert segunda.json()["cargos_aplicados"] == 0

    cartera = client.get(f"/v3/contabilidad/cartera?conjunto_id={conjunto_id}", headers=admin)
    assert cartera.status_code == 200 and float(cartera.json()["total_vencido"]) > 0 and cartera.json()["por_inmueble"]
    assert client.get(f"/v3/contabilidad/cartera?conjunto_id={conjunto_id}", headers=residente).status_code == 403

    # Extracto bancario: una cuota pendiente del valor exacto se concilia sola
    a_conciliar = _cuota(admin, unidad, 777000, date.today(), concepto="Cuota conciliable")
    extracto = "\n".join([
        "fecha,descripcion,referencia,debito,credito",
        f"{date.today().isoformat()},Transferencia recibida,REF-CONC-1,0,777000",
        f"{date.today().isoformat()},Comisión bancaria,REF-COM-1,15000,0",
    ]).encode("utf-8")
    importado = client.post(f"/v3/contabilidad/extracto/importar?conjunto_id={conjunto_id}", headers=admin,
                            files={"file": ("extracto.csv", extracto, "text/csv")})
    assert importado.status_code == 201 and importado.json()["movimientos_creados"] == 2, importado.text
    conciliacion = client.post("/v3/contabilidad/conciliar-bancaria", headers=admin,
                               json={"conjunto_id": conjunto_id, "dias_tolerancia": 0})
    assert conciliacion.status_code == 200 and conciliacion.json()["conciliados"], conciliacion.text
    assert client.get(f"/v3/contabilidad/movimientos?conjunto_id={conjunto_id}", headers=admin).status_code == 200
    cuota_conciliada = [c for c in client.get("/cuotas/", headers=admin).json() if c["id"] == a_conciliar["id"]][0]
    assert cuota_conciliada["estado"] == "pagada"

    informe = client.get(f"/v3/contabilidad/informes/periodo?conjunto_id={conjunto_id}"
                         f"&desde={(date.today() - timedelta(days=90)).isoformat()}&hasta={date.today().isoformat()}", headers=admin)
    assert informe.status_code == 200 and float(informe.json()["egresos"]) > 0 and "resultado" in informe.json()
    assert client.get(f"/v3/contabilidad/export/cartera.xlsx?conjunto_id={conjunto_id}", headers=admin).content.startswith(b"PK")
    assert client.get(f"/v3/contabilidad/export/egresos.xlsx?conjunto_id={conjunto_id}", headers=admin).content.startswith(b"PK")
    assert client.get(f"/v3/contabilidad/export/conciliaciones.csv?conjunto_id={conjunto_id}", headers=admin).content


# ---------------------------------------------------------------------------
# Asambleas y votación digital
# ---------------------------------------------------------------------------
def test_v3_asambleas_quorum_votacion_y_acta():
    admin, residente, portero, usuario, unidad = _contexto()
    conjunto_id = unidad["conjunto_id"]
    titulo = f"Asamblea extraordinaria {uuid.uuid4().hex[:4]}"

    creada = client.post("/v3/asambleas", headers=admin, json={
        "conjunto_id": conjunto_id, "titulo": titulo, "tipo": "extraordinaria", "modalidad": "virtual",
        "enlace": "https://meet.example/iris-extra", "quorum_requerido": 1,
        "fecha_inicio": (datetime.now() - timedelta(days=1)).isoformat(),
        "fecha_fin": (datetime.now() + timedelta(days=3)).isoformat(),
    })
    assert creada.status_code == 201, creada.text
    asamblea_id = creada.json()["id"]
    assert client.patch(f"/v3/asambleas/{asamblea_id}", headers=admin, json={"estado": "en_curso"}).status_code == 200

    asistencia = client.post(f"/v3/asambleas/{asamblea_id}/asistencia", headers=residente, json={})
    assert asistencia.status_code == 201 and asistencia.json()["quorum"]["unidades_representadas"] >= 1
    quorum = client.get(f"/v3/asambleas/{asamblea_id}/quorum", headers=residente).json()
    assert quorum["unidades_totales"] >= 1 and quorum["alcanzado"] is True

    votacion = client.post(f"/v3/asambleas/{asamblea_id}/votaciones", headers=admin, json={
        "titulo": "¿Apruebas el nuevo reglamento de zonas comunes?", "tipo": "si_no", "mayoria": "simple",
    })
    assert votacion.status_code == 201, votacion.text
    votacion_id = votacion.json()["votacion_id"]
    assert client.patch(f"/v3/asambleas/votaciones/{votacion_id}", headers=admin, json={"estado": "abierta"}).status_code == 200
    assert client.post(f"/v3/asambleas/votaciones/{votacion_id}/votar", headers=admin, json={"opcion": "si"}).status_code == 403
    assert client.post(f"/v3/asambleas/votaciones/{votacion_id}/votar", headers=portero, json={"opcion": "si"}).status_code == 403

    voto = client.post(f"/v3/asambleas/votaciones/{votacion_id}/votar", headers=residente, json={"opcion": "si"})
    assert voto.status_code == 200 and voto.json()["registrado"] is True and voto.json()["hash_validacion"]
    assert client.post(f"/v3/asambleas/votaciones/{votacion_id}/votar", headers=residente, json={"opcion": "no"}).status_code == 409
    assert client.post(f"/v3/asambleas/votaciones/{votacion_id}/votar", headers=residente, json={"opcion": "quizá"}).status_code == 422

    resultados = client.get(f"/v3/asambleas/votaciones/{votacion_id}/resultados", headers=residente).json()
    assert resultados["ganador"] == "si" and resultados["aprobada"] is True
    assert client.patch(f"/v3/asambleas/votaciones/{votacion_id}", headers=admin, json={"estado": "cerrada"}).status_code == 200

    convocatoria = client.post(f"/v3/asambleas/{asamblea_id}/convocar", headers=admin, json={})
    assert convocatoria.status_code == 200 and convocatoria.json()["convocados"] >= 1
    acta = client.post(f"/v3/asambleas/{asamblea_id}/acta/generar", headers=admin)
    assert acta.status_code == 200 and "ACTA DE ASAMBLEA" in acta.json()["acta"] and "APROBADA" in acta.json()["acta"]
    assert client.get(f"/v3/asambleas/{asamblea_id}/acta", headers=residente).status_code == 200
    assert any(a["id"] == asamblea_id for a in client.get("/v3/asambleas", headers=admin).json())
    assert any(a["id"] == asamblea_id for a in client.get("/v3/asambleas", headers=residente).json())


# ---------------------------------------------------------------------------
# Reservas con reglas avanzadas
# ---------------------------------------------------------------------------
def test_v3_reservas_cupos_lista_espera_cierres_y_penalizaciones():
    admin, residente, portero, usuario, unidad = _contexto()
    conjunto_id = unidad["conjunto_id"]
    reglas = client.get(f"/v3/reservas/reglas?conjunto_id={conjunto_id}", headers=admin).json()
    assert reglas
    zona = reglas[0]
    zona_id = zona["zona_id"]
    inmuebles = client.get(f"/conjuntos/{conjunto_id}/inmuebles/", headers=admin).json()

    ajustada = client.put(f"/v3/reservas/reglas/{zona_id}", headers=admin, json={
        "cupos_por_franja": 1, "duracion_franja_minutos": 60, "antelacion_minima_horas": 0,
        "horas_limite_cancelacion": 0, "requiere_pago": True, "tarifa_por_uso": 45000,
        "lista_espera_activa": True, "cupos_lista_espera": 5, "penalizacion_inasistencia": 30000,
        "max_reservas_activas_inmueble": 4,
    })
    assert ajustada.status_code == 200 and ajustada.json()["cupos_por_franja"] == 1
    assert client.put(f"/v3/reservas/reglas/{zona_id}", headers=admin, json={"cupos_por_franja": 0}).status_code == 422

    manana = (date.today() + timedelta(days=1)).isoformat()
    disponible = client.get(f"/v3/reservas/disponibilidad?zona_id={zona_id}&fecha={manana}", headers=residente)
    assert disponible.status_code == 200
    franjas = [f for f in disponible.json()["franjas"] if f["disponible"]]
    assert franjas, disponible.text
    franja = franjas[0]

    reserva = client.post("/v3/reservas/solicitar", headers=residente, json={
        "zona_id": zona_id, "inmueble_id": unidad["id"], "fecha_inicio": franja["inicio"], "fecha_fin": franja["fin"],
    })
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["requiere_pago"] is True and reserva.json()["cargo"]
    reserva_id = reserva.json()["id"]

    ocupada = client.post("/v3/reservas/solicitar", headers=residente, json={
        "zona_id": zona_id, "inmueble_id": unidad["id"], "fecha_inicio": franja["inicio"], "fecha_fin": franja["fin"],
    })
    assert ocupada.status_code == 409

    otro_inmueble = inmuebles[-1]["id"]
    assert client.post("/v3/reservas/solicitar", headers=admin, json={
        "zona_id": zona_id, "inmueble_id": otro_inmueble, "fecha_inicio": franja["inicio"], "fecha_fin": franja["fin"],
    }).status_code == 409  # sin cupos: la franja admite una sola reserva

    espera = client.post("/v3/reservas/lista-espera", headers=admin, json={
        "zona_id": zona_id, "inmueble_id": otro_inmueble, "fecha_inicio": franja["inicio"], "fecha_fin": franja["fin"],
    })
    assert espera.status_code == 201 and espera.json()["posicion"] >= 1

    cancelada = client.post(f"/v3/reservas/{reserva_id}/cancelar", headers=residente)
    assert cancelada.status_code == 200, cancelada.text
    assert cancelada.json()["lista_espera_promovida"], "el cupo liberado debe promover la lista de espera"
    promovida = cancelada.json()["lista_espera_promovida"]["reserva_id"]
    assert client.get(f"/v3/reservas/lista-espera?zona_id={zona_id}", headers=admin).json()

    asistencia = client.post(f"/v3/reservas/{promovida}/asistencia", headers=admin, json={"asistio": False})
    assert asistencia.status_code == 200 and asistencia.json()["penalizacion"], asistencia.text

    nuevo = client.post("/v3/reservas/solicitar", headers=admin, json={
        "zona_id": zona_id, "inmueble_id": otro_inmueble, "fecha_inicio": franjas[-1]["inicio"], "fecha_fin": franjas[-1]["fin"],
    })
    assert nuevo.status_code == 201, nuevo.text

    cierre = client.post("/v3/reservas/cierres", headers=admin, json={
        "zona_id": zona_id, "motivo": "Mantenimiento del piso",
        "fecha_inicio": franjas[-1]["inicio"], "fecha_fin": franjas[-1]["fin"],
    })
    assert cierre.status_code == 201 and cierre.json()["reservas_afectadas_canceladas"] >= 1
    assert client.get(f"/v3/reservas/cierres?conjunto_id={conjunto_id}", headers=admin).status_code == 200

    cerrada = client.get(f"/v3/reservas/disponibilidad?zona_id={zona_id}&fecha={manana}", headers=residente).json()
    assert any(f["cerrado"] for f in cerrada["franjas"])
    assert client.get("/v3/reservas/cargos", headers=admin).status_code == 200
    assert client.get(f"/v3/reservas/resumen?conjunto_id={conjunto_id}", headers=admin).json()["zonas"] >= 1
    assert client.put(f"/v3/reservas/reglas/{zona_id}", headers=residente, json={"cupos_por_franja": 5}).status_code == 403


# ---------------------------------------------------------------------------
# Panel de indicadores
# ---------------------------------------------------------------------------
def test_v3_indicadores_panel_y_exportacion():
    admin, residente, _, usuario, unidad = _contexto()
    conjunto_id = unidad["conjunto_id"]

    panel = client.get(f"/v3/indicadores/panel?conjunto_id={conjunto_id}", headers=admin)
    assert panel.status_code == 200, panel.text
    datos = panel.json()
    for clave in ("cartera", "pqrs", "uso_zonas", "reservas", "paquetes", "visitantes", "mantenimiento", "avisos"):
        assert clave in datos, clave
    assert "total_vencido" in datos["cartera"] and "indice_vencido_pct" in datos["cartera"]
    assert datos["pqrs"]["objetivos_sla_horas"]["peticion"] == 72
    assert datos["paquetes"]["por_mes"] is not None
    assert client.get(f"/v3/indicadores/panel?conjunto_id={conjunto_id}", headers=residente).status_code == 403
    assert client.get(f"/v3/indicadores/export.xlsx?conjunto_id={conjunto_id}", headers=admin).content.startswith(b"PK")
    assert client.get(f"/v3/indicadores/cartera-detalle?conjunto_id={conjunto_id}", headers=admin).status_code == 200


# ---------------------------------------------------------------------------
# Operación: respaldos, prueba de restauración y salud
# ---------------------------------------------------------------------------
def test_v3_operacion_respaldos_prueba_restauracion_y_salud():
    admin, residente, _, usuario, unidad = _contexto()

    salud = client.get("/v3/admin/salud")
    assert salud.status_code == 200 and salud.json()["ok"] is True

    estado = client.get("/v3/admin/estado-sistema", headers=admin)
    assert estado.status_code == 200, estado.text
    assert estado.json()["migraciones_faltantes"] == [] and estado.json()["tablas_v3"] >= 30
    assert client.get("/v3/admin/estado-sistema", headers=residente).status_code == 403

    checklist = client.get("/v3/admin/checklist-produccion", headers=admin)
    assert checklist.status_code == 200 and checklist.json()["total"] >= 8

    respaldo = client.post("/v3/admin/respaldos", headers=admin)
    assert respaldo.status_code == 201, respaldo.text
    assert respaldo.json()["checksum"] and respaldo.json()["tamano_bytes"] > 0
    verificado = client.post(f"/v3/admin/respaldos/{respaldo.json()['id']}/verificar", headers=admin)
    assert verificado.status_code == 200 and verificado.json()["estado_prueba"] == "ok", verificado.text
    assert verificado.json()["filas_verificadas"] > 0
    assert client.get("/v3/admin/respaldos", headers=admin).json()
    assert client.get(f"/v3/admin/respaldos/{respaldo.json()['id']}/descargar", headers=admin).status_code == 200
    descarga = client.get("/v3/admin/backup", headers=admin)
    assert descarga.status_code == 200 and descarga.content[:16].startswith(b"SQLite format 3")
    assert client.get("/v3/admin/backup", headers=residente).status_code == 403


# ---------------------------------------------------------------------------
# Segundo factor obligatorio para la administración (se ejecuta al final)
# ---------------------------------------------------------------------------
def test_v3_segundo_factor_admin_obliga_codigo_y_recuperacion():
    admin, residente, _, usuario, unidad = _contexto()
    conjunto_id = unidad["conjunto_id"]

    inicio = client.post("/v3/seguridad/2fa/iniciar", headers=admin)
    assert inicio.status_code == 201 and inicio.json()["secreto"]
    secreto = inicio.json()["secreto"]
    assert "otpauth" in inicio.json()["uri"]

    confirmado = client.post("/v3/seguridad/2fa/confirmar", headers=admin, json={"codigo": totp.codigo_en(secreto)})
    assert confirmado.status_code == 200, confirmado.text
    codigos = confirmado.json()["codigos_recuperacion"]
    assert len(codigos) == 8
    assert client.post("/v3/seguridad/2fa/confirmar", headers=admin,
                       json={"codigo": totp.codigo_en(secreto)}).status_code == 409

    assert client.get("/v3/seguridad/estado", headers=admin).json()["habilitado"] is True

    # Operación sensible sin código: rechazada
    sin_codigo = client.post("/v3/contabilidad/egresos", headers=admin, json={
        "conjunto_id": conjunto_id, "concepto": "Sin 2FA", "monto": 10000, "fecha": date.today().isoformat(),
    })
    assert sin_codigo.status_code == 403 and "2fa" in sin_codigo.text.lower()

    # Operación sensible con código: permitida
    con_codigo = client.post("/v3/contabilidad/egresos", headers={**admin, "X-IRIS-OTP": totp.codigo_en(secreto)}, json={
        "conjunto_id": conjunto_id, "concepto": "Con 2FA", "monto": 10000, "fecha": date.today().isoformat(),
    })
    assert con_codigo.status_code == 201, con_codigo.text

    # El inicio de sesión exige el segundo paso
    login = client.post("/auth/login", json={"email": "admin@iris-demo.com", "password": "Admin2026"})
    assert login.status_code == 200 and login.json()["requiere_2fa"] is True and "access_token" not in login.json()
    desafio = login.json()["desafio"]
    assert client.post("/v3/seguridad/2fa/login", json={"desafio": desafio, "codigo": "000000"}).status_code == 401
    segundo_paso = client.post("/v3/seguridad/2fa/login", json={"desafio": desafio, "codigo": totp.codigo_en(secreto)})
    assert segundo_paso.status_code == 200 and segundo_paso.json()["access_token"]
    nuevo = {"Authorization": "Bearer " + segundo_paso.json()["access_token"]}
    assert client.get("/v3/seguridad/estado", headers=nuevo).status_code == 200

    # Código de recuperación (un solo uso)
    desafio_dos = client.post("/auth/login", json={"email": "admin@iris-demo.com", "password": "Admin2026"}).json()["desafio"]
    assert client.post("/v3/seguridad/2fa/login", json={"desafio": desafio_dos, "codigo": codigos[0]}).status_code == 200
    desafio_tres = client.post("/auth/login", json={"email": "admin@iris-demo.com", "password": "Admin2026"}).json()["desafio"]
    assert client.post("/v3/seguridad/2fa/login", json={"desafio": desafio_tres, "codigo": codigos[0]}).status_code == 401

    # Desactivación protegida con el código vigente
    assert client.delete("/v3/seguridad/2fa", headers=admin).status_code == 403
    assert client.delete("/v3/seguridad/2fa", headers={**admin, "X-IRIS-OTP": totp.codigo_en(secreto)}).status_code == 204
    assert client.get("/v3/seguridad/estado", headers=admin).json()["habilitado"] is False
    assert client.post("/v3/contabilidad/egresos", headers=admin, json={
        "conjunto_id": conjunto_id, "concepto": "Sin 2FA tras desactivar", "monto": 10000, "fecha": date.today().isoformat(),
    }).status_code == 201
