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
}