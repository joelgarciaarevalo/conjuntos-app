# IRIS · Módulo profesional de contador

Esta ampliación está aplicada **solo en la copia de trabajo**. El ZIP adjunto original no se edita ni se reemplaza.

## Inicio de sesión y acceso

El rol `contador` ya estaba habilitado en autenticación y redirige a `/contador`. La vista financiera ahora reúne accesos para registros contables, estados financieros, certificación, presupuestos, obligaciones tributarias, PUC, documentos, asientos, cartera, proveedores, fondos y auditoría. Los endpoints verifican el acceso al conjunto asignado; el contador no obtiene permisos generales de administración, usuarios o portería.

## Funciones añadidas

- **PUC:** catálogo inicial de cuentas comunes (base de referencia) y alta de cuentas por código, clase y naturaleza. El profesional debe validar el plan contra las políticas contables aplicables al conjunto.
- **Asientos:** creación manual solo si débitos y créditos cuadran. Causación idempotente de factura de administración (`débito 1305 / crédito 4170`) y del recaudo (`débito 1110 / crédito 1305`). Los pagos confirmados por las rutas existentes —incluida la conciliación de pagos en línea— disparan sincronización; los cargos monetarios de reserva y cartera se causan como cuenta por cobrar e ingreso. Existe botón de sincronización para recuperar pendientes.
- **Estados financieros:** resumen por clase contable y balance de prueba con filtro de fechas.
- **Facturación masiva:** creación de cuotas para los inmuebles del conjunto, con prevención de duplicados por inmueble, periodo y concepto; cada cuota creada genera su causación contable. El botón ejecuta el lote del periodo indicado. **No queda instalado un programador mensual autónomo** porque el importe, fecha de vencimiento y reglas de aprobación deben ser decididos por el conjunto.
- **PSE y cartera:** reutiliza la pasarela ya configurada en `/v3/pagos` y su conciliación existente. La liquidación de mora aplica la configuración previa de cartera y es idempotente por cuota y día. La tasa y días de gracia requieren revisión y configuración por administración.
- **Ejecución presupuestal:** compara presupuesto mensual existente con egresos por categoría. Continúan disponibles las funciones base de registrar egresos y presupuesto.
- **Cuentas por pagar:** registro de factura, causación de gasto y pasivo y, al registrar el pago, débito del pasivo y crédito de bancos.
- **Fondos:** control del Fondo de Imprevistos y otros fondos; el porcentaje mínimo de configuración se fija en 1 %. El traslado solicita la base aprobada del presupuesto, calcula el valor y crea asiento idempotente por periodo.
- **Documentos y reportes:** registro de metadatos de soportes, certificados HTML imprimibles y exportación de libro, cartera y balance de prueba a XLSX/CSV/PDF.
- **Auditoría:** consulta de la bitácora existente de cambios a pagos, cuotas, reservas y contabilidad, con fecha/hora, usuario, ruta y respuesta HTTP.

## Endpoints nuevos

Prefijo: `/v3/contabilidad/profesional`

| Ruta | Uso |
|---|---|
| `GET/POST /puc` | Consultar o crear cuentas del PUC |
| `GET/POST /asientos` | Listar o registrar asientos balanceados |
| `POST /asientos/sincronizar` | Procesar causaciones financieras pendientes sin duplicar |
| `GET /estados-financieros` | Resumen y balance de prueba por periodo |
| `GET /exportar` | Libros, cartera y balance en XLSX, CSV o PDF |
| `POST /facturacion/lote` | Generar cuentas mensuales del conjunto |
| `POST /cartera/calcular-mora` | Aplicar mora usando las tasas configuradas |
| `GET/POST /cuentas-por-pagar` | Registrar y listar obligaciones con proveedores |
| `PATCH /cuentas-por-pagar/{id}/pagar` | Registrar pago y asiento asociado |
| `GET /ejecucion-presupuestal` | Comparar presupuesto y gastos del periodo |
| `GET /fondos`, `PUT /fondos/{id}`, `POST /fondos/{id}/causar` | Gestionar fondos y traslado mensual |
| `GET/POST /documentos` | Registrar y consultar documentos contables |
| `GET /auditoria` | Consultar eventos financieros auditados |
| `GET /tributario/estado`, `GET /tributario/resumen` | Estado de integración y datos de trabajo tributario |
| `GET /certificacion` | Generar un borrador imprimible de certificación |

## Integraciones externas y límites operativos

- **DIAN:** la interfaz reporta que la integración requiere habilitación del facturador, resolución de numeración, firma/certificado digital y credenciales del proveedor tecnológico. Esta ampliación **no transmite documentos a DIAN ni los marca como aceptados** sin esas credenciales y acuses.
- **PSE:** la aplicación ya incluye proveedores/configuración y conciliación; cobros reales requieren las llaves habilitadas y modo de producción del conjunto. No se han introducido secretos.
- La certificación se entrega como **borrador**, no como certificación firmada. El contador responsable debe revisar cifras y firmar.
- El PUC de ejemplo y los porcentajes/tasas requieren validación profesional según reglas, estatutos y autorizaciones vigentes.
- El cálculo de lote y de mora está disponible bajo acción del contador, pero no se creó cron ni tarea recurrente; la configuración mensual de importe, vencimiento y política legal requiere decisión del conjunto.

## Pruebas verificadas

- Backend: `pytest -q` → 20 pruebas aprobadas.
- Frontend: `npm run build` aprobado. Angular informa un aviso preexistente de tamaño inicial del bundle y de librerías CommonJS.


## Solución para Windows con Python 3.14

La dependencia `tzdata` está incluida en `backend/requirements.txt` para que `ZoneInfo("America/Bogota")` funcione en Windows, donde Python puede no tener base IANA del sistema. Al ejecutar `npm start`, `scripts/setup.js` detecta el cambio del hash de requisitos e instala el paquete en `backend/.venv` automáticamente. Si el entorno virtual ya existía, vuelve a ejecutar `npm start` con conexión a Internet para que actualice sus dependencias.


## Alta de una cuenta de contador aparte

Desde una sesión de administrador del conjunto, abre **Gestión del conjunto** (`/admin/gestion`) y usa **Crear cuenta independiente para el contador**. El formulario crea un usuario nuevo, asigna únicamente el rol `contador` y una membresía al conjunto seleccionado, exige contraseña de al menos 12 caracteres y marca cambio obligatorio al primer ingreso. En producción se envía además verificación de correo. El usuario entra por la pantalla normal de inicio de sesión y el sistema lo lleva a `/contador`; esa sesión no tiene acceso al panel ni a la gestión administrativa general.


## Cuenta demo de contador en desarrollo local

Al ejecutar el proyecto en modo local (`APP_ENV=development`), se crea o corrige de forma idempotente esta cuenta demo:

- **Usuario:** `contador@iris-demo.com`
- **Contraseña:** `Contador2026!`
- **Ruta posterior al inicio de sesión:** `/contador`
- **Alcance:** conjunto demo, con acceso al panel financiero del contador.

Estas credenciales son únicamente para demostración y desarrollo local. No se crean en producción.
