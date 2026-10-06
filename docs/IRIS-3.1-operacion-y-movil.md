# IRIS 3.1 · Operación guiada y experiencia móvil

Esta versión se construyó como **copia separada** de la copia anterior del proyecto. El ZIP de entrada y la carpeta v3 no se editan.

## Cambios agregados

- **Asistente de alta de conjunto** para superadministración: crea el conjunto y, de manera secuencial, las zonas iniciales con horarios y reglas seguras por defecto. Un error parcial se muestra con el ID ya creado y el número de zonas completadas para que se pueda continuar sin recrear el conjunto.
- **Aprobación previa del gasto de mantenimiento**: las cotizaciones quedan pendientes hasta aprobación/rechazo de administración; se captura una nota, usuario y hora, y la decisión se agrega al historial de avances. No se puede seleccionar un proveedor antes de aprobar el importe.
- **PWA instalable** con evento estándar de instalación, instrucciones para Safari en iPhone/iPad, accesos rápidos a PQRS, reservas y portería, y estado visible cuando falta conexión. Los formularios no se encolan ni se sincronizan fuera de línea: las operaciones necesitan conexión para no duplicar pagos, reservas o movimientos.
- **Ajustes responsivos** en tablas, formularios y botones de módulos para pantallas pequeñas, conservando la interfaz completa para PC.

## Validación

- Backend: `cd backend && .venv/bin/pytest -q`.
- Frontend: `cd frontend && npm ci && npm run build`.
- La migración de cotizaciones es aditiva/idempotente; no borra registros.

## Activación requerida en operación

El asistente de conjuntos requiere iniciar sesión como superadministrador. El botón PWA se ofrece en navegadores que exponen `beforeinstallprompt`; iOS usa Compartir → Agregar a pantalla de inicio. La instalación/cámara y las notificaciones del navegador requieren HTTPS en un dominio real (excepto localhost). Pagos reales y WhatsApp/SMS dependen de configurar credenciales y webhooks de los proveedores; sin eso se mantiene el modo de prueba. Antes de producción deben configurarse dominio, TLS, PostgreSQL, secretos y copia externa.
