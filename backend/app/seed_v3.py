"""Datos de ejemplo idempotentes para los módulos de IRIS 3.0 (solo desarrollo).

No duplica ni borra nada: si los datos ya existen, no los vuelve a crear.
"""
from __future__ import annotations

from datetime import date, timedelta

from app import models, models_v3
from app.database import SessionLocal
from app.routers.v3_avisos import PLANTILLAS_SUGERIDAS
from app.routers.v3_common import json_dumps, localnow

TEXTO_PRIVACIDAD_DEMO = (
    "IRIS trata los datos personales de residentes, visitantes y proveedores para administrar la copropiedad: "
    "control de acceso, PQRS, cuotas, reservas, mantenimiento y comunicaciones. Los números de tarjeta nunca se "
    "almacenan en IRIS. Puedes solicitar acceso, corrección, revocatoria del consentimiento de avisos y supresión "
    "de tus datos ante la administración. Este texto es de demostración."
)


def ensure_datos_v3() -> None:
    db = SessionLocal()
    creados = []
    try:
        conjuntos = db.query(models.Conjunto).order_by(models.Conjunto.id).all()
        admin = db.query(models.Usuario).filter_by(email="admin@iris-demo.com").first()
        residente = db.query(models.Usuario).filter_by(email="residente@iris-demo.com").first()
        portero = db.query(models.Usuario).filter_by(email="portero@iris-demo.com").first()

        # Política global de datos
        if not db.query(models_v3.PoliticaDatos).filter_by(conjunto_id=None).first():
            db.add(models_v3.PoliticaDatos(conjunto_id=None, texto_privacidad=TEXTO_PRIVACIDAD_DEMO))
            creados.append("politica_global")

        for conjunto in conjuntos:
            # Política, cartera y pasarela simulada por conjunto
            if not db.query(models_v3.PoliticaDatos).filter_by(conjunto_id=conjunto.id).first():
                db.add(models_v3.PoliticaDatos(conjunto_id=conjunto.id, texto_privacidad=TEXTO_PRIVACIDAD_DEMO))
                creados.append(f"politica_conjunto_{conjunto.id}")
            if not db.query(models_v3.ConfigCartera).filter_by(conjunto_id=conjunto.id).first():
                db.add(models_v3.ConfigCartera(conjunto_id=conjunto.id, tasa_mora_mensual="0.0200",
                                               interes_moratorio_diario="0.0000", recargo_fijo=5000,
                                               dias_gracia=5, activo=False))
                creados.append(f"cartera_{conjunto.id}")
            if not db.query(models_v3.ConfigPasarela).filter_by(conjunto_id=conjunto.id).first():
                db.add(models_v3.ConfigPasarela(
                    conjunto_id=conjunto.id, proveedor="simulado", modo="sandbox", moneda="COP",
                    public_key="pk_test_iris_simulado", private_key_cifrada=None, events_secret_cifrado=None,
                    permite_tarjeta=True, permite_pse=True, permite_nequi=True, activo=True, conciliacion_automatica=True,
                ))
                creados.append(f"pasarela_{conjunto.id}")

            # Reglas avanzadas de reservas por zona
            for zona in db.query(models.ZonaComun).filter_by(conjunto_id=conjunto.id).all():
                if not db.query(models_v3.ReglaZonaReserva).filter_by(zona_id=zona.id).first():
                    db.add(models_v3.ReglaZonaReserva(
                        zona_id=zona.id, cupos_por_franja=2, duracion_franja_minutos=120, antelacion_minima_horas=2,
                        horas_limite_cancelacion=12, requiere_pago=(zona.nombre.lower().startswith("salón") or zona.nombre.lower().startswith("salon")),
                        tarifa_por_uso=50000 if zona.nombre.lower().startswith("sal") else 0,
                        lista_espera_activa=True, cupos_lista_espera=5, penalizacion_inasistencia=30000,
                        max_reservas_activas_inmueble=3,
                    ))
                    creados.append(f"regla_zona_{zona.id}")

            # Plantillas de aviso sugeridas
            for evento, titulo, cuerpo, canales in PLANTILLAS_SUGERIDAS:
                if not db.query(models_v3.PlantillaAviso).filter_by(conjunto_id=conjunto.id, evento=evento).first():
                    db.add(models_v3.PlantillaAviso(conjunto_id=conjunto.id, evento=evento, titulo=titulo,
                                                    cuerpo=cuerpo, canales=canales, creado_por=admin.id if admin else None))
                    creados.append(f"plantilla_{conjunto.id}_{evento}")

            # Proveedor demo
            if admin and not db.query(models_v3.Proveedor).filter_by(conjunto_id=conjunto.id, nombre="Servicios Eléctricos Andinos").first():
                db.add(models_v3.Proveedor(conjunto_id=conjunto.id, nombre="Servicios Eléctricos Andinos",
                                           nit="900123456-7", especialidad="Eléctrico", contacto="Jorge Ruiz",
                                           telefono="+573001234567", email="contacto@andinos.co", calificacion=4))
                creados.append(f"proveedor_{conjunto.id}")

            unidades = db.query(models.Inmueble).filter_by(conjunto_id=conjunto.id).all()
            if not unidades:
                continue
            unidad_demo = unidades[0]

            # Orden de mantenimiento demo
            proveedor = db.query(models_v3.Proveedor).filter_by(conjunto_id=conjunto.id).first()
            if admin and not db.query(models_v3.OrdenMantenimiento).filter_by(conjunto_id=conjunto.id, titulo="Revisión de bombas de agua").first():
                orden = models_v3.OrdenMantenimiento(
                    conjunto_id=conjunto.id, titulo="Revisión de bombas de agua",
                    descripcion="Mantenimiento preventivo trimestral del cuarto de bombas.",
                    categoria="mantenimiento", prioridad="alta", estado="en_ejecucion",
                    responsable_id=admin.id, proveedor_id=proveedor.id if proveedor else None,
                    fecha_limite=localnow() + timedelta(days=7), costo_estimado="850000", creado_por=admin.id,
                )
                db.add(orden)
                db.flush()
                db.add(models_v3.CotizacionMantenimiento(orden_id=orden.id, proveedor_id=proveedor.id if proveedor else None,
                                                         proveedor_nombre=proveedor.nombre if proveedor else "Proveedor demo",
                                                         monto="850000", descripcion="Incluye cambio de sellos y revisión de tablero",
                                                         estado="seleccionada", creado_por=admin.id))
                db.add(models_v3.AvanceMantenimiento(orden_id=orden.id, estado="en_ejecucion",
                                                     nota="Se inició la revisión de las bombas 1 y 2.", usuario_id=admin.id))
                creados.append(f"orden_mantenimiento_{conjunto.id}")

            # Visita autorizada demo + acceso registrado
            if residente and not db.query(models_v3.Visitante).filter_by(inmueble_id=unidad_demo.id, nombre="Ana Martínez").first():
                visitante = models_v3.Visitante(
                    conjunto_id=conjunto.id, inmueble_id=unidad_demo.id, nombre="Ana Martínez", documento="1020304050",
                    telefono="+573009998877", placa="ABC123", tipo="familiar", creado_por=residente.id,
                )
                db.add(visitante)
                db.flush()
                db.add(models_v3.AutorizacionVisita(
                    conjunto_id=conjunto.id, inmueble_id=unidad_demo.id, visitante_id=visitante.id, residente_id=residente.id,
                    valido_desde=localnow(), valido_hasta=localnow() + timedelta(days=30), recurrente=False,
                    usos_maximos=5, permite_vehiculo=True,
                ))
                creados.append(f"visitante_{conjunto.id}")
            if portero and not db.query(models_v3.RegistroAcceso).filter_by(conjunto_id=conjunto.id, nombre_visitante="Domiciliario Rappi").first():
                db.add(models_v3.RegistroAcceso(
                    conjunto_id=conjunto.id, inmueble_id=unidad_demo.id, nombre_visitante="Domiciliario Rappi",
                    tipo="domiciliario", registrado_por=portero.id, autorizado_por_residente=False,
                    alerta_detalle="Ingreso sin autorización previa (registro manual del residente)",
                ))
                creados.append(f"acceso_{conjunto.id}")

            # Asamblea demo con votación y asistencia
            if admin and not db.query(models_v3.Asamblea).filter_by(conjunto_id=conjunto.id, titulo="Asamblea ordinaria de presupuesto").first():
                asamblea = models_v3.Asamblea(
                    conjunto_id=conjunto.id, titulo="Asamblea ordinaria de presupuesto", tipo="ordinaria",
                    modalidad="mixta", lugar="Salón comunal", enlace="https://meet.example/iris",
                    fecha_convocatoria=localnow(), fecha_inicio=localnow() + timedelta(days=2),
                    fecha_fin=localnow() + timedelta(days=2, hours=2), quorum_requerido="50.00",
                    estado="convocada", creado_por=admin.id,
                )
                db.add(asamblea)
                db.flush()
                db.add(models_v3.Votacion(asamblea_id=asamblea.id, titulo="¿Apruebas el presupuesto 2027?",
                                          descripcion="Incremento del 8% en la cuota de administración.",
                                          tipo="si_no", opciones=json_dumps(["si", "no"]),
                                          permite_abstencion=True, mayoria="simple", orden=1))
                db.add(models_v3.AsistenciaAsamblea(asamblea_id=asamblea.id, inmueble_id=unidad_demo.id,
                                                    usuario_id=(residente.id if residente else None),
                                                    representado_por="Residente demo"))
                creados.append(f"asamblea_{conjunto.id}")

            # Egreso y presupuesto demo
            if admin and not db.query(models_v3.Egreso).filter_by(conjunto_id=conjunto.id, concepto="Vigilancia - cuota mensual").first():
                db.add(models_v3.Egreso(conjunto_id=conjunto.id, concepto="Vigilancia - cuota mensual",
                                        categoria="seguridad", monto="4200000", fecha=date.today().replace(day=1),
                                        notas="Contrato de vigilancia del periodo", creado_por=admin.id))
                db.add(models_v3.Presupuesto(conjunto_id=conjunto.id, periodo=date.today().strftime("%Y-%m"),
                                             categoria="seguridad", monto_presupuestado="4500000",
                                             notas="Presupuesto mensual aprobado", creado_por=admin.id))
                creados.append(f"contabilidad_{conjunto.id}")

            # Consentimiento demo de avisos para el residente
            if residente and not db.query(models_v3.ConsentimientoAviso).filter_by(usuario_id=residente.id, canal="whatsapp").first():
                db.add(models_v3.ConsentimientoAviso(
                    usuario_id=residente.id, canal="whatsapp", telefono="+573001112233", otorgado=True,
                    version_politica="1.0", evidencia="Consentimiento de demostración creado por el seed de desarrollo",
                    otorgado_en=localnow(),
                ))
                creados.append("consentimiento_demo")

        db.commit()
        if creados:
            print(f"IRIS 3.0 · datos demo preparados ({len(creados)} elementos)")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()