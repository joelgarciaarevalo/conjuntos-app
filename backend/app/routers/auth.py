from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.dependencies import verificar_password, hashear_password, crear_token

# Crear endpoints para registro y login de usuarios
router = APIRouter(prefix="/auth", tags=["Autenticación"])

@router.post("/registro", response_model=schemas.UsuarioResponse, status_code=201)
def registrar_usuario(datos: schemas.UsuarioCreate, db: Session = Depends(get_db)):
    # Verificar existencia email
    if db.query(models.Usuario).filter(models.Usuario.email == datos.email).first():
        raise HTTPException(status_code=400, detail="El email ya está registrado")
    
    # Verificar existencia cedula
    if db.query(models.Usuario).filter(models.Usuario.cedula == datos.cedula).first():
        raise HTTPException(status_code=400, detail="La cédula ya está registrada")
    
    nuevo_usuario = models.Usuario(
        nombre_completo=datos.nombre_completo,
        cedula=datos.cedula,
        email=datos.email,
        password_hash=hashear_password(datos.password),
        telefono=datos.telefono
    )
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    return nuevo_usuario

@router.post("/login")
def login(datos: schemas.LoginData, db: Session = Depends(get_db)):
    usuario = db.query(models.Usuario).filter(models.Usuario.email == datos.email).first()

    if not usuario or not verificar_password(datos.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos"
        )

    token = crear_token({"sub": usuario.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "nombre_completo": usuario.nombre_completo,
        "es_super_admin": usuario.es_super_admin,
        "id": usuario.id
    }