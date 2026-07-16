import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatBadgeModule } from '@angular/material/badge';
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
    MatBadgeModule
  ],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.css']
})
export class DashboardComponent implements OnInit {
  nombreUsuario = '';
  reservasPendientes = 0;
  pqrsPendientes = 0;

  constructor(
    private apiService: ApiService,
    private authService: AuthService,
    private router: Router
  ) {}

  ngOnInit(): void {
    const usuario = this.authService.getUsuario();
    if (usuario) this.nombreUsuario = usuario.nombre_completo;

    this.apiService.getReservas().subscribe({
      next: (data) => {
        this.reservasPendientes = data.filter((r: any) => r.estado === 'pendiente').length;
      }
    });

    this.apiService.getPQRS().subscribe({
      next: (data) => {
        this.pqrsPendientes = data.filter((p: any) => p.estado === 'radicado').length;
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