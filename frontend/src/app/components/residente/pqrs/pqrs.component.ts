import { Component, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { debounceTime } from 'rxjs/operators';
import { toDataURL } from 'qrcode';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatIconModule } from '@angular/material/icon';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatChipsModule } from '@angular/material/chips';
import { MatExpansionModule } from '@angular/material/expansion';
import { ApiService } from '../../../services/api.service';
import { AuthService } from '../../../services/auth.service';

@Component({
  selector: 'app-residente-pqrs',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatInputModule,
    MatSelectModule,
    MatTableModule,
    MatIconModule,
    MatToolbarModule,
    MatSnackBarModule,
    MatChipsModule,
    MatExpansionModule
  ],
  templateUrl: './pqrs.component.html',
  styleUrls: ['./pqrs.component.css']
})
export class PqrsComponent implements OnInit {
  form: FormGroup;
  pqrsList: any[] = [];
  inmuebles: any[] = [];
  cargando = false;
  qrImagen = '';
  qrError = '';
  private qrSeq = 0;
  tiposPQRS = ['peticion', 'queja', 'reclamo', 'sugerencia'];
  pasos = ['Radicada', 'En proceso', 'Resuelta'];

  private tiposInfo: any = {
    peticion:   { etiqueta: 'Petición',   icono: 'edit_note',                ayuda: 'Solicitar algo a la administración' },
    queja:      { etiqueta: 'Queja',      icono: 'sentiment_dissatisfied',   ayuda: 'Inconformidad por un servicio o situación' },
    reclamo:    { etiqueta: 'Reclamo',    icono: 'report_problem',           ayuda: 'Pedir corrección de algo incumplido' },
    sugerencia: { etiqueta: 'Sugerencia', icono: 'lightbulb',                ayuda: 'Proponer una mejora para el conjunto' }
  };

  constructor(
    private fb: FormBuilder,
    private apiService: ApiService,
    private authService: AuthService,
    private router: Router,
    private snackBar: MatSnackBar
  ) {
    this.form = this.fb.group({
      inmueble_id: ['', Validators.required],
      tipo: ['', Validators.required],
      descripcion: ['', Validators.required]
    });

    // El QR se genera en vivo con lo que el usuario escriba (sin mínimo de caracteres)
    this.form.get('descripcion')!.valueChanges
      .pipe(debounceTime(200), takeUntilDestroyed())
      .subscribe((texto) => this.generarQR(texto));
  }

  ngOnInit(): void {
    this.cargarDatos();
  }

  cargarDatos(): void {
    this.apiService.getPQRS().subscribe({
      next: (data) => this.pqrsList = data,
      error: () => this.snackBar.open('Error al cargar PQRS', 'Cerrar', { duration: 3000 })
    });

    this.apiService.getConjuntos().subscribe({
      next: (conjuntos) => {
        if (conjuntos.length > 0) {
          const conjuntoId = conjuntos[0].id;
          this.apiService.getInmuebles(conjuntoId).subscribe({
            next: (data) => {
              const usuario = this.authService.getUsuario();
              this.inmuebles = data.filter((i: any) =>
                i.propietario_id === usuario.id || i.inquilino_id === usuario.id
              );
            }
          });
        }
      }
    });
  }

  crearPQRS(): void {
    if (this.form.invalid) return;
    this.cargando = true;

    this.apiService.crearPQRS(this.form.value).subscribe({
      next: () => {
        this.snackBar.open('¡PQRS radicada exitosamente!', 'Cerrar', { duration: 3000 });
        this.form.reset();
        this.generarQR('');
        this.cargando = false;
        this.cargarDatos();
      },
      error: (err) => {
        this.cargando = false;
        this.snackBar.open(
          err.error?.detail || 'Error al radicar la PQRS',
          'Cerrar',
          { duration: 4000 }
        );
      }
    });
  }

  // ---------------- Código QR del texto escrito ----------------
  get textoQR(): string {
    return String(this.form.get('descripcion')?.value ?? '');
  }

  generarQR(texto: string | null): void {
    const contenido = texto ?? '';
    const seq = ++this.qrSeq;

    if (!contenido.trim()) {
      this.qrImagen = '';
      this.qrError = '';
      return;
    }

    toDataURL(contenido, {
      width: 320,
      margin: 2,
      errorCorrectionLevel: 'L',
      color: { dark: '#0c3b45', light: '#ffffff' }
    }).then((url) => {
      if (seq !== this.qrSeq) return;
      this.qrImagen = url;
      this.qrError = '';
    }).catch(() => {
      if (seq !== this.qrSeq) return;
      this.qrImagen = '';
      this.qrError = 'El texto es demasiado largo para un código QR. Acórtalo un poco.';
    });
  }

  descargarQR(): void {
    if (!this.qrImagen) return;
    const enlace = document.createElement('a');
    enlace.href = this.qrImagen;
    enlace.download = 'qr-iris.png';
    document.body.appendChild(enlace);
    enlace.click();
    document.body.removeChild(enlace);
  }

  async copiarTexto(): Promise<void> {
    if (!this.textoQR) return;
    try {
      await navigator.clipboard.writeText(this.textoQR);
      this.snackBar.open('Texto copiado', 'Cerrar', { duration: 2500 });
    } catch {
      this.snackBar.open('No se pudo copiar el texto', 'Cerrar', { duration: 3000 });
    }
  }

  limpiarTexto(): void {
    this.form.get('descripcion')!.setValue('');
    this.generarQR('');
  }

  seleccionarTipo(tipo: string): void {
    this.form.patchValue({ tipo });
    this.form.get('tipo')?.markAsTouched();
  }

  etiquetaTipo(tipo: string): string { return this.tiposInfo[tipo]?.etiqueta || tipo; }
  icono(tipo: string): string { return this.tiposInfo[tipo]?.icono || 'forum'; }
  ayudaTipo(tipo: string): string { return this.tiposInfo[tipo]?.ayuda || ''; }

  etiquetaEstado(estado: string): string {
    const e = (estado || '').replace('_', ' ');
    return e.charAt(0).toUpperCase() + e.slice(1);
  }

  indicePaso(estado: string): number {
    return ({ radicado: 0, en_proceso: 1, resuelto: 2 } as any)[estado] ?? 0;
  }

  getColorEstado(estado: string): string {
    const colores: any = {
      'radicado': 'accent',
      'en_proceso': 'primary',
      'resuelto': ''
    };
    return colores[estado] || '';
  }

  volver(): void {
    this.router.navigate(['/residente']);
  }

  cerrarSesion(): void {
    this.authService.logout();
  }
}