import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { irisApiBase } from '../../services/api-url';

@Component({
  selector: 'app-password', standalone: true, imports: [CommonModule, FormsModule, RouterModule],
  template: `<main class="password-page"><section class="password-card"><p class="eyebrow">IRIS · Seguridad de la cuenta</p><h1>{{ resetMode ? 'Restablecer contraseña' : 'Cambiar contraseña' }}</h1><p>{{ resetMode ? 'Elige una contraseña nueva. El enlace es de un solo uso y vence pronto.' : 'Usa una contraseña larga que no reutilices en otros servicios.' }}</p><form (ngSubmit)="submit()"><label *ngIf="!resetMode"><span>Contraseña actual</span><input type="password" name="current" [(ngModel)]="currentPassword" autocomplete="current-password" required></label><label><span>Nueva contraseña</span><input type="password" name="password" [(ngModel)]="password" autocomplete="new-password" minlength="12" required><small>Mínimo 12 caracteres.</small></label><label><span>Confirmar contraseña</span><input type="password" name="confirmation" [(ngModel)]="confirmation" autocomplete="new-password" minlength="12" required></label><p class="error" *ngIf="error" role="alert">{{ error }}</p><p class="success" *ngIf="success" role="status">{{ success }}</p><button type="submit" [disabled]="busy">{{ busy ? 'Guardando…' : 'Actualizar contraseña' }}</button></form><a routerLink="/login" *ngIf="resetMode">Volver a iniciar sesión</a></section></main>`,
  styles: [`:host{display:block;min-height:100vh;background:#f2f7f6;color:#173d44;font-family:Arial,sans-serif}.password-page{min-height:100vh;display:grid;place-items:center;padding:20px}.password-card{width:min(470px,100%);padding:32px;border:1px solid #d5e4e1;border-radius:18px;background:#fff;box-shadow:0 14px 38px #173d4417}.eyebrow{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#176d69}.password-card h1{margin:8px 0}.password-card p{line-height:1.55;color:#58706f}.password-card form{display:grid;gap:16px;margin:22px 0}.password-card label{display:grid;gap:7px;font-weight:600}.password-card input{padding:12px;border:1px solid #cbd9d7;border-radius:9px;font:inherit}.password-card small{color:#687c7b;font-weight:400}.password-card button{padding:13px;border:0;border-radius:9px;background:#176d69;color:white;font-weight:700;cursor:pointer}.password-card button:disabled{opacity:.6}.password-card a{color:#176d69}.error{color:#a23131!important}.success{color:#176d69!important}`]
})
export class PasswordComponent {
  currentPassword = ''; password = ''; confirmation = ''; error = ''; success = ''; busy = false;
  readonly token = this.route.snapshot.queryParamMap.get('token') || '';
  readonly resetMode = Boolean(this.token);
  constructor(private http: HttpClient, private route: ActivatedRoute, private router: Router) {}
  submit(): void {
    this.error = ''; this.success = '';
    if (this.password.length < 12) { this.error = 'La contraseña debe tener al menos 12 caracteres.'; return; }
    if (this.password !== this.confirmation) { this.error = 'Las contraseñas no coinciden.'; return; }
    this.busy = true;
    const request = this.resetMode
      ? this.http.post<any>(`${irisApiBase()}/auth/reset-password`, { token: this.token, password: this.password })
      : this.http.post<any>(`${irisApiBase()}/auth/change-password`, { current_password: this.currentPassword, new_password: this.password }, { headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` } });
    request.subscribe({ next: () => { this.busy = false; this.success = 'Contraseña actualizada correctamente.'; if (this.resetMode) { window.setTimeout(() => this.router.navigate(['/login']), 1200); } else { const user = JSON.parse(localStorage.getItem('usuario') || '{}'); user.cambio_password_requerido = false; localStorage.setItem('usuario', JSON.stringify(user)); const path = user.rol === 'portero' ? '/portero' : user.rol === 'contador' ? '/contador' : (user.rol === 'admin' || user.es_super_admin ? '/admin' : '/residente'); window.setTimeout(() => this.router.navigate([path]), 700); } }, error: err => { this.busy = false; this.error = err?.error?.detail || 'No fue posible actualizar la contraseña.'; } });
  }
}
