import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService, Inmueble } from '../../../services/api.service';
import { AuthService } from '../../../services/auth.service';
@Component({selector:'app-residente-comunidad',standalone:true,imports:[CommonModule],templateUrl:'./comunidad.component.html',styleUrls:['./comunidad.component.css']})
export class ComunidadComponent implements OnInit {
 anuncios:any[]=[]; cuotas:any[]=[]; paquetes:any[]=[]; notificaciones:any[]=[]; inmuebles:Inmueble[]=[]; paz:any={}; error='';
 constructor(private api:ApiService,public auth:AuthService,private router:Router){}
 ngOnInit(){this.refresh();this.api.getConjuntos().subscribe(cs=>cs.forEach(c=>this.api.getInmuebles(c.id).subscribe(xs=>{const me=this.auth.getUsuario();this.inmuebles.push(...xs.filter(x=>x.propietario_id===me.id||x.inquilino_id===me.id));this.inmuebles.forEach(i=>this.api.pazYSalvo(i.id).subscribe(v=>this.paz[i.id]=v));})));}
 refresh(){this.api.getAnuncios().subscribe(x=>this.anuncios=x);this.api.getCuotas().subscribe(x=>this.cuotas=x);this.api.getPaquetes().subscribe(x=>this.paquetes=x);this.api.getNotificaciones().subscribe(x=>this.notificaciones=x);}
 read(n:any){this.api.marcarNotificacion(n.id).subscribe(()=>n.leida=true);}
 pickup(p:any){this.api.retirarPaquete(p.id,this.auth.getUsuario()?.nombre_completo||'Residente').subscribe({next:()=>this.refresh(),error:e=>this.error=e.error?.detail||'No se pudo registrar retiro'});}
 labelUnit(id:number){const u=this.inmuebles.find(x=>x.id===id);return u?`${u.torre||''} ${u.numero}`:`Inmueble ${id}`;}
 back(){this.router.navigate(['/residente']);} logout(){this.auth.logout();}
}
