import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { AuthService } from '../../services/auth.service';
import { HttpClient } from '@angular/common/http';
import { irisApiBase } from '../../services/api-url';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatCardModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule
  ],
  templateUrl: './login.component.html',
  styleUrl: './login.component.css'
})
export class LoginComponent {
  form: FormGroup;
  cargando = false;
  recuperando = false;
  mensajeRecuperacion = '';
  desafio2fa = '';
  codigo2fa = '';
  error2fa = '';
  mostrarContrasena = false;

  constructor(
    private fb: FormBuilder,
    private authService: AuthService,
    private router: Router,
    private snackBar: MatSnackBar,
    private http: HttpClient
  ) {
    this.form = this.fb.group({
      email: ['', [Validators.required, Validators.email]],
      password: ['', Validators.required]
    });
  }

  recuperarContrasena(): void {
    const email = String(this.form.get('email')?.value || '').trim().toLowerCase();
    if (!email || this.form.get('email')?.invalid) { this.mensajeRecuperacion = 'Escribe primero un correo válido en el campo de correo.'; return; }
    this.recuperando = true; this.mensajeRecuperacion = '';
    this.http.post<any>(`${irisApiBase()}/auth/forgot-password`, { email }).subscribe({
      next: response => { this.recuperando = false; if (response?.debug_token) { this.router.navigate(['/reset-password'], { queryParams: { token: response.debug_token } }); return; } this.mensajeRecuperacion = response?.mensaje || 'Si la cuenta existe, recibirás instrucciones en el correo registrado.'; },
      error: () => { this.recuperando = false; this.mensajeRecuperacion = 'No fue posible solicitar el restablecimiento. Inténtalo más tarde.'; }
    });
  }

  login(): void {
    if (this.form.invalid) return;
    this.cargando = true;

    this.authService.login(this.form.value).subscribe({
      next: (respuesta) => {
        this.cargando = false;
        // Cuenta con segundo factor activo: IRIS pide el código antes de emitir la sesión.
        if (respuesta?.requiere_2fa) {
          this.desafio2fa = respuesta.desafio;
          this.codigo2fa = '';
          this.error2fa = '';
          return;
        }
        this.router.navigate([this.authService.rutaInicial()]);
      },
      error: (err) => {
        this.cargando = false;
        const detalle = err.error?.detail;
        this.snackBar.open(
          typeof detalle === 'string' ? detalle : detalle?.mensaje || 'Error al iniciar sesión',
          'Cerrar',
          { duration: 3000 }
        );
      }
    });
  }

  /** Completa el inicio de sesión con el código de la app de autenticación o de recuperación. */
  verificarSegundoFactor(): void {
    const codigo = String(this.codigo2fa || '').trim();
    if (!codigo) { this.error2fa = 'Ingresa el código de 6 dígitos o uno de tus códigos de recuperación.'; return; }
    this.cargando = true;
    this.error2fa = '';
    this.authService.verificarSegundoFactor(this.desafio2fa, codigo).subscribe({
      next: () => { this.cargando = false; this.router.navigate([this.authService.rutaInicial()]); },
      error: (err) => {
        this.cargando = false;
        this.error2fa = err.error?.detail || 'El código no es válido o el desafío venció. Intenta de nuevo.';
      }
    });
  }

  cancelarSegundoFactor(): void {
    this.desafio2fa = '';
    this.codigo2fa = '';
    this.error2fa = '';
  }
}
