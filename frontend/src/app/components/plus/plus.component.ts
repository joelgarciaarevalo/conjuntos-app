import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, firstValueFrom } from 'rxjs';
import { irisApiBase } from '../../services/api-url';

type PaymentDecision = 'verificado' | 'rechazado';
type SummaryItem = { label: string; value: string | number | boolean };

@Component({
  selector: 'app-plus',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './plus.component.html',
  styleUrls: ['./plus.component.css']
})
export class PlusComponent implements OnInit {
  usuario: any = {};
  rol = '';
  esAdmin = false;
  esResidente = false;
  esPortero = false;
  esSuperAdmin = false;

  resumen: any = {};
  notificaciones: any[] = [];
  pagos: any[] = [];
  incidentes: any[] = [];
  contactos: any[] = [];
  bitacora: any[] = [];
  membresias: any[] = [];
  conjuntos: any[] = [];
  usuarios: any[] = [];
  bloqueos: any[] = [];
  cuotas: any[] = [];
  inmuebles: any[] = [];
  zonas: any[] = [];
  paquetes: any[] = [];
  paqueteDraft: any = { inmueble_id: '', transportadora: '', descripcion: '' };
  importConjuntoId: number | string = '';

  error = '';
  feedback = '';
  private busy = new Set<string>();

  paymentDraft: any = { cuota_id: '', referencia: '' };
  manualPaymentDraft: any = { cuota_id: '', metodo: 'efectivo', referencia: '', notas: '' };
  incidentDraft: any = {
    conjunto_id: '', inmueble_id: '', categoria: 'mantenimiento', titulo: '', descripcion: ''
  };
  contactDraft: any = {
    conjunto_id: '', inmueble_id: '', nombre: '', telefono: '', parentesco: '', visible: true
  };
  membershipDraft: any = { conjunto_id: '', usuario_id: '', rol: 'portero' };
  blockDraft: any = { zona_id: '', fecha_inicio: '', fecha_fin: '', motivo: '' };
  importFiles: Record<string, File | null> = { residentes: null, inmuebles: null, pagos: null };

  readonly importKinds = [
    { kind: 'residentes', label: 'Residentes' },
    { kind: 'inmuebles', label: 'Inmuebles' },
    { kind: 'pagos', label: 'Pagos' }
  ];

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.readLocalUser();
    this.loadSummary();
    if (this.esAdmin || this.esResidente || this.esPortero) {
      this.loadIncidents();
    }
    if (this.esAdmin || this.esResidente) this.loadPayments();
    if (this.esAdmin) this.loadFees();
    if (this.esAdmin) this.loadFees();
    if (this.esResidente) { this.loadFees(); this.loadMyUnits(); }
    if (this.esPortero) { this.loadPackages(); this.loadOperationalUnits(); }
    if (this.esResidente) {
      this.loadEmergencyContacts();
    }
    if (this.esAdmin) {
      this.loadAudit();
      if (this.esSuperAdmin) this.loadMemberships();
      this.loadUsers();
      this.loadOperationalUnits();
      this.loadConjuntos();
      this.loadReservationBlocks();
    }
  }

  private get apiBase(): string {
    const configured = irisApiBase();
    return String(configured).replace(/\/+$/, '');
  }

  private endpoint(path: string): string {
    return `${this.apiBase}${path}`;
  }

  private authHeaders(): HttpHeaders {
    const token = localStorage.getItem('token');
    return new HttpHeaders(token ? { Authorization: `Bearer ${token}` } : {});
  }

  private readLocalUser(): void {
    const stored = localStorage.getItem('usuario');
    if (!stored) return;
    try {
      const parsed = JSON.parse(stored);
      this.usuario = parsed?.usuario ?? parsed ?? {};
    } catch {
      this.usuario = {};
    }
    this.rol = String(this.usuario?.rol ?? '');
    this.esSuperAdmin = Boolean(this.usuario?.es_super_admin);
    this.esAdmin = this.rol === 'admin' || this.esSuperAdmin;
    this.esResidente = this.rol === 'residente';
    this.esPortero = this.rol === 'portero';

    const conjuntoId = this.usuario?.conjunto_id ?? '';
    const inmuebleId = this.usuario?.inmueble_id ?? '';
    this.paymentDraft.inmueble_id = inmuebleId;
    this.incidentDraft.conjunto_id = conjuntoId;
    this.incidentDraft.inmueble_id = inmuebleId;
    this.contactDraft.conjunto_id = conjuntoId;
    this.contactDraft.inmueble_id = inmuebleId;
  }

  isBusy(key: string): boolean {
    return this.busy.has(key);
  }

  private request<T>(
    key: string,
    observable: Observable<T>,
    onSuccess: (value: T) => void,
    successMessage = ''
  ): void {
    this.clearFeedback();
    this.busy.add(key);
    observable.subscribe({
      next: value => {
        this.busy.delete(key);
        onSuccess(value);
        if (successMessage) this.feedback = successMessage;
      },
      error: problem => {
        this.busy.delete(key);
        this.showError(problem);
      }
    });
  }

  private clearFeedback(): void {
    this.error = '';
    this.feedback = '';
  }

  private showError(problem: any): void {
    const detail = problem?.error?.detail ?? problem?.error?.message ?? problem?.message;
    this.error = typeof detail === 'string' && detail.trim()
      ? detail
      : 'No fue posible completar la operación. Intenta de nuevo.';
    this.feedback = '';
  }

  private unwrap(response: any): any {
    if (response && typeof response === 'object' && response.data !== undefined) return response.data;
    return response;
  }

  private listFrom(response: any, possibleKeys: string[]): any[] {
    const data = this.unwrap(response);
    if (Array.isArray(data)) return data;
    for (const key of possibleKeys) {
      if (Array.isArray(data?.[key])) return data[key];
    }
    return [];
  }

  loadSummary(): void {
    this.request('summary', this.http.get<any>(this.endpoint('/v2/summary'), { headers: this.authHeaders() }), response => { this.resumen = this.unwrap(response) ?? {}; });
    this.request('notifications', this.http.get<any>(this.endpoint('/notificaciones/'), { headers: this.authHeaders() }), response => { this.notificaciones = this.listFrom(response, ['notificaciones', 'notifications']); });
  }

  loadFees(): void {
    this.request('fees', this.http.get<any>(this.endpoint('/cuotas/'), { headers: this.authHeaders() }), response => { this.cuotas = this.listFrom(response, ['cuotas', 'items']); });
  }

  loadMyUnits(): void {
    this.request('my-units', this.http.get<any>(this.endpoint('/v2/my-units'), { headers: this.authHeaders() }), response => {
      this.inmuebles = this.listFrom(response, ['inmuebles', 'items']);
      if (this.inmuebles.length) {
        const unit = this.inmuebles[0];
        this.paymentDraft.inmueble_id = unit.id; this.incidentDraft.inmueble_id = unit.id; this.incidentDraft.conjunto_id = unit.conjunto_id;
        this.contactDraft.inmueble_id = unit.id; this.contactDraft.conjunto_id = unit.conjunto_id;
        this.paqueteDraft.inmueble_id = unit.id;
      }
    });
  }

  loadOperationalUnits(): void {
    this.request('operational-units', this.http.get<any>(this.endpoint('/v2/operational-units'), { headers: this.authHeaders() }), response => { this.inmuebles = this.listFrom(response, ['inmuebles', 'items']); if (this.esPortero && this.inmuebles.length && !this.paqueteDraft.inmueble_id) this.paqueteDraft.inmueble_id = this.inmuebles[0].id; });
  }

  selectResidentUnit(id: number): void {
    const unit = this.inmuebles.find(x => Number(x.id) === Number(id));
    if (!unit) return;
    this.incidentDraft.conjunto_id = unit.conjunto_id; this.contactDraft.conjunto_id = unit.conjunto_id;
  }

  loadPackages(): void {
    this.request('packages', this.http.get<any>(this.endpoint('/paquetes/'), { headers: this.authHeaders() }), response => { this.paquetes = this.listFrom(response, ['paquetes', 'items']); });
  }

  loadPayments(): void {
    this.request('payments', this.http.get<any>(this.endpoint('/v2/payments'), { headers: this.authHeaders() }), response => {
      this.pagos = this.listFrom(response, ['payments', 'pagos', 'items', 'results']);
    });
  }

  loadIncidents(): void {
    this.request('incidents', this.http.get<any>(this.endpoint('/v2/incidents'), { headers: this.authHeaders() }), response => {
      this.incidentes = this.listFrom(response, ['incidents', 'incidentes', 'items', 'results']);
    });
  }

  loadEmergencyContacts(): void {
    this.request('contacts', this.http.get<any>(this.endpoint('/v2/emergency-contacts'), { headers: this.authHeaders() }), response => {
      this.contactos = this.listFrom(response, ['contacts', 'contactos', 'items', 'results']);
    });
  }

  loadAudit(): void {
    this.request('audit', this.http.get<any>(this.endpoint('/v2/audit?limit=50'), { headers: this.authHeaders() }), response => {
      this.bitacora = this.listFrom(response, ['audit', 'events', 'items', 'results']);
    });
  }

  loadMemberships(): void {
    this.request('memberships', this.http.get<any>(this.endpoint('/v2/memberships'), { headers: this.authHeaders() }), response => {
      this.membresias = this.listFrom(response, ['memberships', 'membresias', 'items', 'results']);
    });
  }

  loadUsers(): void {
    this.request('users', this.http.get<any>(this.endpoint('/gestion/usuarios'), { headers: this.authHeaders() }), response => {
      this.usuarios = this.listFrom(response, ['usuarios', 'users', 'items', 'results']);
    });
  }

  loadConjuntos(): void {
    this.request('conjuntos', this.http.get<any>(this.endpoint('/conjuntos/'), { headers: this.authHeaders() }), response => {
      this.conjuntos = this.listFrom(response, ['conjuntos', 'items', 'results']);
      if (!this.importConjuntoId && this.conjuntos.length) this.importConjuntoId = this.conjuntos[0].id;
      this.zonas = [];
      for (const group of this.conjuntos) {
        this.http.get<any[]>(this.endpoint(`/conjuntos/${group.id}/zonas-comunes/`), { headers: this.authHeaders() }).subscribe({ next: rows => { this.zonas = [...this.zonas, ...(rows || [])]; if (!this.blockDraft.zona_id && this.zonas.length) this.blockDraft.zona_id = this.zonas[0].id; }, error: () => {} });
      }
      if (!this.membershipDraft.conjunto_id && this.conjuntos.length) {
        this.membershipDraft.conjunto_id = this.conjuntos[0].id;
      }
      if (!this.blockDraft.conjunto_id && this.conjuntos.length) {
        this.blockDraft.conjunto_id = this.conjuntos[0].id;
      }
    });
  }

  loadReservationBlocks(): void {
    this.request('blocks', this.http.get<any>(this.endpoint('/v2/reservation-blocks'), { headers: this.authHeaders() }), response => {
      this.bloqueos = this.listFrom(response, ['reservation_blocks', 'blocks', 'bloqueos', 'items', 'results']);
    });
  }

  reload(): void {
    this.loadSummary();
    if (this.esAdmin || this.esResidente || this.esPortero) this.loadIncidents();
    if (this.esAdmin || this.esResidente) this.loadPayments();
    if (this.esResidente) { this.loadFees(); this.loadMyUnits(); }
    if (this.esPortero) { this.loadPackages(); this.loadOperationalUnits(); }
    if (this.esResidente) this.loadEmergencyContacts();
    if (this.esAdmin) {
      this.loadAudit();
      if (this.esSuperAdmin) this.loadMemberships();
      this.loadUsers();
      this.loadOperationalUnits();
      this.loadConjuntos();
      this.loadReservationBlocks();
    }
  }

  solicitarVerificacionPago(): void {
    this.clearFeedback();
    if (!Number(this.paymentDraft.cuota_id)) {
      this.error = 'Selecciona la cuota que deseas reportar.';
      return;
    }
    const body = {
      cuota_id: Number(this.paymentDraft.cuota_id),
      metodo: 'transferencia',
      referencia: String(this.paymentDraft.referencia ?? '').trim() || null
    };
    this.request('create-payment', this.http.post<any>(this.endpoint('/v2/payments'), body, { headers: this.authHeaders() }), () => {
      this.paymentDraft = { cuota_id: '', referencia: '' };
      this.loadPayments();
    }, 'Solicitud de verificación enviada para conciliación manual.');
  }

  registrarPagoManual(): void {
    this.clearFeedback();
    if (!Number(this.manualPaymentDraft.cuota_id)) { this.error = 'Selecciona una cuota pendiente.'; return; }
    const body = { cuota_id: Number(this.manualPaymentDraft.cuota_id), metodo: this.manualPaymentDraft.metodo, referencia: String(this.manualPaymentDraft.referencia || '').trim(), notas: String(this.manualPaymentDraft.notas || '').trim() };
    this.request('manual-payment', this.http.post<any>(this.endpoint('/v2/payments/manual'), body, { headers: this.authHeaders() }), () => { this.manualPaymentDraft = { cuota_id: '', metodo: 'efectivo', referencia: '', notas: '' }; this.loadPayments(); this.loadFees(); }, 'Pago manual registrado y cuota actualizada.');
  }

  decidirPago(payment: any, estado: PaymentDecision): void {
    if (!payment?.id) return;
    const body = { estado, notas: '' };
    this.request(`payment-${payment.id}`, this.http.patch<any>(
      this.endpoint(`/v2/payments/${payment.id}`), body, { headers: this.authHeaders() }
    ), () => this.loadPayments(), estado === 'verificado' ? 'Pago confirmado.' : 'Pago rechazado.');
  }

  abrirRecibo(payment: any): void {
    if (!payment?.id) return;
    const tab = window.open('about:blank', '_blank');
    if (!tab) {
      this.error = 'El navegador bloqueó la nueva pestaña. Permite ventanas emergentes e inténtalo de nuevo.';
      return;
    }
    tab.opener = null;
    this.request(`receipt-${payment.id}`, this.http.get(this.endpoint(`/v2/payments/${payment.id}/receipt`), { headers: this.authHeaders(), responseType: 'text' }), response => {
      const url = URL.createObjectURL(new Blob([response], { type: 'text/html' }));
      tab.location.href = url; window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    });
  }

  reportarIncidente(): void {
    this.clearFeedback();
    if (!Number(this.incidentDraft.conjunto_id) || !String(this.incidentDraft.titulo).trim() || !String(this.incidentDraft.descripcion).trim()) {
      this.error = 'Completa el conjunto, el título y la descripción del incidente.';
      return;
    }
    const body = {
      conjunto_id: Number(this.incidentDraft.conjunto_id),
      inmueble_id: this.incidentDraft.inmueble_id ? Number(this.incidentDraft.inmueble_id) : null,
      categoria: this.incidentDraft.categoria,
      titulo: String(this.incidentDraft.titulo).trim(),
      descripcion: String(this.incidentDraft.descripcion).trim()
    };
    this.request('create-incident', this.http.post<any>(this.endpoint('/v2/incidents'), body, { headers: this.authHeaders() }), () => {
      this.incidentDraft = {
        conjunto_id: this.usuario?.conjunto_id ?? '', inmueble_id: this.usuario?.inmueble_id ?? '',
        categoria: 'mantenimiento', titulo: '', descripcion: ''
      };
      this.loadIncidents();
    }, 'Incidente reportado.');
  }

  actualizarIncidente(incident: any): void {
    if (!incident?.id) return;
    const body = {
      estado: incident.estado,
      prioridad: incident.prioridad,
      asignado_a: incident.asignado_a ? Number(incident.asignado_a) : null
    };
    this.request(`incident-${incident.id}`, this.http.patch<any>(
      this.endpoint(`/v2/incidents/${incident.id}`), body, { headers: this.authHeaders() }
    ), () => this.loadIncidents(), 'Incidente actualizado.');
  }

  registrarPaquete(): void {
    this.clearFeedback();
    if (!Number(this.paqueteDraft.inmueble_id)) { this.error = 'Selecciona el inmueble destinatario.'; return; }
    const body = { inmueble_id: Number(this.paqueteDraft.inmueble_id), transportadora: this.paqueteDraft.transportadora, descripcion: this.paqueteDraft.descripcion || 'Paquete' };
    this.request('create-package', this.http.post<any>(this.endpoint('/paquetes/'), body, { headers: this.authHeaders() }), () => { this.paqueteDraft = { inmueble_id: '', transportadora: '', descripcion: '' }; this.loadPackages(); }, 'Paquete registrado y residente notificado.');
  }

  agregarContactoEmergencia(): void {
    this.clearFeedback();
    if (!Number(this.contactDraft.conjunto_id) || !Number(this.contactDraft.inmueble_id) ||
        !String(this.contactDraft.nombre).trim() || !String(this.contactDraft.telefono).trim()) {
      this.error = 'Completa conjunto, inmueble, nombre y teléfono del contacto.';
      return;
    }
    const body = {
      conjunto_id: Number(this.contactDraft.conjunto_id),
      inmueble_id: Number(this.contactDraft.inmueble_id),
      nombre: String(this.contactDraft.nombre).trim(),
      telefono: String(this.contactDraft.telefono).trim(),
      parentesco: String(this.contactDraft.parentesco ?? '').trim(),
      visible: Boolean(this.contactDraft.visible)
    };
    this.request('create-contact', this.http.post<any>(this.endpoint('/v2/emergency-contacts'), body, { headers: this.authHeaders() }), () => {
      this.contactDraft.nombre = '';
      this.contactDraft.telefono = '';
      this.contactDraft.parentesco = '';
      this.contactDraft.visible = true;
      this.loadEmergencyContacts();
    }, 'Contacto de emergencia guardado.');
  }

  eliminarContacto(contact: any): void {
    if (!contact?.id || !window.confirm('¿Eliminar este contacto de emergencia?')) return;
    this.request(`delete-contact-${contact.id}`, this.http.delete<any>(
      this.endpoint(`/v2/emergency-contacts/${contact.id}`), { headers: this.authHeaders() }
    ), () => this.loadEmergencyContacts(), 'Contacto eliminado.');
  }

  agregarMembresia(): void {
    this.clearFeedback();
    if (!Number(this.membershipDraft.conjunto_id) || !Number(this.membershipDraft.usuario_id)) {
      this.error = 'Selecciona un conjunto y un usuario.';
      return;
    }
    const body = {
      conjunto_id: Number(this.membershipDraft.conjunto_id),
      usuario_id: Number(this.membershipDraft.usuario_id),
      rol: this.membershipDraft.rol
    };
    this.request('create-membership', this.http.post<any>(this.endpoint('/v2/memberships'), body, { headers: this.authHeaders() }), () => {
      this.loadMemberships();
    }, 'Membresía creada.');
  }

  eliminarMembresia(membership: any): void {
    if (!membership?.id || !window.confirm('¿Eliminar esta membresía?')) return;
    this.request(`delete-membership-${membership.id}`, this.http.delete<any>(
      this.endpoint(`/v2/memberships/${membership.id}`), { headers: this.authHeaders() }
    ), () => this.loadMemberships(), 'Membresía eliminada.');
  }

  crearBloqueoZona(): void {
    this.clearFeedback();
    if (!Number(this.blockDraft.zona_id) || !this.blockDraft.fecha_inicio || !this.blockDraft.fecha_fin || !String(this.blockDraft.motivo).trim()) {
      this.error = 'Completa la zona, las fechas de inicio y fin, y el motivo.';
      return;
    }
    const body = {
      zona_id: Number(this.blockDraft.zona_id),
      fecha_inicio: this.blockDraft.fecha_inicio,
      fecha_fin: this.blockDraft.fecha_fin,
      motivo: String(this.blockDraft.motivo).trim()
    };
    this.request('create-block', this.http.post<any>(this.endpoint('/v2/reservation-blocks'), body, { headers: this.authHeaders() }), () => {
      this.blockDraft = { zona_id: '', fecha_inicio: '', fecha_fin: '', motivo: '' };
      this.loadReservationBlocks();
    }, 'Bloqueo de zona creado.');
  }

  eliminarBloqueo(block: any): void {
    if (!block?.id || !window.confirm('¿Eliminar este bloqueo de zona?')) return;
    this.request(`delete-block-${block.id}`, this.http.delete<any>(
      this.endpoint(`/v2/reservation-blocks/${block.id}`), { headers: this.authHeaders() }
    ), () => this.loadReservationBlocks(), 'Bloqueo eliminado.');
  }

  seleccionarArchivo(event: Event, kind: string): void {
    const input = event.target as HTMLInputElement;
    this.importFiles[kind] = input.files?.item(0) ?? null;
  }

  importar(kind: string): void {
    const file = this.importFiles[kind];
    if (!Number(this.importConjuntoId)) { this.error = 'Selecciona un conjunto antes de importar.'; this.feedback = ''; return; }
    if (!file) {
      this.error = 'Selecciona un archivo XLSX antes de importar.';
      this.feedback = '';
      return;
    }
    const form = new FormData();
    form.append('file', file, file.name);
    const apiKind = this.apiKind(kind);
    this.request(`import-${kind}`, this.http.post<any>(
      this.endpoint(`/v2/import/${encodeURIComponent(apiKind)}?conjunto_id=${Number(this.importConjuntoId)}`), form, { headers: this.authHeaders() }
    ), () => {
      this.importFiles[kind] = null;
      if (kind === 'pagos') this.loadPayments();
      if (kind === 'residentes') this.loadUsers();
    }, `Importación de ${kind} completada.`);
  }

  descargarPlantilla(kind: string): void {
    this.downloadXlsx(`/v2/import/template/${encodeURIComponent(this.apiKind(kind))}`, `plantilla-${kind}.xlsx`, `template-${kind}`);
  }

  private apiKind(kind: string): string { return ({ residentes: 'residents', inmuebles: 'properties', pagos: 'payments' } as Record<string, string>)[kind] ?? kind; }

  descargarReporte(kind: string): void {
    this.downloadXlsx(`/v2/export/${encodeURIComponent(this.apiKind(kind))}.xlsx`, `reporte-${kind}.xlsx`, `export-${kind}`);
  }

  crearRespaldo(): void {
    const stamp = new Date().toISOString().slice(0, 10);
    this.request('backup', this.http.get(this.endpoint('/v2/admin/backup'), {
      headers: this.authHeaders(), responseType: 'blob'
    }), blob => this.saveBlob(blob, `respaldo-iris-${stamp}`), 'Respaldo descargado.');
  }

  private downloadXlsx(path: string, filename: string, key: string): void {
    this.request(key, this.http.get(this.endpoint(path), {
      headers: this.authHeaders(), responseType: 'blob'
    }), blob => this.saveBlob(blob, filename), 'Descarga lista.');
  }

  private saveBlob(blob: Blob, filename: string): void {
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.style.display = 'none';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }

  async activarPush(): Promise<void> {
    this.clearFeedback();
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      this.error = 'Este navegador no admite notificaciones push.';
      return;
    }
    this.busy.add('push');
    try {
      const keyResponse = await firstValueFrom(this.http.get<any>(
        this.endpoint('/v2/push/public-key'), { headers: this.authHeaders() }
      ));
      const keyData = this.unwrap(keyResponse);
      const publicKey = typeof keyData === 'string' ? keyData : keyData?.publicKey ?? keyData?.public_key;
      if (typeof publicKey !== 'string' || !publicKey) throw new Error('No se recibió la clave pública de push.');

      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        this.error = 'No se concedió permiso para enviar notificaciones.';
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: this.decodePublicKey(publicKey)
      });
      await firstValueFrom(this.http.post<any>(
        this.endpoint('/v2/push/subscriptions'), subscription.toJSON(), { headers: this.authHeaders() }
      ));
      this.feedback = 'Notificaciones push activadas.';
    } catch (problem) {
      this.showError(problem);
    } finally {
      this.busy.delete('push');
    }
  }

  async desactivarPush(): Promise<void> {
    this.clearFeedback();
    if (!('serviceWorker' in navigator)) {
      this.error = 'Este navegador no admite notificaciones push.';
      return;
    }
    this.busy.add('push-delete');
    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      const options: { headers: HttpHeaders; body?: unknown } = { headers: this.authHeaders() };
      if (subscription) options.body = subscription.toJSON();
      await firstValueFrom(this.http.delete<any>(this.endpoint('/v2/push/subscriptions'), options));
      if (subscription) await subscription.unsubscribe();
      this.feedback = 'Notificaciones push desactivadas.';
    } catch (problem) {
      this.showError(problem);
    } finally {
      this.busy.delete('push-delete');
    }
  }

  private decodePublicKey(value: string): Uint8Array {
    const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized + '='.repeat((4 - normalized.length % 4) % 4);
    const raw = window.atob(padded);
    return Uint8Array.from(raw, character => character.charCodeAt(0));
  }

  get summaryItems(): SummaryItem[] {
    const data = this.unwrap(this.resumen);
    if (!data || typeof data !== 'object' || Array.isArray(data)) return [];
    return Object.entries(data)
      .filter(([key, value]) => !['notificaciones', 'notifications'].includes(key) &&
        (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'))
      .slice(0, 8)
      .map(([key, value]) => ({ label: this.summaryLabel(key), value: value as string | number | boolean }));
  }

  get adminKpis(): SummaryItem[] {
    return [
      { label: 'Pagos recibidos', value: this.metric(['pagos_total', 'payments_total'], this.pagos.length) },
      { label: 'Pagos por revisar', value: this.metric(['pagos_pendientes', 'payments_pending'], this.pagos.filter(p => this.isPending(p?.estado)).length) },
      { label: 'Incidentes abiertos', value: this.metric(['incidentes_abiertos', 'open_incidents'], this.incidentes.filter(i => !['cerrado', 'resuelto', 'cancelado'].includes(String(i?.estado ?? '').toLowerCase())).length) },
      { label: 'Membresías', value: this.metric(['membresias_total', 'memberships_total'], this.membresias.length) }
    ];
  }

  private metric(keys: string[], fallback: number): number {
    const source = this.resumen?.kpis ?? this.resumen?.stats ?? this.resumen;
    for (const key of keys) {
      const value = Number(source?.[key]);
      if (Number.isFinite(value)) return value;
    }
    return fallback;
  }

  retirarPaquete(pkg: any): void {
    if (!pkg?.id) return;
    this.request(`package-${pkg.id}`, this.http.patch<any>(this.endpoint(`/paquetes/${pkg.id}/retirar`), {}, { headers: this.authHeaders() }), () => this.loadPackages(), 'Paquete marcado como retirado.');
  }

  private isPending(state: unknown): boolean {
    return ['pendiente', 'en_revision', 'pendiente_revision'].includes(String(state ?? '').toLowerCase());
  }

  private summaryLabel(key: string): string {
    const labels: Record<string, string> = {
      pagos_pendientes: 'Pagos pendientes',
      pagos_total: 'Pagos registrados',
      payments_pending: 'Pagos pendientes',
      incidents_open: 'Incidentes abiertos',
      incidentes_abiertos: 'Incidentes abiertos',
      notificaciones_pendientes: 'Notificaciones pendientes',
      cuota_pendiente: 'Cuotas pendientes'
    };
    return labels[key] ?? key.replace(/_/g, ' ').replace(/^./, letter => letter.toLocaleUpperCase('es'));
  }
}
