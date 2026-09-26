"""Reglas del flujo de solicitudes de stickers de los inventariadores."""
from datetime import datetime
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.models import (
    BienInventarioImpresion,
    ItemSolicitudImpresionInventario,
    SolicitudImpresionInventario,
)


ESTADO_SINCRONIZACION = "Pendiente de sincronización"
MENSAJE_SINCRONIZACION = (
    "Aún no aparece en el último reporte cargado. Se vinculará "
    "automáticamente al actualizar One Vision."
)
MOTIVO_NO_ENCONTRADO_ANTERIOR = "QR no encontrado en el inventario vigente."
ESTADOS_ACTIVOS_ITEM = (
    "Pendiente", "En lote", "Listo para recojo", ESTADO_SINCRONIZACION,
)


def normalizar_codigo_qr(valor) -> str:
    texto = str(valor or "").strip()
    if texto.isdigit():
        return texto.lstrip("0") or "0"
    return texto


def normalizar_lista_qr(texto: str) -> list[str]:
    """Acepta uno o varios QR separados por espacios, saltos, coma o punto y coma."""
    resultado = []
    vistos = set()
    for parte in re.split(r"[\s,;]+", str(texto or "")):
        codigo = normalizar_codigo_qr(parte)
        if codigo and codigo not in vistos:
            resultado.append(codigo)
            vistos.add(codigo)
    return resultado


def actualizar_estado_solicitud(solicitud: SolicitudImpresionInventario) -> str:
    estados = [item.estado for item in solicitud.items]
    validos = [estado for estado in estados if estado != "Observado"]
    observados = estados.count("Observado")
    sincronizando = validos.count(ESTADO_SINCRONIZACION)
    if not validos:
        estado = "Observado"
    elif sincronizando == len(validos):
        estado = "Esperando actualización"
    elif all(valor == "Recogido" for valor in validos):
        estado = "Recogido con observados" if observados else "Recogido"
        if solicitud.recogido_en is None:
            solicitud.recogido_en = datetime.utcnow()
    elif all(valor == "Listo para recojo" for valor in validos):
        estado = "Listo para recojo con observados" if observados else "Listo para recojo"
    elif any(valor == "Listo para recojo" for valor in validos):
        estado = "Atención parcial"
    elif any(valor == "En lote" for valor in validos):
        estado = "En lote con sincronización" if sincronizando else "En lote"
    elif any(valor == "Pendiente" for valor in validos):
        estado = "Pendiente con sincronización" if sincronizando else "Pendiente"
    else:
        estado = "Atención parcial"
    solicitud.estado = estado
    solicitud.actualizado_en = datetime.utcnow()
    return estado


def validar_qrs_solicitud(
    db: Session, inventario_id: int, codigos: list[str]
) -> list[dict]:
    resultados = []
    for codigo in codigos:
        item_activo = (
            db.query(ItemSolicitudImpresionInventario)
            .join(ItemSolicitudImpresionInventario.solicitud)
            .filter(
                SolicitudImpresionInventario.inventario_id == inventario_id,
                ItemSolicitudImpresionInventario.codigo_qr == codigo,
                ItemSolicitudImpresionInventario.estado.in_(ESTADOS_ACTIVOS_ITEM),
            )
            .order_by(ItemSolicitudImpresionInventario.id.desc())
            .first()
        )
        if item_activo is not None:
            resultados.append({
                "codigo_qr": codigo,
                "estado": "Observado",
                "motivo": (
                    f"Ya figura en la solicitud #{item_activo.solicitud_id} "
                    f"con estado {item_activo.estado}."
                ),
                "bien": item_activo.bien,
                "requiere_reimpresion": False,
            })
            continue
        bienes = db.query(BienInventarioImpresion).filter(
            BienInventarioImpresion.inventario_id == inventario_id,
            BienInventarioImpresion.activo == 1,
            BienInventarioImpresion.codigo_qr == codigo,
        ).all()
        if not bienes:
            resultados.append({
                "codigo_qr": codigo,
                "estado": "Esperando actualización",
                "motivo": MENSAJE_SINCRONIZACION,
                "bien": None,
                "requiere_reimpresion": False,
            })
            continue
        if len(bienes) > 1:
            resultados.append({
                "codigo_qr": codigo,
                "estado": "Observado",
                "motivo": "El QR está asociado a más de un bien y requiere revisión.",
                "bien": None,
                "requiere_reimpresion": False,
            })
            continue
        bien = bienes[0]
        if not bien.imprimible:
            resultados.append({
                "codigo_qr": codigo,
                "estado": "Observado",
                "motivo": bien.motivo_bloqueo or "El bien no es imprimible.",
                "bien": bien,
                "requiere_reimpresion": False,
            })
            continue
        reimpresion = bien.estado_impresion == "Impreso"
        resultados.append({
            "codigo_qr": codigo,
            "estado": "Reimpresión" if reimpresion else "Disponible",
            "motivo": (
                "Este QR ya fue impreso. Confirma si requiere una reimpresión."
                if reimpresion else ""
            ),
            "bien": bien,
            "requiere_reimpresion": reimpresion,
        })
    return resultados


def crear_solicitud(
    db: Session,
    inventario_id: int,
    usuario_id: int,
    codigos: list[str],
    reimpresiones_confirmadas: set[str] | None = None,
) -> SolicitudImpresionInventario:
    reimpresiones_confirmadas = reimpresiones_confirmadas or set()
    resultados = validar_qrs_solicitud(db, inventario_id, codigos)
    solicitud = SolicitudImpresionInventario(
        inventario_id=inventario_id,
        usuario_id=usuario_id,
        estado="Pendiente",
    )
    db.add(solicitud)
    db.flush()
    for resultado in resultados:
        estado = "Pendiente"
        motivo = None
        reimpresion = bool(resultado["requiere_reimpresion"])
        if resultado["estado"] == "Observado":
            estado = "Observado"
            motivo = resultado["motivo"]
        elif resultado["estado"] == "Esperando actualización":
            estado = ESTADO_SINCRONIZACION
            motivo = MENSAJE_SINCRONIZACION
        elif reimpresion and resultado["codigo_qr"] not in reimpresiones_confirmadas:
            estado = "Observado"
            motivo = "La reimpresión no fue confirmada."
        db.add(ItemSolicitudImpresionInventario(
            solicitud_id=solicitud.id,
            bien_id=resultado["bien"].id if resultado["bien"] else None,
            codigo_qr=resultado["codigo_qr"],
            estado=estado,
            motivo_observacion=motivo,
            es_reimpresion=1 if reimpresion and estado == "Pendiente" else 0,
        ))
    db.flush()
    db.refresh(solicitud)
    actualizar_estado_solicitud(solicitud)
    db.commit()
    db.refresh(solicitud)
    return solicitud


def reconciliar_solicitudes_pendientes(
    db: Session, inventario_id: int,
) -> dict[str, int]:
    """Vincula solicitudes anticipadas después de actualizar el reporte."""
    items = (
        db.query(ItemSolicitudImpresionInventario)
        .join(ItemSolicitudImpresionInventario.solicitud)
        .options(selectinload(ItemSolicitudImpresionInventario.solicitud))
        .filter(
            SolicitudImpresionInventario.inventario_id == inventario_id,
            or_(
                ItemSolicitudImpresionInventario.estado == ESTADO_SINCRONIZACION,
                (
                    (ItemSolicitudImpresionInventario.estado == "Observado")
                    & (
                        ItemSolicitudImpresionInventario.motivo_observacion
                        == MOTIVO_NO_ENCONTRADO_ANTERIOR
                    )
                ),
            ),
        )
        .all()
    )
    solicitudes_afectadas = set()
    vinculados = 0
    observados = 0
    esperando = 0
    for item in items:
        solicitudes_afectadas.add(item.solicitud_id)
        bienes = db.query(BienInventarioImpresion).filter(
            BienInventarioImpresion.inventario_id == inventario_id,
            BienInventarioImpresion.activo == 1,
            BienInventarioImpresion.codigo_qr == item.codigo_qr,
        ).all()
        if not bienes:
            item.estado = ESTADO_SINCRONIZACION
            item.bien_id = None
            item.motivo_observacion = MENSAJE_SINCRONIZACION
            esperando += 1
            continue
        if len(bienes) > 1:
            item.estado = "Observado"
            item.bien_id = None
            item.motivo_observacion = (
                "El QR está asociado a más de un bien y requiere revisión."
            )
            observados += 1
            continue
        bien = bienes[0]
        item.bien_id = bien.id
        if not bien.imprimible:
            item.estado = "Observado"
            item.motivo_observacion = bien.motivo_bloqueo or "El bien no es imprimible."
            observados += 1
        elif bien.estado_impresion == "Impreso":
            item.estado = "Observado"
            item.motivo_observacion = (
                "El QR ya figura como impreso. Envía una nueva solicitud y "
                "confirma la reimpresión."
            )
            observados += 1
        else:
            item.estado = "Pendiente"
            item.motivo_observacion = None
            vinculados += 1
    db.flush()
    for solicitud_id in solicitudes_afectadas:
        solicitud = (
            db.query(SolicitudImpresionInventario)
            .options(selectinload(SolicitudImpresionInventario.items))
            .filter(SolicitudImpresionInventario.id == solicitud_id)
            .one()
        )
        actualizar_estado_solicitud(solicitud)
    return {
        "vinculados": vinculados,
        "observados": observados,
        "esperando": esperando,
    }
