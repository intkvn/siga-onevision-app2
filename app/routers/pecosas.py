from datetime import date
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc

from sqlalchemy import desc, or_

from app.database import get_db
from app.models import Pecosa, Expediente, Persona
from app.auth import requiere_login

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ESTADOS_PECOSA = ["Recibida", "Normalizada", "StickerGenerado", "Firmada"]
FILAS_POR_PAGINA = 50


@router.get("/pecosas", response_class=HTMLResponse)
def listar_pecosas(
    request: Request,
    numero: str = "",
    expediente: str = "",
    estado: str = "",
    firmante: str = "",
    pagina: int = 1,
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    consulta = db.query(Pecosa).join(Expediente, isouter=True)
    if numero:
        consulta = consulta.filter(Pecosa.numero.ilike(f"%{numero.strip()}%"))
    if expediente:
        consulta = consulta.filter(Expediente.numero.ilike(f"%{expediente.strip()}%"))
    if estado:
        consulta = consulta.filter(Pecosa.estado == estado)
    if firmante:
        consulta = consulta.filter(Pecosa.firmante.ilike(f"%{firmante.strip()}%"))

    total = consulta.order_by(None).count()
    total_paginas = max(1, (total + FILAS_POR_PAGINA - 1) // FILAS_POR_PAGINA)
    pagina = max(1, min(pagina, total_paginas))
    pecosas = (
        consulta.options(joinedload(Pecosa.expediente))
        .order_by(desc(Pecosa.creado_en))
        .offset((pagina - 1) * FILAS_POR_PAGINA)
        .limit(FILAS_POR_PAGINA)
        .all()
    )
    return templates.TemplateResponse(
        "pecosas.html",
        {
            "request": request, "pecosas": pecosas,
            "estados": ESTADOS_PECOSA,
            "filtros": {"numero": numero, "expediente": expediente, "estado": estado, "firmante": firmante},
            "total": total, "pagina": pagina, "total_paginas": total_paginas,
        },
    )


@router.get("/pecosas/personas-buscar")
def buscar_personas_firmantes(
    q: str = "",
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    """Devuelve solo coincidencias del maestro para el autocompletado.

    Antes la página enviaba las 5129 personas en cada respuesta. La búsqueda
    bajo demanda mantiene el mismo campo de firma sin cargar todo el maestro.
    """
    termino = q.strip()
    if not termino:
        return JSONResponse([])
    patron = f"%{termino}%"
    personas = (
        db.query(Persona.id, Persona.nombre_completo, Persona.dni)
        .filter((Persona.nombre_completo.ilike(patron)) | (Persona.dni.ilike(patron)))
        .order_by(Persona.nombre_completo)
        .limit(20)
        .all()
    )
    return JSONResponse([
        {"id": persona.id, "nombre": persona.nombre_completo, "dni": persona.dni}
        for persona in personas
    ])


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
    expediente_firma: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    pecosa = db.query(Pecosa).get(pecosa_id)
    if pecosa:
        pecosa.firmante = firmante.strip()
        pecosa.expediente_firma = expediente_firma.strip()
        pecosa.fecha_firma = date.today()
        pecosa.estado = "Firmada"
        db.commit()
    return RedirectResponse(url="/pecosas", status_code=303)
