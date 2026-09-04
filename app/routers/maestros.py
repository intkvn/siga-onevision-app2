import pandas as pd
from fastapi import APIRouter, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Persona, CentroCosto
from app.auth import requiere_login

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
FILAS_POR_PAGINA = 50


def _encontrar_columna(df: pd.DataFrame, exactas: list[str], contiene: list[str]) -> str | None:
    """Busca una columna por nombre exacto primero; si no la encuentra,
    busca alguna cuyo nombre CONTENGA alguno de los fragmentos dados
    (sin importar mayúsculas/tildes). Devuelve el nombre real de la
    columna en el archivo, o None si no encontró nada parecido."""
    columnas = list(df.columns)
    for exacta in exactas:
        for col in columnas:
            if str(col).strip().lower() == exacta.lower():
                return col
    for col in columnas:
        col_normalizada = str(col).strip().lower()
        for fragmento in contiene:
            if fragmento.lower() in col_normalizada:
                return col
    return None



@router.get("/maestros", response_class=HTMLResponse)
def ver_maestros(
    request: Request,
    buscar_persona: str = "",
    buscar_centro: str = "",
    pagina_personas: int = 1,
    pagina_centros: int = 1,
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    incompletas_p = db.query(Persona).filter(Persona.dni == "").count()
    incompletos_c = db.query(CentroCosto).filter(CentroCosto.ipress == "").count()

    consulta_personas = db.query(Persona)
    if buscar_persona:
        termino = f"%{buscar_persona.strip()}%"
        consulta_personas = consulta_personas.filter(
            (Persona.nombre_completo.ilike(termino)) | (Persona.dni.ilike(termino))
        )
    total_personas = consulta_personas.order_by(None).count()
    total_paginas_personas = max(1, (total_personas + FILAS_POR_PAGINA - 1) // FILAS_POR_PAGINA)
    pagina_personas = max(1, min(pagina_personas, total_paginas_personas))
    personas = (
        consulta_personas
        .order_by(Persona.dni == "", Persona.nombre_completo)
        .offset((pagina_personas - 1) * FILAS_POR_PAGINA)
        .limit(FILAS_POR_PAGINA)
        .all()
    )

    consulta_centros = db.query(CentroCosto)
    if buscar_centro:
        termino = f"%{buscar_centro.strip()}%"
        consulta_centros = consulta_centros.filter(
            (CentroCosto.nombre_depend.ilike(termino)) | (CentroCosto.ipress.ilike(termino))
        )
    total_centros = consulta_centros.order_by(None).count()
    total_paginas_centros = max(1, (total_centros + FILAS_POR_PAGINA - 1) // FILAS_POR_PAGINA)
    pagina_centros = max(1, min(pagina_centros, total_paginas_centros))
    centros = (
        consulta_centros
        .order_by(CentroCosto.ipress == "", CentroCosto.nombre_depend)
        .offset((pagina_centros - 1) * FILAS_POR_PAGINA)
        .limit(FILAS_POR_PAGINA)
        .all()
    )

    return templates.TemplateResponse(
        "maestros.html",
        {
            "request": request, "personas": personas, "centros": centros,
            "incompletas_p": incompletas_p, "incompletos_c": incompletos_c,
            "buscar_persona": buscar_persona, "buscar_centro": buscar_centro,
            "total_personas": total_personas, "pagina_personas": pagina_personas,
            "total_paginas_personas": total_paginas_personas,
            "total_centros": total_centros, "pagina_centros": pagina_centros,
            "total_paginas_centros": total_paginas_centros,
        },
    )


@router.post("/maestros/personas/nueva")
def nueva_persona(
    nombre_completo: str = Form(...),
    dni: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    db.add(Persona(nombre_completo=nombre_completo.strip().upper(), dni=dni.strip()))
    db.commit()
    return RedirectResponse(url="/maestros", status_code=303)


@router.post("/maestros/centros/nuevo")
def nuevo_centro(
    nombre_depend: str = Form(...),
    ipress: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    db.add(CentroCosto(nombre_depend=nombre_depend.strip().upper(), ipress=ipress.strip()))
    db.commit()
    return RedirectResponse(url="/maestros", status_code=303)


@router.post("/maestros/personas/{persona_id}/editar")
def editar_persona(
    persona_id: int,
    dni: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    persona = db.query(Persona).get(persona_id)
    if persona:
        persona.dni = dni.strip()
        db.commit()
    return RedirectResponse(url="/maestros", status_code=303)


@router.post("/maestros/centros/{centro_id}/editar")
def editar_centro(
    centro_id: int,
    ipress: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    centro = db.query(CentroCosto).get(centro_id)
    if centro:
        centro.ipress = ipress.strip()
        db.commit()
    return RedirectResponse(url="/maestros", status_code=303)
@router.post("/maestros/personas/importar")
async def importar_personas(
    archivo: UploadFile = File(...), db: Session = Depends(get_db), _=Depends(requiere_login)
):
    """Importa desde el Excel de usuarios_responsable.xlsx. Detecta las
    columnas de nombre y DNI aunque no se llamen exactamente
    "NOMBRE COMPLETO" / "DNI" (ej. "docum_identidad"). Si el nombre ya
    existía pero sin DNI (de una prueba anterior), lo completa."""
    df = pd.read_excel(archivo.file)

    col_nombre = _encontrar_columna(df, ["NOMBRE COMPLETO"], ["nombre completo", "nombre_completo"])
    col_dni = _encontrar_columna(
        df, ["DNI"], ["dni", "documento", "doc_ident", "docum_ident", "num_doc"]
    )
    if col_nombre is None or col_dni is None:
        columnas_disponibles = ", ".join(str(c) for c in df.columns)
        mensaje = (
            f"No encontré la columna de {'nombre' if col_nombre is None else 'DNI'} en el archivo. "
            f"Columnas disponibles: {columnas_disponibles}"
        )
        return RedirectResponse(url=f"/maestros?error={mensaje}", status_code=303)

    existentes = {p.nombre_completo: p for p in db.query(Persona).all()}
    nuevas = 0
    actualizadas = 0
    for _, fila in df.iterrows():
        nombre = str(fila.get(col_nombre, "")).strip().upper()
        dni = str(fila.get(col_dni, "")).strip()
        if dni.endswith(".0"):
            dni = dni[:-2]
        if not nombre or not dni or dni.lower() == "nan":
            continue
        existente = existentes.get(nombre)
        if existente is None:
            nueva = Persona(nombre_completo=nombre, dni=dni)
            db.add(nueva)
            existentes[nombre] = nueva
            nuevas += 1
        elif not existente.dni:
            existente.dni = dni
            actualizadas += 1
    db.commit()
    return RedirectResponse(
        url=f"/maestros?importadas={nuevas}&actualizadas={actualizadas}", status_code=303
    )


@router.post("/maestros/centros/importar")
async def importar_centros(
    archivo: UploadFile = File(...), db: Session = Depends(get_db), _=Depends(requiere_login)
):
    """Importa desde CENTROS_DE_COSTO.xlsx. Detecta las columnas de
    nombre_depend e IPRESS aunque no se llamen exactamente igual. Si el
    nombre ya existía pero sin IPRESS, lo completa en vez de ignorarlo."""
    df = pd.read_excel(archivo.file)

    col_nombre = _encontrar_columna(df, ["nombre_depend"], ["nombre_depend", "dependencia"])
    col_ipress = _encontrar_columna(
        df, ["centro_costo One vision"], ["centro_costo", "ipress", "one vision"]
    )
    if col_nombre is None or col_ipress is None:
        columnas_disponibles = ", ".join(str(c) for c in df.columns)
        mensaje = (
            f"No encontré la columna de {'nombre_depend' if col_nombre is None else 'IPRESS'} en el archivo. "
            f"Columnas disponibles: {columnas_disponibles}"
        )
        return RedirectResponse(url=f"/maestros?error={mensaje}", status_code=303)

    existentes = {c.nombre_depend: c for c in db.query(CentroCosto).all()}
    nuevos = 0
    actualizados = 0
    for _, fila in df.iterrows():
        nombre = str(fila.get(col_nombre, "")).strip().upper()
        ipress = str(fila.get(col_ipress, "")).strip()
        if ipress.endswith(".0"):
            ipress = ipress[:-2]
        if not nombre or not ipress or ipress.lower() == "nan":
            continue
        existente = existentes.get(nombre)
        if existente is None:
            nuevo = CentroCosto(nombre_depend=nombre, ipress=ipress)
            db.add(nuevo)
            existentes[nombre] = nuevo
            nuevos += 1
        elif not existente.ipress:
            existente.ipress = ipress
            actualizados += 1
    db.commit()
    return RedirectResponse(
        url=f"/maestros?importados={nuevos}&actualizados={actualizados}", status_code=303
    )
