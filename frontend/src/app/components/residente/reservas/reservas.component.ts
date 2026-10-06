import { Component, OnInit } from '@angular/core';
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
import { ApiService, ZonaComun } from '../../../services/api.service';
import { AuthService } from '../../../services/auth.service';
@Component({selector:'app-residente-reservas',standalone:true,imports:[CommonModule,ReactiveFormsModule,RouterModule,MatCardModule,MatButtonModule,MatInputModule,MatSelectModule,MatTableModule,MatIconModule,MatToolbarModule,MatSnackBarModule,MatChipsModule],templateUrl:'./reservas.component.html',styleUrls:['./reservas.component.css']})
export class ReservasComponent implements OnInit {
 form:FormGroup; reservas:any[]=[]; zonas:ZonaComun[]=[]; inmuebles:any[]=[]; disponibilidad:any[]=[]; cargando=false; minFecha=''; columnas=['zona','fecha_inicio','fecha_fin','estado','acciones'];
 constructor(private fb:FormBuilder,private api:ApiService,private auth:AuthService,private router:Router,private snack:MatSnackBar){this.form=this.fb.group({zona_id:['',Validators.required],inmueble_id:['',Validators.required],fecha_inicio:['',Validators.required],fecha_fin:['',Validators.required]});}
 ngOnInit(){this.minFecha=this.localValue(new Date());this.cargarDatos();}
 private localValue(d:Date){const p=(n:number)=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;}
 private localApi(v:string){return v.length===16?v+':00':v;}
 cargarDatos(){this.api.getReservas().subscribe({next:x=>this.reservas=x,error:()=>this.snack.open('Error al cargar reservas','Cerrar',{duration:3000})});this.api.getConjuntos().subscribe({next:cs=>{const me=this.auth.getUsuario();cs.forEach(c=>{this.api.getZonas(c.id).subscribe({next:z=>{this.zonas.push(...z);if(!this.form.value.zona_id&&z.length){this.form.patchValue({zona_id:z[0].id});this.cargarDisponibilidad();}},error:()=>{}});this.api.getInmuebles(c.id).subscribe({next:items=>this.inmuebles.push(...items.filter(i=>i.propietario_id===me.id||i.inquilino_id===me.id)),error:()=>{}});});}});}
 zonaActual():ZonaComun|undefined{return this.zonas.find(z=>z.id===Number(this.form.value.zona_id));}
 cargarDisponibilidad(){const id=Number(this.form.value.zona_id);if(!id)return;const start=new Date();start.setHours(0,0,0,0);const end=new Date(start);end.setDate(end.getDate()+7);this.api.disponibilidad(id,this.localApi(this.localValue(start)),this.localApi(this.localValue(end))).subscribe({next:x=>this.disponibilidad=x,error:()=>this.disponibilidad=[]});}
 nombreZona(id:number){return this.zonas.find(z=>z.id===id)?.nombre||`Zona #${id}`;}
 crearReserva(){if(this.form.invalid)return;const start=new Date(this.form.value.fecha_inicio),end=new Date(this.form.value.fecha_fin),zone=this.zonaActual();if(isNaN(start.getTime())||isNaN(end.getTime()))return this.msg('Revisa las fechas de la reserva');if(start.getTime()<Date.now()-60000)return this.msg('La fecha de inicio no puede estar en el pasado');if(end<=start)return this.msg('La fecha de fin debe ser posterior a la de inicio');if(zone&&end.getTime()-start.getTime()>zone.duracion_max_minutos*60000)return this.msg(`Duración máxima: ${zone.duracion_max_minutos} minutos`);this.cargando=true;this.api.crearReserva({zona_id:Number(this.form.value.zona_id),inmueble_id:Number(this.form.value.inmueble_id),fecha_inicio:this.localApi(this.form.value.fecha_inicio),fecha_fin:this.localApi(this.form.value.fecha_fin)}).subscribe({next:()=>{this.cargando=false;this.msg(zone&&!zone.requiere_aprobacion?'Reserva aprobada automáticamente':'Reserva creada y enviada a aprobación');this.form.patchValue({fecha_inicio:'',fecha_fin:''});this.cargarDatos();this.cargarDisponibilidad();},error:e=>{this.cargando=false;this.msg(e.error?.detail||'Error al crear la reserva');}});}
 cancelar(r:any){if(!confirm('¿Cancelar esta reserva?'))return;this.api.cancelarReserva(r.id).subscribe({next:()=>{this.msg('Reserva cancelada');this.cargarDatos();this.cargarDisponibilidad();},error:e=>this.msg(e.error?.detail||'No se pudo cancelar')});}
 msg(t:string){this.snack.open(t,'Cerrar',{duration:4000});}
 volver(){this.router.navigate(['/residente']);}cerrarSesion(){this.auth.logout();}
}
