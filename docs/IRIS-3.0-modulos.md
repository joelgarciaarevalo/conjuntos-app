# IRIS 3.0 · Módulos agregados

Este documento describe **todo lo que se agregó a la copia del proyecto** para cubrir los diez puntos solicitados. El ZIP y la carpeta originales **no se modificaron**: este trabajo vive en una copia ampliada (`conjuntos-app-iris-v3`).

Todo quedó **funcional**: la API está cubierta con pruebas automatizadas (14 pruebas, todas en verde) y la interfaz se verificó en el navegador con los roles de administración y residente (login con segundo factor, pago en línea conciliado, orden de mantenimiento con evidencia adjunta y reserva con reglas avanzadas).

---

## 1. Pagos en línea con pasarela compatible con Colombia y conciliación automática

**Reglas de diseño**
- IRIS **nunca recibe ni almacena datos de tarjeta**. El navegador tokeniza con la pasarela; IRIS solo guarda token, marca, últimos cuatro dígitos y el estado. `payload_sin_tarjetas()` depura cualquier dato sensible antes de persistir.
- Las llaves privadas y los secretos de webhook se guardan **cifrados** (Fernet derivado de `SECRET_KEY`) y se devuelven **enmascarados** (`prv_…ta`).

**Proveedores soportados:** `wompi` (Colombia, tokenización por `checkout.wompi.co/widget.js`), `epayco`, `payulatam` y `simulado` (pasarela local para pruebas y demostraciones).

**Endpoints** (`/v3/pagos`)

| Método | Ruta | Para qué sirve |
| --- | --- | --- |
| GET | `/proveedores` | Catálogo de pasarelas y capacidades |
| GET/PUT | `/config` | Leer/guardar configuración por conjunto (llaves cifradas) |
| GET | `/metodos` | Medios disponibles (tarjeta, PSE, Nequi) y datos de tokenización |
| POST | `/checkout` | Crea la intención de pago y devuelve los datos de tokenización |
| POST | `/cobrar` | Cobra con el token generado por la pasarela |
| POST | `/webhook/{proveedor}` | Recibe eventos con verificación de firma (checksum) |
| GET | `/transacciones` | Listado con estado y conciliación |
| POST | `/transacciones/{id}/conciliar` | Conciliación manual |
| POST | `/conciliacion/ejecutar` | Conciliación automática en lote |
| GET | `/transacciones/{id}/comprobante` | Comprobante HTML imprimible |
| GET | `/resumen`, `/eventos` | Indicadores y bitácora de webhooks |

**Conciliación automática:** al aprobarse una transacción (por cobro o por webhook) se crea/actualiza el pago de la cuota, se marca la cuota como pagada y se registra `v3_conciliaciones_pago` con el monto, la diferencia y la observación. Sin coincidencia exacta, la transacción queda **sin conciliar** y disponible para revisión manual.

---

## 2. Avisos por WhatsApp o SMS con consentimiento del residente

- Tablas `v3_consentimientos_aviso`, `v3_plantillas_aviso`, `v3_avisos_enviados`.
- **Sin consentimiento vigente no se envía nada**: el intento queda en bitácora como `omitido_sin_consentimiento`. Hay límite diario por usuario.
- El teléfono se guarda/expone **enmascarado** y debe venir en formato internacional (`+57…`).
- Eventos: aprobaciones y rechazos de reserva, respuesta de PQRS, paquete recibido, vencimiento de cuota, visita, asamblea, mantenimiento y pago confirmado.
- Proveedores intercambiables: `simulado`, Meta WhatsApp Cloud API y Twilio (SMS/WhatsApp) por variables de entorno.
- Endpoints: `/v3/avisos/{consentimientos, plantillas, plantillas/instalar-sugeridas, enviar, bitacora, mis-avisos, vencimientos/ejecutar, estado-consentimientos, eventos}`.
- `POST /v3/avisos/vencimientos/ejecutar` recorre cuotas próximas a vencer, PQRS sin responder y paquetes pendientes y dispara los avisos correspondientes.

---

## 3. Seguimiento de mantenimiento

- Tablas: `v3_proveedores`, `v3_ordenes_mantenimiento`, `v3_cotizaciones_mantenimiento`, `v3_evidencias_mantenimiento`, `v3_avances_mantenimiento`.
- Órdenes con **responsable**, **proveedor**, prioridad, estado, **fecha límite**, costo estimado y costo final; aviso al responsable al asignar.
- **Cotizaciones**: se registran varias y se selecciona una (al seleccionar se rechazan las demás y la orden pasa a ejecución con el monto elegido).
- **Evidencias**: carga de fotos (`/evidencias`) y soportes en PDF (`/soportes`) con validación de tipo y tamaño; se sirven por `/v3/files/{archivo}` **solo con permiso** sobre la orden.
- **Vencidas** (`/vencidas`) y **resumen** (`/resumen`); exportación XLSX (`/export.xlsx`).

---

## 4. Control de visitantes ampliado

- Tablas: `v3_visitantes`, `v3_autorizaciones_visita`, `v3_accesos_visitantes`.
- Autorización desde el panel del residente con **nombre, documento, placa, tipo, vigencia y número de usos**; tabla `v3_directorio_visitantes` para los invitados frecuentes.
- Portería autoriza o registra el ingreso indicando **la autorización o el nombre**; se valida la vigencia, los usos y la **placa del vehículo** (normalizada a mayúsculas y sin espacios).
- Registro de **salida** (`PATCH /accesos/{id}/salida`), vista **en sitio** con tiempo de permanencia, historial y `resumen` del día.
- Cada ingreso **alerta al residente** por notificación interna y, si hay consentimiento, por WhatsApp/SMS.

---

## 5. Seguridad y protección de datos

- **Segundo factor (TOTP, RFC 6238, implementación propia sin dependencias)**: `/v3/seguridad/2fa/{iniciar, confirmar, verificar, login}` y `DELETE /2fa`. Incluye **códigos de recuperación** de un solo uso.
- El login del backend ahora devuelve `requiere_2fa` con un desafío firmado; el frontend tiene una pantalla intermedia para el código (no emite token hasta validarlo).
- Las operaciones sensibles de administración exigen el encabezado `X-IRIS-OTP` cuando el segundo factor está activo (`exigir_2fa_admin`).
- **Límite de intentos de acceso** (5 intentos en 15 minutos → bloqueo temporal), tabla `v3_intentos_acceso`, y **registro de sesiones** (`v3_sesiones`) con IP, agente, origen y última actividad; el usuario puede cerrar una o todas (`/v3/seguridad/sesiones`).
- **Retención y privacidad**: `GET/PUT /v3/seguridad/politica` (días de retención por tipo de dato, texto de privacidad, anonimización) y `POST /v3/seguridad/politica/purgar` con **simulación previa** antes de aplicar.
- **Habeas data**: `GET /v3/seguridad/privacidad` publica la política, la retención y los derechos; `POST /v3/seguridad/privacidad/solicitud` radica solicitudes de acceso, rectificación, revocatoria, supresión o queja.

---

## 6. Contabilidad y cartera

- Tablas: `v3_egresos`, `v3_presupuestos`, `v3_config_cartera`, `v3_cargos_cartera`, `v3_movimientos_bancarios`, `v3_conciliaciones_pago`.
- **Egresos** (crear, listar, editar, eliminar) y **presupuestos por periodo/categoría**.
- **Intereses y recargos configurables** por conjunto (interés moratorio diario, tasa mensual, recargo fijo, días de gracia, activo) con `POST /cartera/calcular-mora`, que aplica cargos idempotentes por cuota vencida (`marca` única) y los deja en la cartera del inmueble.
- **Conciliación bancaria**: importación de extractos **CSV y XLSX** (`POST /extracto/importar`), emparejamiento automático por valor y fecha (± días de tolerancia) en `POST /conciliar-bancaria`, conciliación manual por movimiento y listado de movimientos.
- **Informes por periodo** (`GET /informes/periodo`) y exportaciones XLSX/CSV de cartera, egresos y conciliaciones.

---

## 7. Votaciones y asambleas

- Tablas: `v3_asambleas`, `v3_asistencias_asamblea`, `v3_votaciones`, `v3_votos`.
- Convocatoria con tipo, modalidad (presencial/virtual/mixta), lugar o enlace y ventana de fechas; **convocatoria a todos los residentes** con aviso (`POST /{id}/convocar`).
- **Quórum** calculado en tiempo real sobre las unidades del conjunto (`GET /{id}/quorum`), con registro de asistencia por unidad, representante y poder.
- **Votación digital**: creación con tipo (`si_no`, `opciones`, `eleccion`), mayoría (simple, absoluta, calificada) y abstención; apertura/cierre, votación por unidad con actualización de votos y **resultados** con conteo, ganador y aprobación.
- **Acta**: `POST /{id}/acta/generar` la construye con convocatoria, quórum, votaciones y resultados; `GET /{id}/acta` la publica en HTML imprimible.

---

## 8. Reservas con reglas avanzadas

- Tablas: `v3_reglas_zona_reserva`, `v3_listas_espera`, `v3_cierres_zona`, `v3_cargos_reserva`, `v3_asistencias_reserva`.
- Reglas por zona: **cupos por franja**, duración de franja, antelación mínima, horas límite de cancelación, máximo de reservas activas por inmueble, cupos de lista de espera, tarifa por uso, penalización por inasistencia y activación de lista de espera.
- **Disponibilidad por franjas** con estado (disponible, sin cupos, cerrado por mantenimiento).
- **Lista de espera**: posición por solicitud y **promoción automática** al liberarse un cupo (cancelación, rechazo o inasistencia).
- **Cobros por uso** y **penalizaciones por inasistencia** con cargo en la cartera del inmueble; la inasistencia se registra y cancela la reserva liberando el cupo.
- **Cierres por mantenimiento** que cancelan las reservas afectadas y notifican.
- `GET /resumen` con reservas, pendientes, esperas, cierres activos e inasistencias.

---

## 9. Panel de indicadores

`GET /v3/indicadores/panel` (por conjunto y rango de fechas) reúne:
- **Cartera vencida**: total vencido y pendiente, índice de vencimiento y distribución por rangos (corriente, 1-30, 31-60, 61-90, +90).
- **Tiempos de respuesta de PQRS**: total del periodo, promedio/máximo de horas, cumplimiento de SLA y pendientes por antigüedad.
- **Uso de zonas**: reservas, horas, ocupación estimada, cancelaciones y cobro por zona.
- **Volumen de paquetes**: por mes, pendientes y tiempo promedio de retiro, además de visitantes, asistentes y mantenimiento.
- Exportación a XLSX (`/export.xlsx`) y detalle de cartera (`/cartera-detalle`).

---

## 10. Despliegue listo para operación

- **Base de datos**: PostgreSQL para operación (`DATABASE_URL`) con `psycopg2-binary` y pool de conexiones; SQLite para desarrollo local. El servidor de aplicación puede ejecutarse con Gunicorn y workers Uvicorn.
- **HTTPS**: debe terminarse en el servidor web o proxy inverso elegido para el despliegue, que publica Angular y reenvía `/api` a FastAPI. Los certificados y la configuración de dominio pertenecen a esa infraestructura; la cámara y PWA requieren un origen HTTPS (salvo localhost).
- **Copias de seguridad con prueba de restauración**: `deploy/backup/backup.sh` (dump de PostgreSQL y adjuntos, retención configurable), `deploy/backup/restore-test.sh` (restaura en una base temporal y verifica tablas y filas) y `deploy/backup/install-cron.sh` para programarlas en Linux/macOS. Además, IRIS expone respaldos desde la aplicación: `POST /v3/admin/respaldos` (crea y **verifica automáticamente**), `POST /respaldos/{id}/verificar`, `GET /respaldos/{id}/descargar`, `GET /backup` y `GET /adjuntos/paquete`.
- **Estado y validación**: `GET /v3/admin/estado-sistema` informa versión, motor de base, tablas y adjuntos; `GET /v3/admin/checklist-produccion` ofrece una lista de verificación. GitHub Actions (`.github/workflows/ci.yml`) ejecuta pruebas y compilación; la publicación en un servidor se realiza según la infraestructura del proyecto.

---

## Cambios en la interfaz

- Nuevo componente `frontend/src/app/components/v3/`: consola de módulos con pestañas por rol (administración, residente y portería), retroalimentación de cada operación y descarga de archivos.
- Rutas nuevas: `/admin/modulos`, `/residente/modulos`, `/portero/modulos`, accesibles desde las tarjetas «Módulos 3.0» de cada panel y desde el encabezado de portería.
- **Login con segundo factor**: si la cuenta tiene 2FA activo aparece la pantalla de verificación (código TOTP o de recuperación). `AuthService.verificarSegundoFactor()` completa la sesión.

## Cómo ejecutar en desarrollo

Usa dos terminales, Python 3.12, Node.js 22 y SQLite. En Windows PowerShell consulta los comandos completos en el README; en macOS/Linux:

```bash
cd backend && python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
APP_ENV=development python -m uvicorn app.main:app --reload --port 8000
```

En otra terminal:

```bash
cd frontend && npm ci && npm start   # http://localhost:4200
```

Para operación en servidor, instala PostgreSQL, Python y Node.js directamente en el host; configura `DATABASE_URL`, secretos, un proceso de servicio para FastAPI y un servidor web con HTTPS para publicar Angular y reenviar `/api`. La configuración de ese servidor depende del proveedor elegido.

Variables relevantes: `SECRET_KEY`, `DATABASE_URL`, `CORS_ORIGINS`, configuración del proveedor de pagos, credenciales WhatsApp/SMS, SMTP/VAPID y políticas de retención.

## Pruebas y verificación

```bash
cd backend && pytest -q          # 14 pruebas (4 previas + 10 de los módulos 3.0)
```

- `tests/test_v3.py` recorre los diez módulos de extremo a extremo: pasarela y webhook firmado, conciliación, consentimiento y avisos, mantenimiento con cotizaciones, evidencias y control de acceso a archivos, visitantes con placa y salida, 2FA y sesiones, egresos/mora/conciliación bancaria/importación de extracto, asambleas con quórum/votación/acta, reservas con cupos/espera/cierres/cargos, indicadores y respaldos con prueba de restauración.
- Verificación manual en navegador (rol administración y rol residente): login, configuración de pasarela con llaves cifradas, pago en línea aprobado y conciliado, orden de mantenimiento creada con foto adjunta, disponibilidad y reserva de piscina.

## Notas de operación

- La pasarela arranca en modo `simulado` (sandbox) para poder demostrar el flujo completo sin mover dinero. Para cobros reales, configure el proveedor colombiano y sus llaves en `/v3/pagos/config` (o por variables de entorno) y cambie el modo a `produccion`.
- Con `IRIS_2FA_OBLIGATORIO=1` (valor por defecto) la administración debe activar el segundo factor para ejecutar operaciones sensibles.
- Los avisos externos requieren proveedor configurado y consentimiento vigente; sin proveedor quedan registrados como simulados en la bitácora y siempre se crea la notificación interna.
- Los archivos adjuntos no se publican como estáticos: se descargan por `/v3/files/{archivo}` con autenticación y permiso sobre el conjunto, el inmueble o la orden.


---

## Ajustes solicitados posteriormente

- **Inicio de sesión:** conserva el enlace visible «¿Olvidaste tu contraseña? Recupérala aquí» y solicita el correo para activar el flujo de recuperación. En desarrollo navega al restablecimiento con el token de prueba; en producción requiere SMTP para enviar el enlace. El campo de contraseña incluye botón de ojo para mostrar/ocultar lo escrito.
- **Cámara QR de portería:** el escáner usa `jsQR` sobre el video de la cámara (`getUserMedia`), selecciona la cámara trasera cuando está disponible y pasa el texto reconocido al endpoint autenticado `/qr/validar`. Los PNG emitidos por IRIS contienen `IRIS-QR:<token>` y son compatibles con este lector. En navegador móvil, la cámara requiere permiso y el sitio debe usar HTTPS; `localhost` es excepción segura para pruebas. El ingreso manual permanece como alternativa.
- **PQRS:** tanto la descripción escrita por residente (petición, queja, reclamo o sugerencia) como la respuesta de administración admiten texto de longitud libre. Los campos de almacenamiento son SQL `TEXT`, los formularios no tienen `maxlength`, y la prueba de integración confirma texto de más de 200 caracteres de punta a punta. El generador auxiliar de QR en el formulario PQRS sí puede indicar que un mensaje muy largo no cabe en un QR; esto no impide radicar la PQRS ni limita su texto.
- **Parqueaderos y pagos:** cada cupo puede asignarse o desasignarse a un inmueble, registrar placa y definir tarifa mensual. Si tiene tarifa mayor a cero, administración puede generar cuotas del periodo con vencimiento; la ruta `POST /parqueaderos/generar-cobros` evita duplicar cargos para el mismo parqueadero/inmueble y periodo y notifica al residente. El residente ve el estado de asignación y tarifa en el inicio, y el cobro en Comunidad → Cuotas; desde ahí se gestiona con el mismo flujo de pago/conciliación de IRIS. La migración agrega tarifa con valor predeterminado cero a las instalaciones existentes.
- **Verificación de esta revisión:** frontend compilado con Angular; `pytest -q` pasa **14 pruebas**, incluyendo texto PQRS largo y generación idempotente de cuotas de parqueadero. La cámara real debe probarse en el dispositivo físico que la utilizará, porque depende de permiso y hardware.
