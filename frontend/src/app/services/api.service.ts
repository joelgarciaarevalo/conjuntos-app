import { Injectable } from '@angular/core';
import { irisApiBase } from './api-url';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { AuthService } from './auth.service';
import { Observable } from 'rxjs';

export interface Conjunto { id: number; nombre: string; nit: string; direccion: string; }
export interface Inmueble { id: number; conjunto_id: number; torre: string | null; numero: string; propietario_id: number; inquilino_id: number | null; estado: string; }
export interface ZonaComun { id: number; conjunto_id: number; nombre: string; requiere_aprobacion: boolean; hora_apertura: string; hora_cierre: string; duracion_max_minutos: number; }
export interface Reserva { id: number; zona_id: number; inmueble_id: number; solicitante_id: number; fecha_inicio: string; fecha_fin: string; estado: string; }
export interface Pqrs { id: number; inmueble_id: number; solicitante_id: number; tipo: string; descripcion: string; estado: string; fecha_radicacion: string; respuesta_admin: string | null; }

@Injectable({ providedIn: 'root' })
export class ApiService {
  readonly apiUrl = irisApiBase();
  constructor(private http: HttpClient, private auth: AuthService) {}
  private opts() { return { headers: new HttpHeaders({ Authorization: `Bearer ${this.auth.getToken()}` }) }; }
  private jsonOpts() { return { ...this.opts(), headers: this.opts().headers.set('Content-Type', 'application/json') }; }

  getConjuntos(): Observable<Conjunto[]> { return this.http.get<Conjunto[]>(`${this.apiUrl}/conjuntos/`, this.opts()); }
  getZonas(id: number): Observable<ZonaComun[]> { return this.http.get<ZonaComun[]>(`${this.apiUrl}/conjuntos/${id}/zonas-comunes/`, this.opts()); }
  getInmuebles(id: number): Observable<Inmueble[]> { return this.http.get<Inmueble[]>(`${this.apiUrl}/conjuntos/${id}/inmuebles/`, this.opts()); }
  crearInmueble(cid: number, data: any) { return this.http.post(`${this.apiUrl}/conjuntos/${cid}/inmuebles`, data, this.jsonOpts()); }
  editarInmueble(cid: number, id: number, data: any) { return this.http.patch(`${this.apiUrl}/conjuntos/${cid}/inmuebles/${id}`, data, this.jsonOpts()); }
  borrarInmueble(cid: number, id: number) { return this.http.delete(`${this.apiUrl}/conjuntos/${cid}/inmuebles/${id}`, this.opts()); }
  crearZona(cid: number, data: any) { return this.http.post(`${this.apiUrl}/conjuntos/${cid}/zonas-comunes`, data, this.jsonOpts()); }
  editarZona(cid: number, id: number, data: any) { return this.http.patch(`${this.apiUrl}/conjuntos/${cid}/zonas-comunes/${id}`, data, this.jsonOpts()); }
  borrarZona(cid: number, id: number) { return this.http.delete(`${this.apiUrl}/conjuntos/${cid}/zonas-comunes/${id}`, this.opts()); }
  getReservas(): Observable<Reserva[]> { return this.http.get<Reserva[]>(`${this.apiUrl}/reservas/`, this.opts()); }
  crearReserva(data: any) { return this.http.post(`${this.apiUrl}/reservas/`, data, this.jsonOpts()); }
  cancelarReserva(id: number) { return this.http.post<Reserva>(`${this.apiUrl}/reservas/${id}/cancelar`, {}, this.jsonOpts()); }
  disponibilidad(zonaId: number, desde: string, hasta: string) { return this.http.get<Reserva[]>(`${this.apiUrl}/reservas/disponibilidad`, { ...this.opts(), params: { zona_id: zonaId, desde, hasta } }); }
  cambiarEstadoReserva(id: number, estado: string) { return this.http.patch(`${this.apiUrl}/reservas/${id}/estado`, { estado }, this.jsonOpts()); }
  getPQRS(): Observable<Pqrs[]> { return this.http.get<Pqrs[]>(`${this.apiUrl}/pqrs/`, this.opts()); }
  crearPQRS(data: any) { return this.http.post(`${this.apiUrl}/pqrs/`, data, this.jsonOpts()); }
  responderPQRS(id: number, data: any) { return this.http.patch(`${this.apiUrl}/pqrs/${id}/responder`, data, this.jsonOpts()); }
  getNotificaciones() { return this.http.get<any[]>(`${this.apiUrl}/notificaciones/`, this.opts()); }
  marcarNotificacion(id: number) { return this.http.patch(`${this.apiUrl}/notificaciones/${id}/leida`, {}, this.jsonOpts()); }
  getAnuncios() { return this.http.get<any[]>(`${this.apiUrl}/comunicados/`, this.opts()); }
  crearAnuncio(data: any) { return this.http.post(`${this.apiUrl}/comunicados/`, data, this.jsonOpts()); }
  getCuotas() { return this.http.get<any[]>(`${this.apiUrl}/cuotas/`, this.opts()); }
  crearCuota(data: any) { return this.http.post(`${this.apiUrl}/cuotas/`, data, this.jsonOpts()); }
  cambiarPago(id: number, pagada: boolean) { return this.http.patch(`${this.apiUrl}/cuotas/${id}/pago`, { pagada }, this.jsonOpts()); }
  getPaquetes() { return this.http.get<any[]>(`${this.apiUrl}/paquetes/`, this.opts()); }
  recibirPaquete(data: any) { return this.http.post(`${this.apiUrl}/paquetes/`, data, this.jsonOpts()); }
  retirarPaquete(id: number, nombre: string) { return this.http.patch(`${this.apiUrl}/paquetes/${id}/retirar`, { retirado_por: nombre }, this.jsonOpts()); }
  getParqueaderos() { return this.http.get<any[]>(`${this.apiUrl}/parqueaderos/`, this.opts()); }
  crearParqueadero(data: any) { return this.http.post(`${this.apiUrl}/parqueaderos/`, data, this.jsonOpts()); }
  actualizarParqueadero(id: number, data: any) { return this.http.patch(`${this.apiUrl}/parqueaderos/${id}`, data, this.jsonOpts()); }
  generarCobrosParqueadero(data: any) { return this.http.post<any>(`${this.apiUrl}/parqueaderos/generar-cobros`, data, this.jsonOpts()); }
  getUsuarios() { return this.http.get<any[]>(`${this.apiUrl}/gestion/usuarios`, this.opts()); }
  cambiarRol(id: number, rol: string) { return this.http.patch(`${this.apiUrl}/gestion/usuarios/${id}/rol`, { rol }, this.jsonOpts()); }
  crearContador(conjuntoId: number, data: any) { return this.http.post<any>(`${this.apiUrl}/gestion/conjuntos/${conjuntoId}/contadores`, data, this.jsonOpts()); }
  descargarReporte(tipo: string) { return this.http.get(`${this.apiUrl}/reportes/${tipo}.xlsx`, { ...this.opts(), responseType: 'blob' }); }
  pazYSalvo(id: number) { return this.http.get<any>(`${this.apiUrl}/cuotas/paz-y-salvo/${id}`, this.opts()); }
}
