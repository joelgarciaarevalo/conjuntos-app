"""
Datos de ejemplo para el conjunto: más inmuebles y más zonas comunes.

- Es idempotente: si se ejecuta varias veces NO duplica nada y NO borra datos existentes.
- Se llama una sola vez al arrancar el backend (ver main.py).
"""
from app import models
from app.database import SessionLocal
from app.dependencies import hashear_password
from datetime import date, timedelta
from zoneinfo import ZoneInfo

CONJUNTO_NOMBRE = "Conjunto Bochica SuperManzana 3"
CONJUNTO_NIT = "900000001-1"
CONJUNTO_DIRECCION = "Bogotá D.C."

EMAIL_RESIDENTE_DEMO = "residente@iris-demo.com"
EMAIL_MARIANA = "marianita1308cas@gmail.com"

# Residentes de ejemplo adicionales (contraseña: Usuario2026)
RESIDENTES_EXTRA = [
    {"clave": "carlos", "nombre": "Carlos Gómez", "cedula": "DEMO-RES-002", "email": "carlos@iris-demo.com"},
    {"clave": "laura", "nombre": "Laura Pérez", "cedula": "DEMO-RES-003", "email": "laura@iris-demo.com"},
    {"clave": "andres", "nombre": "Andrés Rojas", "cedula": "DEMO-RES-004", "email": "andres@iris-demo.com"},
]

# (torre, número, propietario, inquilino, estado)
INMUEBLES = [
    ("1", "102", "residente", None, "ocupado"),
    ("1", "201", "mariana", None, "ocupado"),
    ("1", "202", "carlos", None, "ocupado"),
    ("2", "101", "mariana", None, "ocupado"),
    ("2", "102", "laura", "residente", "ocupado"),
    ("2", "201", "residente", None, "ocupado"),
    ("2", "202", "andres", None, "desocupado"),
    ("3", "101", "carlos", "mariana", "ocupado"),
    ("3", "102", "laura", None, "ocupado"),
    ("3", "201", "andres", None, "en_venta"),
    ("3", "202", "mariana", None, "ocupado"),
]

# (nombre, requiere_aprobacion)
ZONAS = [
    ("Piscina", True),
    ("Salón comunal", True),
    ("Zona de asados (BBQ)", True),
    ("Gimnasio", True),
    ("Cancha múltiple", True),
]


def ensure_datos_demo() -> None:
    db = SessionLocal()
    try:
        # ---------------- Conjunto ----------------
        conjunto = db.query(models.Conjunto).order_by(models.Conjunto.id).first()
        if not conjunto:
            conjunto = models.Conjunto(nombre=CONJUNTO_NOMBRE, nit=CONJUNTO_NIT, direccion=CONJUNTO_DIRECCION)
            db.add(conjunto)
            db.flush()

        # ---------------- Usuarios ----------------
        usuarios: dict[str, int] = {}
        residente = db.query(models.Usuario).filter(models.Usuario.email == EMAIL_RESIDENTE_DEMO).first()
        if not residente:
            residente = db.query(models.Usuario).filter(models.Usuario.es_super_admin.is_(False)).order_by(models.Usuario.id).first()
        if not residente:
            # Sin ningún residente no se pueden crear inmuebles (necesitan propietario)
            db.commit()
            return
        usuarios["residente"] = residente.id

        mariana = db.query(models.Usuario).filter(models.Usuario.email == EMAIL_MARIANA).first()
        usuarios["mariana"] = mariana.id if mariana else residente.id

        for r in RESIDENTES_EXTRA:
            u = db.query(models.Usuario).filter(models.Usuario.email == r["email"]).first()
            if not u:
                u = db.query(models.Usuario).filter(models.Usuario.cedula == r["cedula"]).first()
            if not u:
                u = models.Usuario(
                    nombre_completo=r["nombre"],
                    cedula=r["cedula"],
                    email=r["email"],
                    password_hash=hashear_password("Usuario2026"),
                    es_super_admin=False,
                )
                db.add(u)
                db.flush()
            usuarios[r["clave"]] = u.id

        # ---------------- Inmuebles ----------------
        # La pantalla ya antepone la palabra "Torre", así que se guarda solo el número
        # (evita que se vea "Torre Torre 1").
        existentes = db.query(models.Inmueble).filter(models.Inmueble.conjunto_id == conjunto.id).all()
        for inm in existentes:
            if inm.torre and inm.torre.strip().lower().startswith("torre "):
                inm.torre = inm.torre.strip()[6:].strip()
        db.flush()

        ya_hay = {((i.torre or "").strip(), i.numero.strip()) for i in existentes}
        estados = {
            "ocupado": models.EstadoInmueble.ocupado,
            "desocupado": models.EstadoInmueble.desocupado,
            "en_venta": models.EstadoInmueble.en_venta,
        }
        nuevos_inmuebles = 0
        for torre, numero, propietario, inquilino, estado in INMUEBLES:
            if (torre, numero) in ya_hay:
                continue
            db.add(models.Inmueble(
                conjunto_id=conjunto.id,
                torre=torre,
                numero=numero,
                propietario_id=usuarios[propietario],
                inquilino_id=usuarios[inquilino] if inquilino else None,
                estado=estados[estado],
            ))
            nuevos_inmuebles += 1

        # ---------------- Zonas comunes ----------------
        nombres_zonas = {
            z.nombre.strip().lower()
            for z in db.query(models.ZonaComun).filter(models.ZonaComun.conjunto_id == conjunto.id).all()
        }
        nuevas_zonas = 0
        for nombre, requiere in ZONAS:
            if nombre.lower() in nombres_zonas:
                continue
            db.add(models.ZonaComun(conjunto_id=conjunto.id, nombre=nombre, requiere_aprobacion=requiere))
            nuevas_zonas += 1

        # El usuario demo de portería queda limitado al conjunto de demostración.
        portero = db.query(models.Usuario).filter_by(email="portero@iris-demo.com").first()
        if portero and not db.query(models.ConjuntoMembership).filter_by(usuario_id=portero.id, conjunto_id=conjunto.id, rol="portero").first():
            db.add(models.ConjuntoMembership(usuario_id=portero.id, conjunto_id=conjunto.id, rol="portero"))
        contador = db.query(models.Usuario).filter_by(email="contador@iris-demo.com").first()
        if contador and not db.query(models.ConjuntoMembership).filter_by(usuario_id=contador.id, conjunto_id=conjunto.id, rol="contador").first():
            db.add(models.ConjuntoMembership(usuario_id=contador.id, conjunto_id=conjunto.id, rol="contador"))

        # Datos iniciales idempotentes para que pagos y cartelera sean probables desde el primer acceso.
        demo_unit = db.query(models.Inmueble).filter_by(conjunto_id=conjunto.id, propietario_id=residente.id).order_by(models.Inmueble.id).first()
        admin_user = db.query(models.Usuario).filter_by(email="admin@iris-demo.com").first()
        if demo_unit and admin_user and not db.query(models.Cuota).filter_by(inmueble_id=demo_unit.id).first():
            db.add(models.Cuota(inmueble_id=demo_unit.id, concepto="Cuota de administración de prueba", periodo=date.today().strftime("%Y-%m"), monto=350000, fecha_vencimiento=date.today() + timedelta(days=30), estado="pendiente", creado_por=admin_user.id))
        if admin_user and not db.query(models.Comunicado).filter_by(conjunto_id=conjunto.id, titulo="Bienvenido a IRIS").first():
            db.add(models.Comunicado(conjunto_id=conjunto.id, titulo="Bienvenido a IRIS", contenido="Este es un comunicado de demostración. La administración puede publicar y adjuntar avisos desde el panel.", creado_por=admin_user.id))

        db.commit()
        if nuevos_inmuebles or nuevas_zonas:
            print(f"Datos de ejemplo agregados: {nuevos_inmuebles} inmueble(s), {nuevas_zonas} zona(s) común(es)")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
