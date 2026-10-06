import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';
import { roleGuard } from './guards/role.guard';
import { LoginComponent } from './components/login/login.component';
import { RegistroComponent } from './components/registro/registro.component';
import { DashboardComponent as ResidenteDashboard } from './components/residente/dashboard/dashboard.component';
import { ReservasComponent as ResidenteReservas } from './components/residente/reservas/reservas.component';
import { PqrsComponent as ResidentePqrs } from './components/residente/pqrs/pqrs.component';
import { ResidenteQrComponent } from './components/residente/qr/qr.component';
import { ComunidadComponent } from './components/residente/comunidad/comunidad.component';
import { DashboardComponent as AdminDashboard } from './components/admin/dashboard/dashboard.component';
import { ReservasComponent as AdminReservas } from './components/admin/reservas/reservas.component';
import { PqrsComponent as AdminPqrs } from './components/admin/pqrs/pqrs.component';
import { QrComponent as AdminQr } from './components/admin/qr/qr.component';
import { GestionComponent } from './components/admin/gestion/gestion.component';
import { EscannerComponent } from './components/portero/escanner.component';
import { PlusComponent } from './components/plus/plus.component';
import { PasswordComponent } from './components/auth/password.component';
import { V3Component } from './components/v3/v3.component';
import { ContadorComponent } from './components/contador/contador.component';

export const routes: Routes = [
  { path: '', redirectTo: '/login', pathMatch: 'full' },
  { path: 'login', component: LoginComponent }, { path: 'registro', component: RegistroComponent },
  { path: 'reset-password', component: PasswordComponent },
  { path: 'auth/password', component: PasswordComponent, canActivate: [authGuard] },
  { path: 'residente', component: ResidenteDashboard, canActivate: [authGuard, roleGuard(['residente'])] },
  { path: 'residente/reservas', component: ResidenteReservas, canActivate: [authGuard, roleGuard(['residente'])] },
  { path: 'residente/pqrs', component: ResidentePqrs, canActivate: [authGuard, roleGuard(['residente'])] },
  { path: 'residente/qr', component: ResidenteQrComponent, canActivate: [authGuard, roleGuard(['residente'])] },
  { path: 'residente/comunidad', component: ComunidadComponent, canActivate: [authGuard, roleGuard(['residente'])] },
  { path: 'residente/servicios', component: PlusComponent, canActivate: [authGuard, roleGuard(['residente'])] },
  { path: 'residente/modulos', component: V3Component, canActivate: [authGuard, roleGuard(['residente'])] },
  { path: 'admin', component: AdminDashboard, canActivate: [authGuard, roleGuard(['admin'])] },
  { path: 'admin/reservas', component: AdminReservas, canActivate: [authGuard, roleGuard(['admin'])] },
  { path: 'admin/pqrs', component: AdminPqrs, canActivate: [authGuard, roleGuard(['admin'])] },
  { path: 'admin/qr', component: AdminQr, canActivate: [authGuard, roleGuard(['admin'])] },
  { path: 'admin/gestion', component: GestionComponent, canActivate: [authGuard, roleGuard(['admin'])] },
  { path: 'admin/plus', component: PlusComponent, canActivate: [authGuard, roleGuard(['admin'])] },
  { path: 'admin/modulos', component: V3Component, canActivate: [authGuard, roleGuard(['admin'])] },
  { path: 'portero', component: EscannerComponent, canActivate: [authGuard, roleGuard(['portero','admin'])] },
  { path: 'contador', component: ContadorComponent, canActivate: [authGuard, roleGuard(['contador'])] },
  { path: 'portero/servicios', component: PlusComponent, canActivate: [authGuard, roleGuard(['portero','admin'])] },
  { path: 'portero/modulos', component: V3Component, canActivate: [authGuard, roleGuard(['portero','admin'])] },
  { path: '**', redirectTo: '/login' }
];
