from fastapi import FastAPI, Depends, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text

from app.config import SECRET_KEY
from app.database import Base, engine, get_db
from app.auth import requiere_login
from app.routers import auth_routes, pecosas, maestros, normalizacion, impresion, control, carga_inicial
from app.models import Pecosa, RelacionPecosaItem  # noqa: F401  (necesario para que create_all las vea)

# Crea las tablas si no existen todavía (para un proyecto de un solo usuario,
# esto es más simple que manejar migraciones)
Base.metadata.create_all(bind=engine)

# create_all NO agrega columnas nuevas a tablas que ya existen — así que las
# columnas que se sumen después de la primera vez se agregan aquí a mano,
# de forma segura (no hace nada si la columna ya existe).
with engine.begin() as conn:
    conn.execute(text(
        "ALTER TABLE lotes_carga ADD COLUMN IF NOT EXISTS pecosas_solicitadas TEXT"
    ))
    conn.execute(text(
        "ALTER TABLE pecosas ADD COLUMN IF NOT EXISTS expediente_firma VARCHAR(50)"
    ))
    conn.execute(text(
        "ALTER TABLE lotes_carga ADD COLUMN IF NOT EXISTS origen_lote VARCHAR(20)"
    ))

app = FastAPI(title="SIGA → One Visión")

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

app.include_router(auth_routes.router)
app.include_router(pecosas.router)
app.include_router(maestros.router)
app.include_router(normalizacion.router)
app.include_router(impresion.router)
app.include_router(control.router)
app.include_router(carga_inicial.router)


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request, _=Depends(requiere_login)):
    return RedirectResponse(url="/pecosas")
