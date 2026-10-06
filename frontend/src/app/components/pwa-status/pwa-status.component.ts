import { Component, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';

interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

@Component({
  selector: 'app-pwa-status',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './pwa-status.component.html',
  styleUrls: ['./pwa-status.component.css'],
})
export class PwaStatusComponent {
  online = typeof navigator === 'undefined' ? true : navigator.onLine;
  installPrompt: InstallPromptEvent | null = null;
  installable = false;
  installed = false;
  helpOpen = false;

  constructor() {
    this.installed = this.esStandalone();
    this.installable = !this.installed && this.esSafariIos() && !this.descartado();
    window.addEventListener('beforeinstallprompt', (event: Event) => {
      event.preventDefault();
      this.installPrompt = event as InstallPromptEvent;
      this.installable = !this.installed && !this.descartado();
    });
    window.addEventListener('appinstalled', () => {
      this.installed = true;
      this.installPrompt = null;
      this.installable = false;
    });
  }

  @HostListener('window:online') alConectar(): void { this.online = true; }
  @HostListener('window:offline') alDesconectar(): void { this.online = false; }

  get mostrar(): boolean { return !this.online || (this.installable && !this.installed); }

  async instalar(): Promise<void> {
    if (!this.installPrompt) { this.helpOpen = !this.helpOpen; return; }
    const prompt = this.installPrompt;
    this.installPrompt = null;
    await prompt.prompt();
    const result = await prompt.userChoice;
    if (result.outcome === 'accepted') {
      this.installed = true;
      this.installable = false;
    } else {
      this.installable = false;
      try { localStorage.setItem('iris-pwa-dismissed', '1'); } catch { /* almacenamiento opcional */ }
    }
  }

  cerrarAyuda(): void { this.helpOpen = false; }

  private descartado(): boolean {
    try { return localStorage.getItem('iris-pwa-dismissed') === '1'; } catch { return false; }
  }

  private esStandalone(): boolean {
    return window.matchMedia('(display-mode: standalone)').matches || (navigator as any).standalone === true;
  }

  private esSafariIos(): boolean {
    const ua = navigator.userAgent || '';
    const ios = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    return ios && /Safari/.test(ua) && !/(CriOS|FxiOS|EdgiOS|OPiOS)/.test(ua);
  }
}
