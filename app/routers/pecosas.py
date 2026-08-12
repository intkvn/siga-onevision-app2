from datetime import date
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models import Pecosa, Expediente
from app.auth import requiere_login

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/pecosas", response_class=HTMLResponse)
def listar_pecosas(request: Request, db: Session = Depends(get_db), _=Depends(requiere_login)):
    pecosas = db.query(Pecosa).order_by(desc(Pecosa.creado_en)).all()
    return templates.TemplateResponse(
        "pecosas.html", {"request": request, "pecosas": pecosas}
    )


@router.post("/pecosas/nuevas-multiples")
def registrar_pecosas_multiples(
    request: Request,
    numero_expediente: str = Form(...),
    numeros_pecosa: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    """Registra varias pecosas de un mismo expediente en un solo envío
    (una por línea o separadas por coma), sin tener que reescribir el
    número de expediente cada vez."""
    numero_expediente = numero_expediente.strip()
    crudos = numeros_pecosa.replace(",", "\n").splitlines()
    numeros = [n.strip() for n in crudos if n.strip()]

    if not numeros:
        return RedirectResponse(url="/pecosas?error=No+ingresaste+ning%C3%BAn+n%C3%BAmero+de+pecosa", status_code=303)

    expediente = db.query(Expediente).filter(Expediente.numero == numero_expediente).first()
    if not expediente:
        expediente = Expediente(numero=numero_expediente, fecha_recepcion=date.today())
        db.add(expediente)
        db.flush()

    existentes = {p.numero for p in db.query(Pecosa.numero).filter(Pecosa.numero.in_(numeros)).all()}
    duplicadas = [n for n in numeros if n in existentes]
    nuevas = [n for n in numeros if n not in existentes]

    for numero in nuevas:
        db.add(Pecosa(numero=numero, expediente_id=expediente.id, fecha_recepcion=date.today()))
    db.commit()

    mensaje = f"Se registraron {len(nuevas)} pecosa(s) del expediente {numero_expediente}."
    if duplicadas:
        mensaje += f" Ya existían y no se duplicaron: {', '.join(duplicadas)}."
    return RedirectResponse(url=f"/pecosas?info={mensaje}", status_code=303)


@router.post("/pecosas/nueva")
def registrar_pecosa(
    request: Request,
    numero_pecosa: str = Form(...),
    numero_expediente: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    numero_pecosa = numero_pecosa.strip()
    numero_expediente = numero_expediente.strip()

    # Regla clave: evitar duplicar el ingreso de una pecosa ya registrada
    ya_existe = db.query(Pecosa).filter(Pecosa.numero == numero_pecosa).first()
    if ya_existe:
        mensaje = f"La pecosa {numero_pecosa} ya está registrada (no se duplicó)."
        return RedirectResponse(url=f"/pecosas?error={mensaje}", status_code=303)

    expediente = db.query(Expediente).filter(Expediente.numero == numero_expediente).first()
    if not expediente:
        expediente = Expediente(numero=numero_expediente, fecha_recepcion=date.today())
        db.add(expediente)
        db.flush()

    nueva = Pecosa(numero=numero_pecosa, expediente_id=expediente.id, fecha_recepcion=date.today())
    db.add(nueva)
    db.commit()

    return RedirectResponse(url="/pecosas", status_code=303)


@router.post("/pecosas/{pecosa_id}/firmar")
def marcar_firmada(
    pecosa_id: int,
    firmante: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    pecosa = db.query(Pecosa).get(pecosa_id)
    if pecosa:
        pecosa.firmante = firmante.strip()
        pecosa.fecha_firma = date.today()
        pecosa.estado = "Firmada"
        db.commit()
    return RedirectResponse(url="/pecosas", status_code=303)
