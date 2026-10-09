import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { AuthService } from './auth.service';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private apiUrl = 'http://127.0.0.1:8000';

  constructor(private http: HttpClient, private auth: AuthService) {}

  private getHeaders(): HttpHeaders {
    return new HttpHeaders({
      'Authorization': `Bearer ${this.auth.getToken()}`
    });
  }

  // Conjuntos
  getConjuntos(): Observable<any> {
    return this.http.get(`${this.apiUrl}/conjuntos/`, { headers: this.getHeaders() });
  }

  // Zonas comunes
  getZonas(conjuntoId: number): Observable<any> {
    return this.http.get(`${this.apiUrl}/conjuntos/${conjuntoId}/zonas-comunes/`, { headers: this.getHeaders() });
  }

  // Inmuebles
  getInmuebles(conjuntoId: number): Observable<any> {
    return this.http.get(`${this.apiUrl}/conjuntos/${conjuntoId}/inmuebles/`, { headers: this.getHeaders() });
  }

  // Reservas
  getReservas(): Observable<any> {
    return this.http.get(`${this.apiUrl}/reservas/`, { headers: this.getHeaders() });
  }

  crearReserva(datos: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/reservas/`, datos, { headers: this.getHeaders() });
  }

  cambiarEstadoReserva(id: number, estado: string): Observable<any> {
    return this.http.patch(`${this.apiUrl}/reservas/${id}/estado`, { estado }, { headers: this.getHeaders() });
  }

  // PQRS
  getPQRS(): Observable<any> {
    return this.http.get(`${this.apiUrl}/pqrs/`, { headers: this.getHeaders() });
  }

  crearPQRS(datos: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/pqrs/`, datos, { headers: this.getHeaders() });
  }

  responderPQRS(id: number, datos: any): Observable<any> {
    return this.http.patch(`${this.apiUrl}/pqrs/${id}/responder`, datos, { headers: this.getHeaders() });
  }

  // PORTERÍA: visitantes
  registrarVisitante(datos: any) {
    return this.http.post(
      `${this.apiUrl}/porteria/visitantes`,
      datos,
      { headers: this.getHeaders() }
    );
  }

  listarVisitantes() {
    return this.http.get(
      `${this.apiUrl}/porteria/visitantes`,
      { headers: this.getHeaders() }
    );
  }

  // PORTERÍA: residentes
  buscarResidentes(nombreOApartamento: string) {
    const q = encodeURIComponent(nombreOApartamento);
    return this.http.get(
      `${this.apiUrl}/porteria/residentes?q=${q}`,
      { headers: this.getHeaders() }
    );
  }

  // PORTERÍA: validar acceso
  validarAcceso(datos: {
    visitante_id: number;
    inmueble_id?: number;
  }) {
    return this.http.post(
      `${this.apiUrl}/porteria/validar-acceso`,
      datos,
      { headers: this.getHeaders() }
    );
  }

  // PORTERÍA: novedades
  registrarNovedad(datos: {
    titulo: string;
    descripcion: string;
  }) {
    return this.http.post(
      `${this.apiUrl}/porteria/novedades`,
      datos,
      { headers: this.getHeaders() }
    );
  }

  consultarNovedades() {
    return this.http.get(
      `${this.apiUrl}/porteria/novedades`,
      { headers: this.getHeaders() }
    );
  }

  // PORTERÍA: historial de entradas y salidas
  consultarMovimientos() {
    return this.http.get(
      `${this.apiUrl}/porteria/movimientos`,
      { headers: this.getHeaders() }
    );
  }

  registrarSalida(movimientoId: number) {
    return this.http.post(
      `${this.apiUrl}/porteria/registrar-salida`,
      { movimiento_id: movimientoId },
      { headers: this.getHeaders() }
    );
  }

}
