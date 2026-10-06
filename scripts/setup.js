'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const backend = path.join(root, 'backend');
const frontend = path.join(root, 'frontend');
const requirements = path.join(backend, 'requirements.txt');
const frontendLock = path.join(frontend, 'package-lock.json');
const venv = path.join(backend, '.venv');
const win = process.platform === 'win32';
const venvPython = path.join(venv, win ? 'Scripts/python.exe' : 'bin/python');

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || root,
    env: options.env || process.env,
    stdio: 'inherit',
    shell: win && /\.cmd$/i.test(command),
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Falló el comando ${command} ${args.join(' ')} (código ${result.status}).`);
  }
}

function probe(command, prefix = []) {
  const result = spawnSync(command, [...prefix, '--version'], {
    cwd: root,
    encoding: 'utf8',
    windowsHide: true,
  });
  if (result.error || result.status !== 0) return null;
  const text = `${result.stdout || ''} ${result.stderr || ''}`.trim();
  const match = text.match(/Python\s+(\d+)\.(\d+)\.(\d+)/i);
  if (!match) return null;
  return { command, prefix, version: match.slice(1).map(Number), label: text };
}

function selectPython() {
  const candidates = win
    ? [{ command: 'python', prefix: [] }, { command: 'py', prefix: ['-3.12'] }, { command: 'python3', prefix: [] }]
    : [{ command: 'python3', prefix: [] }, { command: 'python', prefix: [] }];
  const found = candidates.map(({ command, prefix }) => probe(command, prefix)).filter(Boolean);
  const supported = found.find((item) => {
    const [major, minor] = item.version;
    return major === 3 && minor >= 12 && minor <= 14;
  });
  if (!supported) {
    const detected = found.length ? found.map((item) => item.label).join(', ') : 'no se detectó Python';
    throw new Error(
      `IRIS necesita Python 3.12, 3.13 o 3.14 para su API FastAPI. Detectado: ${detected}. ` +
      'Instala Python desde python.org marcando “Add python.exe to PATH”, cierra y abre PowerShell, y vuelve a ejecutar npm install.'
    );
  }
  return supported;
}

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function ensureBackend() {
  const selected = selectPython();
  console.log(`\n[IRIS] Python encontrado: ${selected.label}`);
  if (!fs.existsSync(venvPython)) {
    console.log('[IRIS] Creando el entorno aislado de la API...');
    fs.rmSync(venv, { recursive: true, force: true });
    run(selected.command, [...selected.prefix, '-m', 'venv', venv]);
  }

  const marker = path.join(venv, '.iris-requirements-sha256');
  const requirementsHash = sha256(requirements);
  if (!fs.existsSync(marker) || fs.readFileSync(marker, 'utf8').trim() !== requirementsHash) {
    console.log('[IRIS] Instalando dependencias de FastAPI (solo la primera vez o cuando cambien)...');
    run(venvPython, ['-m', 'pip', 'install', '-r', requirements], { cwd: backend });
    fs.writeFileSync(marker, `${requirementsHash}\n`);
  } else {
    console.log('[IRIS] Dependencias de FastAPI ya están instaladas.');
  }
}

function ensureFrontend() {
  const marker = path.join(frontend, 'node_modules', '.iris-lock-sha256');
  const lockHash = sha256(frontendLock);
  if (!fs.existsSync(marker) || fs.readFileSync(marker, 'utf8').trim() !== lockHash) {
    console.log('\n[IRIS] Instalando dependencias de Angular...');
    run(win ? 'npm.cmd' : 'npm', ['ci', '--no-audit', '--no-fund'], { cwd: frontend });
    fs.writeFileSync(marker, `${lockHash}\n`);
  } else {
    console.log('[IRIS] Dependencias de Angular ya están instaladas.');
  }
}

try {
  if (!fs.existsSync(requirements) || !fs.existsSync(frontendLock)) {
    throw new Error('Abre PowerShell en la carpeta principal de IRIS (la que contiene package.json, backend y frontend).');
  }
  ensureBackend();
  ensureFrontend();
  console.log('\n[IRIS] Instalación local lista. Ejecuta npm start para iniciar la aplicación.');
} catch (error) {
  console.error(`\n[IRIS] No se pudo completar la preparación.\n${error.message}`);
  process.exit(1);
}
