import os
import tempfile
from urllib.parse import quote

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

    lotes_query = db.query(LoteCarga).order_by(LoteCarga.id.desc()).all()
    lotes = [_resumen_lote(db, lote) for lote in lotes_query]
    bienes_historicos_pendientes = _bienes_historicos_pendientes_siga(db)
    lotes_historicos_sin_datos = _lotes_historicos_sin_datos_lote(db)
    return templates.TemplateResponse(
        "normalizacion.html",
        {
            "request": request,
            "expedientes": expedientes,
            "lotes": lotes,
            "bienes_historicos_pendientes": bienes_historicos_pendientes,
            "lotes_historicos_sin_datos": lotes_historicos_sin_datos,
        },
    )


def _resumen_lote(db: Session, lote: LoteCarga) -> dict:
    """Arma el estado de un lote (Vacío / Incompleto / Completo / Generado)
    y sus expedientes, para mostrarlo en la lista sin tener que entrar."""
    bienes = db.query(BienAlta).filter(BienAlta.lote_id == lote.id).all()
    pendientes = [b for b in bienes if _cruce_incompleto(b)]
    no_encontradas = _pecosas_no_encontradas(lote, bienes)
    pendientes_siga = [b for b in bienes if _bien_historico_pendiente_siga(b)]

    if lote.archivo_generado:
        estado = "Generado"
    elif not bienes:
        estado = "Vacío / sin procesar"
    elif pendientes_siga:
        estado = f"Histórico: faltan datos SIGA ({len(pendientes_siga)})"
    elif pendientes or no_encontradas:
        estado = "Incompleto"
    else:
        estado = "Completo (listo para generar)"

    return {
        "lote": lote,
        "estado": estado,
        "expedientes": expedientes_de_lote(db, lote),
    }


def _es_lote_historico(lote: LoteCarga) -> bool:
    """Los lotes creados por Carga Inicial no tienen año ni ejecutora.

    La normalización habitual siempre crea ambos valores desde la configuración.
    Esto permite ofrecer la regularización solo a los datos migrados, sin
    alterar el flujo de pecosas nuevas.
    """
    return not str(lote.anio or "").strip() or not str(lote.ejecutora or "").strip()


def _bien_historico_pendiente_siga(bien: BienAlta) -> bool:
    """Indica que un bien migrado no conserva aún sus datos fuente de SIGA."""
    return (
        bien.lote is not None
        and _es_lote_historico(bien.lote)
        and (
            not str(bien.nombre_depend_siga or "").strip()
            or not str(bien.nombre_completo_siga or "").strip()
        )
    )


def _bienes_historicos_pendientes_siga(db: Session) -> list[BienAlta]:
    bienes = db.query(BienAlta).join(LoteCarga).all()
    return [bien for bien in bienes if _bien_historico_pendiente_siga(bien)]


def _lotes_historicos_sin_datos_lote(db: Session) -> list[LoteCarga]:
    return [
        lote for lote in db.query(LoteCarga).all()
        if _es_lote_historico(lote)
    ]


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


def _codigo_patrimonial_normalizado(valor) -> str:
    return str(valor or "").strip().upper()


def _texto_siga(valor) -> str:
    """Convierte un valor de Excel a texto sin dejar sufijos como '.0'."""
    import pandas as pd

    if valor is None or pd.isna(valor):
        return ""
    texto = str(valor).strip()
    if texto.endswith(".0") and texto[:-2].isdigit():
        return texto[:-2]
    return texto


def _regularizar_bienes_historicos(db: Session, df) -> dict:
    """Completa los datos SIGA y los datos de lote de la Carga Inicial.

    El código patrimonial es la clave de cruce. Una fila con código repetido
    en el reporte se considera ambigua y no modifica ningún bien.
    """
    filas_por_codigo = {}
    codigos_duplicados = set()
    for _, fila in df.iterrows():
        codigo = _codigo_patrimonial_normalizado(fila.get("codigo_patrimonial"))
        if not codigo:
            continue
        if codigo in filas_por_codigo:
            codigos_duplicados.add(codigo)
        else:
            filas_por_codigo[codigo] = fila

    resumen = {
        "pendientes": 0,
        "actualizados": 0,
        "no_encontrados": 0,
        "duplicados": 0,
        "sin_persona": 0,
        "sin_centro": 0,
        "lotes_actualizados": 0,
        "lotes_inconsistentes": 0,
    }
    pendientes_siga = {bien.id for bien in _bienes_historicos_pendientes_siga(db)}
    lotes_sin_datos = {lote.id for lote in _lotes_historicos_sin_datos_lote(db)}
    valores_lote = {}

    bienes_historicos = [
        bien for bien in db.query(BienAlta).join(LoteCarga).all()
        if bien.lote and _es_lote_historico(bien.lote)
    ]
    for bien in bienes_historicos:
        completar_datos_siga = bien.id in pendientes_siga
        completar_datos_lote = bien.lote_id in lotes_sin_datos
        if completar_datos_siga:
            resumen["pendientes"] += 1
        codigo = _codigo_patrimonial_normalizado(bien.codigo_patrimonial)
        if codigo in codigos_duplicados:
            if completar_datos_siga or completar_datos_lote:
                resumen["duplicados"] += 1
            continue
        fila = filas_por_codigo.get(codigo)
        if fila is None:
            if completar_datos_siga or completar_datos_lote:
                resumen["no_encontrados"] += 1
            continue

        if completar_datos_lote:
            anio = _texto_siga(fila.get("ano_eje"))
            ejecutora = _texto_siga(fila.get("sec_ejec"))
            if anio and ejecutora:
                valores_lote.setdefault(bien.lote_id, set()).add((anio, ejecutora))

        if not completar_datos_siga:
            continue

        resultado = cruzar_fila(db, fila.get("nombre_completo"), fila.get("nombre_depend"))
        bien.nombre_depend_siga = str(fila.get("nombre_depend", "") or "").strip()
        bien.nombre_completo_siga = str(fila.get("nombre_completo", "") or "").strip()
        bien.fecha_alta = pd_to_datetime(fila.get("fecha_movimto"))
        bien.estado_conservacion = str(fila.get("estado_conserv", "") or "").strip()

        # Solo reemplazamos una asignación manual cuando SIGA tiene una
        # coincidencia exacta en el maestro. Si no la tiene, conservamos lo
        # que el usuario haya podido corregir previamente.
        if resultado["persona"]:
            bien.persona_id = resultado["persona"].id
        else:
            resumen["sin_persona"] += 1
        if resultado["centro_costo"]:
            bien.centro_costo_id = resultado["centro_costo"].id
        else:
            resumen["sin_centro"] += 1
        resumen["actualizados"] += 1

    for lote in _lotes_historicos_sin_datos_lote(db):
        valores = valores_lote.get(lote.id, set())
        if len(valores) == 1:
            anio, ejecutora = valores.pop()
            lote.anio = anio
            lote.ejecutora = ejecutora
            resumen["lotes_actualizados"] += 1
        elif len(valores) > 1:
            resumen["lotes_inconsistentes"] += 1

    return resumen


@router.post("/normalizacion/regularizar-carga-inicial")
async def regularizar_carga_inicial(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    """Procesa una sola vez un reporte completo de Altas SIGA para todos
    los lotes que provinieron de la Carga Inicial."""
    if not _bienes_historicos_pendientes_siga(db) and not _lotes_historicos_sin_datos_lote(db):
        return RedirectResponse(
            url="/normalizacion?mensaje=No+hay+bienes+hist%C3%B3ricos+pendientes+de+regularizar",
            status_code=303,
        )

    extension = os.path.splitext(archivo.filename or "")[1] or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
        tmp.write(await archivo.read())
        ruta_temporal = tmp.name
    try:
        df = leer_reporte_siga(ruta_temporal)
        resumen = _regularizar_bienes_historicos(db, df)
        db.commit()
    except (ValueError, OSError) as error:
        db.rollback()
        return RedirectResponse(
            url=f"/normalizacion?error={quote(str(error))}", status_code=303
        )
    finally:
        os.remove(ruta_temporal)

    mensaje = (
        "Regularización terminada: "
        f"{resumen['actualizados']} bien(es) actualizados; "
        f"{resumen['no_encontrados']} no aparecen en el reporte; "
        f"{resumen['duplicados']} con código repetido en el reporte; "
        f"{resumen['sin_persona']} sin coincidencia de persona; "
        f"{resumen['sin_centro']} sin coincidencia de centro de costo; "
        f"{resumen['lotes_actualizados']} lote(s) con Año y Ejecutora completados; "
        f"{resumen['lotes_inconsistentes']} lote(s) con valores distintos en el reporte."
    )
    return RedirectResponse(url=f"/normalizacion?mensaje={quote(mensaje)}", status_code=303)


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
