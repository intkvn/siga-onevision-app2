from fastapi import FastAPI, Depends, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect, text

from app.config import SECRET_KEY
from app.database import Base, engine, get_db
from app.auth import requiere_login
from app.routers import (
    auth_routes, pecosas, maestros, normalizacion, impresion, control,
    carga_inicial, verificacion, control_impresion,
)
from app.models import (  # noqa: F401  (necesario para que create_all las vea)
    Pecosa, PerfilImpresionEtiqueta, InventarioImpresion,
    BienInventarioImpresion, LoteImpresionInventario,
    ItemLoteImpresionInventario, RelacionPecosaItem, VerificacionPecosaSiga,
    ObservacionControlPecosa,
)

# Crea las tablas si no existen todavía (para un proyecto de un solo usuario,
# esto es más simple que manejar migraciones)
Base.metadata.create_all(bind=engine)

# Estos índices permiten agrupar rápidamente bienes por pecosa y lote. Se
# aplican también a las bases ya existentes, sin modificar registros.
with engine.begin() as conn:
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_bienes_alta_pecosa_id ON bienes_alta (pecosa_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_bienes_alta_lote_id ON bienes_alta (lote_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relacion_pecosas_ano_numero "
        "ON relacion_pecosa_items (ano_eje, nro_pecosa)"
    ))

# create_all tampoco agrega columnas a una tabla ya creada. Estas columnas
# guardan el estado actual de impresión para no recalcularlo recorriendo todo
# el historial cada vez que se abre o filtra el inventario.
with engine.begin() as conn:
    columnas_inventario = {
        columna["name"]
        for columna in inspect(conn).get_columns("bienes_inventario_impresion")
    }
    estado_agregado = "estado_impresion" not in columnas_inventario
    if estado_agregado:
        conn.execute(text(
            "ALTER TABLE bienes_inventario_impresion "
            "ADD COLUMN estado_impresion VARCHAR(30) NOT NULL DEFAULT 'Pendiente'"
        ))
    if "sticker_generado_en" not in columnas_inventario:
        conn.execute(text(
            "ALTER TABLE bienes_inventario_impresion "
            "ADD COLUMN sticker_generado_en TIMESTAMP"
        ))
    if "impreso_en" not in columnas_inventario:
        conn.execute(text(
            "ALTER TABLE bienes_inventario_impresion ADD COLUMN impreso_en TIMESTAMP"
        ))

    if estado_agregado:
        conn.execute(text("""
            UPDATE bienes_inventario_impresion
            SET estado_impresion = CASE
                WHEN EXISTS (
                    SELECT 1 FROM items_lote_impresion_inventario AS item
                    WHERE item.bien_id = bienes_inventario_impresion.id
                      AND item.impreso_en IS NOT NULL
                ) THEN 'Impreso'
                WHEN imprimible = 0 THEN 'Bloqueado'
                WHEN EXISTS (
                    SELECT 1
                    FROM items_lote_impresion_inventario AS item
                    JOIN lotes_impresion_inventario AS lote
                      ON lote.id = item.lote_id
                    WHERE item.bien_id = bienes_inventario_impresion.id
                      AND lote.pdf_generado_en IS NOT NULL
                ) THEN 'Sticker generado'
                ELSE 'Pendiente'
            END
        """))
        conn.execute(text("""
            UPDATE bienes_inventario_impresion
            SET sticker_generado_en = (
                SELECT MAX(lote.pdf_generado_en)
                FROM items_lote_impresion_inventario AS item
                JOIN lotes_impresion_inventario AS lote ON lote.id = item.lote_id
                WHERE item.bien_id = bienes_inventario_impresion.id
            )
            WHERE estado_impresion IN ('Sticker generado', 'Impreso')
        """))
        conn.execute(text("""
            UPDATE bienes_inventario_impresion
            SET impreso_en = (
                SELECT MAX(item.impreso_en)
                FROM items_lote_impresion_inventario AS item
                WHERE item.bien_id = bienes_inventario_impresion.id
            )
            WHERE estado_impresion = 'Impreso'
        """))

    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_bien_inventario_estado "
        "ON bienes_inventario_impresion (inventario_id, activo, estado_impresion)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_bien_inventario_red "
        "ON bienes_inventario_impresion (inventario_id, activo, red)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_bien_inventario_establecimiento "
        "ON bienes_inventario_impresion (inventario_id, activo, establecimiento)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_bien_inventario_area "
        "ON bienes_inventario_impresion (inventario_id, activo, area)"
    ))

# create_all NO agrega columnas nuevas a tablas que ya existen. En PostgreSQL,
# las columnas que se sumen después de la primera vez se agregan aquí a mano,
# de forma segura (no hace nada si la columna ya existe). SQLite omite estas
# instrucciones porque no admite esta sintaxis de ALTER TABLE.
if engine.dialect.name == "postgresql":
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE lotes_carga ADD COLUMN IF NOT EXISTS pecosas_solicitadas TEXT"
        ))
        conn.execute(text(
            "ALTER TABLE pecosas ADD COLUMN IF NOT EXISTS expediente_firma VARCHAR(50)"
        ))
        conn.execute(text(
            "ALTER TABLE lotes_carga DROP COLUMN IF EXISTS origen_lote"
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
app.include_router(verificacion.router)
app.include_router(carga_inicial.router)
app.include_router(control_impresion.router)


@app.get("/health")
def health_check():
    """Respuesta pública mínima para comprobar que el servicio está activo."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request, _=Depends(requiere_login)):
    return RedirectResponse(url="/pecosas")
