import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { irisApiBase } from '../../services/api-url';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-contador',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './contador.component.html',
  styleUrls: ['./contador.component.css'],
})
export class ContadorComponent implements OnInit {
  conjuntos: any[] = [];
  conjuntoId: number | null = null;
  inmuebles: any[] = [];
  cuotas: any[] = [];
  pagos: any[] = [];
  egresos: any[] = [];
  presupuestos: any[] = [];
  cartera: any = null;
  informe: any = null;
  loading = false;
  saving = false;
  error = '';
  success = '';
  metodoPago = 'efectivo';
  referenciaPago = '';
  cuota = { inmueble_id: null as number | null, concepto: 'Cuota de administración', periodo: '', monto: '', fecha_vencimiento: '' };
  egresoEditId: number | null = null;
  egreso = { concepto: '', categoria: 'general', monto: '', fecha: '' };
  presupuesto = { periodo: '', categoria: 'general', monto_presupuestado: '', notas: '' };
  desde = '';
  hasta = '';

  // Módulos de trabajo profesional del contador.
  puc: any[] = [];
  asientos: any[] = [];
  estadoFinanciero: any = null;
  cuentasPagar: any[] = [];
  fondos: any[] = [];
  documentos: any[] = [];
  auditoria: any[] = [];
  estadoTributario: any = null;
  ejecucion: any[] = [];
  periodoTrabajo = '';
  buscarPagos = '';
  buscarCuotas = '';
  buscarEgresos = '';
  buscarAsientos = '';
  lote = { periodo: '', concepto: 'Administración', monto: '', fecha_vencimiento: '' };
  asientoManual = { fecha: '', descripcion: '', cuentaDebito: '1110', cuentaCredito: '4170', monto: '' };
  proveedorFactura = { proveedor: '', documento: '', concepto: '', fecha_documento: '', fecha_vencimiento: '', monto: '' };
  documentoContable = { tipo: 'soporte_gasto', numero: '', fecha: '', tercero: '', descripcion: '', valor: '' };
  baseFondo = '';
  cuentaPUC = { codigo: '', nombre: '', clase: 'activo', naturaleza: 'debito' };

  private readonly base = String(irisApiBase()).replace(/\/+$/, '');
  private get headers(): HttpHeaders {
    return new HttpHeaders({ Authorization: `Bearer ${this.auth.getToken() || ''}` });
  }

  constructor(private http: HttpClient, private auth: AuthService) {}

  ngOnInit(): void {
    const now = new Date();
    const mes = String(now.getMonth() + 1).padStart(2, '0');
    const hoy = `${now.getFullYear()}-${mes}-${String(now.getDate()).padStart(2, '0')}`;
    const finDeMes = `${now.getFullYear()}-${mes}-${String(new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()).padStart(2, '0')}`;
    this.desde = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`;
    this.hasta = hoy;
    this.periodoTrabajo = this.hasta.slice(0, 7);
    this.lote.periodo = this.periodoTrabajo;
    this.lote.fecha_vencimiento = finDeMes;
    this.cuota.periodo = this.periodoTrabajo;
    this.cuota.fecha_vencimiento = finDeMes;
    this.egreso.fecha = hoy;
    this.presupuesto.periodo = this.periodoTrabajo;
    this.asientoManual.fecha = this.hasta;
    this.documentoContable.fecha = this.hasta;
    this.http.get<any[]>(`${this.base}/conjuntos/`, { headers: this.headers }).subscribe({
      next: (rows) => {
        this.conjuntos = rows || [];
        this.conjuntoId = this.conjuntos[0]?.id ?? null;
        if (this.conjuntoId !== null) this.cargarDatos();
      },
      error: (err) => this.setError(err),
    });
  }

  cambiarConjunto(raw: string): void {
    this.conjuntoId = Number(raw) || null;
    this.inmuebles = []; this.cuotas = []; this.pagos = []; this.egresos = []; this.presupuestos = [];
    this.cartera = null; this.informe = null; this.puc = []; this.asientos = []; this.estadoFinanciero = null;
    this.cuentasPagar = []; this.fondos = []; this.documentos = []; this.auditoria = []; this.estadoTributario = null; this.ejecucion = [];
    this.buscarPagos = ''; this.buscarCuotas = ''; this.buscarEgresos = ''; this.buscarAsientos = '';
    if (this.conjuntoId !== null) this.cargarDatos();
  }

  cargarDatos(): void {
    if (this.conjuntoId === null) return;
    this.loading = true; this.error = '';
    forkJoin({
      inmuebles: this.http.get<any[]>(`${this.base}/conjuntos/${this.conjuntoId}/inmuebles/`, { headers: this.headers }),
      cuotas: this.http.get<any[]>(`${this.base}/cuotas/`, { headers: this.headers }),
      pagos: this.http.get<any[]>(`${this.base}/v2/payments`, { headers: this.headers }),
      egresos: this.http.get<any[]>(`${this.base}/v3/contabilidad/egresos`, { headers: this.headers, params: { conjunto_id: String(this.conjuntoId) } }),
      presupuestos: this.http.get<any[]>(`${this.base}/v3/contabilidad/presupuestos`, { headers: this.headers, params: { conjunto_id: String(this.conjuntoId) } }),
      cartera: this.http.get<any>(`${this.base}/v3/contabilidad/cartera`, { headers: this.headers, params: { conjunto_id: String(this.conjuntoId) } }),
    }).subscribe({
      next: (data) => {
        this.inmuebles = data.inmuebles || [];
        const unitIds = new Set(this.inmuebles.map((unit) => unit.id));
        this.cuotas = (data.cuotas || []).filter((row) => unitIds.has(row.inmueble_id));
        this.pagos = (data.pagos || []).filter((row) => unitIds.has(row.inmueble_id));
        this.egresos = data.egresos || [];
        this.presupuestos = data.presupuestos || [];
        this.cartera = data.cartera;
        if (!this.cuota.inmueble_id && this.inmuebles.length) this.cuota.inmueble_id = this.inmuebles[0].id;
        this.loading = false;
        this.cargarProfesional();
      },
      error: (err) => { this.loading = false; this.setError(err); },
    });
  }

  crearCuota(): void {
    if (this.conjuntoId === null || !this.cuota.inmueble_id) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.post(`${this.base}/cuotas/`, { ...this.cuota, monto: Number(this.cuota.monto) }, { headers: this.headers }).subscribe({
      next: () => { this.saving = false; this.success = 'Cuota registrada y notificada a los residentes.'; this.cuota = { ...this.cuota, concepto: 'Cuota de administración', periodo: '', monto: '', fecha_vencimiento: '' }; this.cargarDatos(); },
      error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  guardarEgreso(): void {
    if (this.conjuntoId === null) return;
    this.saving = true; this.error = ''; this.success = '';
    const body = { ...this.egreso, conjunto_id: this.conjuntoId, monto: Number(this.egreso.monto) };
    const request = this.egresoEditId
      ? this.http.patch(`${this.base}/v3/contabilidad/egresos/${this.egresoEditId}`, body, { headers: this.headers })
      : this.http.post(`${this.base}/v3/contabilidad/egresos`, body, { headers: this.headers });
    request.subscribe({
      next: () => { this.saving = false; this.egresoEditId = null; this.egreso = { concepto: '', categoria: 'general', monto: '', fecha: '' }; this.success = 'Egreso guardado.'; this.cargarDatos(); },
      error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  editarEgreso(row: any): void {
    this.egresoEditId = row.id;
    this.egreso = { concepto: row.concepto, categoria: row.categoria, monto: String(row.monto), fecha: String(row.fecha).slice(0, 10) };
    document.getElementById('egreso-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  cancelarEdicionEgreso(): void { this.egresoEditId = null; this.egreso = { concepto: '', categoria: 'general', monto: '', fecha: '' }; }

  eliminarEgreso(row: any): void {
    if (!window.confirm(`¿Eliminar el egreso «${row.concepto}» por $${row.monto}?`)) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.delete(`${this.base}/v3/contabilidad/egresos/${row.id}`, { headers: this.headers }).subscribe({
      next: () => { this.saving = false; this.success = 'Egreso eliminado.'; this.cargarDatos(); },
      error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  guardarPresupuesto(): void {
    if (this.conjuntoId === null) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.post(`${this.base}/v3/contabilidad/presupuestos`, {
      ...this.presupuesto, conjunto_id: this.conjuntoId, monto_presupuestado: Number(this.presupuesto.monto_presupuestado),
    }, { headers: this.headers }).subscribe({
      next: () => { this.saving = false; this.success = 'Presupuesto guardado.'; this.cargarDatos(); },
      error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  consultarInforme(): void {
    if (this.conjuntoId === null || this.loading) return;
    this.loading = true; this.error = ''; this.success = '';
    this.http.get<any>(`${this.base}/v3/contabilidad/informes/periodo`, {
      headers: this.headers, params: { conjunto_id: String(this.conjuntoId), desde: this.desde, hasta: this.hasta },
    }).subscribe({ next: (row) => { this.informe = row; this.loading = false; this.success = 'Informe financiero actualizado.'; }, error: (err) => { this.loading = false; this.setError(err); } });
    this.cargarProfesional();
  }

  registrarPago(row: any): void {
    if (!window.confirm(`¿Registrar como recibido el pago de ${row.concepto} por $${row.monto}?`)) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.post(`${this.base}/v2/payments/manual`, {
      cuota_id: row.id, metodo: this.metodoPago, referencia: this.referenciaPago, notas: 'Registrado por el contador del conjunto',
    }, { headers: this.headers }).subscribe({
      next: () => { this.saving = false; this.referenciaPago = ''; this.success = 'Pago registrado correctamente.'; this.cargarDatos(); },
      error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  verificarPago(row: any, estado: 'verificado' | 'rechazado'): void {
    const action = estado === 'verificado' ? 'aprobar' : 'rechazar';
    if (!window.confirm(`¿Deseas ${action} el pago #${row.id} por $${row.monto}?`)) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.patch(`${this.base}/v2/payments/${row.id}`, {
      estado, notas: estado === 'verificado' ? 'Verificado por el contador' : 'Rechazado por el contador',
    }, { headers: this.headers }).subscribe({
      next: () => { this.saving = false; this.success = `Pago ${estado === 'verificado' ? 'verificado' : 'rechazado'}.`; this.cargarDatos(); },
      error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  cargarProfesional(): void {
    if (this.conjuntoId === null) return;
    const params = { conjunto_id: String(this.conjuntoId) };
    const profesional = `${this.base}/v3/contabilidad/profesional`;
    forkJoin({
      puc: this.http.get<any[]>(`${profesional}/puc`, { headers: this.headers, params }).pipe(catchError(() => of([]))),
      asientos: this.http.get<any[]>(`${profesional}/asientos`, { headers: this.headers, params }).pipe(catchError(() => of([]))),
      estado: this.http.get<any>(`${profesional}/estados-financieros`, { headers: this.headers, params: { ...params, desde: this.desde, hasta: this.hasta } }).pipe(catchError(() => of(null))),
      cxp: this.http.get<any[]>(`${profesional}/cuentas-por-pagar`, { headers: this.headers, params }).pipe(catchError(() => of([]))),
      fondos: this.http.get<any[]>(`${profesional}/fondos`, { headers: this.headers, params }).pipe(catchError(() => of([]))),
      documentos: this.http.get<any[]>(`${profesional}/documentos`, { headers: this.headers, params }).pipe(catchError(() => of([]))),
      auditoria: this.http.get<any[]>(`${profesional}/auditoria`, { headers: this.headers, params }).pipe(catchError(() => of([]))),
      tributario: this.http.get<any>(`${profesional}/tributario/estado`, { headers: this.headers, params }).pipe(catchError(() => of(null))),
    }).subscribe((data) => {
      this.puc = data.puc || []; this.asientos = data.asientos || []; this.estadoFinanciero = data.estado;
      this.cuentasPagar = data.cxp || []; this.fondos = data.fondos || []; this.documentos = data.documentos || [];
      this.auditoria = data.auditoria || []; this.estadoTributario = data.tributario;
    });
  }

  sincronizarAsientos(): void {
    if (this.conjuntoId === null || this.saving) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.post<any>(`${this.base}/v3/contabilidad/profesional/asientos/sincronizar`, { conjunto_id: this.conjuntoId }, { headers: this.headers }).subscribe({
      next: (r) => { this.saving = false; this.success = `Sincronización lista: ${r.asientos_creados} asiento(s) nuevo(s).`; this.cargarProfesional(); }, error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  calcularMora(): void {
    if (this.conjuntoId === null || this.saving) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.post<any>(`${this.base}/v3/contabilidad/profesional/cartera/calcular-mora`, { conjunto_id: this.conjuntoId }, { headers: this.headers }).subscribe({
      next: (r) => { this.saving = false; this.success = `Liquidación de mora: ${r.cargos_aplicados} cargo(s) aplicado(s); ${r.omitidos} omitido(s).`; this.cargarDatos(); },
      error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  crearAsientoManual(): void {
    if (this.conjuntoId === null || this.saving || !this.asientoManual.descripcion || Number(this.asientoManual.monto) <= 0) return;
    this.saving = true; this.error = ''; this.success = '';
    const amount = Number(this.asientoManual.monto);
    this.http.post(`${this.base}/v3/contabilidad/profesional/asientos`, {
      conjunto_id: this.conjuntoId, fecha: this.asientoManual.fecha, descripcion: this.asientoManual.descripcion,
      lineas: [{ codigo: this.asientoManual.cuentaDebito, debito: amount, credito: 0 }, { codigo: this.asientoManual.cuentaCredito, debito: 0, credito: amount }],
    }, { headers: this.headers }).subscribe({
      next: () => { this.saving = false; this.success = 'Asiento balanceado registrado.'; this.asientoManual.descripcion = ''; this.asientoManual.monto = ''; this.cargarProfesional(); }, error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  crearCuentaPUC(): void {
    if (this.conjuntoId === null || this.saving) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.post(`${this.base}/v3/contabilidad/profesional/puc`, { ...this.cuentaPUC, conjunto_id: this.conjuntoId }, { headers: this.headers }).subscribe({
      next: () => { this.saving = false; this.success = 'Cuenta PUC creada.'; this.cuentaPUC = { codigo: '', nombre: '', clase: 'activo', naturaleza: 'debito' }; this.cargarProfesional(); },
      error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  facturarLote(): void {
    if (this.conjuntoId === null || this.saving) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.post<any>(`${this.base}/v3/contabilidad/profesional/facturacion/lote`, { ...this.lote, conjunto_id: this.conjuntoId, monto: Number(this.lote.monto) }, { headers: this.headers }).subscribe({
      next: (r) => { this.saving = false; this.success = `Facturación ${r.periodo}: ${r.cuentas_creadas} cuentas creadas; ${r.omitidas_duplicadas} duplicadas omitidas.`; this.cargarDatos(); }, error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  crearCuentaPagar(): void {
    if (this.conjuntoId === null || this.saving) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.post(`${this.base}/v3/contabilidad/profesional/cuentas-por-pagar`, { ...this.proveedorFactura, conjunto_id: this.conjuntoId, monto: Number(this.proveedorFactura.monto) }, { headers: this.headers }).subscribe({
      next: () => { this.saving = false; this.success = 'Factura del proveedor registrada como cuenta por pagar.'; this.proveedorFactura = { proveedor: '', documento: '', concepto: '', fecha_documento: '', fecha_vencimiento: '', monto: '' }; this.cargarProfesional(); }, error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  pagarProveedor(row: any): void {
    if (this.saving || !window.confirm(`¿Registrar pago al proveedor ${row.proveedor} por ${row.monto} COP?`)) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.patch(`${this.base}/v3/contabilidad/profesional/cuentas-por-pagar/${row.id}/pagar`, {}, { headers: this.headers }).subscribe({
      next: () => { this.saving = false; this.success = 'Pago registrado con su asiento contable.'; this.cargarProfesional(); }, error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  registrarDocumento(): void {
    if (this.conjuntoId === null || this.saving) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.post(`${this.base}/v3/contabilidad/profesional/documentos`, { ...this.documentoContable, conjunto_id: this.conjuntoId, valor: Number(this.documentoContable.valor || 0) }, { headers: this.headers }).subscribe({
      next: () => { this.saving = false; this.success = 'Documento contable registrado.'; this.documentoContable = { tipo: 'soporte_gasto', numero: '', fecha: this.hasta, tercero: '', descripcion: '', valor: '' }; this.cargarProfesional(); }, error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  causarFondo(fondo: any): void {
    if (this.conjuntoId === null || this.saving || !this.periodoTrabajo || Number(this.baseFondo) <= 0) return;
    this.saving = true; this.error = ''; this.success = '';
    this.http.post<any>(`${this.base}/v3/contabilidad/profesional/fondos/${fondo.id}/causar`, {
      periodo: this.periodoTrabajo, fecha: `${this.periodoTrabajo}-01`, base_presupuestal: Number(this.baseFondo),
    }, { headers: this.headers }).subscribe({
      next: (r) => { this.saving = false; this.success = `Traslado al fondo registrado: ${r.traslado} COP.`; this.cargarProfesional(); }, error: (err) => { this.saving = false; this.setError(err); },
    });
  }

  consultarEjecucion(): void {
    if (this.conjuntoId === null || this.loading) return;
    this.loading = true; this.error = ''; this.success = '';
    this.http.get<any[]>(`${this.base}/v3/contabilidad/profesional/ejecucion-presupuestal`, {
      headers: this.headers, params: { conjunto_id: String(this.conjuntoId), periodo: this.periodoTrabajo },
    }).subscribe({ next: (rows) => { this.ejecucion = rows || []; this.loading = false; this.success = 'Ejecución presupuestal actualizada.'; }, error: (err) => { this.loading = false; this.setError(err); } });
  }

  exportarLibro(tipo: string, formato: string): void {
    if (this.conjuntoId === null || this.loading) return;
    this.loading = true; this.error = '';
    this.http.get(`${this.base}/v3/contabilidad/profesional/exportar`, {
      headers: this.headers, params: { conjunto_id: String(this.conjuntoId), tipo, formato, desde: this.desde, hasta: this.hasta }, responseType: 'blob',
    }).subscribe({ next: (blob) => { this.loading = false; const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `iris-${tipo}-${this.conjuntoId}.${formato}`; document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); this.success = 'Archivo exportado correctamente.'; }, error: (err) => { this.loading = false; this.setError(err); } });
  }

  abrirCertificacion(): void {
    if (this.conjuntoId === null || this.loading) return;
    this.loading = true; this.error = '';
    this.http.get(`${this.base}/v3/contabilidad/profesional/certificacion`, { headers: this.headers, params: { conjunto_id: String(this.conjuntoId), fecha_corte: this.hasta }, responseType: 'blob' }).subscribe({
      next: (blob) => { this.loading = false; const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener'; link.download = `certificacion-contable-${this.conjuntoId}.html`; document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); this.success = 'Borrador de certificación generado.'; }, error: (err) => { this.loading = false; this.setError(err); },
    });
  }

  get cuotasPendientes(): any[] { return this.cuotas.filter((row) => row.estado !== 'pagada'); }
  get pagosPendientes(): any[] { return this.pagos.filter((row) => row.estado === 'pendiente'); }
  get saldoPendiente(): number { return this.cuotasPendientes.reduce((sum, row) => sum + Number(row.monto || 0), 0); }
  get totalPagado(): number { return this.cuotas.filter((row) => row.estado === 'pagada').reduce((sum, row) => sum + Number(row.monto || 0), 0); }
  get totalCuotas(): number { return this.cuotas.reduce((sum, row) => sum + Number(row.monto || 0), 0); }
  get porcentajeRecaudo(): number { return this.totalCuotas > 0 ? Math.round((this.totalPagado / this.totalCuotas) * 100) : 0; }
  get puedeCausarFondo(): boolean { return !this.saving && this.conjuntoId !== null && !!this.periodoTrabajo && Number(this.baseFondo) > 0; }
  get pagosPendientesFiltrados(): any[] {
    const query = this.normalizarBusqueda(this.buscarPagos);
    return this.pagosPendientes.filter((row) => this.coincideBusqueda(query, row.metodo, row.referencia, row.estado, row.monto, row.cuota_id, this.etiquetaUnidad(row.inmueble_id)));
  }
  get cuotasFiltradas(): any[] {
    const query = this.normalizarBusqueda(this.buscarCuotas);
    return this.cuotas.filter((row) => this.coincideBusqueda(query, row.concepto, row.periodo, row.estado, row.monto, this.etiquetaUnidad(row.inmueble_id)));
  }
  get egresosFiltrados(): any[] {
    const query = this.normalizarBusqueda(this.buscarEgresos);
    return this.egresos.filter((row) => this.coincideBusqueda(query, row.concepto, row.categoria, row.fecha, row.monto));
  }
  get asientosFiltrados(): any[] {
    const query = this.normalizarBusqueda(this.buscarAsientos);
    return this.asientos.filter((row) => this.coincideBusqueda(query, row.numero, row.fecha, row.descripcion, row.origen));
  }

  private normalizarBusqueda(value: any): string {
    return String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();
  }

  private coincideBusqueda(query: string, ...values: any[]): boolean {
    return !query || values.some((value) => this.normalizarBusqueda(value).includes(query));
  }

  etiquetaUnidad(id: number): string {
    const unit = this.inmuebles.find((row) => row.id === id);
    return unit ? `${unit.torre ? `${unit.torre} · ` : ''}${unit.numero}` : `Inmueble ${id}`;
  }

  exportarCsv(): void {
    const rows = [['Tipo', 'ID', 'Inmueble', 'Concepto / método', 'Periodo / referencia', 'Monto', 'Estado', 'Vencimiento / fecha']];
    this.cuotas.forEach((row) => rows.push(['Cuota', row.id, this.etiquetaUnidad(row.inmueble_id), row.concepto, row.periodo, row.monto, row.estado, row.fecha_vencimiento]));
    this.pagos.forEach((row) => rows.push(['Pago', row.id, this.etiquetaUnidad(row.inmueble_id), row.metodo, row.referencia || '', row.monto, row.estado, row.creado_en || '']));
    this.egresos.forEach((row) => rows.push(['Egreso', row.id, '', row.concepto, row.categoria, row.monto, 'registrado', row.fecha || '']));
    const quote = (value: any) => `"${String(value ?? '').replace(/"/g, '""')}"`;
    const csv = '\ufeff' + rows.map((row) => row.map(quote).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = `iris-finanzas-${this.conjuntoId}.csv`; link.click(); URL.revokeObjectURL(url);
  }

  salir(): void { this.auth.logout(); }
  private setError(err: any): void {
    const detail = err?.error?.detail;
    this.error = typeof detail === 'string' ? detail : detail?.mensaje || 'No fue posible cargar o guardar la información financiera.';
  }
}
