import { Component, ElementRef, OnDestroy, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import jsQR from 'jsqr';
import { QrService, ResultadoValidacion } from '../../services/qr.service';
import { AuthService } from '../../services/auth.service';

@Component({ selector: 'app-portero-escanner', standalone: true, imports: [CommonModule, FormsModule], templateUrl: './escanner.component.html', styleUrls: ['./escanner.component.css'] })
export class EscannerComponent implements OnDestroy {
  @ViewChild('video') video?: ElementRef<HTMLVideoElement>;
  codigo = '';
  resultado: ResultadoValidacion | null = null;
  error = '';
  scanning = false;
  busy = false;
  private stream?: MediaStream;
  private frameHandle = 0;
  private canvas?: HTMLCanvasElement;
  private context?: CanvasRenderingContext2D | null;

  constructor(private qr: QrService, public auth: AuthService, private router: Router) {}

  async start(): Promise<void> {
    this.error = '';
    this.resultado = null;
    const video = this.video?.nativeElement;
    if (!video) {
      this.error = 'No se encontró el visor de la cámara. Recarga la página e inténtalo de nuevo.';
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      this.error = 'El navegador no habilita cámara en esta dirección. Abre IRIS en localhost o en un sitio HTTPS y concede permiso para usar la cámara.';
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }
      });
      video.srcObject = this.stream;
      video.setAttribute('playsinline', 'true');
      await video.play();
      this.canvas = document.createElement('canvas');
      this.context = this.canvas.getContext('2d', { willReadFrequently: true });
      if (!this.context) throw new Error('canvas');
      this.scanning = true;
      this.scanFrame();
    } catch (e: any) {
      const name = e?.name || '';
      if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
        this.error = 'No se concedió permiso para la cámara. Actívalo en el navegador y pulsa “Activar cámara” otra vez.';
      } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
        this.error = 'No se detectó ninguna cámara conectada al dispositivo.';
      } else {
        this.error = 'No fue posible iniciar la cámara. Comprueba permisos, HTTPS y que ninguna otra aplicación la esté usando.';
      }
      this.stop();
    }
  }

  private scanFrame(): void {
    const video = this.video?.nativeElement;
    const context = this.context;
    if (!this.scanning || !video || !context || video.readyState < HTMLMediaElement.HAVE_ENOUGH_DATA) {
      if (this.scanning) this.frameHandle = requestAnimationFrame(() => this.scanFrame());
      return;
    }
    const width = video.videoWidth;
    const height = video.videoHeight;
    if (width && height) {
      this.canvas!.width = width;
      this.canvas!.height = height;
      context.drawImage(video, 0, 0, width, height);
      const pixels = context.getImageData(0, 0, width, height);
      const found = jsQR(pixels.data, width, height, { inversionAttempts: 'attemptBoth' });
      if (found?.data) {
        // Los códigos emitidos por IRIS guardan IRIS-QR:<token>; el texto
        // se envía al mismo endpoint que la validación manual de portería.
        this.codigo = found.data;
        this.stop();
        this.validar();
        return;
      }
    }
    this.frameHandle = requestAnimationFrame(() => this.scanFrame());
  }

  stop(): void {
    this.scanning = false;
    if (this.frameHandle) cancelAnimationFrame(this.frameHandle);
    this.frameHandle = 0;
    this.stream?.getTracks().forEach(track => track.stop());
    this.stream = undefined;
    const video = this.video?.nativeElement;
    if (video) video.srcObject = null;
    this.context = undefined;
    this.canvas = undefined;
  }

  validar(): void {
    if (!this.codigo.trim() || this.busy) return;
    this.busy = true;
    this.error = '';
    this.qr.validar(this.codigo.trim(), true).subscribe({
      next: r => { this.resultado = r; this.busy = false; },
      error: e => { this.error = e.error?.detail || 'No se pudo validar el código'; this.busy = false; }
    });
  }

  nuevaLectura(): void { this.codigo = ''; this.resultado = null; this.error = ''; }
  back(): void { this.stop(); this.router.navigate([this.auth.getUsuario()?.rol === 'portero' ? '/portero/servicios' : '/admin']); }
  goServices(): void { this.stop(); this.router.navigate(['/portero/servicios']); }
  goModulos(): void { this.stop(); this.router.navigate(['/portero/modulos']); }
  logout(): void { this.stop(); this.auth.logout(); }
  ngOnDestroy(): void { this.stop(); }
}
