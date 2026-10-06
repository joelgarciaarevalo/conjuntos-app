import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService, Conjunto, Inmueble, ZonaComun } from '../../../services/api.service';
import { AuthService } from '../../../services/auth.service';

@Component({ selector: 'app-admin-gestion', standalone: true, imports: [CommonModule, FormsModule], templateUrl: './gestion.component.html', styleUrls: ['./gestion.component.css'] })
export class GestionComponent implements OnInit {
  conjuntos: Conjunto[]=[]; selected=0; inmuebles: Inmueble[]=[]; zonas: ZonaComun[]=[]; usuarios:any[]=[]; cuotas:any[]=[]; paquetes:any[]=[]; parqueaderos:any[]=[]; anuncios:any[]=[]; error=''; ok='';
  unit:any={torre:'',numero:'',propietario_id:'',inquilino_id:null,estado:'ocupado'}; editingUnit=0;
  zone:any={nombre:'',requiere_aprobacion:true,hora_apertura:'08:00',hora_cierre:'18:00',duracion_max_minutos:120}; editingZone=0;
  anuncio:any={titulo:'',contenido:''}; fee:any={inmueble_id:'',concepto:'Cuota de administración',periodo:'',monto:'',fecha_vencimiento:''}; parking:any={identificador:'',tipo:'privado',inmueble_id:null,placa:'',tarifa_mensual:0}; parkingCharge:any={periodo:new Date().toISOString().slice(0,7),fecha_vencimiento:new Date(new Date().getFullYear(),new Date().getMonth()+1,0).toISOString().slice(0,10)}; pkg:any={inmueble_id:'',transportadora:'',descripcion:''}; contadorDraft:any={nombre_completo:'',cedula:'',email:'',telefono:'',password:''};
  constructor(private api:ApiService, public auth:AuthService, private router:Router){}
  ngOnInit(){this.api.getConjuntos().subscribe({next:x=>{this.conjuntos=x;this.selected=x[0]?.id||0;this.load();},error:e=>this.fail(e)});this.api.getUsuarios().subscribe({next:x=>this.usuarios=x,error:()=>{}});this.api.getCuotas().subscribe({next:x=>this.cuotas=x,error:()=>{}});this.api.getPaquetes().subscribe({next:x=>this.paquetes=x,error:()=>{}});this.api.getParqueaderos().subscribe({next:x=>this.parqueaderos=x,error:()=>{}});this.api.getAnuncios().subscribe({next:x=>this.anuncios=x,error:()=>{}});}
  load(){if(!this.selected)return;this.api.getInmuebles(this.selected).subscribe({next:x=>this.inmuebles=x,error:e=>this.fail(e)});this.api.getZonas(this.selected).subscribe({next:x=>this.zonas=x,error:e=>this.fail(e)});}
  changeSet(){this.load();}
  saveUnit(){this.clear();const data={...this.unit,propietario_id:Number(this.unit.propietario_id),inquilino_id:this.unit.inquilino_id?Number(this.unit.inquilino_id):null};const req=this.editingUnit?this.api.editarInmueble(this.selected,this.editingUnit,data):this.api.crearInmueble(this.selected,data);req.subscribe({next:()=>{this.ok=this.editingUnit?'Inmueble actualizado':'Inmueble creado';this.unit={torre:'',numero:'',propietario_id:'',inquilino_id:null,estado:'ocupado'};this.editingUnit=0;this.load();},error:e=>this.fail(e)});}
  editUnit(i:Inmueble){this.editingUnit=i.id;this.unit={...i};}
  deleteUnit(x:Inmueble){if(!confirm(`¿Eliminar ${x.torre||''} ${x.numero}?`))return;this.api.borrarInmueble(this.selected,x.id).subscribe({next:()=>{this.ok='Inmueble eliminado';this.load();},error:e=>this.fail(e)});}
  saveZone(){this.clear();const data={...this.zone,duracion_max_minutos:Number(this.zone.duracion_max_minutos)};const req=this.editingZone?this.api.editarZona(this.selected,this.editingZone,data):this.api.crearZona(this.selected,data);req.subscribe({next:()=>{this.ok=this.editingZone?'Zona actualizada':'Zona creada';this.editingZone=0;this.zone={nombre:'',requiere_aprobacion:true,hora_apertura:'08:00',hora_cierre:'18:00',duracion_max_minutos:120};this.load();},error:e=>this.fail(e)});}
  editZone(z:ZonaComun){this.editingZone=z.id;this.zone={...z};}
  deleteZone(z:ZonaComun){if(!confirm(`¿Eliminar zona ${z.nombre}?`))return;this.api.borrarZona(this.selected,z.id).subscribe({next:()=>{this.ok='Zona eliminada';this.load();},error:e=>this.fail(e)});}
  publish(){this.clear();this.api.crearAnuncio({...this.anuncio,conjunto_id:this.selected}).subscribe({next:()=>{this.ok='Comunicado publicado y notificaciones enviadas';this.anuncio={titulo:'',contenido:''};this.api.getAnuncios().subscribe(x=>this.anuncios=x);},error:e=>this.fail(e)});}
  createFee(){this.clear();this.api.crearCuota({...this.fee,inmueble_id:Number(this.fee.inmueble_id),monto:Number(this.fee.monto)}).subscribe({next:()=>{this.ok='Cuota asignada; residente notificado';this.fee={inmueble_id:'',concepto:'Cuota de administración',periodo:'',monto:'',fecha_vencimiento:''};this.api.getCuotas().subscribe(x=>this.cuotas=x);},error:e=>this.fail(e)});}
  setPaid(x:any, paid:boolean){this.api.cambiarPago(x.id,paid).subscribe({next:()=>this.api.getCuotas().subscribe(v=>this.cuotas=v),error:e=>this.fail(e)});}
  createParking(){this.clear();this.api.crearParqueadero({...this.parking,conjunto_id:this.selected,inmueble_id:this.parking.inmueble_id?Number(this.parking.inmueble_id):null,tarifa_mensual:Number(this.parking.tarifa_mensual||0)}).subscribe({next:()=>{this.ok='Parqueadero registrado';this.parking={identificador:'',tipo:'privado',inmueble_id:null,placa:'',tarifa_mensual:0};this.api.getParqueaderos().subscribe(x=>this.parqueaderos=x);},error:e=>this.fail(e)});}
  updateParking(p:any){this.clear();this.api.actualizarParqueadero(p.id,{inmueble_id:p.inmueble_id?Number(p.inmueble_id):null,tarifa_mensual:Number(p.tarifa_mensual||0),placa:p.placa||null}).subscribe({next:()=>{this.ok=`Parqueadero ${p.identificador} actualizado`;this.api.getParqueaderos().subscribe(x=>this.parqueaderos=x);},error:e=>this.fail(e)});}
  generateParkingCharges(){this.clear();this.api.generarCobrosParqueadero({...this.parkingCharge,conjunto_id:this.selected}).subscribe({next:r=>{this.ok=`Cobros de parqueadero creados: ${r.creados}; ya existentes/sin tarifa: ${r.omitidos}. Los residentes los verán en sus cuotas.`;this.api.getCuotas().subscribe(x=>this.cuotas=x);},error:e=>this.fail(e)});}
  receivePackage(){this.clear();this.api.recibirPaquete({...this.pkg,inmueble_id:Number(this.pkg.inmueble_id)}).subscribe({next:()=>{this.ok='Paquete recibido; residente notificado';this.api.getPaquetes().subscribe(x=>this.paquetes=x);},error:e=>this.fail(e)});}
  pickup(p:any){this.api.retirarPaquete(p.id,'Portería').subscribe({next:()=>this.api.getPaquetes().subscribe(x=>this.paquetes=x),error:e=>this.fail(e)});}
  setRole(u:any){this.api.cambiarRol(u.id,u.rol).subscribe({next:()=>this.ok=`Rol de ${u.nombre_completo} actualizado`,error:e=>this.fail(e)});}
  crearCuentaContador(){this.clear();if(!this.selected)return;if(!confirm('Se creará una cuenta independiente con acceso contable al conjunto seleccionado. ¿Continuar?'))return;this.api.crearContador(this.selected,this.contadorDraft).subscribe({next:r=>{this.ok=`Cuenta de contador creada para ${r.email}. Debe iniciar sesión y cambiar la contraseña temporal.`;this.contadorDraft={nombre_completo:'',cedula:'',email:'',telefono:'',password:''};this.api.getUsuarios().subscribe(x=>this.usuarios=x);},error:e=>this.fail(e)});}
  report(type:string){this.api.descargarReporte(type).subscribe(blob=>{const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`iris-${type}.xlsx`;a.click();URL.revokeObjectURL(a.href);});}
  labelUnit(id:number){const i=this.inmuebles.find(x=>x.id===id);return i?`${i.torre||''} ${i.numero}`:`Inmueble #${id}`;}
  fail(e:any){this.error=e.error?.detail||'No fue posible completar la operación';this.ok='';}
  clear(){this.error='';this.ok='';}
  back(){this.router.navigate(['/admin']);} logout(){this.auth.logout();}
}
