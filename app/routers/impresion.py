import os
import tempfile
import xlwt
from fastapi import APIRouter, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LoteCarga, BienAlta
from app.auth import requiere_login
from app.services.excel_onevision import leer_reporte_qr_onevision, corregir_codigo_patrimonial

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ENCABEZADOS_IMPRESION = [
    "Codigo Patrimonial", "Codigo QR", "Ruta QR", "Bien", "Establecimiento",
    "Marca", "Modelo", "Nro Serie", "Numero pecosa",
]


@router.get("/impresion", response_class=HTMLResponse)
def formulario_impresion(request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)):
    lotes = db.query(LoteCarga).order_by(LoteCarga.id.desc()).limit(15).all()
    return templates.TemplateResponse("impresion.html", {"request": request, "lotes": lotes})


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

    encontrados_en_este_intento = 0
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

        encontrados_en_este_intento += 1

    db.commit()
    return RedirectResponse(url=f"/impresion/resultado/{lote_id}", status_code=303)


@router.get("/impresion/resultado/{lote_id}", response_class=HTMLResponse)
def resultado_impresion(
    lote_id: int, request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)
):
    """Muestra qué bienes del lote sí tienen su código QR (encontrados en el
    reporte de One Visión que subiste) y cuáles todavía no, para que sepas
    si falta volver a subir el reporte o si hay algo que revisar."""
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

    nombre_archivo = f"impresion_stickers_lote_{lote_id}.xls"
    ruta_salida = os.path.join(tempfile.gettempdir(), nombre_archivo)
    _generar_hoja_impresion(bienes, expedientes, ruta_salida)

    return FileResponse(ruta_salida, filename=nombre_archivo, media_type="application/vnd.ms-excel")


def _generar_hoja_impresion(bienes, expedientes, ruta_salida):
    """Genera el archivo con: Hoja 'BarTender' (datos limpios para imprimir el
    sticker) y 'Hoja 1' (listado con encabezado de expedientes, para el
    responsable de pegar los stickers)."""
    libro = xlwt.Workbook(encoding="utf-8")

    hoja_bt = libro.add_sheet("BarTender")
    for col, titulo in enumerate(ENCABEZADOS_IMPRESION):
        hoja_bt.write(0, col, titulo)
    for fila_idx, bien in enumerate(bienes, start=1):
        _escribir_fila_impresion(hoja_bt, fila_idx, bien)

    hoja1 = libro.add_sheet("Hoja 1")
    hoja1.write(0, 0, f"EXPEDIENTE(S): {';'.join(expedientes)}")
    for col, titulo in enumerate(ENCABEZADOS_IMPRESION):
        hoja1.write(2, col, titulo)
    for fila_idx, bien in enumerate(bienes, start=3):
        _escribir_fila_impresion(hoja1, fila_idx, bien)

    libro.save(ruta_salida)


def _escribir_fila_impresion(hoja, fila_idx, bien):
    hoja.write(fila_idx, 0, bien.codigo_patrimonial)
    hoja.write(fila_idx, 1, bien.codigo_qr or "")
    hoja.write(fila_idx, 2, bien.ruta_qr or "")
    hoja.write(fila_idx, 3, bien.descripcion)
    hoja.write(fila_idx, 4, bien.centro_costo.nombre_depend if bien.centro_costo else "")
    hoja.write(fila_idx, 5, bien.marca or "")
    hoja.write(fila_idx, 6, bien.modelo or "")
    hoja.write(fila_idx, 7, bien.nro_serie or "")
    hoja.write(fila_idx, 8, bien.pecosa.numero if bien.pecosa else "")
