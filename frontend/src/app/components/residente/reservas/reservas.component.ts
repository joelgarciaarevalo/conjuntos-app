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
import { ApiService } from '../../../services/api.service';
import { AuthService } from '../../../services/auth.service';

@Component({
  selector: 'app-residente-reservas',
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
    MatChipsModule
  ],
  templateUrl: './reservas.component.html',
  styleUrls: ['./reservas.component.css']
})
export class ReservasComponent implements OnInit {
  form: FormGroup;
  reservas: any[] = [];
  zonas: any[] = [];
  inmuebles: any[] = [];
  cargando = false;
  columnas = ['zona', 'fecha_inicio', 'fecha_fin', 'estado'];

  constructor(
    private fb: FormBuilder,
    private apiService: ApiService,
    private authService: AuthService,
    private router: Router,
    private snackBar: MatSnackBar
  ) {
    this.form = this.fb.group({
      zona_id: ['', Validators.required],
      inmueble_id: ['', Validators.required],
      fecha_inicio: ['', Validators.required],
      fecha_fin: ['', Validators.required]
    });
  }

  ngOnInit(): void {
    this.cargarDatos();
  }

  cargarDatos(): void {
    // Cargar reservas del usuario
    this.apiService.getReservas().subscribe({
      next: (data) => this.reservas = data,
      error: () => this.snackBar.open('Error al cargar reservas', 'Cerrar', { duration: 3000 })
    });

    // Cargar conjuntos para obtener zonas e inmuebles
    this.apiService.getConjuntos().subscribe({
      next: (conjuntos) => {
        if (conjuntos.length > 0) {
          const conjuntoId = conjuntos[0].id;
          this.apiService.getZonas(conjuntoId).subscribe({
            next: (data) => this.zonas = data
          });
          this.apiService.getInmuebles(conjuntoId).subscribe({
            next: (data) => {
              const usuario = this.authService.getUsuario();
              // Solo mostrar inmuebles donde el usuario es propietario o inquilino
              this.inmuebles = data.filter((i: any) =>
                i.propietario_id === usuario.id || i.inquilino_id === usuario.id
              );
            }
          });
        }
      }
    });
  }

  crearReserva(): void {
    if (this.form.invalid) return;
    this.cargando = true;

    const datos = {
      zona_id: this.form.value.zona_id,
      inmueble_id: this.form.value.inmueble_id,
      fecha_inicio: new Date(this.form.value.fecha_inicio).toISOString(),
      fecha_fin: new Date(this.form.value.fecha_fin).toISOString()
    };

    this.apiService.crearReserva(datos).subscribe({
      next: () => {
        this.snackBar.open('¡Reserva creada exitosamente!', 'Cerrar', { duration: 3000 });
        this.form.reset();
        this.cargando = false;
        this.cargarDatos();
      },
      error: (err) => {
        this.cargando = false;
        this.snackBar.open(
          err.error?.detail || 'Error al crear la reserva',
          'Cerrar',
          { duration: 4000 }
        );
      }
    });
  }

  getColorEstado(estado: string): string {
    const colores: any = {
      'pendiente': 'accent',
      'aprobada': 'primary',
      'rechazada': 'warn',
      'cancelada': ''
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