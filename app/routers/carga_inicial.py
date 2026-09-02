import os
import tempfile

from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Expediente, Pecosa, BienAlta, CentroCosto, LoteCarga, Persona
from app.auth import requiere_login
from app.services.excel_carga_inicial import leer_consolidado
from app.services.excel_siga import extraer_numero_pecosa

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ESTADOS_QUE_SE_PUEDEN_SUBIR = ("Recibida", "Normalizada")  # no se pisa una pecosa ya más avanzada


def _estado_maestros(db: Session) -> dict:
    personas_cargadas = db.query(Persona).count()
    centros_cargados = db.query(CentroCosto).count()
    return {
        "personas_cargadas": personas_cargadas,
        "centros_cargados": centros_cargados,
        "maestros_listos": personas_cargadas > 0 and centros_cargados > 0,
    }


def _normalizar(t) -> str:
    return " ".join(str(t or "").strip().upper().split())


def _limpiar_numero(valor) -> str:
    """Convierte un valor de Excel (que puede llegar como float 7600.0)
    a texto limpio sin decimales."""
    texto = str(valor).strip()
    if texto.endswith(".0"):
        texto = texto[:-2]
    return texto


@router.get("/carga-inicial", response_class=HTMLResponse)
def formulario_carga_inicial(
    request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)
):
    return templates.TemplateResponse(
        "carga_inicial.html",
        {"request": request, "resultado": None, **_estado_maestros(db)},
    )


@router.post("/carga-inicial/procesar", response_class=HTMLResponse)
async def procesar_carga_inicial(
    request: Request,
    archivos: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    estado_maestros = _estado_maestros(db)
    if not estado_maestros["maestros_listos"]:
        return templates.TemplateResponse(
            "carga_inicial.html",
            {"request": request, "resultado": None, **estado_maestros},
            status_code=400,
        )

    centros_por_nombre = {_normalizar(c.nombre_depend): c for c in db.query(CentroCosto).all()}
    codigos_ya_cargados = {b.codigo_patrimonial for b in db.query(BienAlta.codigo_patrimonial).all()}
    expedientes_cache = {e.numero: e for e in db.query(Expediente).all()}
    pecosas_cache = {p.numero: p for p in db.query(Pecosa).all()}

    resumen_archivos = []
    establecimientos_sin_match = set()
    lotes_con_id_no_numerico = set()
    total_pecosas_nuevas = 0
    total_bienes_nuevos = 0
    total_bienes_omitidos = 0
    total_lotes_creados = 0

    for archivo in archivos:
        nombre_archivo = archivo.filename
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(await archivo.read())
            ruta_temporal = tmp.name

        try:
            df = leer_consolidado(ruta_temporal)
        except ValueError as e:
            resumen_archivos.append({"archivo": nombre_archivo, "error": str(e)})
            os.remove(ruta_temporal)
            continue
        finally:
            if os.path.exists(ruta_temporal):
                os.remove(ruta_temporal)

        pecosas_nuevas_archivo = 0
        bienes_nuevos_archivo = 0
        bienes_omitidos_archivo = 0
        lotes_del_archivo = {}  # id de lote (el número del excel) -> LoteCarga

        for _, fila in df.iterrows():
            numero_pecosa = extraer_numero_pecosa(fila.get("pecosa"))
            if numero_pecosa.isdigit():
                numero_pecosa = str(int(numero_pecosa))  # quita ceros a la izquierda
            numero_expediente = _limpiar_numero(fila.get("expediente"))
            valor_lote = _limpiar_numero(fila.get("lote"))
            codigo_patrimonial = _limpiar_numero(fila.get("codigo_patrimonial"))

            if not numero_pecosa or not codigo_patrimonial or codigo_patrimonial.lower() == "nan":
                continue
            if codigo_patrimonial in codigos_ya_cargados:
                bienes_omitidos_archivo += 1
                continue

            expediente = expedientes_cache.get(numero_expediente)
            if not expediente:
                expediente = Expediente(numero=numero_expediente)
                db.add(expediente)
                db.flush()
                expedientes_cache[numero_expediente] = expediente

            pecosa = pecosas_cache.get(numero_pecosa)
            if pecosa is None:
                pecosa = Pecosa(numero=numero_pecosa, expediente_id=expediente.id, estado="StickerGenerado")
                db.add(pecosa)
                db.flush()
                pecosas_cache[numero_pecosa] = pecosa
                pecosas_nuevas_archivo += 1
            elif pecosa.estado in ESTADOS_QUE_SE_PUEDEN_SUBIR:
                pecosa.estado = "StickerGenerado"

            # El "lote" del excel se usa DIRECTAMENTE como ID del LoteCarga
            # (no un ID interno aparte) — así el número que ves en la app
            # es el mismo que llevas en tu control manual.
            if valor_lote.isdigit():
                id_lote = int(valor_lote)
                lote = lotes_del_archivo.get(id_lote) or db.query(LoteCarga).get(id_lote)
                if lote is None:
                    lote = LoteCarga(id=id_lote, anio="", ejecutora="")
                    db.add(lote)
                    db.flush()
                lotes_del_archivo[id_lote] = lote
            else:
                # Si el valor de "lote" no es un número limpio, no podemos
                # usarlo como ID — se crea con un ID autogenerado normal.
                lotes_con_id_no_numerico.add(valor_lote)
                clave = ("SIN-NUMERO", valor_lote)
                lote = lotes_del_archivo.get(clave)
                if lote is None:
                    lote = LoteCarga(anio="", ejecutora="")
                    db.add(lote)
                    db.flush()
                lotes_del_archivo[clave] = lote

            establecimiento = str(fila.get("establecimiento", "") or "").strip()
            centro = centros_por_nombre.get(_normalizar(establecimiento))
            if establecimiento and not centro:
                establecimientos_sin_match.add(establecimiento)

            codigo_qr = str(fila.get("codigo_qr", "") or "").strip()
            if codigo_qr.endswith(".0"):
                codigo_qr = codigo_qr[:-2]

            bien = BienAlta(
                pecosa_id=pecosa.id,
                lote_id=lote.id,
                codigo_patrimonial=codigo_patrimonial,
                descripcion=str(fila.get("bien", "") or ""),
                marca=str(fila.get("marca", "") or ""),
                modelo=str(fila.get("modelo", "") or ""),
                nro_serie=str(fila.get("nro_serie", "") or ""),
                codigo_qr=codigo_qr or None,
                centro_costo_id=centro.id if centro else None,
            )
            db.add(bien)
            codigos_ya_cargados.add(codigo_patrimonial)
            bienes_nuevos_archivo += 1

        db.commit()

        # Ahora que ya existen los bienes, se completa pecosas_solicitadas
        # de cada lote tocado en este archivo (para que Normalización/
        # Impresión lo muestren igual que a los lotes hechos desde la app).
        for lote in lotes_del_archivo.values():
            numeros = sorted({
                b.pecosa.numero for b in
                db.query(BienAlta).filter(BienAlta.lote_id == lote.id).all()
                if b.pecosa
            })
            lote.pecosas_solicitadas = ",".join(numeros)
        db.commit()

        resumen_archivos.append({
            "archivo": nombre_archivo,
            "lotes_creados": len(lotes_del_archivo),
            "pecosas_nuevas": pecosas_nuevas_archivo,
            "bienes_nuevos": bienes_nuevos_archivo,
            "bienes_omitidos": bienes_omitidos_archivo,
        })
        total_pecosas_nuevas += pecosas_nuevas_archivo
        total_bienes_nuevos += bienes_nuevos_archivo
        total_bienes_omitidos += bienes_omitidos_archivo
        total_lotes_creados += len(lotes_del_archivo)

    # Como algunos lotes se crearon con un ID puesto a mano (el número de
    # tu excel), hay que avisarle a Postgres cuál es el próximo ID libre
    # para que los lotes normales (creados desde Normalización) no choquen
    # con los números que acabas de importar.
    if db.bind.dialect.name == "postgresql":
        db.execute(text(
            "SELECT setval(pg_get_serial_sequence('lotes_carga', 'id'), "
            "COALESCE((SELECT MAX(id) FROM lotes_carga), 1))"
        ))
        db.commit()

    resultado = {
        "archivos": resumen_archivos,
        "total_lotes_creados": total_lotes_creados,
        "total_pecosas_nuevas": total_pecosas_nuevas,
        "total_bienes_nuevos": total_bienes_nuevos,
        "total_bienes_omitidos": total_bienes_omitidos,
        "establecimientos_sin_match": sorted(establecimientos_sin_match),
        "lotes_con_id_no_numerico": sorted(lotes_con_id_no_numerico),
    }
    return templates.TemplateResponse(
        "carga_inicial.html",
        {"request": request, "resultado": resultado, **estado_maestros},
    )
