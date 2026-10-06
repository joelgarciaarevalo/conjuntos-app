import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { PwaStatusComponent } from './components/pwa-status/pwa-status.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, PwaStatusComponent],
  template: `<router-outlet></router-outlet><app-pwa-status></app-pwa-status>`
})
export class AppComponent {}
