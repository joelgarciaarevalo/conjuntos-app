import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatTableModule } from '@angular/material/table';
import { MatChipsModule } from '@angular/material/chips';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../../services/api.service';
import { AuthService } from '../../../services/auth.service';

@Component({
  selector: 'app-admin-reservas',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatToolbarModule,
    MatTableModule,
    MatChipsModule,
    MatSnackBarModule
  ],
  templateUrl: './reservas.component.html',
  styleUrls: ['./reservas.component.css']
})
export class ReservasComponent implements OnInit {
  reservas: any[] = [];
  columnas = ['id', 'inmueble', 'zona', 'fecha_inicio', 'fecha_fin', 'estado', 'acciones'];

  constructor(
    private apiService: ApiService,
    private authService: AuthService,
    private router: Router,
    private snackBar: MatSnackBar
  ) {}

  ngOnInit(): void {
    this.cargarReservas();
  }

  cargarReservas(): void {
    this.apiService.getReservas().subscribe({
      next: (data) => this.reservas = data,
      error: () => this.snackBar.open('Error al cargar reservas', 'Cerrar', { duration: 3000 })
    });
  }

  cambiarEstado(id: number, estado: string): void {
    this.apiService.cambiarEstadoReserva(id, estado).subscribe({
      next: () => {
        this.snackBar.open(`Reserva ${estado} exitosamente`, 'Cerrar', { duration: 3000 });
        this.cargarReservas();
      },
      error: (err) => {
        this.snackBar.open(
          err.error?.detail || 'Error al cambiar estado',
          'Cerrar',
          { duration: 3000 }
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
    this.router.navigate(['/admin']);
  }

  cerrarSesion(): void {
    this.authService.logout();
  }
}