from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    ROL_INVENTARIADOR,
    guardar_sesion,
    verificar_credenciales,
)
from app.database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request, error: str = ""):
    if request.session.get("logueado"):
        destino = (
            "/inventariador"
            if request.session.get("rol") == ROL_INVENTARIADOR
            else "/"
        )
        return RedirectResponse(url=destino, status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@router.post("/login")
def procesar_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    usuario = verificar_credenciales(db, username, password)
    if usuario is not None:
        guardar_sesion(request, usuario)
        destino = "/inventariador" if usuario.rol == ROL_INVENTARIADOR else "/"
        return RedirectResponse(url=destino, status_code=303)
    return RedirectResponse(url="/login?error=Usuario+o+contraseña+incorrectos", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
