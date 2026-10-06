import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { toDataURL } from 'qrcode';
import { ApiService, Inmueble } from '../../../services/api.service';
import { AuthService } from '../../../services/auth.service';
import { CodigoQR, QrService } from '../../../services/qr.service';

@Component({ selector: 'app-residente-qr', standalone: true, imports: [CommonModule, FormsModule], templateUrl: './qr.component.html', styleUrls: ['./qr.component.css'] })
export class ResidenteQrComponent implements OnInit {
  inmuebles: Inmueble[] = []; codigos: CodigoQR[] = []; images: Record<number, string> = {};
  inmuebleId = 0; nombre = ''; documento = ''; horas = 24; usos = 1; busy = false; error = '';
  constructor(private api: ApiService, private qr: QrService, public auth: AuthService, private router: Router) {}
  ngOnInit() {
    const user = this.auth.getUsuario();
    this.api.getConjuntos().subscribe({ next: cs => cs.forEach(c => this.api.getInmuebles(c.id).subscribe({ next: units => { this.inmuebles.push(...units.filter(u => u.propietario_id === user.id || u.inquilino_id === user.id)); if (!this.inmuebleId && this.inmuebles.length) this.inmuebleId = this.inmuebles[0].id; this.load(); } })) });
    this.load();
  }
  load() { this.qr.listarMios().subscribe({ next: xs => { this.codigos = xs; xs.forEach(x => this.paint(x)); }, error: e => this.error = e.error?.detail || 'No se pudieron cargar tus códigos.' }); }
  private paint(q: CodigoQR) { toDataURL(`IRIS-QR:${q.token}`, { width: 240, margin: 2, color: { dark: '#0c3b45', light: '#ffffff' } }).then(url => this.images[q.id] = url); }
  generarMiQr() { if (!this.inmuebleId || this.busy) return; this.busy = true; this.qr.crearMiQr(this.inmuebleId).subscribe({ next: x => { this.busy = false; this.upsert(x); }, error: e => { this.busy = false; this.error = e.error?.detail || 'No se pudo crear el QR'; } }); }
  crearVisita() { if (!this.inmuebleId || !this.nombre.trim() || this.busy) return; this.busy = true; this.qr.crearQrVisita({ tipo: 'visita', inmueble_id: this.inmuebleId, visitante_nombre: this.nombre.trim(), visitante_documento: this.documento.trim() || undefined, horas_validez: this.horas, usos_maximos: this.usos }).subscribe({ next: x => { this.busy = false; this.nombre = ''; this.documento = ''; this.upsert(x); }, error: e => { this.busy = false; this.error = e.error?.detail || 'No se pudo crear la invitación'; } }); }
  private upsert(x: CodigoQR) { this.codigos = [x, ...this.codigos.filter(y => y.id !== x.id)]; this.paint(x); this.error = ''; }
  revoke(x: CodigoQR) { if (!confirm('¿Revocar este código? Dejará de ser válido inmediatamente.')) return; this.qr.revocarMio(x.id).subscribe({ next: q => this.upsert(q), error: e => this.error = e.error?.detail || 'No se pudo revocar' }); }
  download(x: CodigoQR) { const a = document.createElement('a'); a.href = this.images[x.id]; a.download = `iris-qr-${x.tipo}-${x.id}.png`; a.click(); }
  etiqueta(x: CodigoQR) { return x.tipo === 'visita' ? `Visita: ${x.visitante_nombre}` : x.tipo === 'residente' ? 'Mi QR de residente' : `Reserva ${x.zona_nombre || ''}`; }
  back() { this.router.navigate(['/residente']); }
  logout() { this.auth.logout(); }
}
