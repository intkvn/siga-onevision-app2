import os
import tempfile
from openpyxl import Workbook
from fastapi import APIRouter, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LoteCarga, BienAlta
from app.auth import requiere_login
from app.services.excel_onevision import leer_reporte_qr_onevision, corregir_codigo_patrimonial
from app.services.lote_status import expedientes_de_lote

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ENCABEZADOS_IMPRESION = [
    "Codigo Patrimonial", "Codigo QR", "Ruta QR", "Bien", "Establecimiento",
    "Marca", "Modelo", "Nro Serie", "Numero pecosa",
]


@router.get("/impresion", response_class=HTMLResponse)
def formulario_impresion(request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)):
    lotes_query = db.query(LoteCarga).order_by(LoteCarga.id.desc()).limit(15).all()
    lotes = [_resumen_impresion_lote(db, lote) for lote in lotes_query]
    return templates.TemplateResponse("impresion.html", {"request": request, "lotes": lotes})


def _resumen_impresion_lote(db: Session, lote: LoteCarga) -> dict:
    bienes = db.query(BienAlta).filter(BienAlta.lote_id == lote.id).all()
    con_qr = [b for b in bienes if b.codigo_qr]

    if not bienes:
        estado = "Lote vacío (normaliza primero)"
    elif not con_qr:
        estado = "Sin reporte QR cargado"
    elif len(con_qr) < len(bienes):
        estado = f"Parcial ({len(con_qr)}/{len(bienes)})"
    else:
        estado = "Completo — listo para BarTender"

    return {
        "lote": lote,
        "estado": estado,
        "expedientes": expedientes_de_lote(db, lote),
        "total": len(bienes),
        "con_qr": len(con_qr),
    }


@router.post("/impresion/procesar")
async def procesar_reporte_qr(
    lote_id: int = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(await archivo.read())
        ruta_temporal = tmp.name

    try:
        df_qr = leer_reporte_qr_onevision(ruta_temporal)
    finally:
        os.remove(ruta_temporal)

    bienes = db.query(BienAlta).filter(BienAlta.lote_id == lote_id).all()
    bienes_por_codigo = {corregir_codigo_patrimonial(b.codigo_patrimonial): b for b in bienes}

    for _, fila in df_qr.iterrows():
        codigo = fila["codigo_patrimonial_corregido"]
        bien = bienes_por_codigo.get(codigo)
        if bien is None:
            continue  # este QR del reporte de One Visión no pertenece a este lote

        for col_qr in ["Código QR", "Codigo QR"]:
            if col_qr in fila:
                bien.codigo_qr = str(fila[col_qr])
        for col_ruta in ["Ruta QR", "URL", "Ruta"]:
            if col_ruta in fila:
                bien.ruta_qr = str(fila[col_ruta])

        if bien.pecosa:
            bien.pecosa.estado = "StickerGenerado"

    db.commit()
    return RedirectResponse(url=f"/impresion/resultado/{lote_id}", status_code=303)


@router.get("/impresion/resultado/{lote_id}", response_class=HTMLResponse)
def resultado_impresion(
    lote_id: int, request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)
):
    """Muestra qué bienes del lote sí tienen su código QR (encontrados en el
    reporte de One Visión que subiste) y cuáles todavía no."""
    bienes = db.query(BienAlta).filter(BienAlta.lote_id == lote_id).all()
    encontrados = [b for b in bienes if b.codigo_qr]
    no_encontrados = [b for b in bienes if not b.codigo_qr]
    return templates.TemplateResponse(
        "impresion_resultado.html",
        {
            "request": request, "lote_id": lote_id,
            "encontrados": encontrados, "no_encontrados": no_encontrados,
        },
    )


@router.get("/impresion/lote/{lote_id}/descargar")
def descargar_impresion(lote_id: int, db: Session = Depends(get_db), _=Depends(requiere_login)):
    bienes = db.query(BienAlta).filter(
        BienAlta.lote_id == lote_id, BienAlta.codigo_qr.isnot(None)
    ).all()
    expedientes = sorted({
        b.pecosa.expediente.numero for b in bienes if b.pecosa and b.pecosa.expediente
    })

    # .xlsx (no .xls) porque BarTender no acepta el formato binario antiguo.
    nombre_archivo = f"impresion_stickers_lote_{lote_id}.xlsx"
    ruta_salida = os.path.join(tempfile.gettempdir(), nombre_archivo)
    _generar_hoja_impresion(bienes, expedientes, ruta_salida)

    return FileResponse(
        ruta_salida,
        filename=nombre_archivo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _generar_hoja_impresion(bienes, expedientes, ruta_salida):
    """Genera el .xlsx con: hoja 'BarTender' (datos limpios para imprimir el
    sticker) y 'Hoja 1' (listado con encabezado de expedientes, para el
    responsable de pegar los stickers)."""
    libro = Workbook()

    hoja_bt = libro.active
    hoja_bt.title = "BarTender"
    hoja_bt.append(ENCABEZADOS_IMPRESION)
    for bien in bienes:
        hoja_bt.append(_fila_impresion(bien))

    hoja1 = libro.create_sheet("Hoja 1")
    hoja1.cell(row=1, column=1, value=f"EXPEDIENTE(S): {';'.join(expedientes)}")
    for col, titulo in enumerate(ENCABEZADOS_IMPRESION, start=1):
        hoja1.cell(row=3, column=col, value=titulo)
    for fila_idx, bien in enumerate(bienes, start=4):
        for col, valor in enumerate(_fila_impresion(bien), start=1):
            hoja1.cell(row=fila_idx, column=col, value=valor)

    libro.save(ruta_salida)


def _fila_impresion(bien) -> list:
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
