import io
import json
import math
import os
import shutil
import tempfile
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import quote_plus, urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import case, func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth import requiere_administrador
from app.config import ANIO_INVENTARIO
from app.database import get_db
from app.models import (
    BienInventarioImpresion,
    CargaInventarioImpresion,
    InventarioImpresion,
    ItemLoteImpresionInventario,
    ItemSolicitudImpresionInventario,
    LoteImpresionInventario,
    SolicitudImpresionInventario,
)
from app.routers.impresion import _obtener_perfil_impresion
from app.services.excel_inventario_impresion import importar_reporte_inventario
from app.services.pagination import paginas_visibles, rango_registros
from app.services.pdf_etiquetas import clasificar_bienes_impresion, generar_pdf_etiquetas
from app.services.solicitudes_impresion import (
    ESTADO_AREA_PENDIENTE,
    ESTADO_SINCRONIZACION,
    MENSAJE_AREA_PENDIENTE,
    actualizar_estado_solicitud,
    es_sede_administrativa_diresa,
    requiere_actualizar_area,
)


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

FILAS_POR_PAGINA = 50
MAX_BIENES_POR_LOTE = 1000
SIN_DATO = "__SIN_DATO__"


def _filtrar_valor(consulta, columna, valor):
    if not valor:
        return consulta
    if valor == SIN_DATO:
        return consulta.filter(or_(columna.is_(None), columna == ""))
    return consulta.filter(columna == valor)


def _aplicar_filtros(
    consulta,
    inventario_id: int,
    red: str = "",
    establecimiento: str = "",
    area: str = "",
    estado: str = "",
    tipo_bien: str = "",
    q: str = "",
):
    consulta = consulta.filter(
        BienInventarioImpresion.inventario_id == inventario_id,
        BienInventarioImpresion.activo == 1,
    )
    consulta = _filtrar_valor(consulta, BienInventarioImpresion.red, red)
    consulta = _filtrar_valor(
        consulta, BienInventarioImpresion.establecimiento, establecimiento
    )
    consulta = _filtrar_valor(consulta, BienInventarioImpresion.area, area)
    if estado:
        consulta = consulta.filter(BienInventarioImpresion.estado_impresion == estado)
    if tipo_bien:
        consulta = consulta.filter(BienInventarioImpresion.tipo_bien == tipo_bien)
    q = q.strip()
    if q:
        condiciones = [
            BienInventarioImpresion.codigo_patrimonial.ilike(f"{q}%"),
            BienInventarioImpresion.codigo_qr.ilike(f"{q}%"),
        ]
        if len(q) >= 3:
            condiciones.append(BienInventarioImpresion.descripcion.ilike(f"%{q}%"))
        consulta = consulta.filter(or_(
            *condiciones,
        ))
    return consulta


def _opciones_distintas(
    db, columna, inventario_id, q: str = "", limite: int = 50, **filtros
):
    consulta = db.query(columna).filter(
        BienInventarioImpresion.inventario_id == inventario_id,
        BienInventarioImpresion.activo == 1,
    )
    for nombre, valor in filtros.items():
        if nombre == "red":
            consulta = _filtrar_valor(consulta, BienInventarioImpresion.red, valor)
        elif nombre == "establecimiento":
            consulta = _filtrar_valor(
                consulta, BienInventarioImpresion.establecimiento, valor
            )
    q = q.strip()
    if q:
        consulta = consulta.filter(columna.ilike(f"%{q}%"))
    valores = [
        fila[0]
        for fila in consulta.distinct().order_by(columna).limit(limite).all()
    ]
    opciones = []
    if not q and any(valor is None or valor == "" for valor in valores):
        opciones.append({"value": SIN_DATO, "label": "Sin dato"})
    opciones.extend(
        {"value": valor, "label": valor}
        for valor in valores if valor is not None and valor != ""
    )
    return opciones


def _estado_bien(bien) -> str:
    return bien.estado_impresion


def _ultima_impresion(bien):
    return bien.impreso_en


def _adaptar_bien_pdf(bien):
    ubicacion = (
        bien.area
        if es_sede_administrativa_diresa(bien)
        else bien.establecimiento
    )
    return SimpleNamespace(
        id=bien.id,
        codigo_patrimonial=bien.codigo_patrimonial,
        codigo_qr=bien.codigo_qr,
        ruta_qr=bien.ruta_qr,
        descripcion=bien.descripcion,
        centro_costo=SimpleNamespace(nombre_depend=ubicacion or ""),
    )


def _codigos_qr_duplicados(
    db: Session, inventario_id: int, codigos: list[str] | set[str],
) -> set[str]:
    codigos = {codigo for codigo in codigos if codigo}
    if not codigos:
        return set()
    return {
        codigo for (codigo,) in (
            db.query(BienInventarioImpresion.codigo_qr)
            .filter(
                BienInventarioImpresion.inventario_id == inventario_id,
                BienInventarioImpresion.activo == 1,
                BienInventarioImpresion.codigo_qr.in_(codigos),
            )
            .group_by(BienInventarioImpresion.codigo_qr)
            .having(func.count(BienInventarioImpresion.id) > 1)
            .all()
        )
    }


def _lotes_abiertos_por_bien(
    db: Session, bien_ids: list[int] | set[int],
) -> dict[int, int]:
    bien_ids = set(bien_ids)
    if not bien_ids:
        return {}
    filas = (
        db.query(
            ItemLoteImpresionInventario.bien_id,
            ItemLoteImpresionInventario.lote_id,
        )
        .filter(
            ItemLoteImpresionInventario.bien_id.in_(bien_ids),
            ItemLoteImpresionInventario.impreso_en.is_(None),
        )
        .order_by(ItemLoteImpresionInventario.lote_id)
        .all()
    )
    return {bien_id: lote_id for bien_id, lote_id in filas}


def _solicitudes_pendientes_por_bien(
    db: Session, inventario_id: int, bien_ids: list[int] | set[int],
) -> dict[int, list[ItemSolicitudImpresionInventario]]:
    bien_ids = set(bien_ids)
    if not bien_ids:
        return {}
    items = (
        db.query(ItemSolicitudImpresionInventario)
        .join(ItemSolicitudImpresionInventario.solicitud)
        .filter(
            SolicitudImpresionInventario.inventario_id == inventario_id,
            ItemSolicitudImpresionInventario.bien_id.in_(bien_ids),
            ItemSolicitudImpresionInventario.estado == "Pendiente",
        )
        .order_by(ItemSolicitudImpresionInventario.id)
        .all()
    )
    resultado = {}
    for item in items:
        resultado.setdefault(item.bien_id, []).append(item)
    return resultado


def _razon_exclusion_control_impresion(
    bien,
    *,
    qr_duplicado: bool = False,
    lote_abierto: int | None = None,
    permitir_reimpresion: bool = False,
) -> str | None:
    if requiere_actualizar_area(bien):
        return MENSAJE_AREA_PENDIENTE
    if qr_duplicado:
        return "QR duplicado en el inventario; requiere revisión."
    if lote_abierto is not None:
        return f"Ya está incluido en el lote #{lote_abierto}."
    if bien.estado_impresion == "Impreso" and not permitir_reimpresion:
        return "El QR ya fue impreso; confirma la reimpresión para generar otro lote."
    adaptado = _adaptar_bien_pdf(bien)
    excluidos = clasificar_bienes_impresion([adaptado])[1]
    return excluidos[0]["razon"] if excluidos else None


def _marcar_pdf_generado(db: Session, lote: LoteImpresionInventario):
    ahora = datetime.utcnow()
    lote.pdf_generado_en = ahora
    lote.estado = (
        "Impreso parcial"
        if any(item.impreso_en is not None for item in lote.items)
        else "Sticker generado"
    )
    ids_bienes = [
        item.bien_id for item in lote.items if item.impreso_en is None
    ]
    if ids_bienes:
        db.query(BienInventarioImpresion).filter(
            BienInventarioImpresion.id.in_(ids_bienes),
            BienInventarioImpresion.estado_impresion != "Impreso",
        ).update({
            BienInventarioImpresion.estado_impresion: "Sticker generado",
            BienInventarioImpresion.sticker_generado_en: ahora,
        }, synchronize_session=False)
    db.commit()


def _confirmar_items_impresos(db: Session, lote, consulta) -> int:
    pendientes_items = consulta.filter(
        ItemLoteImpresionInventario.impreso_en.is_(None)
    ).all()
    ids_bienes = [item.bien_id for item in pendientes_items]
    ids_solicitud = [
        item.solicitud_item_id for item in pendientes_items
        if item.solicitud_item_id is not None
    ]
    ahora = datetime.utcnow()
    for item in pendientes_items:
        item.impreso_en = ahora
    if ids_bienes:
        db.query(BienInventarioImpresion).filter(
            BienInventarioImpresion.id.in_(ids_bienes)
        ).update({
            BienInventarioImpresion.estado_impresion: "Impreso",
            BienInventarioImpresion.impreso_en: ahora,
        }, synchronize_session=False)
    solicitudes_afectadas = set()
    if ids_solicitud:
        items_solicitud = db.query(ItemSolicitudImpresionInventario).filter(
            ItemSolicitudImpresionInventario.id.in_(ids_solicitud)
        ).all()
        for item in items_solicitud:
            item.estado = "Listo para recojo"
            item.listo_recojo_en = ahora
            solicitudes_afectadas.add(item.solicitud_id)
        db.flush()
        for solicitud_id in solicitudes_afectadas:
            actualizar_estado_solicitud(
                db.get(SolicitudImpresionInventario, solicitud_id)
            )
    db.flush()
    pendientes = db.query(ItemLoteImpresionInventario).filter(
        ItemLoteImpresionInventario.lote_id == lote.id,
        ItemLoteImpresionInventario.impreso_en.is_(None),
    ).count()
    lote.estado = "Impreso" if pendientes == 0 else "Impreso parcial"
    db.commit()
    return len(pendientes_items)


def _resumen_establecimientos(consulta):
    estado = BienInventarioImpresion.estado_impresion
    filas = (
        consulta.with_entities(
            BienInventarioImpresion.red,
            BienInventarioImpresion.establecimiento,
            func.count(BienInventarioImpresion.id),
            func.sum(case((estado == "Pendiente", 1), else_=0)),
            func.sum(case((estado == "Sticker generado", 1), else_=0)),
            func.sum(case((estado == "Impreso", 1), else_=0)),
            func.sum(case((estado == "Bloqueado", 1), else_=0)),
        )
        .group_by(
            BienInventarioImpresion.red,
            BienInventarioImpresion.establecimiento,
        )
        .order_by(
            BienInventarioImpresion.red,
            BienInventarioImpresion.establecimiento,
        )
        .all()
    )
    return [
        {
            "red": red or "Sin RED",
            "establecimiento": establecimiento or "Sin establecimiento",
            "total": total,
            "pendientes": pendientes or 0,
            "generados": generados or 0,
            "impresos": impresos or 0,
            "bloqueados": bloqueados or 0,
            "porcentaje": round((impresos or 0) * 100 / total, 1) if total else 0,
            "completo": bool(total and impresos == total),
        }
        for red, establecimiento, total, pendientes, generados, impresos, bloqueados
        in filas
    ]


@router.get("/control-impresion/opciones")
def opciones_filtro_impresion(
    inventario_id: int,
    campo: str,
    q: str = "",
    red: str = "",
    establecimiento: str = "",
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    columnas = {
        "red": BienInventarioImpresion.red,
        "establecimiento": BienInventarioImpresion.establecimiento,
        "area": BienInventarioImpresion.area,
    }
    columna = columnas.get(campo)
    if columna is None:
        raise HTTPException(status_code=400, detail="Filtro no válido.")
    filtros = {}
    if campo in ("establecimiento", "area"):
        filtros["red"] = red
    if campo == "area":
        filtros["establecimiento"] = establecimiento
    return {
        "options": _opciones_distintas(
            db, columna, inventario_id, q=q, limite=50, **filtros
        )
    }


@router.get("/control-impresion", response_class=HTMLResponse)
def control_impresion(
    request: Request,
    inventario_id: int | None = None,
    red: str = "",
    establecimiento: str = "",
    area: str = "",
    estado: str = "",
    tipo_bien: str = "",
    q: str = "",
    pagina: int = 1,
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    inventarios = db.query(InventarioImpresion).order_by(
        InventarioImpresion.anio.desc(), InventarioImpresion.id.desc()
    ).all()
    inventario = None
    if inventario_id:
        inventario = db.get(InventarioImpresion, inventario_id)
    if inventario is None and inventarios:
        inventario = inventarios[0]

    contexto = {
        "request": request,
        "inventarios": inventarios,
        "inventario": inventario,
        "anio_predeterminado": ANIO_INVENTARIO,
        "max_bienes_lote": MAX_BIENES_POR_LOTE,
        "estados": ("Pendiente", "Sticker generado", "Impreso", "Bloqueado"),
        "filtros": {
            "red": red,
            "establecimiento": establecimiento,
            "area": area,
            "estado": estado,
            "tipo_bien": tipo_bien,
            "q": q,
        },
        "bienes": [],
        "resumen": {nombre: 0 for nombre in (
            "total", "Pendiente", "Sticker generado", "Impreso", "Bloqueado"
        )},
        "resumen_establecimientos": [],
        "lotes": [],
        "cargas_reportes": [],
        "tipos": {"Activo fijo": 0, "Sobrante": 0},
        "solicitudes_pendientes": 0,
        "solicitudes_sincronizacion": 0,
        "solicitudes_area_pendiente": 0,
        "pagina": 1,
        "total_paginas": 1,
        "paginas": [1],
        "inicio": 0,
        "fin": 0,
        "total": 0,
        "url_base": "/control-impresion?",
    }
    if inventario is None:
        return templates.TemplateResponse("control_impresion.html", contexto)

    base = _aplicar_filtros(
        db.query(BienInventarioImpresion), inventario.id,
        red=red, establecimiento=establecimiento, area=area, estado=estado,
        tipo_bien=tipo_bien, q=q,
    )
    total = base.count()
    total_paginas = max(1, math.ceil(total / FILAS_POR_PAGINA))
    pagina = max(1, min(pagina, total_paginas))
    bienes = (
        base.options(
            joinedload(BienInventarioImpresion.bien_alta),
        )
        .order_by(
            BienInventarioImpresion.establecimiento,
            BienInventarioImpresion.area,
            BienInventarioImpresion.codigo_patrimonial,
        )
        .offset((pagina - 1) * FILAS_POR_PAGINA)
        .limit(FILAS_POR_PAGINA)
        .all()
    )
    qr_duplicados = _codigos_qr_duplicados(
        db, inventario.id, {bien.codigo_qr for bien in bienes}
    )
    lotes_abiertos = _lotes_abiertos_por_bien(
        db, {bien.id for bien in bienes}
    )
    filas_bienes = [
        {
            "bien": bien,
            "estado": _estado_bien(bien),
            "ultima_impresion": _ultima_impresion(bien),
            "area_pendiente": requiere_actualizar_area(bien),
            "qr_duplicado": bool(
                bien.codigo_qr and bien.codigo_qr in qr_duplicados
            ),
            "lote_abierto": lotes_abiertos.get(bien.id),
        }
        for bien in bienes
    ]

    conteos = {nombre: 0 for nombre in (
        "Pendiente", "Sticker generado", "Impreso", "Bloqueado"
    )}
    for nombre, cantidad in (
        base.with_entities(
            BienInventarioImpresion.estado_impresion,
            func.count(BienInventarioImpresion.id),
        )
        .group_by(BienInventarioImpresion.estado_impresion)
        .all()
    ):
        conteos[nombre] = cantidad

    parametros = {
        "inventario_id": inventario.id,
        "red": red,
        "establecimiento": establecimiento,
        "area": area,
        "estado": estado,
        "tipo_bien": tipo_bien,
        "q": q,
    }
    url_base = "/control-impresion?" + urlencode(
        {clave: valor for clave, valor in parametros.items() if valor not in (None, "")}
    )
    inicio, fin = rango_registros(pagina, FILAS_POR_PAGINA, total)
    contexto.update({
        "bienes": filas_bienes,
        "resumen": {"total": total, **conteos},
        "tipos": {
            **{"Activo fijo": 0, "Sobrante": 0},
            **dict(
                base.with_entities(
                    BienInventarioImpresion.tipo_bien,
                    func.count(BienInventarioImpresion.id),
                ).group_by(BienInventarioImpresion.tipo_bien).all()
            ),
        },
        "solicitudes_pendientes": db.query(
            ItemSolicitudImpresionInventario
        ).filter(
            ItemSolicitudImpresionInventario.estado == "Pendiente"
        ).count(),
        "solicitudes_sincronizacion": db.query(
            ItemSolicitudImpresionInventario
        ).filter(
            ItemSolicitudImpresionInventario.estado == ESTADO_SINCRONIZACION
        ).count(),
        "solicitudes_area_pendiente": db.query(
            ItemSolicitudImpresionInventario
        ).filter(
            ItemSolicitudImpresionInventario.estado == ESTADO_AREA_PENDIENTE
        ).count(),
        "resumen_establecimientos": _resumen_establecimientos(base),
        "lotes": (
            db.query(LoteImpresionInventario)
            .filter(LoteImpresionInventario.inventario_id == inventario.id)
            .order_by(LoteImpresionInventario.id.desc())
            .limit(20)
            .all()
        ),
        "cargas_reportes": (
            db.query(CargaInventarioImpresion)
            .filter(CargaInventarioImpresion.inventario_id == inventario.id)
            .order_by(
                CargaInventarioImpresion.creado_en.desc(),
                CargaInventarioImpresion.id.desc(),
            )
            .limit(50)
            .all()
        ),
        "pagina": pagina,
        "total_paginas": total_paginas,
        "paginas": paginas_visibles(pagina, total_paginas),
        "inicio": inicio,
        "fin": fin,
        "total": total,
        "url_base": url_base,
    })
    return templates.TemplateResponse("control_impresion.html", contexto)


@router.post("/control-impresion/importar")
def importar_inventario(
    archivo: UploadFile = File(...),
    anio: str = Form(ANIO_INVENTARIO),
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    ruta_temporal = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            ruta_temporal = tmp.name
            shutil.copyfileobj(archivo.file, tmp, length=1024 * 1024)
        resultado = importar_reporte_inventario(
            db, ruta_temporal, archivo.filename or "reporte.xlsx", anio=anio,
        )
    except (ValueError, OSError) as exc:
        db.rollback()
        return RedirectResponse(
            url=f"/control-impresion?error={quote_plus(str(exc))}", status_code=303
        )
    except SQLAlchemyError:
        db.rollback()
        return RedirectResponse(
            url=(
                "/control-impresion?error="
                + quote_plus(
                    "No se pudo completar la carga por un conflicto entre "
                    "identificadores. Revisa los códigos QR del archivo."
                )
            ),
            status_code=303,
        )
    finally:
        if ruta_temporal and os.path.exists(ruta_temporal):
            os.remove(ruta_temporal)

    mensaje = (
        f"Importación acumulativa completada: {resultado['total']} filas "
        f"procesadas, {resultado['nuevos']} nuevas, "
        f"{resultado['actualizados']} actualizadas y "
        f"{resultado['sin_cambios']} sin cambios. Universo actual: "
        f"{resultado['total_universo']} bienes, "
        f"{resultado['activos_fijos_universo']} activos fijos y "
        f"{resultado['sobrantes_universo']} sobrantes."
    )
    if resultado["solicitudes_vinculadas"]:
        mensaje += (
            f" {resultado['solicitudes_vinculadas']} QR solicitado(s) quedaron "
            "listos para preparar su impresión."
        )
    return RedirectResponse(
        url=(
            f"/control-impresion?inventario_id={resultado['inventario_id']}"
            f"&info={quote_plus(mensaje)}"
        ),
        status_code=303,
    )


@router.post("/control-impresion/lotes")
def crear_lote_impresion(
    inventario_id: int = Form(...),
    alcance: str = Form(...),
    bien_ids: list[int] = Form(default=[]),
    red: str = Form(""),
    establecimiento: str = Form(""),
    area: str = Form(""),
    estado: str = Form(""),
    tipo_bien: str = Form(""),
    q: str = Form(""),
    confirmar_reimpresion: bool = Form(False),
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    inventario = db.get(InventarioImpresion, inventario_id)
    if inventario is None:
        raise HTTPException(status_code=404, detail="Inventario no encontrado.")
    consulta = _aplicar_filtros(
        db.query(BienInventarioImpresion), inventario_id,
        red=red, establecimiento=establecimiento, area=area, estado=estado,
        tipo_bien=tipo_bien, q=q,
    )
    if alcance == "seleccionados":
        if not bien_ids:
            return RedirectResponse(
                url=f"/control-impresion?inventario_id={inventario_id}&error="
                    + quote_plus("Selecciona al menos un bien."),
                status_code=303,
            )
        consulta = consulta.filter(BienInventarioImpresion.id.in_(set(bien_ids)))
    elif alcance != "filtrados":
        raise HTTPException(status_code=400, detail="Alcance no válido.")

    bienes = consulta.order_by(BienInventarioImpresion.id).all()
    if len(bienes) > MAX_BIENES_POR_LOTE:
        mensaje = (
            f"La selección tiene {len(bienes)} bienes. El máximo por lote es "
            f"{MAX_BIENES_POR_LOTE}; aplica más filtros."
        )
        return RedirectResponse(
            url=f"/control-impresion?inventario_id={inventario_id}&error="
                + quote_plus(mensaje),
            status_code=303,
        )

    qr_duplicados = _codigos_qr_duplicados(
        db, inventario_id, {bien.codigo_qr for bien in bienes}
    )
    lotes_abiertos = _lotes_abiertos_por_bien(
        db, {bien.id for bien in bienes}
    )
    solicitudes_por_bien = _solicitudes_pendientes_por_bien(
        db, inventario_id, {bien.id for bien in bienes}
    )
    excluidos = []
    seleccionados = []
    for bien in bienes:
        solicitudes_bien = solicitudes_por_bien.get(bien.id, [])
        solicitud_item = solicitudes_bien[0] if len(solicitudes_bien) == 1 else None
        if len(solicitudes_bien) > 1:
            razon = "Tiene más de una solicitud pendiente y requiere revisión."
        else:
            reimpresion_autorizada = bool(
                solicitud_item and solicitud_item.es_reimpresion
            )
            razon = _razon_exclusion_control_impresion(
                bien,
                qr_duplicado=bool(
                    bien.codigo_qr and bien.codigo_qr in qr_duplicados
                ),
                lote_abierto=lotes_abiertos.get(bien.id),
                permitir_reimpresion=(
                    confirmar_reimpresion or reimpresion_autorizada
                ),
            )
        if razon:
            excluidos.append({"bien": bien, "razon": razon})
        else:
            seleccionados.append((bien, solicitud_item))
    if not seleccionados:
        motivos = list(dict.fromkeys(
            excluido["razon"] for excluido in excluidos
        ))
        detalle = f" Motivo: {'; '.join(motivos[:3])}" if motivos else ""
        return RedirectResponse(
            url=f"/control-impresion?inventario_id={inventario_id}&error="
                + quote_plus(
                    "No hay bienes disponibles para crear el lote." + detalle
                ),
            status_code=303,
        )

    filtros = {
        "red": red or None,
        "establecimiento": establecimiento or None,
        "area": area or None,
        "estado": estado or None,
        "tipo_bien": tipo_bien or None,
        "busqueda": q or None,
        "reimpresion_confirmada": confirmar_reimpresion,
        "excluidos": len(excluidos),
    }
    lote = LoteImpresionInventario(
        inventario_id=inventario_id,
        estado="Preparado",
        filtros=json.dumps(filtros, ensure_ascii=False),
        total_bienes=len(seleccionados),
    )
    db.add(lote)
    db.flush()
    solicitudes_afectadas = set()
    for bien, solicitud_item in seleccionados:
        db.add(ItemLoteImpresionInventario(
            lote_id=lote.id,
            bien_id=bien.id,
            solicitud_item_id=solicitud_item.id if solicitud_item else None,
        ))
        if solicitud_item:
            solicitud_item.estado = "En lote"
            solicitudes_afectadas.add(solicitud_item.solicitud_id)
    db.flush()
    for solicitud_id in solicitudes_afectadas:
        actualizar_estado_solicitud(
            db.get(SolicitudImpresionInventario, solicitud_id)
        )
    db.commit()
    info = f"Lote preparado con {len(seleccionados)} bienes."
    if excluidos:
        info += (
            f" Se excluyeron {len(excluidos)} bienes por validaciones "
            "de impresión."
        )
    return RedirectResponse(
        url=f"/control-impresion/lotes/{lote.id}?info={quote_plus(info)}",
        status_code=303,
    )


@router.get("/control-impresion/solicitudes", response_class=HTMLResponse)
def solicitudes_inventariadores(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    solicitudes = (
        db.query(SolicitudImpresionInventario)
        .options(
            joinedload(SolicitudImpresionInventario.usuario),
            selectinload(SolicitudImpresionInventario.items)
            .joinedload(ItemSolicitudImpresionInventario.bien),
        )
        .order_by(SolicitudImpresionInventario.id.desc())
        .limit(200)
        .all()
    )
    pendientes = [
        item for solicitud in solicitudes for item in solicitud.items
        if item.estado == "Pendiente"
    ]
    esperando = [
        item for solicitud in solicitudes for item in solicitud.items
        if item.estado == ESTADO_SINCRONIZACION
    ]
    esperando_area = [
        item for solicitud in solicitudes for item in solicitud.items
        if item.estado == ESTADO_AREA_PENDIENTE
    ]
    return templates.TemplateResponse(
        "control_impresion_solicitudes.html",
        {
            "request": request,
            "solicitudes": solicitudes,
            "pendientes": pendientes,
            "esperando": esperando,
            "esperando_area": esperando_area,
            "max_bienes_lote": MAX_BIENES_POR_LOTE,
        },
    )


@router.post("/control-impresion/solicitudes/lote")
def crear_lote_desde_solicitudes(
    item_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    if not item_ids:
        return RedirectResponse(
            "/control-impresion/solicitudes?error="
            + quote_plus("Selecciona al menos un QR pendiente."),
            status_code=303,
        )
    items = (
        db.query(ItemSolicitudImpresionInventario)
        .options(
            joinedload(ItemSolicitudImpresionInventario.bien),
            joinedload(ItemSolicitudImpresionInventario.solicitud),
        )
        .filter(
            ItemSolicitudImpresionInventario.id.in_(set(item_ids)),
            ItemSolicitudImpresionInventario.estado == "Pendiente",
        )
        .order_by(ItemSolicitudImpresionInventario.id)
        .all()
    )
    if not items:
        return RedirectResponse(
            "/control-impresion/solicitudes?error="
            + quote_plus("Los QR seleccionados ya no están pendientes."),
            status_code=303,
        )
    inventarios = {item.solicitud.inventario_id for item in items}
    if len(inventarios) != 1:
        return RedirectResponse(
            "/control-impresion/solicitudes?error="
            + quote_plus("Selecciona solicitudes de un solo inventario."),
            status_code=303,
        )
    if len(items) > MAX_BIENES_POR_LOTE:
        return RedirectResponse(
            "/control-impresion/solicitudes?error=" + quote_plus(
                f"El máximo por lote es {MAX_BIENES_POR_LOTE} QR."
            ), status_code=303,
        )

    seleccionados = []
    bienes_vistos = set()
    solicitudes_afectadas = set()
    inventario_id = items[0].solicitud.inventario_id
    qr_duplicados = _codigos_qr_duplicados(
        db, inventario_id,
        {item.bien.codigo_qr for item in items if item.bien is not None},
    )
    lotes_abiertos = _lotes_abiertos_por_bien(
        db, {item.bien_id for item in items if item.bien_id is not None}
    )
    for item in items:
        solicitudes_afectadas.add(item.solicitud_id)
        if item.bien is None:
            item.estado = "Observado"
            item.motivo_observacion = "El QR ya no tiene un bien relacionado."
            continue
        if item.bien_id in bienes_vistos:
            item.estado = "Observado"
            item.motivo_observacion = "El mismo bien fue incluido más de una vez."
            continue
        razon = _razon_exclusion_control_impresion(
            item.bien,
            qr_duplicado=bool(
                item.bien.codigo_qr
                and item.bien.codigo_qr in qr_duplicados
            ),
            lote_abierto=lotes_abiertos.get(item.bien_id),
            permitir_reimpresion=bool(item.es_reimpresion),
        )
        if razon:
            if requiere_actualizar_area(item.bien):
                item.estado = ESTADO_AREA_PENDIENTE
            else:
                item.estado = "Observado"
            item.motivo_observacion = razon
            continue
        bienes_vistos.add(item.bien_id)
        seleccionados.append(item)

    if not seleccionados:
        for solicitud_id in solicitudes_afectadas:
            actualizar_estado_solicitud(db.get(SolicitudImpresionInventario, solicitud_id))
        db.commit()
        return RedirectResponse(
            "/control-impresion/solicitudes?error="
            + quote_plus("Ninguno de los QR seleccionados puede imprimirse."),
            status_code=303,
        )

    lote = LoteImpresionInventario(
        inventario_id=inventario_id,
        estado="Preparado",
        filtros=json.dumps({"origen": "Solicitudes de inventariadores"}),
        total_bienes=len(seleccionados),
    )
    db.add(lote)
    db.flush()
    for item in seleccionados:
        db.add(ItemLoteImpresionInventario(
            lote_id=lote.id,
            bien_id=item.bien_id,
            solicitud_item_id=item.id,
        ))
        item.estado = "En lote"
    db.flush()
    for solicitud_id in solicitudes_afectadas:
        actualizar_estado_solicitud(db.get(SolicitudImpresionInventario, solicitud_id))
    db.commit()
    return RedirectResponse(
        f"/control-impresion/lotes/{lote.id}?info=" + quote_plus(
            f"Lote preparado con {len(seleccionados)} QR solicitados."
        ), status_code=303,
    )


@router.get("/control-impresion/lotes/{lote_id}", response_class=HTMLResponse)
def detalle_lote_impresion(
    lote_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    lote = (
        db.query(LoteImpresionInventario)
        .options(
            joinedload(LoteImpresionInventario.inventario),
            selectinload(LoteImpresionInventario.items)
            .joinedload(ItemLoteImpresionInventario.bien)
            .joinedload(BienInventarioImpresion.bien_alta),
        )
        .filter(LoteImpresionInventario.id == lote_id)
        .first()
    )
    if lote is None:
        raise HTTPException(status_code=404, detail="Lote no encontrado.")
    impresos = sum(1 for item in lote.items if item.impreso_en)
    faltantes_area = sum(
        1 for item in lote.items
        if item.impreso_en is None and requiere_actualizar_area(item.bien)
    )
    items_area_pendiente = {
        item.id for item in lote.items
        if item.impreso_en is None and requiere_actualizar_area(item.bien)
    }
    return templates.TemplateResponse(
        "control_impresion_lote.html",
        {
            "request": request,
            "lote": lote,
            "impresos": impresos,
            "pendientes": len(lote.items) - impresos,
            "faltantes_area": faltantes_area,
            "items_area_pendiente": items_area_pendiente,
        },
    )


@router.get("/control-impresion/lotes/{lote_id}/pdf")
def pdf_lote_impresion(
    lote_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    lote = (
        db.query(LoteImpresionInventario)
        .options(
            selectinload(LoteImpresionInventario.items)
            .joinedload(ItemLoteImpresionInventario.bien)
        )
        .filter(LoteImpresionInventario.id == lote_id)
        .first()
    )
    if lote is None:
        raise HTTPException(status_code=404, detail="Lote no encontrado.")
    items_pendientes = [
        item for item in lote.items if item.impreso_en is None
    ]
    if not items_pendientes:
        return RedirectResponse(
            url=f"/control-impresion/lotes/{lote_id}?error=" + quote_plus(
                "El lote ya está completamente impreso."
            ),
            status_code=303,
        )
    faltantes_area = [
        item.bien.codigo_qr
        for item in items_pendientes
        if requiere_actualizar_area(item.bien)
    ]
    if faltantes_area:
        codigos = ", ".join(faltantes_area[:10])
        if len(faltantes_area) > 10:
            codigos += f" y {len(faltantes_area) - 10} más"
        return RedirectResponse(
            url=f"/control-impresion/lotes/{lote_id}?error=" + quote_plus(
                "No se puede generar el PDF. Falta actualizar el área de los "
                f"QR: {codigos}."
            ),
            status_code=303,
        )
    bienes = [_adaptar_bien_pdf(item.bien) for item in items_pendientes]
    perfil = _obtener_perfil_impresion(db)
    contenido = generar_pdf_etiquetas(bienes, perfil)
    _marcar_pdf_generado(db, lote)
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="inventario_lote_{lote.id}.pdf"',
            "Cache-Control": "no-store",
        },
    )


def _crear_excel_lote(lote) -> bytes:
    libro = Workbook()
    hoja = libro.active
    hoja.title = "BarTender"
    encabezados = [
        "Codigo Patrimonial", "Codigo QR", "Ruta QR", "Bien",
        "Establecimiento", "RED", "Area", "Marca", "Modelo", "Color",
        "Nro Serie",
    ]
    hoja.append(encabezados)
    for item in lote.items:
        if item.impreso_en is not None:
            continue
        bien = item.bien
        hoja.append([
            bien.codigo_patrimonial, bien.codigo_qr or "", bien.ruta_qr or "",
            bien.descripcion, bien.establecimiento or "", bien.red or "",
            bien.area or "", bien.marca or "", bien.modelo or "",
            bien.color or "", bien.nro_serie or "",
        ])

    control = libro.create_sheet("Control")
    control.append([
        "Item", "Codigo Patrimonial", "Codigo QR", "Bien", "RED",
        "Establecimiento", "Area", "Estado impresión", "Fecha impresión",
    ])
    for numero, item in enumerate(lote.items, start=1):
        bien = item.bien
        control.append([
            numero, bien.codigo_patrimonial, bien.codigo_qr or "", bien.descripcion,
            bien.red or "Sin RED", bien.establecimiento or "Sin establecimiento",
            bien.area or "Sin área", "Impreso" if item.impreso_en else "Pendiente",
            item.impreso_en,
        ])
    for hoja_actual in (hoja, control):
        for celda in hoja_actual[1]:
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = PatternFill("solid", fgColor="1F4E78")
            celda.alignment = Alignment(horizontal="center", vertical="center")
        hoja_actual.freeze_panes = "A2"
        hoja_actual.auto_filter.ref = hoja_actual.dimensions
        hoja_actual.sheet_view.showGridLines = False
    for columna, ancho in enumerate((22, 18, 55, 40, 32, 25, 30, 18, 18, 15, 20), 1):
        hoja.column_dimensions[hoja.cell(1, columna).column_letter].width = ancho
    for columna, ancho in enumerate((8, 22, 18, 40, 25, 32, 30, 18, 22), 1):
        control.column_dimensions[control.cell(1, columna).column_letter].width = ancho

    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


@router.get("/control-impresion/lotes/{lote_id}/excel")
def excel_lote_impresion(
    lote_id: int,
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    lote = (
        db.query(LoteImpresionInventario)
        .options(
            selectinload(LoteImpresionInventario.items)
            .joinedload(ItemLoteImpresionInventario.bien)
        )
        .filter(LoteImpresionInventario.id == lote_id)
        .first()
    )
    if lote is None:
        raise HTTPException(status_code=404, detail="Lote no encontrado.")
    contenido = _crear_excel_lote(lote)
    return Response(
        content=contenido,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="inventario_lote_{lote.id}.xlsx"'
            )
        },
    )


@router.post("/control-impresion/lotes/{lote_id}/confirmar")
def confirmar_impresion_lote(
    lote_id: int,
    alcance: str = Form(...),
    item_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    lote = db.get(LoteImpresionInventario, lote_id)
    if lote is None:
        raise HTTPException(status_code=404, detail="Lote no encontrado.")
    if lote.pdf_generado_en is None:
        return RedirectResponse(
            url=f"/control-impresion/lotes/{lote_id}?error="
                + quote_plus("Genera primero el PDF del lote."),
            status_code=303,
        )
    consulta = db.query(ItemLoteImpresionInventario).filter(
        ItemLoteImpresionInventario.lote_id == lote_id
    )
    if alcance == "seleccionados":
        if not item_ids:
            return RedirectResponse(
                url=f"/control-impresion/lotes/{lote_id}?error="
                    + quote_plus("Selecciona al menos un bien."),
                status_code=303,
            )
        consulta = consulta.filter(ItemLoteImpresionInventario.id.in_(set(item_ids)))
    elif alcance != "todo":
        raise HTTPException(status_code=400, detail="Alcance no válido.")

    faltantes_area = [
        item.bien.codigo_qr
        for item in consulta.options(
            joinedload(ItemLoteImpresionInventario.bien)
        ).all()
        if item.impreso_en is None and requiere_actualizar_area(item.bien)
    ]
    if faltantes_area:
        return RedirectResponse(
            url=f"/control-impresion/lotes/{lote_id}?error=" + quote_plus(
                "No se puede confirmar la impresión mientras existan bienes "
                "de DIRESA - CAJAMARCA sin área actualizada."
            ),
            status_code=303,
        )

    actualizados = _confirmar_items_impresos(db, lote, consulta)
    return RedirectResponse(
        url=(
            f"/control-impresion/lotes/{lote_id}?info="
            + quote_plus(f"Se confirmaron {actualizados} bienes como impresos.")
        ),
        status_code=303,
    )
