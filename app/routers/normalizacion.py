import os
import tempfile

from fastapi import APIRouter, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Pecosa, Expediente, BienAlta, LoteCarga, Persona, CentroCosto
from app.auth import requiere_login
from app.config import ANIO_INVENTARIO, EJECUTORA, ESTADOS
from app.services.excel_siga import leer_reporte_siga, filtrar_por_pecosas, extraer_numero_pecosa
from app.services.matching import cruzar_fila
from app.services.excel_onevision import generar_formato_importacion
from app.services.lote_status import expedientes_de_lote

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/normalizacion", response_class=HTMLResponse)
def formulario_normalizacion(request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)):
    pecosas_pendientes = (
        db.query(Pecosa).filter(Pecosa.estado == "Recibida").join(Expediente).all()
    )
    # Agrupamos por expediente, porque un expediente puede traer muchas pecosas
    # y no tiene sentido marcarlas una por una.
    expedientes = {}
    for p in pecosas_pendientes:
        exp = p.expediente
        if exp is None:
            continue
        expedientes.setdefault(exp.numero, []).append(p.numero)

    lotes_query = db.query(LoteCarga).order_by(LoteCarga.id.desc()).limit(10).all()
    lotes = [_resumen_lote(db, lote) for lote in lotes_query]
    return templates.TemplateResponse(
        "normalizacion.html",
        {"request": request, "expedientes": expedientes, "lotes": lotes},
    )


def _resumen_lote(db: Session, lote: LoteCarga) -> dict:
    """Arma el estado de un lote (Vacío / Incompleto / Completo / Generado)
    y sus expedientes, para mostrarlo en la lista sin tener que entrar."""
    bienes = db.query(BienAlta).filter(BienAlta.lote_id == lote.id).all()
    pendientes = [b for b in bienes if _cruce_incompleto(b)]
    no_encontradas = _pecosas_no_encontradas(lote, bienes)

    if lote.archivo_generado:
        estado = "Generado"
    elif not bienes:
        estado = "Vacío / sin procesar"
    elif pendientes or no_encontradas:
        estado = "Incompleto"
    else:
        estado = "Completo (listo para generar)"

    return {
        "lote": lote,
        "estado": estado,
        "expedientes": expedientes_de_lote(db, lote),
    }


def _procesar_pecosas_en_lote(db: Session, lote: LoteCarga, pecosas: list[Pecosa], df_filtrado):
    """Crea los BienAlta para las pecosas dadas a partir del reporte ya
    filtrado, sin duplicar si un código patrimonial ya estaba cargado
    en este lote (por si se reintenta subir el mismo reporte)."""
    pecosas_por_clave = {p.numero.lstrip("0") or "0": p for p in pecosas}
    ya_cargados = {
        (b.pecosa_id, b.codigo_patrimonial)
        for b in db.query(BienAlta).filter(BienAlta.lote_id == lote.id).all()
    }
    pecosas_encontradas = set()

    for _, fila in df_filtrado.iterrows():
        numero_pecosa = extraer_numero_pecosa(fila["observaciones"])
        pecosa = pecosas_por_clave.get(numero_pecosa.lstrip("0") or "0")
        if pecosa is None:
            continue
        pecosas_encontradas.add(pecosa.numero)

        codigo_patrimonial = str(fila.get("codigo_patrimonial", "")).strip()
        if (pecosa.id, codigo_patrimonial) in ya_cargados:
            continue  # ya estaba cargado en este lote, no duplicar

        resultado_cruce = cruzar_fila(db, fila.get("nombre_completo"), fila.get("nombre_depend"))

        bien = BienAlta(
            pecosa_id=pecosa.id,
            lote_id=lote.id,
            codigo_patrimonial=codigo_patrimonial,
            descripcion=str(fila.get("descripcion", "")).strip(),
            modelo=str(fila.get("modelo", "") or ""),
            marca=str(fila.get("marca", "") or ""),
            estado_conservacion=str(fila.get("estado_conserv", "") or ""),
            nro_serie=str(fila.get("nro_serie", "") or ""),
            fecha_alta=pd_to_datetime(fila.get("fecha_movimto")),
            nombre_depend_siga=str(fila.get("nombre_depend", "") or ""),
            nombre_completo_siga=str(fila.get("nombre_completo", "") or ""),
            persona_id=resultado_cruce["persona"].id if resultado_cruce["persona"] else None,
            centro_costo_id=resultado_cruce["centro_costo"].id if resultado_cruce["centro_costo"] else None,
        )
        db.add(bien)
        pecosa.estado = "Normalizada"

    return pecosas_encontradas


@router.post("/normalizacion/procesar")
async def procesar_reporte(
    request: Request,
    archivo: UploadFile = File(...),
    expedientes_seleccionados: list[str] = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    pecosas = (
        db.query(Pecosa)
        .join(Expediente)
        .filter(Expediente.numero.in_(expedientes_seleccionados), Pecosa.estado == "Recibida")
        .all()
    )
    if not pecosas:
        return RedirectResponse(
            url="/normalizacion?error=No+hay+pecosas+pendientes+en+los+expedientes+elegidos",
            status_code=303,
        )
    pecosas_seleccionadas = [p.numero for p in pecosas]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(await archivo.read())
        ruta_temporal = tmp.name
    try:
        df = leer_reporte_siga(ruta_temporal)
        df_filtrado = filtrar_por_pecosas(df, pecosas_seleccionadas)
    finally:
        os.remove(ruta_temporal)

    lote = LoteCarga(
        anio=ANIO_INVENTARIO, ejecutora=EJECUTORA,
        pecosas_solicitadas=",".join(pecosas_seleccionadas),
    )
    db.add(lote)
    db.flush()

    _procesar_pecosas_en_lote(db, lote, pecosas, df_filtrado)
    db.commit()
    return RedirectResponse(url=f"/normalizacion/lote/{lote.id}", status_code=303)


@router.post("/normalizacion/lote/{lote_id}/completar")
async def completar_lote(
    lote_id: int,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    """Reintenta con otro reporte de SIGA, pero SOLO para las pecosas de
    este mismo lote que todavía no se encontraron — no crea un lote nuevo
    ni duplica lo que ya estaba bien."""
    lote = db.query(LoteCarga).get(lote_id)
    bienes_actuales = db.query(BienAlta).filter(BienAlta.lote_id == lote_id).all()
    faltantes = _pecosas_no_encontradas(lote, bienes_actuales)
    if not faltantes:
        return RedirectResponse(url=f"/normalizacion/lote/{lote_id}", status_code=303)

    pecosas = db.query(Pecosa).filter(Pecosa.numero.in_(faltantes)).all()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(await archivo.read())
        ruta_temporal = tmp.name
    try:
        df = leer_reporte_siga(ruta_temporal)
        df_filtrado = filtrar_por_pecosas(df, faltantes)
    finally:
        os.remove(ruta_temporal)

    _procesar_pecosas_en_lote(db, lote, pecosas, df_filtrado)
    db.commit()
    return RedirectResponse(url=f"/normalizacion/lote/{lote_id}", status_code=303)


def pd_to_datetime(valor):
    import pandas as pd
    try:
        ts = pd.to_datetime(valor)
        return ts.to_pydatetime() if ts is not None else None
    except Exception:
        return None


def _cruce_incompleto(b):
    """True si falta la persona/centro, o si están asignados pero con
    DNI/IPRESS vacío (dato incompleto en el maestro)."""
    sin_persona = not b.persona_id or not (b.persona and b.persona.dni)
    sin_centro = not b.centro_costo_id or not (b.centro_costo and b.centro_costo.ipress)
    return sin_persona or sin_centro


def _pecosas_no_encontradas(lote, bienes):
    """Pecosas que se marcaron para este lote pero no tienen ningún bien
    (no aparecieron en el reporte de SIGA que se subió)."""
    if not lote.pecosas_solicitadas:
        return []
    solicitadas = [p for p in lote.pecosas_solicitadas.split(",") if p]
    con_bienes = {b.pecosa.numero for b in bienes if b.pecosa}
    return [p for p in solicitadas if p not in con_bienes]


@router.get("/normalizacion/lote/{lote_id}", response_class=HTMLResponse)
def ver_lote(lote_id: int, request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)):
    lote = db.query(LoteCarga).get(lote_id)
    bienes = db.query(BienAlta).filter(BienAlta.lote_id == lote_id).all()
    personas = db.query(Persona).order_by(Persona.nombre_completo).all()
    centros = db.query(CentroCosto).order_by(CentroCosto.nombre_depend).all()
    pendientes = [b for b in bienes if _cruce_incompleto(b)]
    pecosas_no_encontradas = _pecosas_no_encontradas(lote, bienes)
    puede_generar = not pendientes and not pecosas_no_encontradas and bienes
    return templates.TemplateResponse(
        "lote_detalle.html",
        {
            "request": request, "lote": lote, "bienes": bienes,
            "personas": personas, "centros": centros,
            "pendientes": pendientes, "estados": ESTADOS,
            "pecosas_no_encontradas": pecosas_no_encontradas,
            "puede_generar": puede_generar,
            "expedientes": expedientes_de_lote(db, lote),
        },
    )


@router.post("/normalizacion/bien/{bien_id}/corregir")
def corregir_bien(
    bien_id: int,
    persona_id: str = Form(""),
    centro_costo_id: str = Form(""),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    bien = db.query(BienAlta).get(bien_id)
    if bien:
        if persona_id:
            bien.persona_id = int(persona_id)
        if centro_costo_id:
            bien.centro_costo_id = int(centro_costo_id)
        db.commit()
        return RedirectResponse(url=f"/normalizacion/lote/{bien.lote_id}", status_code=303)
    return RedirectResponse(url="/normalizacion", status_code=303)


@router.get("/normalizacion/lote/{lote_id}/generar")
def generar_archivo(lote_id: int, db: Session = Depends(get_db), _=Depends(requiere_login)):
    lote = db.query(LoteCarga).get(lote_id)
    todos = db.query(BienAlta).filter(BienAlta.lote_id == lote_id).all()

    pecosas_no_encontradas = _pecosas_no_encontradas(lote, todos)
    pendientes = [b for b in todos if _cruce_incompleto(b)]
    if pecosas_no_encontradas or pendientes or not todos:
        mensaje = (
            "No se puede generar el archivo: revisa las pecosas sin filas y los cruces "
            "pendientes marcados en esta página antes de generar."
        )
        return RedirectResponse(url=f"/normalizacion/lote/{lote_id}?error={mensaje}", status_code=303)

    nombre_archivo = f"formato_importacion_lote_{lote_id}.xls"
    ruta_salida = os.path.join(tempfile.gettempdir(), nombre_archivo)
    generar_formato_importacion(todos, lote.anio, lote.ejecutora, ruta_salida)

    lote.archivo_generado = nombre_archivo
    db.commit()

    return FileResponse(
        ruta_salida,
        filename=nombre_archivo,
        media_type="application/vnd.ms-excel",
    )
