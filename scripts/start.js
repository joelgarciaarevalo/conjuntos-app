'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const backend = path.join(root, 'backend');
const frontend = path.join(root, 'frontend');
const win = process.platform === 'win32';
const python = path.join(backend, '.venv', win ? 'Scripts/python.exe' : 'bin/python');
const angularCli = path.join(frontend, 'node_modules', '@angular', 'cli', 'bin', 'ng.js');

if (!fs.existsSync(python) || !fs.existsSync(angularCli)) {
  console.error('[IRIS] Faltan dependencias. Ejecuta npm install en la carpeta principal del proyecto.');
  process.exit(1);
}

const lanAddresses = [];
for (const entries of Object.values(os.networkInterfaces())) {
  for (const entry of entries || []) {
    if (entry.family === 'IPv4' && !entry.internal && !entry.address.startsWith('169.254.')) {
      lanAddresses.push(entry.address);
    }
  }
}
const origins = new Set(['http://localhost:4200', 'http://127.0.0.1:4200']);
for (const origin of (process.env.CORS_ORIGINS || '').split(',')) {
  if (origin.trim()) origins.add(origin.trim());
}
for (const address of lanAddresses) origins.add(`http://${address}:4200`);

const baseEnv = {
  ...process.env,
  APP_ENV: 'development',
  CORS_ORIGINS: [...origins].join(','),
  PYTHONUTF8: '1',
  PYTHONIOENCODING: 'utf-8',
};

const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child && child.exitCode === null) child.kill();
  }
  setTimeout(() => process.exit(code), 250);
}

console.log('\nIRIS 3.1 — modo local, sin Docker');
console.log('API:      http://localhost:8000');
console.log('Interfaz: http://localhost:4200');
if (lanAddresses.length) {
  console.log('Celular (misma Wi-Fi):');
  for (const address of lanAddresses) console.log(`          http://${address}:4200`);
}
console.log('Para detener ambos servicios, presiona Ctrl+C.');
console.log('Nota: el navegador requiere HTTPS para permitir cámara QR/PWA desde otro dispositivo.\n');

const api = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--reload', '--host', '0.0.0.0', '--port', '8000'], {
  cwd: backend,
  env: baseEnv,
  stdio: 'inherit',
  windowsHide: true,
});
children.push(api);

const web = spawn(process.execPath, [angularCli, 'serve', '--host', '0.0.0.0', '--port', '4200'], {
  cwd: frontend,
  env: baseEnv,
  stdio: 'inherit',
  windowsHide: true,
});
children.push(web);

for (const child of children) {
  child.on('error', (error) => {
    console.error(`[IRIS] No se pudo iniciar un servicio: ${error.message}`);
    stop(1);
  });
  child.on('exit', (code, signal) => {
    if (!stopping) {
      console.error(`[IRIS] Un servicio terminó (código ${code ?? 'n/a'}, señal ${signal ?? 'n/a'}).`);
      stop(code && code !== 0 ? code : 1);
    }
  });
}

process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));
