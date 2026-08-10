from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from app.auth import verificar_credenciales

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@router.post("/login")
def procesar_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if verificar_credenciales(username, password):
        request.session["logueado"] = True
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url="/login?error=Usuario+o+contraseña+incorrectos", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
