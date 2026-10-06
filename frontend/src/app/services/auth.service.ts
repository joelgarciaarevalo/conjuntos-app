import { Injectable } from '@angular/core';
import { irisApiBase } from './api-url';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable } from 'rxjs';
import { tap } from 'rxjs/operators';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private apiUrl = irisApiBase();
  constructor(private http: HttpClient, private router: Router) {}

  registro(datos: any): Observable<any> { return this.http.post(`${this.apiUrl}/auth/registro`, datos); }

  /** Guarda la sesión local a partir de la respuesta (login o segundo factor). */
  guardarSesion(r: any): void {
    if (!r?.access_token) return;
    localStorage.setItem('token', r.access_token);
    localStorage.setItem('usuario', JSON.stringify({
      nombre_completo: r.nombre_completo,
      es_super_admin: r.es_super_admin,
      rol: r.rol || (r.es_super_admin ? 'admin' : 'residente'),
      id: r.id,
      cambio_password_requerido: Boolean(r.cambio_password_requerido),
    }));
  }

  login(datos: any): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/auth/login`, datos).pipe(tap((r) => {
      // Si la cuenta tiene segundo factor activo, la respuesta trae un desafío y
      // todavía no hay token: se completa con verificarSegundoFactor().
      if (r?.access_token) this.guardarSesion(r);
    }));
  }

  /** Segundo paso del inicio de sesión: código TOTP o código de recuperación. */
  verificarSegundoFactor(desafio: string, codigo: string): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/v3/seguridad/2fa/login`, { desafio, codigo }).pipe(
      tap((r) => this.guardarSesion(r))
    );
  }

  /** Ruta inicial según el rol de la sesión activa. */
  rutaInicial(usuario: any = this.getUsuario()): string {
    if (usuario?.cambio_password_requerido) return '/auth/password';
    if (usuario?.rol === 'portero') return '/portero';
    if (usuario?.rol === 'contador') return '/contador';
    if (usuario?.es_super_admin || usuario?.rol === 'admin') return '/admin';
    return '/residente';
  }

  logout(): void { localStorage.removeItem('token'); localStorage.removeItem('usuario'); this.router.navigate(['/login']); }
  getToken(): string | null { return localStorage.getItem('token'); }
  estaAutenticado(): boolean { return !!this.getToken(); }
  getUsuario(): any { const value = localStorage.getItem('usuario'); return value ? JSON.parse(value) : null; }
}
