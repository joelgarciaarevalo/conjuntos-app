import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';
export const roleGuard = (roles: string[]): CanActivateFn => () => {
  const auth = inject(AuthService); const router = inject(Router); const user = auth.getUsuario();
  if (!auth.estaAutenticado()) { router.navigate(['/login']); return false; }
  const role = user?.es_super_admin ? 'admin' : (user?.rol || 'residente');
  if (roles.includes(role)) return true;
  router.navigate([role === 'portero' ? '/portero' : role === 'contador' ? '/contador' : role === 'admin' ? '/admin' : '/residente']);
  return false;
};
