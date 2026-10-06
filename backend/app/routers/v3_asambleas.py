"""Votaciones y asambleas: convocatorias, quórum, votación digital y actas."""
from __future__ import annotations

import hashlib
import html as html_lib
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import models, models_v3
from app.database import get_db
from app.permissions import can_access_set, is_admin, require_admin_set, require_staff_set
from app.dependencies import SECRET_KEY
from app.security_v3 import dependencia_2fa, exigir_2fa_admin, get_usuario_v3
from app.routers.v3_common import (
    admin_only, alcance, avisar_evento, conjunto_de, dec, dt, etiqueta_unidad, json_dumps, json_loads,
    localnow, model_data, notificar, units_for_user,
)

router = APIRouter(prefix="/v3/asambleas", tags=["v3 · Asambleas y votaciones"])

OPCIONES_BASE = {"si_no": ["si", "no"], "opciones": [], "eleccion": []}


def _conjunto_de_asamblea(db: Session, user: models.Usuario, asamblea: models_v3.Asamblea) -> None:
    if user.es_super_admin:
        return
    if not can_access_set(db, user, asamblea.conjunto_id):
        raise HTTPException(403, "No tienes acceso a esta asamblea")


def _unidades_conjunto(db: Session, conjunto_id: int) -> list[models.Inmueble]:
    return db.query(models.Inmueble).filter_by(conjunto_id=conjunto_id).all()


def _quorum(db: Session, asamblea: models_v3.Asamblea) -> dict:
    unidades = _unidades_conjunto(db, asamblea.conjunto_id)
    total = len(unidades)
    asistencias = db.query(models_v3.AsistenciaAsamblea).filter_by(asamblea_id=asamblea.id).all()
    representadas = len({a.inmueble_id for a in asistencias})
    porcentaje = (Decimal(representadas) / Decimal(total) * 100).quantize(Decimal("0.01")) if total else Decimal("0")
    return {
        "unidades_totales": total,
        "unidades_representadas": representadas,
        "porcentaje": str(porcentaje),
        "requerido": str(asamblea.quorum_requerido),
        "alcanzado": porcentaje >= dec(asamblea.quorum_requerido),
    }


def _resultados(db: Session, votacion: models_v3.Votacion) -> dict:
    votos = db.query(models_v3.Voto).filter_by(votacion_id=votacion.id).all()
    opciones = json_loads(votacion.opciones, []) or OPCIONES_BASE.get(votacion.tipo, ["si", "no"])
    conteo: dict[str, Decimal] = {opcion: Decimal("0") for opcion in opciones}
    conteo.setdefault("abstencion", Decimal("0"))
    for voto in votos:
        conteo[voto.opcion] = conteo.get(voto.opcion, Decimal("0")) + dec(voto.peso)
    validos = sum((valor for clave, valor in conteo.items() if clave != "abstencion"), Decimal("0"))
    total = sum(conteo.values(), Decimal("0"))
    ganador, cumple = None, False
    if validos > 0:
        if votacion.mayoria == "simple":
            maximo = max((valor for clave, valor in conteo.items() if clave != "abstencion"), default=Decimal("0"))
            lideres = [clave for clave, valor in conteo.items() if clave != "abstencion" and valor == maximo]
            if len(lideres) == 1:
                ganador, cumple = lideres[0], True
            else:
                ganador, cumple = "empate", False
        else:
            requerido = Decimal("0.5") if votacion.mayoria == "absoluta" else Decimal("0.6667")
            for clave, valor in conteo.items():
                if clave == "abstencion":
                    continue
                if valor / validos > requerido:
                    ganador, cumple = clave, True
                    break
            if ganador is None:
                maximo = max((valor for clave, valor in conteo.items() if clave != "abstencion"), default=Decimal("0"))
                ganador = next((clave for clave, valor in conteo.items() if clave != "abstencion" and valor == maximo), None)
    return {
        "votacion_id": votacion.id, "titulo": votacion.titulo, "tipo": votacion.tipo,
        "mayoria": votacion.mayoria, "estado": votacion.estado,
        "conteo": {clave: str(valor) for clave, valor in conteo.items()},
        "votos_totales": str(total), "votos_validos": str(validos),
        "ganador": ganador, "aprobada": cumple, "opciones": opciones,
    }


# ---------------------------------------------------------------------------
# Convocatorias y asambleas
# ---------------------------------------------------------------------------
@router.get("")
def listar(conjunto_id: int | None = None, estado: str | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    q = db.query(models_v3.Asamblea)
    if is_admin(user):
        ids = [conjunto_id] if conjunto_id else alcance(db, user)
        if conjunto_id:
            require_admin_set(db, user, conjunto_id)
        q = q.filter(models_v3.Asamblea.conjunto_id.in_(ids)) if ids else q.filter(models_v3.Asamblea.id < 0)
    else:
        unidades = units_for_user(db, user)
        ids = {u.conjunto_id for u in unidades}
        q = q.filter(models_v3.Asamblea.conjunto_id.in_(ids)) if ids else q.filter(models_v3.Asamblea.id < 0)
    if estado:
        q = q.filter(models_v3.Asamblea.estado == estado)
    salida = []
    for fila in q.order_by(models_v3.Asamblea.fecha_inicio.desc()).limit(200).all():
        datos = model_data(fila)
        datos["quorum"] = _quorum(db, fila)
        datos["votaciones"] = db.query(models_v3.Votacion).filter_by(asamblea_id=fila.id).count()
        datos["conjunto"] = db.query(models.Conjunto.nombre).filter_by(id=fila.conjunto_id).scalar()
        salida.append(datos)
    return salida


@router.post("", status_code=201)
def crear(data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    conjunto_id = conjunto_de(db, user, data, staff=False)
    titulo = str(data.get("titulo") or "").strip()
    if not titulo:
        raise HTTPException(422, "El título de la asamblea es obligatorio")
    if not data.get("fecha_inicio") or not data.get("fecha_fin"):
        raise HTTPException(422, "Indica fecha de inicio y de cierre")
    inicio, fin = dt(data["fecha_inicio"]), dt(data["fecha_fin"])
    if fin <= inicio:
        raise HTTPException(422, "La fecha de cierre debe ser posterior al inicio")
    quorum = dec(data.get("quorum_requerido") or 50)
    if not 0 < quorum <= 100:
        raise HTTPException(422, "El quórum debe estar entre 0 y 100 %")
    modalidad = str(data.get("modalidad") or "virtual")
    if modalidad not in ("presencial", "virtual", "mixta"):
        raise HTTPException(422, "Modalidad inválida")
    fila = models_v3.Asamblea(
        conjunto_id=conjunto_id, titulo=titulo[:160], tipo=str(data.get("tipo") or "ordinaria")[:20],
        modalidad=modalidad, lugar=str(data.get("lugar") or "")[:255] or None, enlace=str(data.get("enlace") or "")[:500] or None,
        fecha_convocatoria=localnow(), fecha_inicio=inicio, fecha_fin=fin, quorum_requerido=quorum, creado_por=user.id,
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.get("/{asamblea_id}")
def detalle(asamblea_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Asamblea).filter_by(id=asamblea_id).first()
    if not fila:
        raise HTTPException(404, "Asamblea no encontrada")
    _conjunto_de_asamblea(db, user, fila)
    datos = model_data(fila)
    datos["quorum"] = _quorum(db, fila)
    datos["votaciones"] = [_resultados(db, v) | {"descripcion": v.descripcion, "permite_abstencion": v.permite_abstencion}
                           for v in db.query(models_v3.Votacion).filter_by(asamblea_id=fila.id).order_by(models_v3.Votacion.orden).all()]
    datos["asistencias"] = [
        {**model_data(a), "inmueble": etiqueta_unidad(db.query(models.Inmueble).filter_by(id=a.inmueble_id).first())}
        for a in db.query(models_v3.AsistenciaAsamblea).filter_by(asamblea_id=fila.id).all()
    ]
    return datos


@router.patch("/{asamblea_id}")
def actualizar(asamblea_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Asamblea).filter_by(id=asamblea_id).first()
    if not fila:
        raise HTTPException(404, "Asamblea no encontrada")
    require_admin_set(db, user, fila.conjunto_id)
    if data.get("titulo"):
        fila.titulo = str(data["titulo"])[:160]
    if data.get("lugar") is not None:
        fila.lugar = str(data["lugar"])[:255] or None
    if data.get("enlace") is not None:
        fila.enlace = str(data["enlace"])[:500] or None
    if data.get("fecha_inicio"):
        fila.fecha_inicio = dt(data["fecha_inicio"])
    if data.get("fecha_fin"):
        fila.fecha_fin = dt(data["fecha_fin"])
    if fila.fecha_fin <= fila.fecha_inicio:
        raise HTTPException(422, "La fecha de cierre debe ser posterior al inicio")
    if data.get("quorum_requerido") is not None:
        quorum = dec(data["quorum_requerido"])
        if not 0 < quorum <= 100:
            raise HTTPException(422, "El quórum debe estar entre 0 y 100 %")
        fila.quorum_requerido = quorum
    if data.get("estado"):
        if data["estado"] not in ("convocada", "en_curso", "cerrada", "cancelada"):
            raise HTTPException(422, "Estado inválido")
        fila.estado = data["estado"]
    db.commit()
    db.refresh(fila)
    return model_data(fila)


@router.delete("/{asamblea_id}", status_code=204)
def borrar(asamblea_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Asamblea).filter_by(id=asamblea_id).first()
    if not fila:
        raise HTTPException(404, "Asamblea no encontrada")
    require_admin_set(db, user, fila.conjunto_id)
    if db.query(models_v3.Voto).filter_by(asamblea_id=asamblea_id).first():
        raise HTTPException(409, "La asamblea ya tiene votos registrados; ciérrala en lugar de eliminarla")
    db.delete(fila)
    db.commit()
    return Response(status_code=204)


@router.post("/{asamblea_id}/convocar")
def convocar(asamblea_id: int, data: dict | None = None, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Asamblea).filter_by(id=asamblea_id).first()
    if not fila:
        raise HTTPException(404, "Asamblea no encontrada")
    require_admin_set(db, user, fila.conjunto_id)
    unidades = _unidades_conjunto(db, fila.conjunto_id)
    residentes = {uid for u in unidades for uid in (u.propietario_id, u.inquilino_id) if uid}
    mensaje = f"{fila.titulo} · inicia {fila.fecha_inicio.strftime('%Y-%m-%d %H:%M')} · modalidad {fila.modalidad} · lugar/enlace: {fila.lugar or fila.enlace or 'por definir'}"
    enviados = 0
    for usuario_id in residentes:
        notificar(db, usuario_id, "Convocatoria a asamblea", mensaje)
        resultado = avisar_evento(db, usuario_id, "asamblea", {
            "titulo": fila.titulo, "fecha": fila.fecha_inicio.strftime("%Y-%m-%d %H:%M"),
            "lugar": fila.lugar or fila.enlace or "por definir",
            "mensaje": mensaje,
        }, conjunto_id=fila.conjunto_id)
        if resultado.get("enviado"):
            enviados += 1
    fila.fecha_convocatoria = localnow()
    db.commit()
    return {"convocados": len(residentes), "avisos_externos_enviados": enviados, "mensaje": mensaje}


# ---------------------------------------------------------------------------
# Asistencia y quórum
# ---------------------------------------------------------------------------
@router.post("/{asamblea_id}/asistencia", status_code=201)
def registrar_asistencia(asamblea_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Asamblea).filter_by(id=asamblea_id).first()
    if not fila:
        raise HTTPException(404, "Asamblea no encontrada")
    _conjunto_de_asamblea(db, user, fila)
    unidades = units_for_user(db, user)
    if is_admin(user):
        unidad = db.query(models.Inmueble).filter_by(id=int(data.get("inmueble_id") or 0), conjunto_id=fila.conjunto_id).first()
        if not unidad:
            raise HTTPException(422, "Indica un inmueble del conjunto")
        usuario_id = data.get("usuario_id") or unidad.propietario_id
    else:
        if not unidades:
            raise HTTPException(403, "No tienes inmuebles en este conjunto")
        unidad = next((u for u in unidades if u.conjunto_id == fila.conjunto_id), None)
        if not unidad:
            raise HTTPException(403, "No tienes inmuebles en este conjunto")
        usuario_id = user.id
    existente = db.query(models_v3.AsistenciaAsamblea).filter_by(asamblea_id=fila.id, inmueble_id=unidad.id).first()
    if existente:
        return {**model_data(existente), "quorum": _quorum(db, fila), "ya_registrado": True}
    asistencia = models_v3.AsistenciaAsamblea(
        asamblea_id=fila.id, inmueble_id=unidad.id, usuario_id=int(usuario_id) if usuario_id else None,
        representado_por=str(data.get("representado_por") or "")[:120] or user.nombre_completo,
        poder=bool(data.get("poder", False)),
    )
    db.add(asistencia)
    db.commit()
    db.refresh(asistencia)
    return {**model_data(asistencia), "quorum": _quorum(db, fila), "ya_registrado": False}


@router.get("/{asamblea_id}/quorum")
def quorum(asamblea_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Asamblea).filter_by(id=asamblea_id).first()
    if not fila:
        raise HTTPException(404, "Asamblea no encontrada")
    _conjunto_de_asamblea(db, user, fila)
    return _quorum(db, fila)


# ---------------------------------------------------------------------------
# Votaciones
# ---------------------------------------------------------------------------
@router.post("/{asamblea_id}/votaciones", status_code=201)
def crear_votacion(asamblea_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Asamblea).filter_by(id=asamblea_id).first()
    if not fila:
        raise HTTPException(404, "Asamblea no encontrada")
    require_admin_set(db, user, fila.conjunto_id)
    titulo = str(data.get("titulo") or "").strip()
    if not titulo:
        raise HTTPException(422, "El título de la votación es obligatorio")
    tipo = str(data.get("tipo") or "si_no")
    if tipo not in OPCIONES_BASE:
        raise HTTPException(422, "Tipo de votación inválido")
    opciones = data.get("opciones")
    if tipo in ("opciones", "eleccion"):
        opciones = [str(o).strip()[:120] for o in (opciones or []) if str(o).strip()]
        if len(opciones) < 2:
            raise HTTPException(422, "Indica al menos dos opciones")
    else:
        opciones = ["si", "no"]
    mayoria = str(data.get("mayoria") or "simple")
    if mayoria not in ("simple", "absoluta", "calificada"):
        raise HTTPException(422, "Mayoría inválida")
    votacion = models_v3.Votacion(
        asamblea_id=fila.id, titulo=titulo[:200], descripcion=str(data.get("descripcion") or "")[:2000] or None,
        tipo=tipo, opciones=json_dumps(opciones), permite_abstencion=bool(data.get("permite_abstencion", True)),
        mayoria=mayoria, orden=int(data.get("orden") or (db.query(models_v3.Votacion).filter_by(asamblea_id=fila.id).count() + 1)),
    )
    db.add(votacion)
    db.commit()
    db.refresh(votacion)
    return _resultados(db, votacion)


@router.patch("/votaciones/{votacion_id}")
def cambiar_estado_votacion(votacion_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    votacion = db.query(models_v3.Votacion).filter_by(id=votacion_id).first()
    if not votacion:
        raise HTTPException(404, "Votación no encontrada")
    asamblea = db.query(models_v3.Asamblea).filter_by(id=votacion.asamblea_id).first()
    require_admin_set(db, user, asamblea.conjunto_id)
    estado = str(data.get("estado") or "")
    if estado not in ("abierta", "cerrada"):
        raise HTTPException(422, "Estado inválido: abierta o cerrada")
    votacion.estado = estado
    if estado == "cerrada":
        resultado = _resultados(db, votacion)
        votacion.ganador = resultado.get("ganador")
    db.commit()
    db.refresh(votacion)
    return _resultados(db, votacion)


@router.post("/votaciones/{votacion_id}/votar")
def votar(votacion_id: int, data: dict, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    votacion = db.query(models_v3.Votacion).filter_by(id=votacion_id).first()
    if not votacion:
        raise HTTPException(404, "Votación no encontrada")
    asamblea = db.query(models_v3.Asamblea).filter_by(id=votacion.asamblea_id).first()
    _conjunto_de_asamblea(db, user, asamblea)
    ahora = localnow()
    if asamblea.estado in ("cerrada", "cancelada"):
        raise HTTPException(409, "La asamblea ya finalizó")
    if asamblea.estado != "en_curso":
        raise HTTPException(409, "La asamblea no está en curso; la administración debe abrirla")
    if ahora < asamblea.fecha_inicio or ahora > asamblea.fecha_fin:
        raise HTTPException(409, "La votación está fuera de la ventana de la asamblea")
    if votacion.estado != "abierta":
        raise HTTPException(409, "La votación está cerrada")
    unidades = units_for_user(db, user)
    if is_admin(user):
        raise HTTPException(403, "La administración no vota en nombre de los residentes")
    unidad = next((u for u in unidades if u.conjunto_id == asamblea.conjunto_id), None)
    if not unidad:
        raise HTTPException(403, "No tienes inmuebles en este conjunto")
    opcion = str(data.get("opcion") or "").strip()
    opciones = json_loads(votacion.opciones, []) or OPCIONES_BASE.get(votacion.tipo, ["si", "no"])
    permitidas = set(opciones) | ({"abstencion"} if votacion.permite_abstencion else set())
    if opcion not in permitidas:
        raise HTTPException(422, f"Opción inválida. Permitidas: {', '.join(sorted(permitidas))}")
    if db.query(models_v3.Voto).filter_by(votacion_id=votacion.id, inmueble_id=unidad.id).first():
        raise HTTPException(409, "Tu inmueble ya emitió su voto en esta votación")
    hash_validacion = hashlib.sha256(f"{SECRET_KEY}:{votacion.id}:{unidad.id}:{user.id}".encode()).hexdigest()
    voto = models_v3.Voto(
        votacion_id=votacion.id, asamblea_id=asamblea.id, inmueble_id=unidad.id, usuario_id=user.id,
        opcion=opcion, peso=Decimal("1"), hash_validacion=hash_validacion,
    )
    db.add(voto)
    db.commit()
    return {"registrado": True, "votacion_id": votacion.id, "inmueble": etiqueta_unidad(unidad),
            "hash_validacion": hash_validacion[:16], "resultados": _resultados(db, votacion)}


@router.get("/votaciones/{votacion_id}/resultados")
def resultados(votacion_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    votacion = db.query(models_v3.Votacion).filter_by(id=votacion_id).first()
    if not votacion:
        raise HTTPException(404, "Votación no encontrada")
    asamblea = db.query(models_v3.Asamblea).filter_by(id=votacion.asamblea_id).first()
    _conjunto_de_asamblea(db, user, asamblea)
    return _resultados(db, votacion)


# ---------------------------------------------------------------------------
# Acta
# ---------------------------------------------------------------------------
@router.post("/{asamblea_id}/acta/generar")
def generar_acta(asamblea_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Asamblea).filter_by(id=asamblea_id).first()
    if not fila:
        raise HTTPException(404, "Asamblea no encontrada")
    require_admin_set(db, user, fila.conjunto_id)
    grupo = db.query(models.Conjunto).filter_by(id=fila.conjunto_id).first()
    quorum = _quorum(db, fila)
    asistencias = db.query(models_v3.AsistenciaAsamblea).filter_by(asamblea_id=fila.id).all()
    votaciones = db.query(models_v3.Votacion).filter_by(asamblea_id=fila.id).order_by(models_v3.Votacion.orden).all()
    lineas = [
        f"ACTA DE ASAMBLEA · {fila.titulo}",
        f"Conjunto: {grupo.nombre if grupo else fila.conjunto_id} · NIT {grupo.nit if grupo else '—'}",
        f"Tipo: {fila.tipo} · Modalidad: {fila.modalidad}",
        f"Convocatoria: {fila.fecha_convocatoria.strftime('%Y-%m-%d %H:%M')}",
        f"Desarrollo: {fila.fecha_inicio.strftime('%Y-%m-%d %H:%M')} a {fila.fecha_fin.strftime('%Y-%m-%d %H:%M')}",
        f"Lugar/enlace: {fila.lugar or fila.enlace or 'no registrado'}",
        f"Quórum: {quorum['unidades_representadas']} de {quorum['unidades_totales']} unidades ({quorum['porcentaje']}%), requerido {quorum['requerido']}% · {'ALCANZADO' if quorum['alcanzado'] else 'NO ALCANZADO'}",
        "",
        "ASISTENCIA",
    ]
    for asistencia in asistencias:
        unidad = db.query(models.Inmueble).filter_by(id=asistencia.inmueble_id).first()
        lineas.append(f"- {etiqueta_unidad(unidad)} · {asistencia.representado_por or '—'}{' (con poder)' if asistencia.poder else ''}")
    lineas.append("")
    lineas.append("PUNTOS VOTADOS")
    for votacion in votaciones:
        resultado = _resultados(db, votacion)
        lineas.append(f"- {resultado['titulo']} ({resultado['tipo']}, mayoría {resultado['mayoria']}): {resultado['conteo']} · Decisión: {resultado['ganador'] or 'sin decisión'} · {'APROBADA' if resultado['aprobada'] else 'NO APROBADA'}")
    lineas.append("")
    lineas.append(f"Acta generada por IRIS el {localnow().strftime('%Y-%m-%d %H:%M')} por {user.nombre_completo}.")
    fila.acta = "\n".join(lineas)
    fila.acta_generada_en = localnow()
    db.commit()
    return {"acta": fila.acta, "generada_en": fila.acta_generada_en.isoformat()}


@router.get("/{asamblea_id}/acta", response_class=HTMLResponse)
def ver_acta(asamblea_id: int, db: Session = Depends(get_db), user=Depends(get_usuario_v3)):
    fila = db.query(models_v3.Asamblea).filter_by(id=asamblea_id).first()
    if not fila:
        raise HTTPException(404, "Asamblea no encontrada")
    _conjunto_de_asamblea(db, user, fila)
    if not fila.acta:
        raise HTTPException(409, "El acta aún no ha sido generada")
    cuerpo = "".join(f"<p>{html_lib.escape(linea) or '&nbsp;'}</p>" for linea in fila.acta.split("\n"))
    return HTMLResponse(f"""<!doctype html><html lang="es"><meta charset="utf-8"><title>Acta · {html_lib.escape(fila.titulo)}</title>
<style>body{{font:15px Arial;max-width:820px;margin:48px auto;color:#0c3b45}}h1{{font-size:22px}}p{{margin:6px 0}}button{{padding:10px 18px;background:#21666b;color:#fff;border:0;cursor:pointer}}@media print{{button{{display:none}}}}</style>
<h1>Acta de asamblea</h1>{cuerpo}<button onclick="window.print()">Imprimir / Guardar PDF</button></html>""")