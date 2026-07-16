from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

# Usuarios
class UsuarioCreate(BaseModel):
    nombre_completo: str
    cedula: str
    email: EmailStr
    password: str
    telefono: Optional[str] = None

class UsuarioResponse(BaseModel):
    id: int
    nombre_completo: str
    cedula: str
    email: EmailStr
    telefono: Optional[str] = None
    es_super_admin: bool

    class Config: from_attributes = True


# Auth
class Token(BaseModel):
    access_token: str
    token_type: str

class LoginData(BaseModel):
    email: EmailStr
    password: str


#Conjuntos
class ConjuntoCreate(BaseModel):
    nombre: str
    nit: str
    direccion: str

class ConjuntoResponse(BaseModel):
    id: int
    nombre: str
    nit: str
    direccion: str

    class Config: from_attributes = True


# Inmuebles
class InmuebleCreate(BaseModel):
    torre: Optional[str] = None
    numero: str
    propietario_id: int
    inquilino_id: Optional[int] = None
    estado: Optional[str] = "Ocupado"

class InmuebleResponse(BaseModel):
    id: int
    conjunto_id: int
    torre: Optional[str]
    numero: str
    propietario_id: int
    inquilino_id: Optional[int]
    estado: str

    class Config: from_attributes = True


# Zonas comunes
class ZonaComunCreate(BaseModel):
    nombre: str
    requiere_aprobacion: Optional[bool] = True

class ZonaComunResponse(BaseModel):
    id: int
    conjunto_id: int
    nombre: str
    requiere_aprobacion: bool

    class Config: from_attributes = True


# Reservas
class ReservaCreate(BaseModel):
    zona_id: int
    inmueble_id: int
    fecha_inicio: datetime
    fecha_fin: datetime

class ReservaResponse(BaseModel):
    id: int
    zona_id: int
    inmueble_id: int
    solicitante_id: int
    fecha_inicio: datetime
    fecha_fin: datetime
    estado: str

    class Config: from_attributes = True

class ReservaEstadoUpdate(BaseModel):
    estado: str # Aprobada o Rechazada


# PQRS
class PQRSCreate(BaseModel):
    inmueble_id: int
    tipo: str
    descripcion: str

class PQRSResponse(BaseModel):
    id: int
    inmueble_id: int
    tipo: str
    descripcion: str
    estado: str
    fecha_radicacion: datetime
    respuesta_admin: Optional[str] = None

    class Config: from_attributes = True

class PQRSRespuestaUpdate(BaseModel):
    respuesta_admin: str
    estado: str 