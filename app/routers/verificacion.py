import os
import tempfile
from collections import defaultdict
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.auth import requiere_login
from app.database import get_db
from app.models import BienAlta, Pecosa, RelacionPecosaItem, VerificacionPecosaSiga
from app.services.excel_verificacion import leer_reporte_verificacion, texto_identificador

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ESTADO_CORRECTA = "PECOSA CORRECTA"
ESTADO_INCORRECTA = "PECOSA INCORRECTA"
ESTADO_SIN_VERIFICAR = "SIN VERIFICAR"
ESTADO_REPORTE_INCOMPLETO = "REPORTE SIGA INCOMPLETO"
ESTADOS_VERIFICACION = [
    ESTADO_INCORRECTA,
    ESTADO_REPORTE_INCOMPLETO,
    ESTADO_SIN_VERIFICAR,
    ESTADO_CORRECTA,
]
FILAS_POR_PAGINA = 50


def _estados_control_por_anio_pecosa(
    db: Session,
    bienes: list[BienAlta],
    items: list[RelacionPecosaItem] | None = None,
    pecosas: dict[str, Pecosa] | None = None,
) -> dict:
    """Calcula el estado de control sin mezclar una pecosa repetida de otro año."""
    bienes_por_clave = defaultdict(list)
    for bien in bienes:
        if bien.lote and bien.pecosa:
            clave = (str(bien.lote.anio or "").strip(), bien.pecosa.numero)
            bienes_por_clave[clave].append(bien)

    items_por_clave = defaultdict(list)
    if items is None:
        items = db.query(RelacionPecosaItem).all()
    for item in items:
        clave = (str(item.ano_eje or "").strip(), item.nro_pecosa)
        items_por_clave[clave].append(item)

    if pecosas is None:
        pecosas = {pecosa.numero: pecosa for pecosa in db.query(Pecosa).all()}
    estados = {}
    for clave, items in items_por_clave.items():
        cantidad_esperada = sum(item.cant_aprobada or 0 for item in items)
        cantidad_ingresada = len(bienes_por_clave.get(clave, []))
        pecosa = pecosas.get(clave[1])
        if pecosa is None:
            estado = "Pendiente envío almacén"
        elif cantidad_ingresada > cantidad_esperada:
            estado = "Inconsistencia: bienes de más"
        elif cantidad_ingresada < cantidad_esperada:
            estado = "Ingresada parcial en SIGA"
        elif pecosa.estado != "Firmada":
            estado = "Ingresado a SIGA y OVC (falta firma)"
        else:
            estado = "Firmada/Completa"
        estados[clave] = estado
    return estados


def _filas_verificacion(db: Session) -> list[dict]:
    bienes = (
        db.query(BienAlta)
        .options(
            joinedload(BienAlta.lote),
            joinedload(BienAlta.pecosa).joinedload(Pecosa.expediente),
        )
        .order_by(BienAlta.id.desc())
        .all()
    )
    reporte_por_codigo = {
        fila.codigo_patrimonial: fila
        for fila in db.query(VerificacionPecosaSiga).all()
    }
    items = db.query(RelacionPecosaItem).all()
    pecosas = {pecosa.numero: pecosa for pecosa in db.query(Pecosa).all()}
    estados_control = _estados_control_por_anio_pecosa(
        db, bienes, items=items, pecosas=pecosas
    )
    filas = []

    for bien in bienes:
        codigo = texto_identificador(bien.codigo_patrimonial)
        registro_siga = reporte_por_codigo.get(codigo)
        pecosa_alta = bien.pecosa.numero if bien.pecosa else ""
        anio_lote = str(bien.lote.anio or "").strip() if bien.lote else ""
        expediente = (
            bien.pecosa.expediente.numero
            if bien.pecosa and bien.pecosa.expediente else ""
        )
        pecosa_real = registro_siga.nro_pecosa if registro_siga else ""
        anio_siga = registro_siga.anio_siga if registro_siga else ""

        if registro_siga is None:
            estado, motivo = ESTADO_SIN_VERIFICAR, "Código no aparece en el último reporte SIGA."
        elif not pecosa_real or not anio_siga:
            estado, motivo = ESTADO_REPORTE_INCOMPLETO, "Falta la pecosa real o el año de fecha_alta en SIGA."
        else:
            diferencias = []
            if texto_identificador(pecosa_alta) != texto_identificador(pecosa_real):
                diferencias.append("Pecosa distinta")
            if anio_lote != anio_siga:
                diferencias.append("Año distinto")
            if diferencias:
                estado, motivo = ESTADO_INCORRECTA, " y ".join(diferencias)
            else:
                estado, motivo = ESTADO_CORRECTA, "Pecosa y año coinciden con SIGA."

        filas.append({
            "codigo_patrimonial": codigo,
            "descripcion": bien.descripcion,
            "pecosa_alta": pecosa_alta,
            "anio_lote": anio_lote,
            "pecosa_real": pecosa_real,
            "anio_siga": anio_siga,
            "lote": bien.lote_id or "",
            "expediente": expediente,
            "estado_control": estados_control.get(
                (anio_lote, pecosa_alta), "Sin relación de pecosas cargada"
            ),
            "estado": estado,
            "motivo": motivo,
        })

    prioridad = {estado: indice for indice, estado in enumerate(ESTADOS_VERIFICACION)}
    filas.sort(key=lambda fila: (prioridad[fila["estado"]], fila["codigo_patrimonial"]))
    return filas


@router.get("/verificacion", response_class=HTMLResponse)
def ver_verificacion(
    request: Request,
    codigo: str = "",
    pecosa: str = "",
    lote: str = "",
    expediente: str = "",
    estado: str = "",
    pagina: int = 1,
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    filas_completas = _filas_verificacion(db)
    filtros = {
        "codigo": codigo.strip(), "pecosa": pecosa.strip(), "lote": lote.strip(),
        "expediente": expediente.strip(), "estado": estado,
    }
    filas_filtradas = filas_completas
    if filtros["codigo"]:
        filas_filtradas = [
            fila for fila in filas_filtradas
            if filtros["codigo"] in fila["codigo_patrimonial"]
        ]
    if filtros["pecosa"]:
        filas_filtradas = [
            fila for fila in filas_filtradas
            if filtros["pecosa"] in fila["pecosa_alta"] or filtros["pecosa"] in fila["pecosa_real"]
        ]
    if filtros["lote"]:
        filas_filtradas = [
            fila for fila in filas_filtradas
            if filtros["lote"] == str(fila["lote"])
        ]
    if filtros["expediente"]:
        filas_filtradas = [
            fila for fila in filas_filtradas
            if filtros["expediente"] in fila["expediente"]
        ]
    if filtros["estado"]:
        filas_filtradas = [
            fila for fila in filas_filtradas if fila["estado"] == filtros["estado"]
        ]

    resumen = defaultdict(int)
    for fila in filas_completas:
        resumen[fila["estado"]] += 1
    lotes = sorted({
        str(fila["lote"]) for fila in filas_completas if fila["lote"]
    }, key=int)
    total_filtradas = len(filas_filtradas)
    total_paginas = max(1, (total_filtradas + FILAS_POR_PAGINA - 1) // FILAS_POR_PAGINA)
    pagina = max(1, min(pagina, total_paginas))
    inicio = (pagina - 1) * FILAS_POR_PAGINA
    filas_pagina = filas_filtradas[inicio:inicio + FILAS_POR_PAGINA]
    ultimo_reporte = db.query(VerificacionPecosaSiga).order_by(
        VerificacionPecosaSiga.importado_en.desc()
    ).first()
    return templates.TemplateResponse(
        "verificacion.html",
        {
            "request": request,
            "filas": filas_pagina,
            "total_bienes": len(filas_completas),
            "total_reporte": db.query(VerificacionPecosaSiga).count(),
            "ultimo_reporte": ultimo_reporte,
            "estados": ESTADOS_VERIFICACION,
            "resumen": resumen,
            "lotes": lotes,
            "filtros": filtros,
            "total_filtradas": total_filtradas,
            "pagina": pagina,
            "total_paginas": total_paginas,
        },
    )


@router.post("/verificacion/importar")
async def importar_reporte_verificacion(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    extension = os.path.splitext(archivo.filename or "")[1].lower()
    if extension not in {".xls", ".xlsx"}:
        return RedirectResponse(
            url="/verificacion?error=" + quote("Selecciona un archivo .xls o .xlsx."),
            status_code=303,
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temporal:
        temporal.write(await archivo.read())
        ruta_temporal = temporal.name
    try:
        reporte = leer_reporte_verificacion(ruta_temporal)
    except ValueError as error:
        return RedirectResponse(url="/verificacion?error=" + quote(str(error)), status_code=303)
    finally:
        os.remove(ruta_temporal)

    db.query(VerificacionPecosaSiga).delete()
    for _, fila in reporte.iterrows():
        db.add(VerificacionPecosaSiga(
            codigo_patrimonial=fila["codigo_patrimonial"],
            nro_pecosa=fila["nro_pecosa"],
            anio_siga=fila["anio_siga"],
        ))
    db.commit()
    return RedirectResponse(
        url="/verificacion?info=" + quote(
            f"Reporte SIGA cargado: {len(reporte)} bien(es) disponibles para verificación."
        ),
        status_code=303,
    )
