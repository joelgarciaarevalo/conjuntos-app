"""Utilidades compartidas por los routers de IRIS 3.0."""
from __future__ import annotations

import csv
import io
import json
import os
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app import models, models_v3
from app.permissions import allowed_set_ids, can_access_set, is_admin, require_admin_set, require_staff_set

TZ = ZoneInfo("America/Bogota")
MAX_UPLOAD = 10 * 1024 * 1024

IMAGE_TYPES = {
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
    "image/webp": (b"RIFF", ".webp"),
}
DOC_TYPES = {
    "application/pdf": (b"%PDF", ".pdf"),
    **IMAGE_TYPES,
}


def localnow() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def dt(value: str | datetime) -> datetime:
    value = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if isinstance(value, str) else value
    return value.astimezone(TZ).replace(tzinfo=None) if value.tzinfo else value


def dec(value, default="0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value))


def money(value) -> str:
    return f"{Decimal(str(value or 0)):,.2f}"


def model_data(row) -> dict:
    data = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, Decimal):
            data[column.name] = str(value)
        elif isinstance(value, datetime):
            data[column.name] = value.isoformat()
        elif hasattr(value, "value"):
            data[column.name] = value.value
        else:
            data[column.name] = value
    return data


def json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_loads(value, default=None):
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else []


def payload_sin_tarjetas(data: dict) -> None:
    """Rechaza cualquier payload que incluya un número de tarjeta o CVV."""
    from app.services.crypto_v3 import contiene_numero_tarjeta, detectar_campos_prohibidos

    prohibidos = detectar_campos_prohibidos(data)
    if prohibidos:
        raise HTTPException(422, f"IRIS no almacena datos de tarjeta. Campos no permitidos: {', '.join(prohibidos)}. Tokeniza la tarjeta en la pasarela y envía solo el token.")
    if contiene_numero_tarjeta(data):
        raise HTTPException(422, "El payload contiene un número de tarjeta. IRIS nunca recibe ni almacena PAN/CVV: usa la tokenización del proveedor.")


def units_for_user(db: Session, user: models.Usuario) -> list[models.Inmueble]:
    return db.query(models.Inmueble).filter((models.Inmueble.propietario_id == user.id) | (models.Inmueble.inquilino_id == user.id)).all()


def unit_access(db: Session, user: models.Usuario, unit_id: int) -> models.Inmueble:
    unit = db.query(models.Inmueble).filter_by(id=unit_id).first()
    if not unit:
        raise HTTPException(404, "Inmueble no encontrado")
    if not is_admin(user) and user.id not in (unit.propietario_id, unit.inquilino_id):
        raise HTTPException(403, "No tienes acceso a este inmueble")
    if is_admin(user):
        require_admin_set(db, user, unit.conjunto_id)
    return unit


def admin_only(user: models.Usuario) -> None:
    if not is_admin(user):
        raise HTTPException(403, "Solo administración puede realizar esta acción")


def alcance(db: Session, user: models.Usuario) -> list[int]:
    return sorted(allowed_set_ids(db, user))


def conjunto_de(db: Session, user: models.Usuario, data: dict, *, staff: bool = True) -> int:
    cid = int(data.get("conjunto_id") or 0)
    if not cid:
        ids = alcance(db, user)
        if len(ids) == 1:
            cid = ids[0]
        else:
            raise HTTPException(422, "Indica el conjunto")
    (require_staff_set if staff else require_admin_set)(db, user, cid)
    return cid


def usuario_visible(db: Session, user: models.Usuario, usuario_id: int) -> models.Usuario | None:
    objetivo = db.query(models.Usuario).filter_by(id=usuario_id).first()
    if not objetivo:
        return None
    if user.es_super_admin:
        return objetivo
    unidades = db.query(models.Inmueble).filter(
        models.Inmueble.conjunto_id.in_(alcance(db, user)),
        (models.Inmueble.propietario_id == objetivo.id) | (models.Inmueble.inquilino_id == objetivo.id),
    ).first()
    if unidades:
        return objetivo
    membresia = db.query(models.ConjuntoMembership).filter(
        models.ConjuntoMembership.usuario_id == objetivo.id,
        models.ConjuntoMembership.conjunto_id.in_(alcance(db, user)),
    ).first()
    if membresia:
        return objetivo
    return None if (is_admin(user) or user.es_super_admin) else (objetivo if objetivo.id == user.id else None)


async def guardar_archivo(file: UploadFile, tipos: dict, max_bytes: int = MAX_UPLOAD) -> str:
    mime = (file.content_type or "").lower()
    if mime not in tipos:
        raise HTTPException(415, "Tipo de archivo no admitido")
    firma, ext = tipos[mime]
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(413, f"El archivo supera {max_bytes // (1024 * 1024)} MB")
    if not content.startswith(firma) or (mime == "image/webp" and content[8:12] != b"WEBP"):
        raise HTTPException(415, "El contenido no coincide con el tipo declarado")
    root = Path(os.getenv("UPLOAD_DIR", "./uploads"))
    root.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ext
    (root / name).write_bytes(content)
    return "/v3/files/" + name


def archivo_local(filename: str) -> Path:
    if Path(filename).name != filename or filename.startswith("."):
        raise HTTPException(404, "Archivo no encontrado")
    root = Path(os.getenv("UPLOAD_DIR", "./uploads")).resolve()
    path = (root / filename).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "Archivo no encontrado")
    return path


def workbook_response(wb: Workbook, filename: str) -> StreamingResponse:
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def csv_response(rows: list[list], headers: list[str], filename: str) -> StreamingResponse:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    stream = io.BytesIO(("\ufeff" + out.getvalue()).encode())
    return StreamingResponse(stream, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def safe_cell(value: Any):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def tabla(headers: list[str], rows: list[list], titulo: str = "Datos") -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31]
    ws.append(headers)
    for row in rows:
        ws.append([safe_cell(v) for v in row])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return wb


def notificar(db: Session, usuario_id: int, titulo: str, mensaje: str) -> None:
    db.add(models.Notificacion(usuario_id=usuario_id, titulo=titulo, mensaje=mensaje))


def avisar_evento(db: Session, usuario_id: int, evento: str, contexto: dict, conjunto_id: int | None = None, canal: str | None = None) -> dict:
    """Encola un aviso externo (WhatsApp/SMS) respetando el consentimiento."""
    from app.services.messaging import avisar
    try:
        return avisar(db, usuario_id, evento, contexto, conjunto_id=conjunto_id, canal=canal)
    except Exception as exc:  # la mensajería nunca debe romper el flujo principal
        import logging
        logging.getLogger("iris.avisos").warning("No se pudo procesar el aviso %s: %s", evento, exc)
        return {"enviado": False, "motivo": "error", "detalle": str(exc)[:200]}


def conjunto_visible(db: Session, user: models.Usuario, conjunto_id: int) -> None:
    if not can_access_set(db, user, conjunto_id):
        raise HTTPException(403, "No tienes acceso a este conjunto")


def paginar(query, page: int = 1, size: int = 50, max_size: int = 200):
    page = max(1, int(page or 1))
    size = max(1, min(int(size or 50), max_size))
    total = query.count()
    filas = query.offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": filas}


def etiqueta_unidad(unidad: models.Inmueble | None) -> str:
    if not unidad:
        return "—"
    return (f"Torre {unidad.torre} · " if unidad.torre else "") + f"Apto {unidad.numero}"


def resumen_conjunto(db: Session, conjunto_id: int) -> dict:
    nombre = db.query(models.Conjunto.nombre).filter_by(id=conjunto_id).scalar()
    return {"id": conjunto_id, "nombre": nombre}


def dias_entre(desde: datetime, hasta: datetime) -> int:
    return max(0, (dt(hasta).date() - dt(desde).date()).days)


def cartera_vencida(db: Session, conjunto_ids: list[int]) -> dict:
    """Resumen de cartera por rangos de mora (30/60/90 días)."""
    hoy = localnow().date()
    filas = db.query(models.Cuota).join(models.Inmueble).filter(
        models.Inmueble.conjunto_id.in_(conjunto_ids),
        models.Cuota.estado == "pendiente",
    ).all() if conjunto_ids else []
    rangos = {"corriente": Decimal("0"), "d_1_30": Decimal("0"), "d_31_60": Decimal("0"), "d_61_90": Decimal("0"), "d_90_mas": Decimal("0")}
    detalle = []
    for cuota in filas:
        dias = (hoy - cuota.fecha_vencimiento).days
        monto = Decimal(str(cuota.monto))
        clave = "corriente" if dias <= 0 else "d_1_30" if dias <= 30 else "d_31_60" if dias <= 60 else "d_61_90" if dias <= 90 else "d_90_mas"
        rangos[clave] += monto
        detalle.append({"cuota_id": cuota.id, "inmueble_id": cuota.inmueble_id, "monto": str(monto), "dias_mora": max(0, dias), "rango": clave})
    vencida = rangos["d_1_30"] + rangos["d_31_60"] + rangos["d_61_90"] + rangos["d_90_mas"]
    total = vencida + rangos["corriente"]
    return {
        "rangos": {k: str(v) for k, v in rangos.items()},
        "total_pendiente": str(total),
        "total_vencido": str(vencida),
        "cuotas_pendientes": len(filas),
        "detalle": sorted(detalle, key=lambda x: -x["dias_mora"]),
    }