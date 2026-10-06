import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { map, switchMap } from 'rxjs/operators';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatBadgeModule } from '@angular/material/badge';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { ApiService } from '../../../services/api.service';
import { AuthService } from '../../../services/auth.service';

@Component({
  selector: 'app-admin-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatToolbarModule,
    MatBadgeModule,
    MatProgressSpinnerModule
  ],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.css']
})
export class DashboardComponent implements OnInit {
  nombreUsuario = '';
  totalConjuntos = 0;
  totalInmuebles = 0;
  totalZonasComunes = 0;
  reservasPendientes = 0;
  pqrsPendientes = 0;
  cargando = false;
  errorCarga = false;

  constructor(
    private apiService: ApiService,
    private authService: AuthService,
    private router: Router
  ) {}

  ngOnInit(): void {
    const usuario = this.authService.getUsuario();
    if (usuario) this.nombreUsuario = usuario.nombre_completo;

    this.cargarResumen();
  }

  cargarResumen(): void {
    this.cargando = true;
    this.errorCarga = false;

    forkJoin({
      conjuntos: this.apiService.getConjuntos(),
      reservas: this.apiService.getReservas(),
      pqrs: this.apiService.getPQRS()
    }).pipe(
      switchMap(({ conjuntos, reservas, pqrs }) => {
        const inventarioPorConjunto = conjuntos.map((conjunto) =>
          forkJoin({
            inmuebles: this.apiService.getInmuebles(conjunto.id),
            zonas: this.apiService.getZonas(conjunto.id)
          })
        );

        const inventarios$ = inventarioPorConjunto.length
          ? forkJoin(inventarioPorConjunto)
          : of([]);

        return inventarios$.pipe(
          map((inventarios) => ({
            totalConjuntos: conjuntos.length,
            totalInmuebles: inventarios.reduce((total, inventario) => total + inventario.inmuebles.length, 0),
            totalZonasComunes: inventarios.reduce((total, inventario) => total + inventario.zonas.length, 0),
            reservasPendientes: reservas.filter((reserva) => reserva.estado === 'pendiente').length,
            pqrsPendientes: pqrs.filter((solicitud) => solicitud.estado !== 'resuelto').length
          }))
        );
      })
    ).subscribe({
      next: (resumen) => {
        this.totalConjuntos = resumen.totalConjuntos;
        this.totalInmuebles = resumen.totalInmuebles;
        this.totalZonasComunes = resumen.totalZonasComunes;
        this.reservasPendientes = resumen.reservasPendientes;
        this.pqrsPendientes = resumen.pqrsPendientes;
        this.cargando = false;
      },
      error: () => {
        this.cargando = false;
        this.errorCarga = true;
      }
    });
  }

  irAReservas(): void {
    this.router.navigate(['/admin/reservas']);
  }

  irAPQRS(): void {
    this.router.navigate(['/admin/pqrs']);
  }

  cerrarSesion(): void {
    this.authService.logout();
  }
}