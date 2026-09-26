from fastapi import FastAPI, Depends, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import SECRET_KEY
from app.database import Base, SessionLocal, engine, get_db
from app.auth import (
    ROL_INVENTARIADOR,
    asegurar_usuario_administrador,
    requiere_login,
)
from app.routers import (
    auth_routes, pecosas, maestros, normalizacion, impresion, control,
    carga_inicial, verificacion, control_impresion, maestro_patrimonial,
    inventariador, usuarios,
)
from app.models import (  # noqa: F401  (necesario para que create_all las vea)
    Pecosa, PerfilImpresionEtiqueta, InventarioImpresion,
    BienInventarioImpresion, LoteImpresionInventario,
    ItemLoteImpresionInventario, RelacionPecosaItem, VerificacionPecosaSiga,
    ObservacionControlPecosa, CargaPatrimonial, BienPatrimonial,
    BienCargaPatrimonial, VersionBienPatrimonial, CambioBienPatrimonial,
    CorreccionBienPatrimonial, ConflictoBienPatrimonial,
    ExportacionPatrimonial, UsuarioAplicacion, SolicitudImpresionInventario,
    ItemSolicitudImpresionInventario,
    CargaInventarioImpresion,
)
from app.services.solicitudes_impresion import reconciliar_solicitudes_pendientes
from app.services.excel_inventario_impresion import reparar_universos_acumulativos

# Crea las tablas si no existen todavía (para un proyecto de un solo usuario,
# esto es más simple que manejar migraciones)
Base.metadata.create_all(bind=engine)


def _migrar_bienes_impresion_sqlite():
    """Permite sobrantes sin código patrimonial en bases locales existentes."""
    if engine.dialect.name != "sqlite":
        return
    columnas = inspect(engine).get_columns("bienes_inventario_impresion")
    codigo = next(
        (columna for columna in columnas if columna["name"] == "codigo_patrimonial"),
        None,
    )
    if codigo is None or codigo.get("nullable", True):
        return
    nombres = {columna["name"] for columna in columnas}
    conexion = engine.raw_connection()
    cursor = conexion.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        cursor.execute("""
            CREATE TABLE bienes_inventario_impresion_nueva (
                id INTEGER NOT NULL PRIMARY KEY,
                inventario_id INTEGER NOT NULL,
                bien_alta_id INTEGER,
                codigo_patrimonial VARCHAR(30),
                codigo_qr VARCHAR(50),
                tipo_bien VARCHAR(30) NOT NULL DEFAULT 'Activo fijo',
                ruta_qr VARCHAR(500),
                descripcion VARCHAR(500) NOT NULL,
                establecimiento VARCHAR(300), red VARCHAR(250), area VARCHAR(300),
                marca VARCHAR(150), modelo VARCHAR(200), color VARCHAR(100),
                nro_serie VARCHAR(150), activo INTEGER NOT NULL,
                imprimible INTEGER NOT NULL, motivo_bloqueo VARCHAR(300),
                estado_impresion VARCHAR(30) NOT NULL DEFAULT 'Pendiente',
                sticker_generado_en TIMESTAMP, impreso_en TIMESTAMP,
                relacion_alta VARCHAR(30) NOT NULL,
                importado_en DATETIME NOT NULL, actualizado_en DATETIME NOT NULL,
                CONSTRAINT uq_bien_inventario_codigo
                    UNIQUE (inventario_id, codigo_patrimonial),
                FOREIGN KEY(inventario_id) REFERENCES inventarios_impresion (id),
                FOREIGN KEY(bien_alta_id) REFERENCES bienes_alta (id)
            )
        """)
        tipo_origen = (
            "tipo_bien" if "tipo_bien" in nombres
            else "CASE WHEN codigo_patrimonial IS NULL OR codigo_patrimonial = '' "
                 "THEN 'Sobrante' ELSE 'Activo fijo' END"
        )
        columnas_copia = (
            "id, inventario_id, bien_alta_id, codigo_patrimonial, codigo_qr, "
            "ruta_qr, descripcion, establecimiento, red, area, marca, modelo, "
            "color, nro_serie, activo, imprimible, motivo_bloqueo, "
            "estado_impresion, sticker_generado_en, impreso_en, relacion_alta, "
            "importado_en, actualizado_en"
        )
        cursor.execute(f"""
            INSERT INTO bienes_inventario_impresion_nueva (
                id, inventario_id, bien_alta_id, codigo_patrimonial, codigo_qr,
                ruta_qr, descripcion, establecimiento, red, area, marca, modelo,
                color, nro_serie, activo, imprimible, motivo_bloqueo,
                estado_impresion, sticker_generado_en, impreso_en, relacion_alta,
                importado_en, actualizado_en, tipo_bien
            ) SELECT {columnas_copia}, {tipo_origen}
              FROM bienes_inventario_impresion
        """)
        cursor.execute("DROP TABLE bienes_inventario_impresion")
        cursor.execute(
            "ALTER TABLE bienes_inventario_impresion_nueva "
            "RENAME TO bienes_inventario_impresion"
        )
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        conexion.close()


_migrar_bienes_impresion_sqlite()

with engine.begin() as conn:
    columnas_bienes_impresion = {
        columna["name"]
        for columna in inspect(conn).get_columns("bienes_inventario_impresion")
    }
    if "tipo_bien" not in columnas_bienes_impresion:
        conn.execute(text(
            "ALTER TABLE bienes_inventario_impresion ADD COLUMN "
            "tipo_bien VARCHAR(30) NOT NULL DEFAULT 'Activo fijo'"
        ))
    if engine.dialect.name == "postgresql":
        conn.execute(text(
            "ALTER TABLE bienes_inventario_impresion "
            "ALTER COLUMN codigo_patrimonial DROP NOT NULL"
        ))
    columnas_items_lote = {
        columna["name"]
        for columna in inspect(conn).get_columns("items_lote_impresion_inventario")
    }
    if "solicitud_item_id" not in columnas_items_lote:
        conn.execute(text(
            "ALTER TABLE items_lote_impresion_inventario ADD COLUMN "
            "solicitud_item_id INTEGER REFERENCES "
            "items_solicitud_impresion_inventario(id)"
        ))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_item_lote_solicitud_item "
        "ON items_lote_impresion_inventario (solicitud_item_id)"
    ))
    for nombre, columna in (
        ("inventario_id", "inventario_id"),
        ("codigo_patrimonial", "codigo_patrimonial"),
        ("codigo_qr", "codigo_qr"),
        ("tipo_bien", "tipo_bien"),
        ("activo", "activo"),
    ):
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_bienes_inventario_impresion_{nombre} "
            f"ON bienes_inventario_impresion ({columna})"
        ))

with SessionLocal() as db:
    asegurar_usuario_administrador(db)
    reparar_universos_acumulativos(db)
    inventarios_solicitudes = db.query(InventarioImpresion.id).all()
    for (inventario_id,) in inventarios_solicitudes:
        reconciliar_solicitudes_pendientes(db, inventario_id)
    db.commit()

with engine.begin() as conn:
    columnas_carga_mp = {
        columna["name"]
        for columna in inspect(conn).get_columns("cargas_patrimoniales")
    }
    if "total_alertas" not in columnas_carga_mp:
        conn.execute(text(
            "ALTER TABLE cargas_patrimoniales "
            "ADD COLUMN total_alertas INTEGER NOT NULL DEFAULT 0"
        ))
    if "detalle_alertas" not in columnas_carga_mp:
        conn.execute(text(
            "ALTER TABLE cargas_patrimoniales ADD COLUMN detalle_alertas TEXT"
        ))
    columnas_nuevas = {
        "tipo_carga": "VARCHAR(20) NOT NULL DEFAULT 'Completa'",
        "progreso": "INTEGER NOT NULL DEFAULT 0",
        "mensaje_progreso": "VARCHAR(300)",
        "archivo_contenido": (
            "BYTEA" if engine.dialect.name == "postgresql" else "BLOB"
        ),
    }
    for nombre, definicion in columnas_nuevas.items():
        if nombre not in columnas_carga_mp:
            conn.execute(text(
                f"ALTER TABLE cargas_patrimoniales ADD COLUMN {nombre} {definicion}"
            ))

# El código de barras de SIGA puede llegar como texto numérico rellenado con
# ceros. Se conserva intacto cualquier QR que contenga letras u otros signos.
with engine.begin() as conn:
    if engine.dialect.name == "postgresql":
        conn.execute(text("""
            UPDATE bienes_patrimoniales
            SET codigo_qr = COALESCE(NULLIF(LTRIM(codigo_qr, '0'), ''), '0')
            WHERE LENGTH(codigo_qr) > 1
              AND codigo_qr ~ '^0[0-9]+$'
        """))
    else:
        conn.execute(text("""
            UPDATE bienes_patrimoniales
            SET codigo_qr = COALESCE(NULLIF(LTRIM(codigo_qr, '0'), ''), '0')
            WHERE LENGTH(codigo_qr) > 1
              AND codigo_qr LIKE '0%'
              AND codigo_qr NOT GLOB '*[^0-9]*'
        """))

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

    # pg_trgm acelera las búsquedas parciales del maestro. Si el proveedor no
    # permite instalar extensiones, la aplicación continúa con los índices
    # convencionales sin impedir el arranque.
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except SQLAlchemyError:
        pass

    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_bien_mp_codigo_busqueda "
            "ON bienes_patrimoniales (lower(codigo_patrimonial) text_pattern_ops)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_bien_mp_qr_busqueda "
            "ON bienes_patrimoniales (lower(codigo_qr) text_pattern_ops)"
        ))

    try:
        with engine.begin() as conn:
            for nombre, columna in (
                ("descripcion", "descripcion"),
                ("dependencia", "nombre_dependencia"),
                ("usuario", "usuario"),
                ("ubicacion", "ubicacion_fisica"),
                ("modelo", "modelo"),
                ("marca", "marca"),
            ):
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS ix_bien_mp_{nombre}_trgm "
                    f"ON bienes_patrimoniales USING gin ({columna} gin_trgm_ops)"
                ))
    except SQLAlchemyError:
        pass

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
app.include_router(maestro_patrimonial.router)
app.include_router(inventariador.router)
app.include_router(usuarios.router)


@app.on_event("startup")
def reanudar_tareas_pendientes():
    """Continúa cargas y exportaciones persistidas antes de un reinicio."""
    maestro_patrimonial.reanudar_tareas_patrimoniales()


@app.get("/health")
def health_check():
    """Respuesta pública mínima para comprobar que el servicio está activo."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request, _=Depends(requiere_login)):
    if request.session.get("rol") == ROL_INVENTARIADOR:
        return RedirectResponse(url="/inventariador")
    return RedirectResponse(url="/pecosas")
