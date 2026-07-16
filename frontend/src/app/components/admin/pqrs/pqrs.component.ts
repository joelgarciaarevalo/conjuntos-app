import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatChipsModule } from '@angular/material/chips';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatExpansionModule } from '@angular/material/expansion';
import { ApiService } from '../../../services/api.service';
import { AuthService } from '../../../services/auth.service';

@Component({
  selector: 'app-admin-pqrs',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatToolbarModule,
    MatInputModule,
    MatSelectModule,
    MatChipsModule,
    MatSnackBarModule,
    MatExpansionModule
  ],
  templateUrl: './pqrs.component.html',
  styleUrls: ['./pqrs.component.css']
})
export class PqrsComponent implements OnInit {
  pqrsList: any[] = [];
  formularios: { [key: number]: FormGroup } = {};

  constructor(
    private fb: FormBuilder,
    private apiService: ApiService,
    private authService: AuthService,
    private router: Router,
    private snackBar: MatSnackBar
  ) {}

  ngOnInit(): void {
    this.cargarPQRS();
  }

  cargarPQRS(): void {
    this.apiService.getPQRS().subscribe({
      next: (data) => {
        this.pqrsList = data;
        // Crear un formulario de respuesta para cada PQRS
        data.forEach((pqrs: any) => {
          this.formularios[pqrs.id] = this.fb.group({
            respuesta_admin: ['', Validators.required],
            estado: ['en_proceso', Validators.required]
          });
        });
      },
      error: () => this.snackBar.open('Error al cargar PQRS', 'Cerrar', { duration: 3000 })
    });
  }

  responder(pqrsId: number): void {
    const form = this.formularios[pqrsId];
    if (form.invalid) return;

    this.apiService.responderPQRS(pqrsId, form.value).subscribe({
      next: () => {
        this.snackBar.open('Respuesta enviada exitosamente', 'Cerrar', { duration: 3000 });
        this.cargarPQRS();
      },
      error: (err) => {
        this.snackBar.open(
          err.error?.detail || 'Error al responder',
          'Cerrar',
          { duration: 3000 }
        );
      }
    });
  }

  getColorEstado(estado: string): string {
    const colores: any = {
      'radicado': 'accent',
      'en_proceso': 'primary',
      'resuelto': ''
    };
    return colores[estado] || '';
  }

  volver(): void {
    this.router.navigate(['/admin']);
  }

  cerrarSesion(): void {
    this.authService.logout();
  }
}