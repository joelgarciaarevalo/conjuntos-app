import { Component, OnInit, ViewEncapsulation } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormControl, FormGroup, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatToolbarModule } from '@angular/material/toolbar';
import { toDataURL } from 'qrcode';
import { AuthService } from '../../../services/auth.service';
import {
  AccesoQR,
  CatalogoQR,
  CodigoQR,
  EstadoQR,
  QRCrear,
  QrService,
  ResidenteOpcion,
  ResultadoValidacion,
  TipoQR
} from '../../../services/qr.service';

type FiltroQR = 'todos' | 'activo' | 'vencido' | 'revocado';

@Component({
  selector: 'app-admin-qr',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatCheckboxModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    MatSnackBarModule,
    MatTableModule,
    MatToolbarModule
  ],
  templateUrl: './qr.component.html',
  styleUrls: ['./qr.component.css'],
  encapsulation: ViewEncapsulation.None
})
export class QrComponent implements OnInit {
  form: FormGroup;
  validarCtrl = new FormControl('', { nonNullable: true });
  registrarCtrl = new FormControl(true, { nonNullable: true });

  codigos: CodigoQR[] = [];
  catalogo: CatalogoQR = { residentes: [], reservas: [] };
  accesos: AccesoQR[] = [];

  filtro: FiltroQR = 'todos';
  seleccionado: CodigoQR | null = null;
  qrImagen = '';

  generando = false;
  generandoLote = false;
  validando = false;
  resultado: ResultadoValidacion | null = null;

  columnas = ['tipo', 'titular', 'vigencia', 'usos', 'estado', 'acciones'];

  tipos: { valor: TipoQR; etiqueta: string; icono: string; ayuda: string }[] = [
    { valor: 'residente', etiqueta: 'Residente', icono: 'badge', ayuda: 'QR permanente y único por residente. Se puede revocar o regenerar.' },
    { valor: 'visita', etiqueta: 'Visita', icono: 'person_add', ayuda: 'QR temporal para un visitante, con vigencia y número de usos.' },
    { valor: 'reserva', etiqueta: 'Reserva', icono: 'event_available', ayuda: 'QR para una reserva aprobada. Vale solo durante el horario reservado.' }
  ];

  opcionesHoras = [
    { valor: 2, etiqueta: '2 horas' },
    { valor: 4, etiqueta: '4 horas' },
    { valor: 8, etiqueta: '8 horas' },
    { valor: 24, etiqueta: '1 día' },
    { valor: 72, etiqueta: '3 días' },
    { valor: 168, etiqueta: '7 días' }
  ];

  mismoResidente = (a: ResidenteOpcion | null, b: ResidenteOpcion | null): boolean =>
    !!a && !!b && a.inmueble_id === b.inmueble_id && a.residente_id === b.residente_id;

  constructor(
    private fb: FormBuilder,
    private qrService: QrService,
    private authService: AuthService,
    private router: Router,
    private snackBar: MatSnackBar
  ) {
    this.form = this.fb.group({
      tipo: ['residente', Validators.required],
      residente: [null],
      reserva_id: [null],
      visitante_nombre: [''],
      visitante_documento: [''],
      horas_validez: [24],
      usos_maximos: [1]
    });
  }

  ngOnInit(): void {
    this.form.get('tipo')!.valueChanges.subscribe((tipo: TipoQR) => this.ajustarValidadores(tipo));
    this.ajustarValidadores('residente');
    this.cargarTodo();
  }

  // ---------------------------------------------------------------- Carga
  get tipoActual(): TipoQR {
    return this.form.get('tipo')!.value as TipoQR;
  }

  get ayudaTipo(): string {
    return this.tipos.find(t => t.valor === this.tipoActual)?.ayuda ?? '';
  }

  cargarTodo(): void {
    this.cargarCodigos();
    this.cargarCatalogo();
    this.cargarAccesos();
  }

  cargarCodigos(): void {
    this.qrService.listar().subscribe({
      next: (data) => {
        this.codigos = data;
        if (this.seleccionado) {
          const actualizado = data.find(c => c.id === this.seleccionado!.id) ?? null;
          if (!actualizado) {
            this.cerrarVista();
          } else if (actualizado.token !== this.seleccionado.token) {
            this.verQR(actualizado, false);
          } else {
            this.seleccionado = actualizado;
          }
        }
      },
      error: (err) => this.mostrarError(err, 'No se pudieron cargar los códigos QR')
    });
  }

  cargarCatalogo(): void {
    this.qrService.getCatalogo().subscribe({
      next: (data) => this.catalogo = data,
      error: () => {}
    });
  }

  cargarAccesos(): void {
    this.qrService.accesosRecientes(8).subscribe({
      next: (data) => this.accesos = data,
      error: () => {}
    });
  }

  // ---------------------------------------------------------------- Formulario
  private ajustarValidadores(tipo: TipoQR): void {
    const poner = (nombre: string, validadores: ValidatorFn[]) => {
      const control = this.form.get(nombre)!;
      control.setValidators(validadores);
      control.updateValueAndValidity({ emitEvent: false });
    };
    poner('residente', tipo === 'reserva' ? [] : [Validators.required]);
    poner('reserva_id', tipo === 'reserva' ? [Validators.required] : []);
    poner('visitante_nombre', tipo === 'visita' ? [Validators.required, Validators.maxLength(100)] : []);
    poner('horas_validez', tipo === 'visita' ? [Validators.required, Validators.min(1), Validators.max(720)] : []);
    poner('usos_maximos', tipo === 'visita' ? [Validators.required, Validators.min(1), Validators.max(100)] : []);
  }

  seleccionarTipo(tipo: TipoQR): void {
    this.form.patchValue({ tipo, residente: null, reserva_id: null });
  }

  crear(): void {
    if (this.form.invalid || this.generando) return;

    const v = this.form.value;
    const tipo = v.tipo as TipoQR;
    const datos: QRCrear = { tipo };

    if (tipo === 'reserva') {
      datos.reserva_id = v.reserva_id;
    } else {
      const r = v.residente as ResidenteOpcion;
      datos.inmueble_id = r.inmueble_id;
      datos.residente_id = r.residente_id;
    }
    if (tipo === 'visita') {
      datos.visitante_nombre = String(v.visitante_nombre ?? '').trim();
      datos.visitante_documento = String(v.visitante_documento ?? '').trim() || undefined;
      datos.horas_validez = Number(v.horas_validez);
      datos.usos_maximos = Number(v.usos_maximos);
    }

    this.generando = true;
    this.qrService.crear(datos).subscribe({
      next: (nuevo) => {
        this.generando = false;
        this.snackBar.open('Código QR generado', 'Cerrar', { duration: 3000 });
        this.form.patchValue({ visitante_nombre: '', visitante_documento: '', residente: null, reserva_id: null });
        this.form.markAsUntouched();
        this.cargarCodigos();
        this.cargarCatalogo();
        this.verQR(nuevo);
      },
      error: (err) => {
        this.generando = false;
        this.mostrarError(err, 'No se pudo generar el código QR');
      }
    });
  }

  generarParaTodos(): void {
    if (this.generandoLote) return;
    this.generandoLote = true;
    this.qrService.generarParaTodosLosResidentes().subscribe({
      next: (r) => {
        this.generandoLote = false;
        const mensaje = r.creados === 0
          ? 'Todos los residentes ya tienen un QR activo'
          : `Se generaron ${r.creados} código(s) QR` + (r.omitidos ? ` (${r.omitidos} ya existían)` : '');
        this.snackBar.open(mensaje, 'Cerrar', { duration: 4000 });
        this.cargarCodigos();
        this.cargarCatalogo();
      },
      error: (err) => {
        this.generandoLote = false;
        this.mostrarError(err, 'No se pudieron generar los códigos');
      }
    });
  }

  // ---------------------------------------------------------------- Lista y acciones
  get codigosFiltrados(): CodigoQR[] {
    return this.filtro === 'todos' ? this.codigos : this.codigos.filter(c => this.grupo(c.estado) === this.filtro);
  }

  conteo(filtro: FiltroQR): number {
    return filtro === 'todos' ? this.codigos.length : this.codigos.filter(c => this.grupo(c.estado) === filtro).length;
  }

  setFiltro(filtro: FiltroQR): void {
    this.filtro = filtro;
  }

  private grupo(estado: EstadoQR): FiltroQR {
    if (estado === 'activo' || estado === 'programado') return 'activo';
    if (estado === 'revocado') return 'revocado';
    return 'vencido';
  }

  etiquetaTipo(tipo: TipoQR): string {
    return this.tipos.find(t => t.valor === tipo)?.etiqueta ?? tipo;
  }

  iconoTipo(tipo: TipoQR): string {
    return this.tipos.find(t => t.valor === tipo)?.icono ?? 'qr_code_2';
  }

  titular(qr: CodigoQR): string {
    if (qr.tipo === 'visita') return qr.visitante_nombre || 'Visitante';
    return qr.residente_nombre || 'Residente';
  }

  detalle(qr: CodigoQR): string {
    const partes: string[] = [];
    if (qr.tipo === 'visita' && qr.residente_nombre) partes.push('Autoriza: ' + qr.residente_nombre);
    if (qr.tipo === 'reserva' && qr.zona_nombre) partes.push(qr.zona_nombre);
    if (qr.inmueble_etiqueta) partes.push(qr.inmueble_etiqueta);
    return partes.join(' · ');
  }

  usosTexto(qr: CodigoQR): string {
    return qr.usos_maximos === null ? `${qr.usos_actuales} (sin límite)` : `${qr.usos_actuales} de ${qr.usos_maximos}`;
  }

  textoEstado(estado: string | null): string {
    const textos: Record<string, string> = {
      activo: 'Activo',
      programado: 'Programado',
      vencido: 'Vencido',
      agotado: 'Agotado',
      revocado: 'Revocado'
    };
    return estado ? (textos[estado] ?? estado) : '';
  }

  puedeOperar(qr: CodigoQR): boolean {
    return qr.estado !== 'revocado';
  }

  revocar(qr: CodigoQR): void {
    if (!confirm(`¿Revocar el QR de ${this.titular(qr)}? Dejará de funcionar de inmediato.`)) return;
    this.qrService.revocar(qr.id).subscribe({
      next: () => {
        this.snackBar.open('Código revocado', 'Cerrar', { duration: 3000 });
        this.cargarCodigos();
        this.cargarCatalogo();
      },
      error: (err) => this.mostrarError(err, 'No se pudo revocar el código')
    });
  }

  regenerar(qr: CodigoQR): void {
    if (!confirm(`¿Regenerar el QR de ${this.titular(qr)}? El código anterior dejará de funcionar.`)) return;
    this.qrService.regenerar(qr.id).subscribe({
      next: (nuevo) => {
        this.snackBar.open('Código regenerado', 'Cerrar', { duration: 3000 });
        this.cargarCodigos();
        this.cargarCatalogo();
        this.verQR(nuevo);
      },
      error: (err) => this.mostrarError(err, 'No se pudo regenerar el código')
    });
  }

  // ---------------------------------------------------------------- Vista previa / descarga
  contenido(qr: CodigoQR): string {
    return `IRIS-QR:${qr.token}`;
  }

  verQR(qr: CodigoQR, desplazar = true): void {
    this.seleccionado = qr;
    toDataURL(this.contenido(qr), {
      width: 360,
      margin: 2,
      errorCorrectionLevel: 'M',
      color: { dark: '#0c3b45', light: '#ffffff' }
    }).then((url) => {
      if (this.seleccionado && this.seleccionado.id === qr.id) {
        this.qrImagen = url;
      }
    }).catch(() => this.snackBar.open('No se pudo dibujar el QR', 'Cerrar', { duration: 3000 }));

    if (desplazar) {
      setTimeout(() => document.getElementById('qr-preview')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 80);
    }
  }

  cerrarVista(): void {
    this.seleccionado = null;
    this.qrImagen = '';
  }

  async descargar(): Promise<void> {
    if (!this.seleccionado) return;
    try {
      const url = await this.componerTarjeta(this.seleccionado);
      const enlace = document.createElement('a');
      enlace.href = url;
      enlace.download = `qr-iris-${this.seleccionado.tipo}-${this.seleccionado.id}.png`;
      document.body.appendChild(enlace);
      enlace.click();
      document.body.removeChild(enlace);
    } catch {
      this.snackBar.open('No se pudo generar la imagen', 'Cerrar', { duration: 3000 });
    }
  }

  async imprimir(): Promise<void> {
    if (!this.seleccionado) return;
    try {
      const url = await this.componerTarjeta(this.seleccionado);
      const ventana = window.open('', '_blank', 'width=520,height=760');
      if (!ventana) {
        this.snackBar.open('Tu navegador bloqueó la ventana de impresión', 'Cerrar', { duration: 4000 });
        return;
      }
      ventana.document.write(
        `<!doctype html><html><head><title>QR IRIS</title></head>` +
        `<body style="margin:0;display:flex;justify-content:center;align-items:flex-start;padding:16px">` +
        `<img src="${url}" style="width:360px;max-width:100%" onload="window.focus();window.print()"></body></html>`
      );
      ventana.document.close();
    } catch {
      this.snackBar.open('No se pudo preparar la impresión', 'Cerrar', { duration: 3000 });
    }
  }

  async copiarCodigo(): Promise<void> {
    if (!this.seleccionado) return;
    try {
      await navigator.clipboard.writeText(this.contenido(this.seleccionado));
      this.snackBar.open('Código copiado', 'Cerrar', { duration: 2500 });
    } catch {
      this.snackBar.open('No se pudo copiar. Selecciónalo manualmente.', 'Cerrar', { duration: 3000 });
    }
  }

  vigenciaTexto(qr: CodigoQR): string {
    const fmt = (iso: string) => {
      const f = new Date(iso);
      const p = (n: number) => String(n).padStart(2, '0');
      return `${p(f.getDate())}/${p(f.getMonth() + 1)}/${f.getFullYear()} ${p(f.getHours())}:${p(f.getMinutes())}`;
    };
    return qr.valido_hasta ? `Hasta ${fmt(qr.valido_hasta)}` : 'Sin vencimiento';
  }

  private cargarImagen(src: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('imagen'));
      img.src = src;
    });
  }

  /** Tarjeta PNG lista para imprimir o enviar: encabezado IRIS + QR + datos. */
  private async componerTarjeta(qr: CodigoQR): Promise<string> {
    const qrUrl = await toDataURL(this.contenido(qr), {
      width: 480,
      margin: 1,
      errorCorrectionLevel: 'M',
      color: { dark: '#0c3b45', light: '#ffffff' }
    });
    const img = await this.cargarImagen(qrUrl);

    const ancho = 600;
    const alto = 800;
    const canvas = document.createElement('canvas');
    canvas.width = ancho;
    canvas.height = alto;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('canvas');

    const fuente = `'Manrope', 'Segoe UI', Arial, sans-serif`;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, ancho, alto);

    ctx.fillStyle = '#0c3b45';
    ctx.fillRect(0, 0, ancho, 120);
    ctx.fillStyle = '#cfefea';
    ctx.textAlign = 'center';
    ctx.font = `800 44px ${fuente}`;
    ctx.fillText('IRIS', ancho / 2, 64);
    ctx.fillStyle = '#88c9c3';
    ctx.font = `600 18px ${fuente}`;
    ctx.fillText('Control de acceso residencial', ancho / 2, 96);

    ctx.drawImage(img, 60, 150, 480, 480);

    ctx.fillStyle = '#3e9b93';
    ctx.font = `700 18px ${fuente}`;
    ctx.fillText(this.etiquetaTipo(qr.tipo).toUpperCase(), ancho / 2, 668);

    ctx.fillStyle = '#0c3b45';
    ctx.font = `800 28px ${fuente}`;
    ctx.fillText(this.titular(qr), ancho / 2, 704, ancho - 60);

    ctx.fillStyle = '#21666b';
    ctx.font = `600 18px ${fuente}`;
    ctx.fillText(this.detalle(qr), ancho / 2, 732, ancho - 60);
    ctx.fillText(this.vigenciaTexto(qr), ancho / 2, 758, ancho - 60);

    ctx.fillStyle = '#6b8f8c';
    ctx.font = `500 12px monospace`;
    ctx.fillText(this.contenido(qr), ancho / 2, 784, ancho - 40);

    return canvas.toDataURL('image/png');
  }

  // ---------------------------------------------------------------- Validación en portería
  validar(): void {
    const codigo = this.validarCtrl.value.trim();
    if (!codigo || this.validando) return;

    this.validando = true;
    this.qrService.validar(codigo, this.registrarCtrl.value).subscribe({
      next: (r) => {
        this.validando = false;
        this.resultado = r;
        this.validarCtrl.setValue('');
        this.cargarCodigos();
        this.cargarAccesos();
      },
      error: (err) => {
        this.validando = false;
        this.mostrarError(err, 'No se pudo validar el código');
      }
    });
  }

  limpiarResultado(): void {
    this.resultado = null;
  }

  // ---------------------------------------------------------------- Varios
  private mostrarError(err: any, porDefecto: string): void {
    const detalle = err?.error?.detail;
    let mensaje = typeof detalle === 'string' ? detalle : porDefecto;
    if (err?.status === 0) mensaje = 'No hay conexión con el servidor';
    this.snackBar.open(mensaje, 'Cerrar', { duration: 4000 });
  }

  volver(): void {
    this.router.navigate(['/admin']);
  }

  cerrarSesion(): void {
    this.authService.logout();
  }
}
