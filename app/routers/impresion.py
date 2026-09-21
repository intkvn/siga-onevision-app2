import logging
import os
import shutil
import tempfile
import time
from collections import defaultdict
from urllib.parse import quote_plus
from zipfile import BadZipFile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.exceptions import InvalidFileException
from fastapi import APIRouter, Request, Form, Depends, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import LoteCarga, BienAlta, Pecosa, PerfilImpresionEtiqueta
from app.auth import requiere_login
from app.services.excel_onevision import iterar_reporte_qr_onevision, corregir_codigo_patrimonial
from app.services.lote_status import expedientes_de_lote, expedientes_de_lotes
from app.services.pdf_etiquetas import (
    NOMBRE_PERFIL_PREDETERMINADO,
    clasificar_bienes_impresion,
    generar_pdf_etiquetas,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

ENCABEZADOS_BARTENDER = [
    "Codigo Patrimonial", "Codigo QR", "Ruta QR", "Bien", "Establecimiento",
    "Marca", "Modelo", "Nro Serie", "Numero pecosa",
]
ENCABEZADOS_HOJA1 = [
    "ITEM", "Codigo Patrimonial", "Codigo QR", "Bien", "Establecimiento",
    "Marca", "Modelo", "Nro Serie", "Numero pecosa",
]


@router.get("/impresion", response_class=HTMLResponse)
def formulario_impresion(request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)):
    lotes_query = db.query(LoteCarga).order_by(LoteCarga.id.desc()).all()
    bienes_por_lote = defaultdict(list)
    lote_ids = [lote.id for lote in lotes_query]
    if lote_ids:
        for bien in db.query(BienAlta).filter(BienAlta.lote_id.in_(lote_ids)).all():
            bienes_por_lote[bien.lote_id].append(bien)
    expedientes_por_lote = expedientes_de_lotes(db, lotes_query)
    lotes = [
        _resumen_impresion_lote(
            db,
            lote,
            bienes=bienes_por_lote[lote.id],
            expedientes=expedientes_por_lote.get(lote.id, []),
        )
        for lote in lotes_query
    ]
    return templates.TemplateResponse("impresion.html", {"request": request, "lotes": lotes})


def _resumen_impresion_lote(
    db: Session,
    lote: LoteCarga,
    bienes: list[BienAlta] | None = None,
    expedientes: list[str] | None = None,
) -> dict:
    if bienes is None:
        bienes = db.query(BienAlta).filter(BienAlta.lote_id == lote.id).all()
    con_qr = [b for b in bienes if b.codigo_qr]

    if not bienes:
        estado = "Lote vacío (normaliza primero)"
    elif not con_qr:
        estado = "Sin reporte QR cargado"
    elif len(con_qr) < len(bienes):
        estado = f"Parcial ({len(con_qr)}/{len(bienes)})"
    else:
        estado = "Completo - listo para BarTender"

    return {
        "lote": lote,
        "estado": estado,
        "expedientes": expedientes if expedientes is not None else expedientes_de_lote(db, lote),
        "total": len(bienes),
        "con_qr": len(con_qr),
    }


@router.post("/impresion/procesar")
def procesar_reporte_qr(
    lote_id: int = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    inicio = time.perf_counter()
    ruta_temporal = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            ruta_temporal = tmp.name
            shutil.copyfileobj(archivo.file, tmp, length=1024 * 1024)

        bienes = (
            db.query(BienAlta)
            .options(joinedload(BienAlta.pecosa))
            .filter(BienAlta.lote_id == lote_id)
            .all()
        )
        bienes_por_codigo = {
            corregir_codigo_patrimonial(b.codigo_patrimonial): b for b in bienes
        }

        filas_procesadas = 0
        bienes_actualizados = set()
        for fila in iterar_reporte_qr_onevision(ruta_temporal):
            filas_procesadas += 1
            codigo = fila["codigo_patrimonial_corregido"]
            bien = bienes_por_codigo.get(codigo)
            if bien is None:
                continue

            if fila["codigo_qr"]:
                bien.codigo_qr = fila["codigo_qr"]
            if fila["ruta_qr"]:
                bien.ruta_qr = fila["ruta_qr"]

            if bien.pecosa and bien.codigo_qr:
                bien.pecosa.estado = "StickerGenerado"
            bienes_actualizados.add(bien.id)

        db.commit()
        logger.info(
            "Cruce de impresión completado: lote=%s filas=%s bienes=%s duracion=%.2fs",
            lote_id,
            filas_procesadas,
            len(bienes_actualizados),
            time.perf_counter() - inicio,
        )
    except (ValueError, OSError, BadZipFile, InvalidFileException) as exc:
        db.rollback()
        logger.warning(
            "No se pudo procesar el reporte QR del lote %s: %s", lote_id, exc
        )
        mensaje = quote_plus(str(exc))
        return RedirectResponse(url=f"/impresion?error={mensaje}", status_code=303)
    finally:
        if ruta_temporal and os.path.exists(ruta_temporal):
            os.remove(ruta_temporal)
    return RedirectResponse(url=f"/impresion/resultado/{lote_id}", status_code=303)


@router.get("/impresion/resultado/{lote_id}", response_class=HTMLResponse)
def resultado_impresion(
    lote_id: int, request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)
):
    """Muestra qué bienes del lote sí tienen su código QR (encontrados en el
    reporte de One Visión que subiste) y cuáles todavía no."""
    bienes = (
        db.query(BienAlta)
        .options(
            joinedload(BienAlta.pecosa),
            joinedload(BienAlta.centro_costo),
        )
        .filter(BienAlta.lote_id == lote_id)
        .order_by(BienAlta.id)
        .all()
    )
    encontrados = [b for b in bienes if b.codigo_qr]
    no_encontrados = [b for b in bienes if not b.codigo_qr]
    imprimibles, excluidos_pdf = clasificar_bienes_impresion(bienes)
    perfil = _obtener_perfil_impresion(db)
    return templates.TemplateResponse(
        "impresion_resultado.html",
        {
            "request": request, "lote_id": lote_id,
            "encontrados": encontrados, "no_encontrados": no_encontrados,
            "imprimibles": imprimibles,
            "excluidos_pdf": excluidos_pdf,
            "perfil": perfil,
            "ancho_pagina_pdf": perfil.ancho_pagina_mm,
            "alto_pagina_pdf": perfil.alto_etiqueta_mm + perfil.avance_adicional_mm,
        },
    )


def _obtener_perfil_impresion(db: Session) -> PerfilImpresionEtiqueta:
    perfil = (
        db.query(PerfilImpresionEtiqueta)
        .filter(PerfilImpresionEtiqueta.nombre == NOMBRE_PERFIL_PREDETERMINADO)
        .first()
    )
    if perfil:
        # Los perfiles creados antes de adaptar el PDF al controlador Argox
        # usaban 90/270 grados. Se normalizan una sola vez al nuevo sistema.
        if perfil.rotacion_contenido not in (0, 180):
            perfil.rotacion_contenido = 0
            db.commit()
            db.refresh(perfil)
        return perfil

    perfil = PerfilImpresionEtiqueta(
        nombre=NOMBRE_PERFIL_PREDETERMINADO,
        ancho_pagina_mm=105.1,
        ancho_etiqueta_mm=50.8,
        alto_etiqueta_mm=38.1,
        margen_izquierdo_mm=0.75,
        margen_derecho_mm=0.75,
        separacion_central_mm=2.0,
        avance_adicional_mm=0.0,
        desplazamiento_x_mm=0.0,
        desplazamiento_y_mm=0.0,
        rotacion_contenido=180,
        anio_1="2026",
        anio_2="2027",
        anio_marcado="2026",
    )
    db.add(perfil)
    db.commit()
    db.refresh(perfil)
    return perfil


@router.post("/impresion/perfil")
def guardar_perfil_impresion(
    lote_id: int = Form(...),
    ancho_pagina_mm: float = Form(...),
    ancho_etiqueta_mm: float = Form(...),
    alto_etiqueta_mm: float = Form(...),
    margen_izquierdo_mm: float = Form(...),
    margen_derecho_mm: float = Form(...),
    separacion_central_mm: float = Form(...),
    avance_adicional_mm: float = Form(...),
    desplazamiento_x_mm: float = Form(...),
    desplazamiento_y_mm: float = Form(...),
    rotacion_contenido: int = Form(...),
    anio_1: str = Form(...),
    anio_2: str = Form(...),
    anio_marcado_posicion: int = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    anio_marcado = anio_1 if anio_marcado_posicion == 1 else anio_2
    if anio_marcado_posicion not in (1, 2):
        anio_marcado = ""
    error = _validar_valores_perfil(
        ancho_pagina_mm=ancho_pagina_mm,
        ancho_etiqueta_mm=ancho_etiqueta_mm,
        alto_etiqueta_mm=alto_etiqueta_mm,
        margen_izquierdo_mm=margen_izquierdo_mm,
        margen_derecho_mm=margen_derecho_mm,
        separacion_central_mm=separacion_central_mm,
        avance_adicional_mm=avance_adicional_mm,
        desplazamiento_x_mm=desplazamiento_x_mm,
        desplazamiento_y_mm=desplazamiento_y_mm,
        rotacion_contenido=rotacion_contenido,
        anio_1=anio_1,
        anio_2=anio_2,
        anio_marcado=anio_marcado,
    )
    if error:
        return RedirectResponse(
            url=f"/impresion/resultado/{lote_id}?error={quote_plus(error)}",
            status_code=303,
        )

    perfil = _obtener_perfil_impresion(db)
    perfil.ancho_pagina_mm = ancho_pagina_mm
    perfil.ancho_etiqueta_mm = ancho_etiqueta_mm
    perfil.alto_etiqueta_mm = alto_etiqueta_mm
    perfil.margen_izquierdo_mm = margen_izquierdo_mm
    perfil.margen_derecho_mm = margen_derecho_mm
    perfil.separacion_central_mm = separacion_central_mm
    perfil.avance_adicional_mm = avance_adicional_mm
    perfil.desplazamiento_x_mm = desplazamiento_x_mm
    perfil.desplazamiento_y_mm = desplazamiento_y_mm
    perfil.rotacion_contenido = rotacion_contenido
    perfil.anio_1 = anio_1.strip()
    perfil.anio_2 = anio_2.strip()
    perfil.anio_marcado = anio_marcado.strip()
    db.commit()
    return RedirectResponse(
        url=(
            f"/impresion/resultado/{lote_id}?info="
            "Perfil+de+impresi%C3%B3n+guardado"
        ),
        status_code=303,
    )


def _validar_valores_perfil(**valores) -> str | None:
    dimensiones_positivas = (
        "ancho_pagina_mm", "ancho_etiqueta_mm", "alto_etiqueta_mm",
        "margen_izquierdo_mm", "margen_derecho_mm", "separacion_central_mm",
    )
    if any(valores[nombre] <= 0 for nombre in dimensiones_positivas):
        return "Las dimensiones y los márgenes deben ser mayores que cero."
    if not 50 <= valores["ancho_pagina_mm"] <= 200:
        return "El ancho de página debe estar entre 50 y 200 mm."
    if not 30 <= valores["ancho_etiqueta_mm"] <= 80:
        return "El ancho de etiqueta debe estar entre 30 y 80 mm."
    if not 25 <= valores["alto_etiqueta_mm"] <= 60:
        return "El alto de etiqueta debe estar entre 25 y 60 mm."
    if not 0 <= valores["avance_adicional_mm"] <= 20:
        return "El avance adicional debe estar entre 0 y 20 mm."
    if not -10 <= valores["desplazamiento_x_mm"] <= 10:
        return "El desplazamiento horizontal debe estar entre -10 y 10 mm."
    if not -10 <= valores["desplazamiento_y_mm"] <= 10:
        return "El desplazamiento vertical debe estar entre -10 y 10 mm."
    if valores["rotacion_contenido"] not in (0, 180):
        return "La rotación debe ser de 0 o 180 grados."

    ocupado = (
        valores["margen_izquierdo_mm"]
        + (2 * valores["ancho_etiqueta_mm"])
        + valores["separacion_central_mm"]
        + valores["margen_derecho_mm"]
    )
    if ocupado > valores["ancho_pagina_mm"] + 0.01:
        return "Las dos etiquetas, márgenes y separación exceden el ancho de página."

    anio_1 = valores["anio_1"].strip()
    anio_2 = valores["anio_2"].strip()
    anio_marcado = valores["anio_marcado"].strip()
    if not (anio_1.isdigit() and len(anio_1) == 4):
        return "El primer año debe tener cuatro dígitos."
    if not (anio_2.isdigit() and len(anio_2) == 4):
        return "El segundo año debe tener cuatro dígitos."
    if anio_marcado not in (anio_1, anio_2):
        return "El año marcado debe coincidir con uno de los dos años configurados."
    return None


@router.post("/impresion/lote/{lote_id}/pdf")
def vista_previa_pdf_etiquetas(
    lote_id: int,
    alcance: str = Form(...),
    bien_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    consulta = (
        db.query(BienAlta)
        .options(
            joinedload(BienAlta.pecosa),
            joinedload(BienAlta.centro_costo),
        )
        .filter(BienAlta.lote_id == lote_id)
    )
    if alcance == "seleccionados":
        if not bien_ids:
            raise HTTPException(
                status_code=400,
                detail="Selecciona al menos un bien para generar el PDF.",
            )
        consulta = consulta.filter(BienAlta.id.in_(set(bien_ids)))
    elif alcance != "todo":
        raise HTTPException(status_code=400, detail="Alcance de impresión no válido.")

    bienes = consulta.order_by(BienAlta.id).all()
    imprimibles, _ = clasificar_bienes_impresion(bienes)
    if not imprimibles:
        raise HTTPException(
            status_code=400,
            detail="No hay bienes con Ruta QR válida en la selección.",
        )

    perfil = _obtener_perfil_impresion(db)
    contenido = generar_pdf_etiquetas(imprimibles, perfil)
    nombre = f"etiquetas_lote_{lote_id}.pdf"
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )


@router.get("/impresion/lote/{lote_id}/descargar")
def descargar_impresion(lote_id: int, db: Session = Depends(get_db), _=Depends(requiere_login)):
    bienes = (
        db.query(BienAlta)
        .options(
            joinedload(BienAlta.pecosa).joinedload(Pecosa.expediente),
            joinedload(BienAlta.centro_costo),
        )
        .filter(BienAlta.lote_id == lote_id, BienAlta.codigo_qr.isnot(None))
        .all()
    )
    expedientes = sorted({
        b.pecosa.expediente.numero for b in bienes if b.pecosa and b.pecosa.expediente
    })

    # .xlsx (no .xls) porque BarTender no acepta el formato binario antiguo.
    nombre_archivo = f"impresion_stickers_lote_{lote_id}.xlsx"
    ruta_salida = os.path.join(tempfile.gettempdir(), nombre_archivo)
    _generar_hoja_impresion(bienes, expedientes, lote_id, ruta_salida)

    return FileResponse(
        ruta_salida,
        filename=nombre_archivo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _generar_hoja_impresion(bienes, expedientes, lote_id, ruta_salida):
    """Genera el .xlsx con: hoja 'BarTender' (datos limpios para imprimir el
    sticker) y 'Hoja 1' (listado con encabezado de expedientes, para el
    responsable de pegar los stickers)."""
    libro = Workbook()

    hoja_bt = libro.active
    hoja_bt.title = "BarTender"
    hoja_bt.append(ENCABEZADOS_BARTENDER)
    for bien in bienes:
        hoja_bt.append(_fila_bartender(bien))

    hoja1 = libro.create_sheet("Hoja 1")
    hoja1.cell(row=1, column=1, value=f"EXPEDIENTE(S): {';'.join(expedientes)}")
    hoja1.cell(row=2, column=1, value=f"LOTE: {lote_id}")
    hoja1.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(ENCABEZADOS_HOJA1))
    hoja1.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(ENCABEZADOS_HOJA1))
    hoja1["A1"].font = Font(bold=True, size=12)
    hoja1["A2"].font = Font(bold=True, size=12)

    for col, titulo in enumerate(ENCABEZADOS_HOJA1, start=1):
        celda = hoja1.cell(row=4, column=col, value=titulo)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="1F4E78")
        celda.alignment = Alignment(horizontal="center", vertical="center")

    borde_fino = Side(style="thin", color="A6A6A6")
    borde_tabla = Border(
        left=borde_fino, right=borde_fino, top=borde_fino, bottom=borde_fino
    )
    for item, bien in enumerate(bienes, start=1):
        fila_idx = item + 4
        for col, valor in enumerate(_fila_hoja1(bien, item), start=1):
            celda = hoja1.cell(row=fila_idx, column=col, value=valor)
            celda.border = borde_tabla
            celda.alignment = Alignment(vertical="top")
            if col in (2, 3, 9):
                celda.number_format = "@"

    for celda in hoja1[4]:
        celda.border = borde_tabla

    anchos = [9, 22, 18, 42, 32, 18, 18, 20, 18]
    for col, ancho in enumerate(anchos, start=1):
        hoja1.column_dimensions[hoja1.cell(row=4, column=col).column_letter].width = ancho

    hoja1.auto_filter.ref = f"A4:{hoja1.cell(row=4, column=len(ENCABEZADOS_HOJA1)).column_letter}{max(4, hoja1.max_row)}"
    hoja1.freeze_panes = "A5"
    hoja1.sheet_view.showGridLines = False
    hoja1.page_setup.orientation = "landscape"
    hoja1.page_setup.fitToWidth = 1
    hoja1.page_setup.fitToHeight = 0
    hoja1.sheet_properties.pageSetUpPr.fitToPage = True
    hoja1.print_title_rows = "1:4"

    libro.save(ruta_salida)


def _fila_bartender(bien) -> list:
    return [
        bien.codigo_patrimonial,
        bien.codigo_qr or "",
        bien.ruta_qr or "",
        bien.descripcion,
        bien.centro_costo.nombre_depend if bien.centro_costo else "",
        bien.marca or "",
        bien.modelo or "",
        bien.nro_serie or "",
        bien.pecosa.numero if bien.pecosa else "",
    ]


def _fila_hoja1(bien, item: int) -> list:
    return [
        item,
        bien.codigo_patrimonial,
        bien.codigo_qr or "",
        bien.descripcion,
        bien.centro_costo.nombre_depend if bien.centro_costo else "",
        bien.marca or "",
        bien.modelo or "",
        bien.nro_serie or "",
        bien.pecosa.numero if bien.pecosa else "",
    ]
