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


@router.get("/maestros", response_class=HTMLResponse)
def ver_maestros(request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)):
    personas = db.query(Persona).order_by(Persona.nombre_completo).all()
    centros = db.query(CentroCosto).order_by(CentroCosto.nombre_depend).all()
    return templates.TemplateResponse(
        "maestros.html", {"request": request, "personas": personas, "centros": centros}
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


@router.post("/maestros/personas/importar")
async def importar_personas(
    archivo: UploadFile = File(...), db: Session = Depends(get_db), _=Depends(requiere_login)
):
    """Importa desde el Excel de usuarios_responsable.xlsx (hoja PERSONA:
    columnas NOMBRE COMPLETO, DNI)."""
    df = pd.read_excel(archivo.file)
    existentes = {p.nombre_completo for p in db.query(Persona.nombre_completo).all()}
    nuevas = 0
    for _, fila in df.iterrows():
        nombre = str(fila.get("NOMBRE COMPLETO", "")).strip().upper()
        dni = str(fila.get("DNI", "")).strip()
        if nombre and nombre not in existentes:
            db.add(Persona(nombre_completo=nombre, dni=dni))
            existentes.add(nombre)
            nuevas += 1
    db.commit()
    return RedirectResponse(url=f"/maestros?importadas={nuevas}", status_code=303)


@router.post("/maestros/centros/importar")
async def importar_centros(
    archivo: UploadFile = File(...), db: Session = Depends(get_db), _=Depends(requiere_login)
):
    """Importa desde CENTROS_DE_COSTO.xlsx (columnas nombre_depend,
    'centro_costo One vision')."""
    df = pd.read_excel(archivo.file)
    existentes = {c.nombre_depend for c in db.query(CentroCosto.nombre_depend).all()}
    nuevos = 0
    for _, fila in df.iterrows():
        nombre = str(fila.get("nombre_depend", "")).strip().upper()
        ipress = str(fila.get("centro_costo One vision", "")).strip()
        if nombre and nombre not in existentes:
            db.add(CentroCosto(nombre_depend=nombre, ipress=ipress))
            existentes.add(nombre)
            nuevos += 1
    db.commit()
    return RedirectResponse(url=f"/maestros?importados={nuevos}", status_code=303)
