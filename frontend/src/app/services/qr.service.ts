import { Injectable } from '@angular/core';
import { irisApiBase } from './api-url';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AuthService } from './auth.service';

export type TipoQR = 'visita' | 'reserva' | 'residente';
export type EstadoQR = 'activo' | 'programado' | 'vencido' | 'agotado' | 'revocado';
export interface CodigoQR { id: number; token: string; tipo: TipoQR; estado: EstadoQR; inmueble_id: number | null; inmueble_etiqueta: string | null; residente_id: number | null; residente_nombre: string | null; reserva_id: number | null; zona_nombre: string | null; visitante_nombre: string | null; visitante_documento: string | null; valido_desde: string; valido_hasta: string | null; usos_maximos: number | null; usos_actuales: number; activo: boolean; creado_en: string; }
export interface ResidenteOpcion { inmueble_id: number; inmueble_etiqueta: string; residente_id: number; nombre: string; rol: string; tiene_qr: boolean; }
export interface ReservaOpcion { id: number; etiqueta: string; inmueble_id: number; fecha_inicio: string; fecha_fin: string; tiene_qr: boolean; }
export interface CatalogoQR { residentes: ResidenteOpcion[]; reservas: ReservaOpcion[]; }
export interface QRCrear { tipo: TipoQR; inmueble_id?: number; residente_id?: number; reserva_id?: number; visitante_nombre?: string; visitante_documento?: string; horas_validez?: number; usos_maximos?: number; }
export interface ResultadoValidacion { valido: boolean; motivo: string; estado: string | null; qr: CodigoQR | null; }
export interface AccesoQR { id: number; fecha: string; resultado: string; motivo: string; descripcion: string; validado_por: string | null; }
export interface ResultadoLote { creados: number; omitidos: number; }
@Injectable({ providedIn: 'root' })
export class QrService {
  private apiUrl = irisApiBase();
  constructor(private http: HttpClient, private auth: AuthService) {}
  private getHeaders(): HttpHeaders { return new HttpHeaders({ Authorization: `Bearer ${this.auth.getToken()}` }); }
  getCatalogo(): Observable<CatalogoQR> { return this.http.get<CatalogoQR>(`${this.apiUrl}/qr/catalogo`, { headers: this.getHeaders() }); }
  listar(): Observable<CodigoQR[]> { return this.http.get<CodigoQR[]>(`${this.apiUrl}/qr/`, { headers: this.getHeaders() }); }
  listarMios(): Observable<CodigoQR[]> { return this.http.get<CodigoQR[]>(`${this.apiUrl}/qr/mio`, { headers: this.getHeaders() }); }
  crearMiQr(inmuebleId: number): Observable<CodigoQR> { return this.http.post<CodigoQR>(`${this.apiUrl}/qr/mio/residente?inmueble_id=${inmuebleId}`, {}, { headers: this.getHeaders() }); }
  crearQrVisita(datos: QRCrear): Observable<CodigoQR> { return this.http.post<CodigoQR>(`${this.apiUrl}/qr/mio/visitas`, datos, { headers: this.getHeaders() }); }
  revocarMio(id: number): Observable<CodigoQR> { return this.http.post<CodigoQR>(`${this.apiUrl}/qr/mio/${id}/revocar`, {}, { headers: this.getHeaders() }); }
  crear(datos: QRCrear): Observable<CodigoQR> { return this.http.post<CodigoQR>(`${this.apiUrl}/qr/`, datos, { headers: this.getHeaders() }); }
  generarParaTodosLosResidentes(): Observable<ResultadoLote> { return this.http.post<ResultadoLote>(`${this.apiUrl}/qr/lote-residentes`, {}, { headers: this.getHeaders() }); }
  revocar(id: number): Observable<CodigoQR> { return this.http.post<CodigoQR>(`${this.apiUrl}/qr/${id}/revocar`, {}, { headers: this.getHeaders() }); }
  regenerar(id: number): Observable<CodigoQR> { return this.http.post<CodigoQR>(`${this.apiUrl}/qr/${id}/regenerar`, {}, { headers: this.getHeaders() }); }
  validar(codigo: string, registrarIngreso: boolean): Observable<ResultadoValidacion> { return this.http.post<ResultadoValidacion>(`${this.apiUrl}/qr/validar`, { codigo, registrar_ingreso: registrarIngreso }, { headers: this.getHeaders() }); }
  accesosRecientes(limite = 10): Observable<AccesoQR[]> { return this.http.get<AccesoQR[]>(`${this.apiUrl}/qr/accesos/recientes?limite=${limite}`, { headers: this.getHeaders() }); }
}
