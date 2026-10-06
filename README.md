# IRIS 3.1 — Ejecución local con npm, sin Docker

Esta es una **copia de trabajo separada** del archivo original recibido. El archivo original no se modifica. La aplicación reúne el frontend Angular y la API FastAPI; el lanzador npm prepara sus dependencias y levanta ambos servicios.

## Requisitos previos (una sola vez)

- **Node.js 22** (incluye npm).
- **Python 3.12, 3.13 o 3.14** disponible como comando `python`. No se necesita el lanzador `py` ni activar manualmente un entorno virtual.
- Internet para descargar las dependencias la primera vez.

El backend sigue siendo Python: `npm install` crea y prepara un entorno virtual aislado automáticamente. No necesita Docker ni que ejecutes comandos `pip` por separado.

## Windows: inicio

1. Descomprime este ZIP en una carpeta nueva.
2. Abre PowerShell **en la carpeta que contiene `package.json`, `backend` y `frontend`**. Compruébalo con:

   ```powershell
   Get-ChildItem
   ```

3. Ejecuta:

   ```powershell
   npm install
   npm start
   ```

La primera instalación puede tardar unos minutos: npm instala Angular, crea `backend\.venv` e instala allí las dependencias de la API. No cierres la ventana mientras instala ni mientras la aplicación esté ejecutándose. Para apagar los dos servicios, presiona `Ctrl+C`.

Abre **http://localhost:4200**. La API está en **http://localhost:8000** y su documentación de desarrollo en **http://localhost:8000/docs**.

### Cuentas de prueba (solo desarrollo)

| Perfil | Correo | Contraseña |
|---|---|---|
| Administración superadmin | `admin@iris-demo.com` | `Admin2026` |
| Residente | `residente@iris-demo.com` | `Usuario2026` |
| Portería | `portero@iris-demo.com` | `Portero2026` |

Son datos de demostración: no los uses en un sistema real.

## Celular en la misma red Wi-Fi

`npm start` enlaza la interfaz y la API a la red local y muestra las direcciones disponibles. Abre en el celular la URL `http://DIRECCION-IP-DEL-PC:4200` que aparezca en PowerShell. Acepta Python y Node.js en el firewall de Windows para la red privada si el sistema lo solicita.

La interfaz adaptable puede probarse por HTTP local. **El navegador exige HTTPS para habilitar la cámara QR y la instalación PWA desde un celular**; para esos usos hay que servir la aplicación con HTTPS. En `localhost`, la cámara sí puede utilizarse desde el navegador del PC.

## Qué queda automático y qué requiere configuración externa

La aplicación incluye los módulos de IRIS 3.1 y usa SQLite/datos de demostración para el uso local. Las operaciones reales de pagos Wompi, WhatsApp/SMS, correo/push, HTTPS de producción y PostgreSQL requieren las cuentas, credenciales, dominio y configuración del proveedor o servidor correspondiente. El modo local no procesa pagos reales.

## Diagnóstico rápido

- Si `npm install` dice que no encuentra `package.json`, PowerShell está en la carpeta equivocada. Cambia a la carpeta principal del proyecto, no a `backend` ni a `frontend`.
- Comprueba versiones con `node --version`, `npm --version` y `python --version`. El lanzador admite Python 3.12–3.14 y no depende de `py`.
- Si Windows pregunta por el firewall, permite Python y Node.js en la red privada.
- Si los puertos 4200 u 8000 ya están ocupados, cierra el otro proceso de IRIS y vuelve a ejecutar `npm start`.
- Si cambian las dependencias, vuelve a ejecutar `npm install`; el siguiente `npm start` verificará la preparación automáticamente.
