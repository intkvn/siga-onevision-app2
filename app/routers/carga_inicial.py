import os
import tempfile

from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Expediente, Pecosa, BienAlta, CentroCosto
from app.auth import requiere_login
from app.services.excel_carga_inicial import leer_reporte_impresion_historico, numeros_de_expediente

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ESTADOS_QUE_SE_PUEDEN_SUBIR = ("Recibida", "Normalizada")  # no se pisa una pecosa ya más avanzada


def _normalizar(t) -> str:
    return " ".join(str(t or "").strip().upper().split())


@router.get("/carga-inicial", response_class=HTMLResponse)
def formulario_carga_inicial(request: Request, _=Depends(requiere_login)):
    return templates.TemplateResponse("carga_inicial.html", {"request": request, "resultado": None})


@router.post("/carga-inicial/procesar", response_class=HTMLResponse)
async def procesar_carga_inicial(
    request: Request,
    archivos: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    centros_por_nombre = {_normalizar(c.nombre_depend): c for c in db.query(CentroCosto).all()}
    codigos_ya_cargados = {b.codigo_patrimonial for b in db.query(BienAlta.codigo_patrimonial).all()}

    resumen_archivos = []
    establecimientos_sin_match = set()
    total_pecosas_nuevas = 0
    total_bienes_nuevos = 0
    total_bienes_omitidos = 0

    for archivo in archivos:
        nombre_archivo = archivo.filename
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(await archivo.read())
            ruta_temporal = tmp.name

        try:
            texto_expediente, df = leer_reporte_impresion_historico(ruta_temporal)
        except ValueError as e:
            resumen_archivos.append({"archivo": nombre_archivo, "error": str(e)})
            os.remove(ruta_temporal)
            continue
        finally:
            if os.path.exists(ruta_temporal):
                os.remove(ruta_temporal)

        numero_expediente = numeros_de_expediente(texto_expediente)
        expediente = db.query(Expediente).filter(Expediente.numero == numero_expediente).first()
        if not expediente:
            expediente = Expediente(numero=numero_expediente)
            db.add(expediente)
            db.flush()

        pecosas_nuevas_archivo = 0
        bienes_nuevos_archivo = 0
        bienes_omitidos_archivo = 0
        pecosas_cache = {}

        for _, fila in df.iterrows():
            numero_pecosa = str(fila.get("pecosa", "")).strip()
            if numero_pecosa.endswith(".0"):
                numero_pecosa = numero_pecosa[:-2]
            codigo_patrimonial = str(fila.get("codigo_patrimonial", "")).strip()
            if not numero_pecosa or numero_pecosa.lower() == "nan" or not codigo_patrimonial:
                continue

            if codigo_patrimonial in codigos_ya_cargados:
                bienes_omitidos_archivo += 1
                continue

            pecosa = pecosas_cache.get(numero_pecosa) or db.query(Pecosa).filter(Pecosa.numero == numero_pecosa).first()
            if pecosa is None:
                pecosa = Pecosa(numero=numero_pecosa, expediente_id=expediente.id, estado="StickerGenerado")
                db.add(pecosa)
                db.flush()
                pecosas_nuevas_archivo += 1
            elif pecosa.estado in ESTADOS_QUE_SE_PUEDEN_SUBIR:
                pecosa.estado = "StickerGenerado"
            pecosas_cache[numero_pecosa] = pecosa

            establecimiento = str(fila.get("establecimiento", "") or "").strip()
            centro = centros_por_nombre.get(_normalizar(establecimiento))
            if establecimiento and not centro:
                establecimientos_sin_match.add(establecimiento)

            bien = BienAlta(
                pecosa_id=pecosa.id,
                lote_id=None,
                codigo_patrimonial=codigo_patrimonial,
                descripcion=str(fila.get("bien", "") or ""),
                marca=str(fila.get("marca", "") or ""),
                modelo=str(fila.get("modelo", "") or ""),
                nro_serie=str(fila.get("nro_serie", "") or ""),
                codigo_qr=str(fila.get("codigo_qr", "") or "") or None,
                ruta_qr=str(fila.get("ruta_qr", "") or "") or None,
                centro_costo_id=centro.id if centro else None,
            )
            db.add(bien)
            codigos_ya_cargados.add(codigo_patrimonial)
            bienes_nuevos_archivo += 1

        db.commit()
        resumen_archivos.append({
            "archivo": nombre_archivo,
            "expediente": numero_expediente,
            "pecosas_nuevas": pecosas_nuevas_archivo,
            "bienes_nuevos": bienes_nuevos_archivo,
            "bienes_omitidos": bienes_omitidos_archivo,
        })
        total_pecosas_nuevas += pecosas_nuevas_archivo
        total_bienes_nuevos += bienes_nuevos_archivo
        total_bienes_omitidos += bienes_omitidos_archivo

    resultado = {
        "archivos": resumen_archivos,
        "total_pecosas_nuevas": total_pecosas_nuevas,
        "total_bienes_nuevos": total_bienes_nuevos,
        "total_bienes_omitidos": total_bienes_omitidos,
        "establecimientos_sin_match": sorted(establecimientos_sin_match),
    }
    return templates.TemplateResponse("carga_inicial.html", {"request": request, "resultado": resultado})
