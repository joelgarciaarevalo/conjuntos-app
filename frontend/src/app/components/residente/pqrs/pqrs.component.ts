import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatIconModule } from '@angular/material/icon';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatChipsModule } from '@angular/material/chips';
import { MatExpansionModule } from '@angular/material/expansion';
import { ApiService } from '../../../services/api.service';
import { AuthService } from '../../../services/auth.service';

@Component({
  selector: 'app-residente-pqrs',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatInputModule,
    MatSelectModule,
    MatTableModule,
    MatIconModule,
    MatToolbarModule,
    MatSnackBarModule,
    MatChipsModule,
    MatExpansionModule
  ],
  templateUrl: './pqrs.component.html',
  styleUrls: ['./pqrs.component.css']
})
export class PqrsComponent implements OnInit {
  form: FormGroup;
  pqrsList: any[] = [];
  inmuebles: any[] = [];
  cargando = false;
  tiposPQRS = ['peticion', 'queja', 'reclamo', 'sugerencia'];

  constructor(
    private fb: FormBuilder,
    private apiService: ApiService,
    private authService: AuthService,
    private router: Router,
    private snackBar: MatSnackBar
  ) {
    this.form = this.fb.group({
      inmueble_id: ['', Validators.required],
      tipo: ['', Validators.required],
      descripcion: ['', [Validators.required, Validators.minLength(10)]]
    });
  }

  ngOnInit(): void {
    this.cargarDatos();
  }

  cargarDatos(): void {
    this.apiService.getPQRS().subscribe({
      next: (data) => this.pqrsList = data,
      error: () => this.snackBar.open('Error al cargar PQRS', 'Cerrar', { duration: 3000 })
    });

    this.apiService.getConjuntos().subscribe({
      next: (conjuntos) => {
        if (conjuntos.length > 0) {
          const conjuntoId = conjuntos[0].id;
          this.apiService.getInmuebles(conjuntoId).subscribe({
            next: (data) => {
              const usuario = this.authService.getUsuario();
              this.inmuebles = data.filter((i: any) =>
                i.propietario_id === usuario.id || i.inquilino_id === usuario.id
              );
            }
          });
        }
      }
    });
  }

  crearPQRS(): void {
    if (this.form.invalid) return;
    this.cargando = true;

    this.apiService.crearPQRS(this.form.value).subscribe({
      next: () => {
        this.snackBar.open('¡PQRS radicada exitosamente!', 'Cerrar', { duration: 3000 });
        this.form.reset();
        this.cargando = false;
        this.cargarDatos();
      },
      error: (err) => {
        this.cargando = false;
        this.snackBar.open(
          err.error?.detail || 'Error al radicar la PQRS',
          'Cerrar',
          { duration: 4000 }
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
    this.router.navigate(['/residente']);
  }

  cerrarSesion(): void {
    this.authService.logout();
  }
}