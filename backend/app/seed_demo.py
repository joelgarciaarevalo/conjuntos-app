import os
from app import models
from app.database import Base, SessionLocal, engine
from app.dependencies import hashear_password, verificar_password


def ensure_demo_users() -> None:
    """Crea o corrige solo cuentas demo en desarrollo local."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        demos = [
            {"nombre_completo": "Administración IRIS", "cedula": "DEMO-ADMIN-001", "email": "admin@iris-demo.com", "password": "Admin2026", "es_super_admin": True, "rol": "admin"},
            {"nombre_completo": "Residente de prueba", "cedula": "DEMO-RES-001", "email": "residente@iris-demo.com", "password": "Usuario2026", "es_super_admin": False, "rol": "residente"},
            {"nombre_completo": "Portería IRIS", "cedula": "DEMO-PORT-001", "email": "portero@iris-demo.com", "password": "Portero2026", "es_super_admin": False, "rol": "portero"},
            {"nombre_completo": "Contador de demostración IRIS", "cedula": "DEMO-CONT-001", "email": "contador@iris-demo.com", "password": "Contador2026!", "es_super_admin": False, "rol": "contador"},
        ]
        for data in demos:
            row = db.query(models.Usuario).filter_by(email=data["email"]).first()
            if row:
                row.nombre_completo = data["nombre_completo"]; row.cedula = data["cedula"]
                row.es_super_admin = data["es_super_admin"]; row.rol = data["rol"]
                if not verificar_password(data["password"], row.password_hash): row.password_hash = hashear_password(data["password"])
            else:
                db.add(models.Usuario(**{k: v for k, v in data.items() if k != "password"}, password_hash=hashear_password(data["password"])))
        db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()


def ensure_bootstrap_admin() -> None:
    """Bootstrap controlado: producción requiere un superadmin inicial, sin cuentas demo."""
    db = SessionLocal()
    try:
        if db.query(models.Usuario).filter(models.Usuario.es_super_admin.is_(True)).first():
            return
        email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
        name = os.getenv("BOOTSTRAP_ADMIN_NAME", "Administrador IRIS").strip()
        document = os.getenv("BOOTSTRAP_ADMIN_DOCUMENT", "").strip()
        if not email or len(password) < 12 or "CAMBIAR" in password.upper() or not document or "DOCUMENTO_" in document.upper():
            raise RuntimeError("Configura BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_PASSWORD (mínimo 12 caracteres) y BOOTSTRAP_ADMIN_DOCUMENT para crear el primer administrador")
        existing = db.query(models.Usuario).filter(models.Usuario.email == email).first()
        if existing:
            existing.es_super_admin = True; existing.rol = "admin"
        else:
            db.add(models.Usuario(nombre_completo=name, cedula=document, email=email, password_hash=hashear_password(password), es_super_admin=True, rol="admin"))
        db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()


def cargar_demo() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_demo_users()


if __name__ == "__main__":
    cargar_demo()
