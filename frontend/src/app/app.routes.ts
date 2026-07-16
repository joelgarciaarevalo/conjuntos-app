import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';

import { LoginComponent } from './components/login/login.component';
import { RegistroComponent } from './components/registro/registro.component';
import { DashboardComponent as ResidenteDashboard } from './components/residente/dashboard/dashboard.component';
import { ReservasComponent as ResidenteReservas } from './components/residente/reservas/reservas.component';
import { PqrsComponent as ResidentePqrs } from './components/residente/pqrs/pqrs.component';
import { DashboardComponent as AdminDashboard } from './components/admin/dashboard/dashboard.component';
import { ReservasComponent as AdminReservas } from './components/admin/reservas/reservas.component';
import { PqrsComponent as AdminPqrs } from './components/admin/pqrs/pqrs.component';

export const routes: Routes = [
  { path: '', redirectTo: '/login', pathMatch: 'full' },
  { path: 'login', component: LoginComponent },
  { path: 'registro', component: RegistroComponent },
  { path: 'residente', component: ResidenteDashboard, canActivate: [authGuard] },
  { path: 'residente/reservas', component: ResidenteReservas, canActivate: [authGuard] },
  { path: 'residente/pqrs', component: ResidentePqrs, canActivate: [authGuard] },
  { path: 'admin', component: AdminDashboard, canActivate: [authGuard] },
  { path: 'admin/reservas', component: AdminReservas, canActivate: [authGuard] },
  { path: 'admin/pqrs', component: AdminPqrs, canActivate: [authGuard] },
];