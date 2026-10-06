import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { irisApiBase } from '../../services/api-url';
import { AuthService } from '../../services/auth.service';

type Seccion =
  | 'indicadores' | 'pagos' | 'avisos' | 'mantenimiento' | 'visitantes'
  | 'seguridad' | 'contabilidad' | 'asambleas' | 'reservas' | 'operacion';

interface Pestana { id: Seccion; titulo: string; descripcion: string; roles: string[] }

@Component({
  selector: 'app-v3',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './v3.component.html',
  styleUrls: ['./v3.component.css'],
})
export class V3Component implements OnInit {
  usuario: any = {};
  rol = '';
  esAdmin = false;
  esResidente = false;
  esPortero = false;
  esSuperAdmin = false;

  /** Código del segundo factor para operaciones sensibles (X-IRIS-OTP). */
  otp = '';
  error = '';
  feedback = '';
  cargando: Record<string, boolean> = {};
  seccion: Seccion = 'indicadores';

  conjuntos: any[] = [];
  conjuntoId: number | null = null;
  inmuebles: any[] = [];
  cuotas: any[] = [];

  /** Indicadores */
  panel: any = null;
  rangoIndicadores = { desde: '', hasta: '' };

  /** Pagos */
  pagoConfig: any = null;
  pagoMetodos: any = null;
  pagoTransacciones: any[] = [];
  pagoResumen: any = null;
  pagoEventos: any[] = [];
  formPagoConfig: any = {
    proveedor: 'simulado', modo: 'sandbox', moneda: 'COP', public_key: '', private_key: '',
    events_secret: '', integrity_secret: '', permite_tarjeta: true, permite_pse: true,
    permite_nequi: true, conciliacion_automatica: true, activo: true,
  };
  formCheckout: any = { cuota_id: null, metodo: 'tarjeta', token: 'tok_visa_aprobado' };
  proveedoresPasarela: any[] = [];

  /** Avisos */
  consentimientos: any[] = [];
  plantillas: any[] = [];
  bitacora: any[] = [];
  misAvisos: any[] = [];
  estadoConsentimientos: any[] = [];
  formConsentimiento: any = { canal: 'whatsapp', telefono: '', otorgado: true, version_politica: '1.0' };
  formAviso: any = { evento: 'paquete_recibido', inmueble_id: null, canal: '', mensaje: '' };
  eventosAviso: string[] = [];

  /** Mantenimiento */
  proveedores: any[] = [];
  ordenes: any[] = [];
  ordenDetalle: any = null;
  ordenesVencidas: any[] = [];
  mantResumen: any = null;
  filtroOrden = '';
  formProveedor: any = { nombre: '', nit: '', especialidad: '', telefono: '', email: '', calificacion: 4 };
  formOrden: any = { titulo: '', descripcion: '', prioridad: 'media', inmueble_id: null, proveedor_id: null, fecha_limite: '', costo_estimado: '' };
  formCotizacion: any = { proveedor_nombre: '', monto: '', descripcion: '' };
  formAvance: any = { nota: '', estado: '' };
  formCierreOrden: any = { estado: 'completada', costo_final: '', nota: '' };
  archivoEvidencia: File | null = null;
  archivoSoporte: File | null = null;

  /** Visitantes */
  autorizaciones: any[] = [];
  accesos: any[] = [];
  visitantesEnSitio: any[] = [];
  visitResumen: any = null;
  directorio: any[] = [];
  formAutorizacion: any = { inmueble_id: null, nombre: '', documento: '', placa: '', tipo: 'visitante', usos_maximos: 1, valido_hasta: '' };
  formAccesoVisitante: any = { inmueble_id: null, nombre: '', documento: '', placa: '', autorizacion_id: null, observacion: '' };

  /** Seguridad */
  segEstado: any = null;
  sesiones: any[] = [];
  intentos: any[] = [];
  politica: any = null;
  privacidad: any = null;
  setup2fa: any = null;
  codigosRecuperacion: string[] = [];
  form2fa: any = { codigo: '' };
  formPolitica: any = { dias_retencion_auditoria: 365, dias_retencion_accesos: 365, dias_retencion_avisos: 180, dias_retencion_intentos: 30, dias_retencion_sesiones: 90, anonimizar_al_purgar: true, texto_privacidad: '' };
  formSolicitudDatos: any = { tipo: 'acceso', detalle: '' };
  purgaSimulada: any = null;

  /** Contabilidad */
  egresos: any[] = [];
  presupuestos: any[] = [];
  carteraConfig: any = null;
  cartera: any = null;
  movimientos: any[] = [];
  informe: any = null;
  moraResultado: any = null;
  formEgreso: any = { concepto: '', categoria: 'general', monto: '', fecha: '' };
  formPresupuesto: any = { periodo: '', categoria: 'general', monto_presupuestado: '' };
  formCarteraConfig: any = { interes_moratorio_diario: '0.001', tasa_mora_mensual: '0', recargo_fijo: 0, dias_gracia: 5, activo: true };
  formInforme: any = { desde: '', hasta: '' };
  archivoExtracto: File | null = null;

  /** Asambleas */
  asambleas: any[] = [];
  asambleaDetalle: any = null;
  acta: string = '';
  formAsamblea: any = { titulo: '', tipo: 'ordinaria', modalidad: 'mixta', lugar: '', enlace: '', fecha_inicio: '', fecha_fin: '', quorum_requerido: 50 };
  formVotacion: any = { titulo: '', tipo: 'si_no', mayoria: 'simple', opcionesTexto: '', permite_abstencion: true };

  /** Reservas */
  reglasZonas: any[] = [];
  zonaId: number | null = null;
  reglaZona: any = null;
  disponibilidad: any = null;
  fechaDisponibilidad = '';
  reservas: any[] = [];
  esperas: any[] = [];
  cierres: any[] = [];
  cargosReserva: any[] = [];
  reservasResumen: any = null;
  formReserva: any = { inmueble_id: null, inicio: '', fin: '' };
  formEspera: any = { inmueble_id: null, inicio: '', fin: '' };
  formCierre: any = { motivo: 'Mantenimiento programado', fecha_inicio: '', fecha_fin: '' };

  /** Operación */
  estadoSistema: any = null;
  checklist: any = null;
  respaldos: any[] = [];
  altaConjunto: any = { nombre: '', nit: '', direccion: '', zonas: 'Piscina\nSalón social\nGimnasio' };
  altaConjuntoCreado: any = null;

  private apiBase = String(irisApiBase()).replace(/\/+$/, '');

  constructor(private http: HttpClient, private auth: AuthService) {}

  ngOnInit(): void {
    this.usuario = this.auth.getUsuario() || {};
    this.rol = this.usuario?.rol || '';
    this.esSuperAdmin = !!this.usuario?.es_super_admin;
    this.esAdmin = this.esSuperAdmin || this.rol === 'admin';
    this.esResidente = this.rol === 'residente';
    this.esPortero = this.rol === 'portero';
    this.seccion = this.esAdmin ? 'indicadores' : this.esResidente ? 'pagos' : 'visitantes';
    this.prepararFechas();
    this.cargarConjuntos();
    if (this.esResidente) this.cargarMisAvisos();
    if (this.esPortero) this.cargarVisitantes();
  }

  pestanas(): Pestana[] {
    const todas: Pestana[] = [
      { id: 'indicadores', titulo: 'Indicadores', descripcion: 'Cartera, PQRS, zonas y paquetes', roles: ['admin'] },
      { id: 'pagos', titulo: 'Pagos en línea', descripcion: 'Pasarela, checkout y conciliación', roles: ['admin', 'residente'] },
      { id: 'avisos', titulo: 'Avisos WhatsApp/SMS', descripcion: 'Consentimiento, plantillas y bitácora', roles: ['admin', 'residente'] },
      { id: 'mantenimiento', titulo: 'Mantenimiento', descripcion: 'Proveedores, cotizaciones y fotos', roles: ['admin', 'portero'] },
      { id: 'visitantes', titulo: 'Visitantes', descripcion: 'Autorizaciones, placas y salidas', roles: ['admin', 'portero', 'residente'] },
      { id: 'seguridad', titulo: 'Seguridad y datos', descripcion: '2FA, sesiones y retención', roles: ['admin', 'residente'] },
      { id: 'contabilidad', titulo: 'Contabilidad y cartera', descripcion: 'Egresos, mora y conciliación bancaria', roles: ['admin'] },
      { id: 'asambleas', titulo: 'Asambleas', descripcion: 'Quórum, votación y actas', roles: ['admin', 'residente'] },
      { id: 'reservas', titulo: 'Reservas avanzadas', descripcion: 'Cupos, espera, cobros y cierres', roles: ['admin', 'residente'] },
      { id: 'operacion', titulo: 'Operación', descripcion: 'Respaldos, restauración y salud', roles: ['admin'] },
    ];
    return todas.filter((p) => this.esSuperAdmin || p.roles.includes(this.rol));
  }

  // ------------------------------------------------------------------
  // Utilidades
  // ------------------------------------------------------------------
  private headers(extra: Record<string, string> = {}): HttpHeaders {
    let cabeceras = new HttpHeaders({ Authorization: `Bearer ${this.auth.getToken()}` });
    if (this.otp) cabeceras = cabeceras.set('X-IRIS-OTP', this.otp);
    Object.entries(extra).forEach(([clave, valor]) => { cabeceras = cabeceras.set(clave, valor); });
    return cabeceras;
  }

  private json(): HttpHeaders { return this.headers({ 'Content-Type': 'application/json' }); }

  private pet(promesa: any, clave: string, alTerminar?: (datos: any) => void): void {
    this.cargando[clave] = true;
    promesa.subscribe({
      next: (datos: any) => {
        this.cargando[clave] = false;
        if (alTerminar) alTerminar(datos);
      },
      error: (err: any) => {
        this.cargando[clave] = false;
        this.fail(err);
      },
    });
  }

  private get(ruta: string, clave: string, alTerminar: (datos: any) => void, params?: Record<string, any>): void {
    const limpios: Record<string, any> = {};
    Object.entries(params || {}).forEach(([claveParametro, valor]) => {
      if (valor !== undefined && valor !== null && valor !== '') limpios[claveParametro] = valor;
    });
    this.pet(this.http.get(`${this.apiBase}${ruta}`, { headers: this.headers(), params: limpios }), clave, alTerminar);
  }

  private mutar(metodo: 'post' | 'put' | 'patch' | 'delete', ruta: string, cuerpo: any, clave: string, exito: string, alTerminar?: (datos: any) => void): void {
    const promesa = metodo === 'delete'
      ? this.http.delete(`${this.apiBase}${ruta}`, { headers: this.headers() })
      : this.http[metodo](`${this.apiBase}${ruta}`, cuerpo, { headers: this.json() });
    this.pet(promesa, clave, (datos) => {
      this.ok(exito);
      if (alTerminar) alTerminar(datos);
    });
  }

  private fail(err: any): void {
    const detalle = err?.error?.detail;
    this.error = typeof detalle === 'string' ? detalle : detalle?.mensaje || err?.message || 'No fue posible completar la operación.';
    this.feedback = '';
  }

  private ok(mensaje: string): void { this.feedback = mensaje; this.error = ''; }

  private prepararFechas(): void {
    const hoy = new Date();
    const iso = (fecha: Date) => fecha.toISOString().slice(0, 10);
    this.formEgreso.fecha = iso(hoy);
    this.formPresupuesto.periodo = iso(hoy).slice(0, 7);
    this.formInforme.desde = iso(new Date(hoy.getTime() - 90 * 86400000));
    this.formInforme.hasta = iso(hoy);
    this.rangoIndicadores.desde = iso(new Date(hoy.getTime() - 90 * 86400000));
    this.rangoIndicadores.hasta = iso(hoy);
    this.fechaDisponibilidad = iso(new Date(hoy.getTime() + 86400000));
    const enDosDias = new Date(hoy.getTime() + 2 * 86400000);
    this.formAsamblea.fecha_inicio = new Date(hoy.getTime() + 86400000).toISOString().slice(0, 16);
    this.formAsamblea.fecha_fin = new Date(enDosDias.getTime() + 3600000).toISOString().slice(0, 16);
    this.formAutorizacion.valido_hasta = enDosDias.toISOString().slice(0, 16);
    this.formCierre.fecha_inicio = new Date(hoy.getTime() + 3 * 86400000).toISOString().slice(0, 16);
    this.formCierre.fecha_fin = new Date(hoy.getTime() + 3 * 86400000 + 7200000).toISOString().slice(0, 16);
  }

  private etiqueta(dato: any, claves: string[]): string {
    for (const clave of claves) {
      const valor = dato?.[clave];
      if (valor !== undefined && valor !== null && valor !== '') return String(valor);
    }
    return '—';
  }

  etiquetaInmueble(inmueble: any): string {
    if (!inmueble) return '—';
    const torre = inmueble.torre ? `${inmueble.torre} · ` : '';
    return `${torre}${inmueble.numero || inmueble.id}`;
  }

  resaltar(dato: any): string {
    if (!dato || typeof dato !== 'object') return String(dato ?? '—');
    return this.etiqueta(dato, ['total_vencido', 'monto', 'total', 'valor', 'estado']);
  }

  abrir(seccion: Seccion): void {
    this.seccion = seccion;
    this.error = '';
    this.feedback = '';
    this.cargarSeccion();
  }

  cargarConjuntos(): void {
    this.pet(this.http.get<any[]>(`${this.apiBase}/conjuntos/`, { headers: this.headers() }), 'conjuntos', (datos) => {
      this.conjuntos = Array.isArray(datos) ? datos : [];
      if (!this.conjuntoId && this.conjuntos.length) this.conjuntoId = this.conjuntos[0].id;
      this.cargarInmuebles();
      this.cargarSeccion();
    });
  }

  cargarInmuebles(): void {
    const ruta = this.esResidente || this.esPortero ? '/v2/my-units' : `/conjuntos/${this.conjuntoId}/inmuebles/`;
    const alterna = this.esPortero ? '/v2/operational-units' : ruta;
    this.pet(this.http.get<any[]>(`${this.apiBase}${alterna}`, { headers: this.headers() }), 'inmuebles', (datos) => {
      this.inmuebles = Array.isArray(datos) ? datos : [];
      if (this.formOrden.inmueble_id === null && this.inmuebles.length) this.formOrden.inmueble_id = this.inmuebles[0].id;
      if (this.formAviso.inmueble_id === null && this.inmuebles.length) this.formAviso.inmueble_id = this.inmuebles[0].id;
      if (this.formAutorizacion.inmueble_id === null && this.inmuebles.length) this.formAutorizacion.inmueble_id = this.inmuebles[0].id;
      if (this.formAccesoVisitante.inmueble_id === null && this.inmuebles.length) this.formAccesoVisitante.inmueble_id = this.inmuebles[0].id;
      if (this.formReserva.inmueble_id === null && this.inmuebles.length) this.formReserva.inmueble_id = this.inmuebles[0].id;
      if (this.formEspera.inmueble_id === null && this.inmuebles.length) this.formEspera.inmueble_id = this.inmuebles[0].id;
      this.cargarCuotas();
    });
  }

  cambiarConjunto(): void { this.cargarInmuebles(); this.cargarSeccion(); }

  /** Refresca el contexto (conjuntos e inmuebles) y la sección activa. */
  actualizar(): void {
    this.error = '';
    if (!this.conjuntoId || !this.conjuntos.length) {
      this.cargarConjuntos();
      return;
    }
    this.cargarSeccion();
  }

  cargarSeccion(): void {
    if (this.esAdmin) {
      if (this.seccion === 'indicadores') this.cargarPanel();
      if (this.seccion === 'operacion') this.cargarOperacion();
    }
    if (this.seccion === 'pagos' && (this.esAdmin || this.esResidente)) this.cargarPagos();
    if (this.seccion === 'avisos') this.cargarAvisos();
    if (this.seccion === 'mantenimiento' && (this.esAdmin || this.esPortero)) this.cargarMantenimiento();
    if (this.seccion === 'visitantes') this.cargarVisitantes();
    if (this.seccion === 'seguridad') this.cargarSeguridad();
    if (this.seccion === 'contabilidad' && this.esAdmin) this.cargarContabilidad();
    if (this.seccion === 'asambleas') this.cargarAsambleas();
    if (this.seccion === 'reservas') this.cargarReservas();
  }

  // ------------------------------------------------------------------
  // Indicadores
  // ------------------------------------------------------------------
  cargarPanel(): void {
    if (!this.esAdmin) return;
    this.get('/v3/indicadores/panel', 'panel', (datos) => { this.panel = datos; },
      { conjunto_id: this.conjuntoId, desde: this.rangoIndicadores.desde, hasta: this.rangoIndicadores.hasta });
  }

  exportarIndicadores(): void {
    this.descargar(`/v3/indicadores/export.xlsx?conjunto_id=${this.conjuntoId}`, 'iris-indicadores.xlsx');
  }

  clavesPanel(dato: any): string[] { return dato && typeof dato === 'object' ? Object.keys(dato).filter((k) => typeof dato[k] !== 'object') : []; }

  valoresPanel(dato: any): any[] {
    return Object.entries(dato || {})
      .filter(([, valor]) => valor === null || ['string', 'number', 'boolean'].includes(typeof valor))
      .map(([clave, valor]) => ({ clave, valor }));
  }

  // ------------------------------------------------------------------
  // Pagos
  // ------------------------------------------------------------------
  cargarPagos(): void {
    this.cargarCuotas();
    if (this.esAdmin) {
      this.get(`/v3/pagos/config`, 'pagoConfig', (datos) => {
        this.pagoConfig = datos;
        this.formPagoConfig = { ...this.formPagoConfig, proveedor: datos.proveedor, modo: datos.modo, moneda: datos.moneda, permite_tarjeta: !!datos.permite_tarjeta, permite_pse: !!datos.permite_pse, permite_nequi: !!datos.permite_nequi, conciliacion_automatica: !!datos.conciliacion_automatica, activo: !!datos.activo };
      }, { conjunto_id: this.conjuntoId });
      this.get('/v3/pagos/transacciones', 'pagoTransacciones', (datos) => { this.pagoTransacciones = datos?.items || []; }, { conjunto_id: this.conjuntoId });
      this.get('/v3/pagos/resumen', 'pagoResumen', (datos) => { this.pagoResumen = datos; }, { conjunto_id: this.conjuntoId });
      this.get('/v3/pagos/eventos', 'pagoEventos', (datos) => { this.pagoEventos = Array.isArray(datos) ? datos : []; }, { conjunto_id: this.conjuntoId });
    }
    this.get('/v3/pagos/proveedores', 'proveedoresPasarela', (datos) => { this.proveedoresPasarela = Array.isArray(datos) ? datos : datos?.proveedores || []; });
    this.get(`/v3/pagos/metodos`, 'pagoMetodos', (datos) => { this.pagoMetodos = datos; }, { conjunto_id: this.conjuntoId });
  }

  cargarCuotas(): void {
    this.get('/cuotas/', 'cuotas', (datos) => {
      const lista = Array.isArray(datos) ? datos : [];
      this.cuotas = this.esResidente && this.inmuebles.length
        ? lista.filter((c: any) => this.inmuebles.some((u: any) => u.id === c.inmueble_id))
        : lista;
      if (!this.formCheckout.cuota_id && this.cuotas.length) this.formCheckout.cuota_id = this.cuotas[0].id;
    });
  }

  guardarPagoConfig(): void {
    this.mutar('put', '/v3/pagos/config', { ...this.formPagoConfig, conjunto_id: this.conjuntoId }, 'pagoConfig',
      'Configuración de la pasarela guardada.', () => this.cargarPagos());
  }

  pagarEnLinea(): void {
    if (!this.formCheckout.cuota_id) { this.error = 'Selecciona la cuota que vas a pagar.'; return; }
    this.pet(this.http.post(`${this.apiBase}/v3/pagos/checkout`, { cuota_id: this.formCheckout.cuota_id, metodo: this.formCheckout.metodo }, { headers: this.json() }), 'pagoCheckout', (datos: any) => {
      this.pet(this.http.post(`${this.apiBase}/v3/pagos/cobrar`, { transaccion_id: datos.transaccion_id, token: this.formCheckout.token }, { headers: this.json() }), 'pagoCobro', (cobro: any) => {
        this.ok(`Pago ${cobro.estado}. ${cobro.conciliacion?.conciliada ? 'Conciliado automáticamente.' : cobro.mensaje || ''}`);
        this.cargarPagos();
      });
    });
  }

  conciliarTransaccion(id: number): void {
    this.mutar('post', `/v3/pagos/transacciones/${id}/conciliar`, {}, 'pagoConciliar', 'Transacción conciliada.', () => this.cargarPagos());
  }

  conciliarLote(): void {
    this.mutar('post', '/v3/pagos/conciliacion/ejecutar', { conjunto_id: this.conjuntoId }, 'pagoLote',
      'Conciliación en lote ejecutada.', () => this.cargarPagos());
  }

  comprobante(id: number): void { this.abrirDocumento(`/v3/pagos/transacciones/${id}/comprobante`); }

  // ------------------------------------------------------------------
  // Avisos
  // ------------------------------------------------------------------
  cargarAvisos(): void {
    this.get('/v3/avisos/consentimientos', 'consentimientos', (datos) => { this.consentimientos = Array.isArray(datos) ? datos : []; });
    this.get('/v3/avisos/eventos', 'eventosAviso', (datos) => { this.eventosAviso = datos?.eventos || []; });
    if (this.esAdmin) {
      this.get('/v3/avisos/plantillas', 'plantillas', (datos) => { this.plantillas = Array.isArray(datos) ? datos : []; }, { conjunto_id: this.conjuntoId });
      this.get('/v3/avisos/bitacora', 'bitacora', (datos) => { this.bitacora = Array.isArray(datos) ? datos : []; }, { conjunto_id: this.conjuntoId });
      this.get('/v3/avisos/estado-consentimientos', 'estadoConsentimientos', (datos) => {
        this.estadoConsentimientos = datos ? [datos] : [];
      }, { conjunto_id: this.conjuntoId });
    } else {
      this.cargarMisAvisos();
    }
  }

  cargarMisAvisos(): void {
    this.get('/v3/avisos/mis-avisos', 'misAvisos', (datos) => { this.misAvisos = Array.isArray(datos) ? datos : []; });
  }

  /** Cualquier usuario puede otorgar o revocar su propio consentimiento de avisos. */
  consentimientoPropio(): boolean { return true; }

  otorgarConsentimiento(): void {
    this.mutar('post', '/v3/avisos/consentimientos', this.formConsentimiento, 'consentimientos',
      'Consentimiento registrado.', () => this.cargarAvisos());
  }

  revocarConsentimiento(id: number): void {
    this.mutar('delete', `/v3/avisos/consentimientos/${id}`, {}, 'consentimientos',
      'Consentimiento revocado: no se enviarán más avisos externos por ese canal.', () => this.cargarAvisos());
  }

  instalarPlantillas(): void {
    this.mutar('post', '/v3/avisos/plantillas/instalar-sugeridas', { conjunto_id: this.conjuntoId }, 'plantillas',
      'Plantillas sugeridas instaladas.', () => this.cargarAvisos());
  }

  guardarPlantilla(plantilla: any): void {
    this.mutar('put', `/v3/avisos/plantillas/${plantilla.id}`, plantilla, 'plantillas', 'Plantilla actualizada.', () => this.cargarAvisos());
  }

  enviarAviso(): void {
    this.mutar('post', '/v3/avisos/enviar', { ...this.formAviso, conjunto_id: this.conjuntoId }, 'aviso',
      'Aviso procesado.', (datos: any) => {
        const primero = datos?.resultados?.[0];
        if (primero && !primero.enviado) this.error = `No se envió: ${primero.estado}${primero.motivo ? ` (${primero.motivo})` : ''}`;
        this.cargarAvisos();
      });
  }

  ejecutarVencimientos(): void {
    this.mutar('post', '/v3/avisos/vencimientos/ejecutar', { conjunto_id: this.conjuntoId, dias_anticipacion: 5 }, 'vencimientos',
      'Avisos de vencimiento procesados.', () => this.cargarAvisos());
  }

  // ------------------------------------------------------------------
  // Mantenimiento
  // ------------------------------------------------------------------
  cargarMantenimiento(): void {
    this.get('/v3/mantenimiento/proveedores', 'proveedores', (datos) => { this.proveedores = Array.isArray(datos) ? datos : []; }, { conjunto_id: this.conjuntoId });
    const filtrosOrdenes: Record<string, any> = { conjunto_id: this.conjuntoId };
    if (this.filtroOrden) filtrosOrdenes['estado'] = this.filtroOrden;
    this.get('/v3/mantenimiento/ordenes', 'ordenes', (datos) => { this.ordenes = Array.isArray(datos) ? datos : []; }, filtrosOrdenes);
    if (this.esAdmin) {
      this.get('/v3/mantenimiento/vencidas', 'ordenesVencidas', (datos) => { this.ordenesVencidas = Array.isArray(datos) ? datos : []; });
      this.get('/v3/mantenimiento/resumen', 'mantResumen', (datos) => { this.mantResumen = datos; }, { conjunto_id: this.conjuntoId });
    }
  }

  crearProveedor(): void {
    this.mutar('post', '/v3/mantenimiento/proveedores', { ...this.formProveedor, conjunto_id: this.conjuntoId }, 'proveedores',
      'Proveedor registrado.', () => this.cargarMantenimiento());
  }

  crearOrden(): void {
    this.mutar('post', '/v3/mantenimiento/ordenes', { ...this.formOrden, conjunto_id: this.conjuntoId }, 'ordenes',
      'Orden de mantenimiento creada.', () => this.cargarMantenimiento());
  }

  abrirOrden(id: number): void {
    this.get(`/v3/mantenimiento/ordenes/${id}`, 'ordenDetalle', (datos) => { this.ordenDetalle = datos; });
  }

  seleccionarCotizacion(id: number): void {
    this.mutar('patch', `/v3/mantenimiento/cotizaciones/${id}`, { accion: 'seleccionar' }, 'ordenDetalle',
      'Cotización seleccionada.', (datos: any) => { if (this.ordenDetalle) this.abrirOrden(this.ordenDetalle.id); });
  }

  crearCotizacion(): void {
    if (!this.ordenDetalle) return;
    this.mutar('post', `/v3/mantenimiento/ordenes/${this.ordenDetalle.id}/cotizaciones`, this.formCotizacion, 'ordenDetalle',
      'Cotización registrada.', () => { this.abrirOrden(this.ordenDetalle.id); this.cargarMantenimiento(); });
  }

  aprobarCotizacion(id: number, decision: 'aprobada' | 'rechazada'): void {
    const nota = window.prompt(decision === 'aprobada' ? 'Nota de aprobación (opcional):' : 'Motivo del rechazo (opcional):') || '';
    this.mutar('patch', `/v3/mantenimiento/cotizaciones/${id}/aprobacion`, { decision, nota }, 'ordenDetalle',
      decision === 'aprobada' ? 'Gasto aprobado; ahora se puede seleccionar la cotización.' : 'Gasto rechazado.',
      () => { if (this.ordenDetalle) this.abrirOrden(this.ordenDetalle.id); });
  }

  agregarAvance(): void {
    if (!this.ordenDetalle) return;
    this.mutar('post', `/v3/mantenimiento/ordenes/${this.ordenDetalle.id}/avances`, this.formAvance, 'ordenDetalle',
      'Avance registrado.', () => { this.abrirOrden(this.ordenDetalle.id); this.cargarMantenimiento(); });
  }

  actualizarOrden(): void {
    if (!this.ordenDetalle) return;
    this.mutar('patch', `/v3/mantenimiento/ordenes/${this.ordenDetalle.id}`, this.formCierreOrden, 'ordenDetalle',
      'Orden actualizada.', () => { this.abrirOrden(this.ordenDetalle.id); this.cargarMantenimiento(); });
  }

  subirEvidencia(tipo: 'evidencias' | 'soportes'): void {
    const archivo = tipo === 'evidencias' ? this.archivoEvidencia : this.archivoSoporte;
    if (!archivo || !this.ordenDetalle) { this.error = 'Elige el archivo que vas a adjuntar.'; return; }
    const datos = new FormData();
    datos.append('file', archivo);
    this.pet(this.http.post(`${this.apiBase}/v3/mantenimiento/ordenes/${this.ordenDetalle.id}/${tipo}`, datos, { headers: this.headers() }), 'evidencia', () => {
      this.ok('Archivo adjuntado.');
      this.archivoEvidencia = null;
      this.archivoSoporte = null;
      this.abrirOrden(this.ordenDetalle.id);
    });
  }

  elegirArchivo(evento: any, destino: 'evidencia' | 'soporte'): void {
    const archivo = evento?.target?.files?.[0] || null;
    if (destino === 'evidencia') this.archivoEvidencia = archivo;
    else this.archivoSoporte = archivo;
  }

  verAdjunto(url: string): void { this.abrirDocumento(url.replace(/^\/v3/, '/v3')); }

  exportarMantenimiento(): void {
    this.descargar(`/v3/mantenimiento/export.xlsx?conjunto_id=${this.conjuntoId}`, 'iris-mantenimiento.xlsx');
  }

  // ------------------------------------------------------------------
  // Visitantes
  // ------------------------------------------------------------------
  cargarVisitantes(): void {
    this.get('/v3/visitantes/autorizaciones', 'autorizaciones', (datos) => { this.autorizaciones = Array.isArray(datos) ? datos : []; });
    this.get('/v3/visitantes/directorio', 'directorio', (datos) => { this.directorio = Array.isArray(datos) ? datos : []; }, { conjunto_id: this.conjuntoId });
    if (this.esAdmin || this.esPortero) {
      this.get('/v3/visitantes/accesos', 'accesos', (datos) => { this.accesos = Array.isArray(datos) ? datos : []; }, { conjunto_id: this.conjuntoId });
      this.get('/v3/visitantes/en-sitio', 'visitantesEnSitio', (datos) => { this.visitantesEnSitio = Array.isArray(datos) ? datos : []; }, { conjunto_id: this.conjuntoId });
      this.get('/v3/visitantes/resumen', 'visitResumen', (datos) => { this.visitResumen = datos; }, { conjunto_id: this.conjuntoId });
    }
  }

  crearAutorizacion(): void {
    this.mutar('post', '/v3/visitantes/autorizaciones', this.formAutorizacion, 'autorizaciones',
      'Visita autorizada.', () => this.cargarVisitantes());
  }

  cancelarAutorizacion(id: number): void {
    this.mutar('delete', `/v3/visitantes/autorizaciones/${id}`, {}, 'autorizaciones', 'Autorización cancelada.', () => this.cargarVisitantes());
  }

  registrarIngreso(): void {
    this.mutar('post', '/v3/visitantes/accesos', this.formAccesoVisitante, 'accesos',
      'Ingreso registrado y alerta enviada al residente.', () => this.cargarVisitantes());
  }

  registrarSalida(id: number): void {
    this.mutar('patch', `/v3/visitantes/accesos/${id}/salida`, { observacion: 'Salida registrada en portería' }, 'accesos',
      'Salida registrada.', () => this.cargarVisitantes());
  }

  // ------------------------------------------------------------------
  // Seguridad
  // ------------------------------------------------------------------
  cargarSeguridad(): void {
    this.get('/v3/seguridad/estado', 'segEstado', (datos) => { this.segEstado = datos; });
    this.get('/v3/seguridad/sesiones', 'sesiones', (datos) => { this.sesiones = Array.isArray(datos) ? datos : []; });
    this.get('/v3/seguridad/privacidad', 'privacidad', (datos) => {
      this.privacidad = datos;
      this.formPolitica.texto_privacidad = datos?.texto || this.formPolitica.texto_privacidad;
      const retencion = datos?.retencion || {};
      this.formPolitica.dias_retencion_auditoria = retencion.auditoria_dias ?? this.formPolitica.dias_retencion_auditoria;
      this.formPolitica.dias_retencion_accesos = retencion.accesos_dias ?? this.formPolitica.dias_retencion_accesos;
      this.formPolitica.dias_retencion_avisos = retencion.avisos_dias ?? this.formPolitica.dias_retencion_avisos;
    });
    this.get('/v3/seguridad/politica', 'politica', (datos) => { this.politica = datos; }, { conjunto_id: this.conjuntoId });
    if (this.esAdmin) {
      this.get('/v3/seguridad/intentos', 'intentos', (datos) => { this.intentos = Array.isArray(datos) ? datos : []; });
    }
  }

  iniciar2fa(): void {
    this.pet(this.http.post(`${this.apiBase}/v3/seguridad/2fa/iniciar`, {}, { headers: this.json() }), 'setup2fa',
      (datos: any) => {
        this.setup2fa = datos;
        this.ok('Escanea el código en tu aplicación de autenticación y confirma con un código de 6 dígitos.');
      });
  }

  confirmar2fa(): void {
    this.pet(this.http.post(`${this.apiBase}/v3/seguridad/2fa/confirmar`, { codigo: this.form2fa.codigo }, { headers: this.json() }), 'confirmar2fa', (datos: any) => {
      this.codigosRecuperacion = datos?.codigos_recuperacion || [];
      this.ok('Segundo factor activado. Guarda tus códigos de recuperación.');
      this.cargarSeguridad();
    });
  }

  verificar2fa(): void {
    this.pet(this.http.post(`${this.apiBase}/v3/seguridad/2fa/verificar`, { codigo: this.form2fa.codigo }, { headers: this.json() }), 'verificar2fa',
      () => { this.otp = String(this.form2fa.codigo || '').trim(); this.ok('Código válido: se enviará en las operaciones sensibles.'); });
  }

  desactivar2fa(): void {
    this.mutar('delete', '/v3/seguridad/2fa', {}, 'desactivar2fa', 'Segundo factor desactivado.', () => this.cargarSeguridad());
  }

  revocarSesion(id: number): void {
    this.mutar('delete', `/v3/seguridad/sesiones/${id}`, {}, 'sesiones', 'Sesión cerrada.', () => this.cargarSeguridad());
  }

  revocarTodas(): void {
    this.mutar('delete', '/v3/seguridad/sesiones', {}, 'sesiones', 'Todas las sesiones cerradas. Vuelve a iniciar sesión.', () => {
      this.cargarSeguridad();
    });
  }

  guardarPolitica(): void {
    this.mutar('put', '/v3/seguridad/politica', { ...this.formPolitica, conjunto_id: this.conjuntoId }, 'politica',
      'Política de retención y privacidad guardada.', () => this.cargarSeguridad());
  }

  purgar(simulacion: boolean): void {
    this.mutar('post', '/v3/seguridad/politica/purgar', { conjunto_id: this.conjuntoId, simulacion }, 'purga',
      simulacion ? 'Simulación de depuración calculada.' : 'Depuración aplicada según la política.',
      (datos: any) => { this.purgaSimulada = datos; });
  }

  solicitarDatos(): void {
    this.mutar('post', '/v3/seguridad/privacidad/solicitud', this.formSolicitudDatos, 'solicitud',
      'Solicitud radicada ante la administración.');
  }

  // ------------------------------------------------------------------
  // Contabilidad
  // ------------------------------------------------------------------
  cargarContabilidad(): void {
    this.get('/v3/contabilidad/egresos', 'egresos', (datos) => { this.egresos = Array.isArray(datos) ? datos : []; }, { conjunto_id: this.conjuntoId });
    this.get('/v3/contabilidad/presupuestos', 'presupuestos', (datos) => { this.presupuestos = Array.isArray(datos) ? datos : []; }, { conjunto_id: this.conjuntoId });
    this.get('/v3/contabilidad/config-cartera', 'carteraConfig', (datos) => {
      this.carteraConfig = datos;
      this.formCarteraConfig = {
        interes_moratorio_diario: String(datos?.interes_moratorio_diario ?? '0'),
        tasa_mora_mensual: String(datos?.tasa_mora_mensual ?? '0'),
        recargo_fijo: Number(datos?.recargo_fijo ?? 0),
        dias_gracia: Number(datos?.dias_gracia ?? 0),
        activo: !!datos?.activo,
      };
    }, { conjunto_id: this.conjuntoId });
    this.get('/v3/contabilidad/cartera', 'cartera', (datos) => { this.cartera = datos; }, { conjunto_id: this.conjuntoId });
    this.get('/v3/contabilidad/movimientos', 'movimientos', (datos) => { this.movimientos = Array.isArray(datos) ? datos : []; }, { conjunto_id: this.conjuntoId });
  }

  crearEgreso(): void {
    this.mutar('post', '/v3/contabilidad/egresos', { ...this.formEgreso, conjunto_id: this.conjuntoId }, 'egresos',
      'Egreso registrado.', () => this.cargarContabilidad());
  }

  borrarEgreso(id: number): void {
    this.mutar('delete', `/v3/contabilidad/egresos/${id}`, {}, 'egresos', 'Egreso eliminado.', () => this.cargarContabilidad());
  }

  guardarPresupuesto(): void {
    this.mutar('post', '/v3/contabilidad/presupuestos', { ...this.formPresupuesto, conjunto_id: this.conjuntoId }, 'presupuestos',
      'Presupuesto guardado.', () => this.cargarContabilidad());
  }

  guardarCarteraConfig(): void {
    this.mutar('put', '/v3/contabilidad/config-cartera', { ...this.formCarteraConfig, conjunto_id: this.conjuntoId }, 'carteraConfig',
      'Parámetros de cartera guardados.', () => this.cargarContabilidad());
  }

  calcularMora(): void {
    this.mutar('post', '/v3/contabilidad/cartera/calcular-mora', { conjunto_id: this.conjuntoId }, 'mora',
      'Intereses y recargos calculados.', (datos: any) => { this.moraResultado = datos; this.cargarContabilidad(); });
  }

  importarExtracto(): void {
    if (!this.archivoExtracto) { this.error = 'Selecciona el archivo del extracto (.csv o .xlsx).'; return; }
    const datos = new FormData();
    datos.append('file', this.archivoExtracto);
    this.pet(this.http.post(`${this.apiBase}/v3/contabilidad/extracto/importar`, datos, { headers: this.headers(), params: { conjunto_id: String(this.conjuntoId) } }), 'extracto',
      (respuesta: any) => {
        this.ok(`Extracto importado: ${respuesta.movimientos_creados} movimientos.`);
        this.cargarContabilidad();
      });
  }

  elegirExtracto(evento: any): void { this.archivoExtracto = evento?.target?.files?.[0] || null; }

  conciliarBancaria(): void {
    this.mutar('post', '/v3/contabilidad/conciliar-bancaria', { conjunto_id: this.conjuntoId, dias_tolerancia: 5 }, 'conciliacion',
      'Conciliación bancaria ejecutada.', () => this.cargarContabilidad());
  }

  generarInforme(): void {
    this.get('/v3/contabilidad/informes/periodo', 'informe', (datos) => { this.informe = datos; },
      { conjunto_id: this.conjuntoId, desde: this.formInforme.desde, hasta: this.formInforme.hasta });
  }

  exportarContabilidad(tipo: 'cartera' | 'egresos'): void {
    this.descargar(`/v3/contabilidad/export/${tipo}.xlsx?conjunto_id=${this.conjuntoId}`, `iris-${tipo}.xlsx`);
  }

  // ------------------------------------------------------------------
  // Asambleas
  // ------------------------------------------------------------------
  cargarAsambleas(): void {
    const filtros = this.esAdmin ? { conjunto_id: this.conjuntoId } : {};
    this.get('/v3/asambleas', 'asambleas', (datos) => {
      this.asambleas = Array.isArray(datos) ? datos : [];
      if (this.asambleaDetalle) {
        const actual = this.asambleas.find((a: any) => a.id === this.asambleaDetalle.id);
        if (!actual) this.asambleaDetalle = null;
      }
    }, filtros);
  }

  crearAsamblea(): void {
    this.mutar('post', '/v3/asambleas', {
      ...this.formAsamblea,
      conjunto_id: this.conjuntoId,
      fecha_inicio: this.formAsamblea.fecha_inicio,
      fecha_fin: this.formAsamblea.fecha_fin,
    }, 'asambleas', 'Asamblea creada.', () => this.cargarAsambleas());
  }

  abrirAsamblea(id: number): void {
    this.get(`/v3/asambleas/${id}`, 'asambleaDetalle', (datos) => { this.asambleaDetalle = datos; });
  }

  cambiarEstadoAsamblea(estado: string): void {
    if (!this.asambleaDetalle) return;
    this.mutar('patch', `/v3/asambleas/${this.asambleaDetalle.id}`, { estado }, 'asambleaDetalle',
      `Asamblea en estado ${estado}.`, () => { this.abrirAsamblea(this.asambleaDetalle.id); this.cargarAsambleas(); });
  }

  convocarAsamblea(): void {
    if (!this.asambleaDetalle) return;
    this.mutar('post', `/v3/asambleas/${this.asambleaDetalle.id}/convocar`, {}, 'convocatoria',
      'Convocatoria enviada a los residentes.', () => this.abrirAsamblea(this.asambleaDetalle.id));
  }

  registrarAsistencia(): void {
    if (!this.asambleaDetalle) return;
    this.mutar('post', `/v3/asambleas/${this.asambleaDetalle.id}/asistencia`, {}, 'asistencia',
      'Asistencia registrada.', () => this.abrirAsamblea(this.asambleaDetalle.id));
  }

  crearVotacion(): void {
    if (!this.asambleaDetalle) return;
    const opciones = String(this.formVotacion.opcionesTexto || '').split(',').map((o) => o.trim()).filter(Boolean);
    this.mutar('post', `/v3/asambleas/${this.asambleaDetalle.id}/votaciones`, {
      titulo: this.formVotacion.titulo,
      tipo: this.formVotacion.tipo,
      mayoria: this.formVotacion.mayoria,
      permite_abstencion: this.formVotacion.permite_abstencion,
      opciones,
    }, 'votacion', 'Votación creada.', () => this.abrirAsamblea(this.asambleaDetalle.id));
  }

  cambiarEstadoVotacion(id: number, estado: string): void {
    this.mutar('patch', `/v3/asambleas/votaciones/${id}`, { estado }, 'votacion',
      `Votación ${estado}.`, () => { if (this.asambleaDetalle) this.abrirAsamblea(this.asambleaDetalle.id); });
  }

  votar(votacionId: number, opcion: string): void {
    this.mutar('post', `/v3/asambleas/votaciones/${votacionId}/votar`, { opcion }, 'voto',
      'Voto registrado.', () => { if (this.asambleaDetalle) this.abrirAsamblea(this.asambleaDetalle.id); });
  }

  generarActa(): void {
    if (!this.asambleaDetalle) return;
    this.mutar('post', `/v3/asambleas/${this.asambleaDetalle.id}/acta/generar`, {}, 'acta',
      'Acta generada.', (datos: any) => { this.acta = datos?.acta || ''; this.abrirAsamblea(this.asambleaDetalle.id); });
  }

  verActa(): void {
    if (!this.asambleaDetalle) return;
    this.abrirDocumento(`/v3/asambleas/${this.asambleaDetalle.id}/acta`);
  }

  // ------------------------------------------------------------------
  // Reservas avanzadas
  // ------------------------------------------------------------------
  cargarReservas(): void {
    // Los residentes obtienen sus zonas y cierres a partir de sus inmuebles: no envían conjunto_id.
    const ctx: Record<string, any> = (this.esAdmin || this.esPortero) ? { conjunto_id: this.conjuntoId } : {};
    this.get('/v3/reservas/reglas', 'reglasZonas', (datos) => {
      this.reglasZonas = Array.isArray(datos) ? datos : [];
      if (!this.zonaId && this.reglasZonas.length) {
        this.zonaId = this.reglasZonas[0].zona_id;
        this.cargarReglaZona();
      }
    }, ctx);
    this.get('/v3/reservas/resumen', 'reservasResumen', (datos) => { this.reservasResumen = datos; }, ctx);
    this.get('/v3/reservas/cargos', 'cargosReserva', (datos) => { this.cargosReserva = Array.isArray(datos) ? datos : []; }, ctx);
    this.get('/v3/reservas/lista-espera', 'esperas', (datos) => { this.esperas = Array.isArray(datos) ? datos : []; }, ctx);
    this.get('/v3/reservas/cierres', 'cierres', (datos) => { this.cierres = Array.isArray(datos) ? datos : []; }, ctx);
  }

  cargarReglaZona(): void {
    if (!this.zonaId) return;
    this.get(`/v3/reservas/reglas/${this.zonaId}`, 'reglaZona', (datos) => { this.reglaZona = datos; });
    this.verDisponibilidad();
  }

  guardarRegla(): void {
    if (!this.zonaId || !this.reglaZona) return;
    this.mutar('put', `/v3/reservas/reglas/${this.zonaId}`, this.reglaZona, 'reglaZona',
      'Reglas de la zona guardadas.', () => { this.cargarReglaZona(); this.cargarReservas(); });
  }

  verDisponibilidad(): void {
    if (!this.zonaId) return;
    this.get('/v3/reservas/disponibilidad', 'disponibilidad', (datos) => { this.disponibilidad = datos; },
      { zona_id: this.zonaId, fecha: this.fechaDisponibilidad });
  }

  solicitarReserva(franja: any): void {
    if (!this.zonaId || !this.formReserva.inmueble_id) { this.error = 'Selecciona la zona y el inmueble.'; return; }
    this.mutar('post', '/v3/reservas/solicitar', {
      zona_id: this.zonaId, inmueble_id: this.formReserva.inmueble_id,
      fecha_inicio: franja?.inicio || this.formReserva.inicio,
      fecha_fin: franja?.fin || this.formReserva.fin,
    }, 'reserva', 'Reserva solicitada.', () => { this.verDisponibilidad(); this.cargarReservas(); });
  }

  cancelarReserva(id: number): void {
    this.mutar('post', `/v3/reservas/${id}/cancelar`, {}, 'reserva',
      'Reserva cancelada.', (datos: any) => {
        if (datos?.lista_espera_promovida) this.ok(`Reserva cancelada y lista de espera promovida (reserva #${datos.lista_espera_promovida.reserva_id}).`);
        this.verDisponibilidad();
        this.cargarReservas();
      });
  }

  entrarEspera(): void {
    if (!this.zonaId) return;
    this.mutar('post', '/v3/reservas/lista-espera', {
      zona_id: this.zonaId, inmueble_id: this.formEspera.inmueble_id,
      fecha_inicio: this.formEspera.inicio, fecha_fin: this.formEspera.fin,
    }, 'espera', 'Solicitud añadida a la lista de espera.', () => this.cargarReservas());
  }

  salirEspera(id: number): void {
    this.mutar('delete', `/v3/reservas/lista-espera/${id}`, {}, 'espera', 'Solicitud retirada de la lista de espera.', () => this.cargarReservas());
  }

  crearCierre(): void {
    if (!this.zonaId) return;
    this.mutar('post', '/v3/reservas/cierres', { zona_id: this.zonaId, ...this.formCierre }, 'cierre',
      'Cierre registrado y reservas afectadas canceladas.', () => { this.cargarReservas(); this.verDisponibilidad(); });
  }

  borrarCierre(id: number): void {
    this.mutar('delete', `/v3/reservas/cierres/${id}`, {}, 'cierre', 'Cierre eliminado.', () => this.cargarReservas());
  }

  marcarAsistencia(id: number, asistio: boolean): void {
    this.mutar('post', `/v3/reservas/${id}/asistencia`, { asistio }, 'asistenciaReserva',
      asistio ? 'Asistencia registrada.' : 'Inasistencia registrada; se aplicó la penalización si estaba configurada.',
      () => this.cargarReservas());
  }

  cambiarEstadoReserva(id: number, estado: string): void {
    this.mutar('patch', `/v3/reservas/${id}/estado`, { estado }, 'reserva', `Reserva ${estado}.`, () => this.cargarReservas());
  }

  // ------------------------------------------------------------------
  // Operación
  // ------------------------------------------------------------------
  cargarOperacion(): void {
    this.get('/v3/admin/estado-sistema', 'estadoSistema', (datos) => { this.estadoSistema = datos; });
    this.get('/v3/admin/checklist-produccion', 'checklist', (datos) => { this.checklist = datos; });
    this.get('/v3/admin/respaldos', 'respaldos', (datos) => { this.respaldos = Array.isArray(datos) ? datos : []; });
  }

  crearConjuntoGuiado(): void {
    if (!this.esSuperAdmin) { this.error = 'Solo superadministración puede crear conjuntos.'; return; }
    const nombre = String(this.altaConjunto.nombre || '').trim();
    const nit = String(this.altaConjunto.nit || '').trim();
    const direccion = String(this.altaConjunto.direccion || '').trim();
    const zonas = String(this.altaConjunto.zonas || '').split(/[\n,;]+/).map((x: string) => x.trim()).filter(Boolean);
    if (!nombre || !nit || !direccion) { this.error = 'Completa nombre, NIT y dirección.'; return; }
    this.error = ''; this.feedback = ''; this.cargando['asistente'] = true;
    this.http.post<any>(`${this.apiBase}/conjuntos/`, { nombre, nit, direccion }, { headers: this.json() }).subscribe({
      next: grupo => {
        this.altaConjuntoCreado = grupo;
        let indice = 0;
        const crearSiguiente = () => {
          if (indice >= zonas.length) {
            this.cargando['asistente'] = false;
            this.ok(`Conjunto creado con ${zonas.length} zona(s). Continúa con inmuebles/residentes y reglas.`);
            this.conjuntoId = grupo.id;
            this.altaConjunto = { nombre: '', nit: '', direccion: '', zonas: '' };
            this.cargarConjuntos(); this.cargarOperacion();
            return;
          }
          const zona = zonas[indice++];
          this.http.post(`${this.apiBase}/conjuntos/${grupo.id}/zonas-comunes`, {
            nombre: zona, requiere_aprobacion: true, hora_apertura: '06:00', hora_cierre: '22:00',
            duracion_max_minutos: 240, max_dias_anticipacion: 30, max_reservas_dia_inmueble: 2,
          }, { headers: this.json() }).subscribe({ next: crearSiguiente, error: err => {
            this.cargando['asistente'] = false; this.conjuntoId = grupo.id; this.cargarConjuntos();
            this.fail(err); this.feedback = `El conjunto #${grupo.id} ya fue creado. Se alcanzaron a crear ${indice - 1} zona(s); añade las restantes desde Gestión.`;
          } });
        };
        crearSiguiente();
      },
      error: err => { this.cargando['asistente'] = false; this.fail(err); },
    });
  }

  descargarPlantillaResidentes(): void { this.descargar('/v2/import/template/residents', 'plantilla-residentes.xlsx'); }

  crearRespaldo(): void {
    this.mutar('post', '/v3/admin/respaldos', {}, 'respaldos', 'Respaldo generado.', () => this.cargarOperacion());
  }

  verificarRespaldo(id: number): void {
    this.mutar('post', `/v3/admin/respaldos/${id}/verificar`, {}, 'respaldos',
      'Prueba de restauración ejecutada.', () => this.cargarOperacion());
  }

  descargarRespaldo(id: number, nombre: string): void {
    this.descargar(`/v3/admin/respaldos/${id}/descargar`, nombre || 'iris-respaldo');
  }

  descargarBackup(): void { this.descargar('/v3/admin/backup', 'iris-backup.db'); }
  descargarAdjuntos(): void { this.descargar('/v3/admin/adjuntos/paquete', 'iris-adjuntos.tar.gz'); }

  // ------------------------------------------------------------------
  // Descargas
  // ------------------------------------------------------------------
  private descargar(ruta: string, nombre: string): void {
    this.http.get(`${this.apiBase}${ruta}`, { headers: this.headers(), responseType: 'blob' }).subscribe({
      next: (blob: Blob) => {
        const url = URL.createObjectURL(blob);
        const enlace = document.createElement('a');
        enlace.href = url;
        enlace.download = nombre.includes('.') ? nombre : `${nombre}.xlsx`;
        enlace.click();
        URL.revokeObjectURL(url);
        this.ok(`Descarga iniciada: ${enlace.download}`);
      },
      error: (err) => this.fail(err),
    });
  }

  private abrirDocumento(ruta: string): void {
    this.http.get(`${this.apiBase}${ruta}`, { headers: this.headers(), responseType: 'blob' }).subscribe({
      next: (blob: Blob) => {
        const url = URL.createObjectURL(blob);
        const ventana = window.open('', '_blank');
        if (ventana && blob.type.includes('html')) {
          ventana.document.write(`<iframe src="${url}" style="border:0;width:100%;height:100vh"></iframe>`);
          ventana.document.close();
        } else if (ventana) {
          ventana.location.href = url;
        } else {
          this.error = 'Habilita las ventanas emergentes para ver el documento.';
        }
      },
      error: (err) => this.fail(err),
    });
  }
}
