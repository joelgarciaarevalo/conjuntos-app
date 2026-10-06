from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime

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
    rol: str = "residente"
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str

class LoginData(BaseModel):
    email: EmailStr
    password: str

class ConjuntoCreate(BaseModel):
    nombre: str
    nit: str
    direccion: str

class ConjuntoResponse(BaseModel):
    id: int
    nombre: str
    nit: str
    direccion: str
    model_config = ConfigDict(from_attributes=True)

class InmuebleCreate(BaseModel):
    torre: Optional[str] = None
    numero: str
    propietario_id: int
    inquilino_id: Optional[int] = None
    estado: Optional[str] = "ocupado"

class InmuebleResponse(BaseModel):
    id: int
    conjunto_id: int
    torre: Optional[str]
    numero: str
    propietario_id: int
    inquilino_id: Optional[int]
    estado: str
    model_config = ConfigDict(from_attributes=True)

class ZonaComunCreate(BaseModel):
    nombre: str
    requiere_aprobacion: Optional[bool] = True
    hora_apertura: str = "06:00"
    hora_cierre: str = "22:00"
    duracion_max_minutos: int = Field(default=240, ge=1, le=1440)
    max_dias_anticipacion: int = Field(default=30, ge=1, le=365)
    max_reservas_dia_inmueble: int = Field(default=2, ge=1, le=20)

class ZonaComunResponse(BaseModel):
    id: int
    conjunto_id: int
    nombre: str
    requiere_aprobacion: bool
    hora_apertura: str = "06:00"
    hora_cierre: str = "22:00"
    duracion_max_minutos: int = 240
    max_dias_anticipacion: int = 30
    max_reservas_dia_inmueble: int = 2
    model_config = ConfigDict(from_attributes=True)

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
    model_config = ConfigDict(from_attributes=True)

class ReservaEstadoUpdate(BaseModel):
    estado: str

class PQRSCreate(BaseModel):
    inmueble_id: int
    tipo: str
    descripcion: str

class PQRSResponse(BaseModel):
    id: int
    inmueble_id: int
    solicitante_id: int
    tipo: str
    descripcion: str
    estado: str
    fecha_radicacion: datetime
    respuesta_admin: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class PQRSRespuestaUpdate(BaseModel):
    respuesta_admin: str
    estado: str
