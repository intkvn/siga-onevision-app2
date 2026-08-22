import os
import tempfile
from collections import defaultdict

from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from openpyxl import Workbook

from app.database import get_db
from app.models import RelacionPecosaItem, Pecosa, BienAlta
from app.auth import requiere_login
from app.services.excel_relacion_pecosas import leer_relacion_pecosas

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ESTADO_PENDIENTE_ALMACEN = "Pendiente envío almacén"
ESTADO_PARCIAL = "Ingresada parcial en SIGA"
ESTADO_FALTA_FIRMA = "Ingresado a SIGA y OVC (falta firma)"
ESTADO_COMPLETA = "Firmada/Completa"


def _calcular_control(db: Session) -> list[dict]:
    """Arma, por cada N° de pecosa que aparece en la Relación de Pecosas
    de SIGA, cuánto se esperaba, cuánto se ha ingresado en nuestro
    sistema, y en qué estado está."""
    items = db.query(RelacionPecosaItem).all()
    por_pecosa = defaultdict(list)
    for it in items:
        por_pecosa[it.nro_pecosa].append(it)

    pecosas_db = {p.numero: p for p in db.query(Pecosa).all()}

    filas = []
    for nro_pecosa, lineas in por_pecosa.items():
        cantidad_esperada = sum(l.cant_aprobada or 0 for l in lineas)
        pecosa = pecosas_db.get(nro_pecosa)
        cantidad_ingresada = 0
        if pecosa:
            cantidad_ingresada = (
                db.query(BienAlta).filter(BienAlta.pecosa_id == pecosa.id).count()
            )

        if pecosa is None:
            estado = ESTADO_PENDIENTE_ALMACEN
        elif cantidad_ingresada < cantidad_esperada:
            estado = ESTADO_PARCIAL
        elif pecosa.estado != "Firmada":
            estado = ESTADO_FALTA_FIRMA
        else:
            estado = ESTADO_COMPLETA

        primera = lineas[0]
        filas.append({
            "nro_pecosa": nro_pecosa,
            "ano_eje": primera.ano_eje,
            "nombre_depend": primera.nombre_depend,
            "fecha_pecosa": primera.fecha_pecosa,
            "motivo_pedido": primera.motivo_pedido,
            "cantidad_esperada": cantidad_esperada,
            "cantidad_ingresada": cantidad_ingresada,
            "estado": estado,
            "firmante": pecosa.firmante if pecosa else None,
            "fecha_firma": pecosa.fecha_firma if pecosa else None,
            "expediente_alta": pecosa.expediente.numero if pecosa and pecosa.expediente else None,
            "expediente_firma": pecosa.expediente_firma if pecosa else None,
            "lineas": lineas,
        })

    orden_estado = {ESTADO_PENDIENTE_ALMACEN: 0, ESTADO_PARCIAL: 1, ESTADO_FALTA_FIRMA: 2, ESTADO_COMPLETA: 3}
    filas.sort(key=lambda f: (orden_estado.get(f["estado"], 9), f["nro_pecosa"]))
    return filas


@router.get("/control", response_class=HTMLResponse)
def ver_control(
    request: Request,
    numero: str = "",
    estado: str = "",
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    filas = _calcular_control(db)
    resumen = defaultdict(int)
    for f in filas:
        resumen[f["estado"]] += 1

    filas_filtradas = filas
    if numero:
        filas_filtradas = [f for f in filas_filtradas if numero.strip() in f["nro_pecosa"]]
    if estado:
        filas_filtradas = [f for f in filas_filtradas if f["estado"] == estado]

    return templates.TemplateResponse(
        "control.html",
        {
            "request": request, "filas": filas_filtradas, "hay_datos": bool(filas), "resumen": resumen,
            "estados": [ESTADO_PENDIENTE_ALMACEN, ESTADO_PARCIAL, ESTADO_FALTA_FIRMA, ESTADO_COMPLETA],
            "filtros": {"numero": numero, "estado": estado},
        },
    )


@router.post("/control/importar")
async def importar_relacion_pecosas(
    archivo: UploadFile = File(...), db: Session = Depends(get_db), _=Depends(requiere_login)
):
    """Reemplaza por completo la tabla con lo que traiga el archivo nuevo
    — la Relación de Pecosas de SIGA es un reporte acumulado a la fecha,
    así que no tiene sentido ir sumando importaciones viejas."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(await archivo.read())
        ruta_temporal = tmp.name

    try:
        df = leer_relacion_pecosas(ruta_temporal)
    except ValueError as e:
        return RedirectResponse(url=f"/control?error={e}", status_code=303)
    finally:
        os.remove(ruta_temporal)

    db.query(RelacionPecosaItem).delete()

    for _, fila in df.iterrows():
        nro_pecosa = str(fila.get("nro_pecosa", "")).strip()
        if nro_pecosa.endswith(".0"):
            nro_pecosa = nro_pecosa[:-2]
        if not nro_pecosa or nro_pecosa.lower() == "nan":
            continue
        cant = fila.get("cant_aprobada")
        try:
            cant = int(cant) if cant == cant else 0  # cant == cant descarta NaN
        except (TypeError, ValueError):
            cant = 0

        db.add(RelacionPecosaItem(
            nro_pecosa=nro_pecosa,
            ano_eje=str(fila.get("ano_eje", "") or ""),
            nombre_item=str(fila.get("nombre_item", "") or ""),
            nombre_depend=str(fila.get("nombre_depend", "") or ""),
            precio_unit=str(fila.get("precio_unit", "") or ""),
            motivo_pedido=str(fila.get("motivo_pedido", "") or ""),
            fecha_pecosa=str(fila.get("fecha_pecosa", "") or ""),
            clasificador=str(fila.get("clasificador", "") or ""),
            cant_aprobada=cant,
        ))
    db.commit()
    return RedirectResponse(url="/control", status_code=303)


def _normalizar_texto(t) -> str:
    return " ".join(str(t or "").strip().upper().split())


@router.get("/control/exportar")
def exportar_control(db: Session = Depends(get_db), _=Depends(requiere_login)):
    """Reporte con DOS hojas:
    1) 'Todas las Pecosas' — el listado completo de pecosas que trae el
       reporte de SIGA cargado, con su estado al final (para enviar a
       almacén y pedir lo que falta).
    2) 'Bienes con QR' — el detalle de cada bien que ya tiene su código
       QR generado (el mismo universo del reporte de BarTender)."""
    filas_control = _calcular_control(db)

    items = db.query(RelacionPecosaItem).all()
    items_por_pecosa = defaultdict(list)
    for it in items:
        items_por_pecosa[it.nro_pecosa].append(it)

    bienes = db.query(BienAlta).filter(BienAlta.codigo_qr.isnot(None)).all()

    libro = Workbook()

    # --- Hoja 1: todas las pecosas del reporte, con su estado ---
    hoja1 = libro.active
    hoja1.title = "Todas las Pecosas"
    hoja1.append([
        "ano_eje", "Numero pecosa", "fecha_pecosa", "nombre_depend", "motivo_pedido",
        "clasificador", "Cant. Esperada", "Cant. Ingresada", "Responsable",
        "Nro Expediente Alta", "Nro Expediente Firma", "Estado",
    ])
    for f in filas_control:
        hoja1.append([
            f["ano_eje"], f["nro_pecosa"], f["fecha_pecosa"], f["nombre_depend"], f["motivo_pedido"],
            f["lineas"][0].clasificador if f["lineas"] else "", f["cantidad_esperada"], f["cantidad_ingresada"],
            f["firmante"] or "", f["expediente_alta"] or "", f["expediente_firma"] or "", f["estado"],
        ])

    # --- Hoja 2: solo los bienes que ya tienen QR generado ---
    hoja2 = libro.create_sheet("Bienes con QR")
    hoja2.append([
        "ano_eje", "Numero pecosa", "fecha_pecosa", "Codigo Patrimonial", "Codigo QR",
        "Bien", "Establecimiento", "Marca", "Modelo", "Nro Serie",
        "motivo_pedido", "clasificador", "Responsable", "Nro Expediente Alta", "Nro Expediente Firma",
    ])
    for bien in bienes:
        numero_pecosa = bien.pecosa.numero if bien.pecosa else ""
        candidatos = items_por_pecosa.get(numero_pecosa, [])

        item = None
        if candidatos:
            descripcion_norm = _normalizar_texto(bien.descripcion)
            item = next(
                (c for c in candidatos if _normalizar_texto(c.nombre_item) == descripcion_norm),
                None,
            )
            if item is None:
                item = candidatos[0]  # mejor esfuerzo si la pecosa trae varios tipos de ítem

        hoja2.append([
            item.ano_eje if item else (bien.lote.anio if bien.lote else ""),
            numero_pecosa,
            item.fecha_pecosa if item else "",
            bien.codigo_patrimonial,
            bien.codigo_qr or "",
            item.nombre_item if item else bien.descripcion,
            bien.centro_costo.nombre_depend if bien.centro_costo else "",
            bien.marca or "",
            bien.modelo or "",
            bien.nro_serie or "",
            item.motivo_pedido if item else "",
            item.clasificador if item else "",
            bien.pecosa.firmante if bien.pecosa else "",
            bien.pecosa.expediente.numero if bien.pecosa and bien.pecosa.expediente else "",
            bien.pecosa.expediente_firma if bien.pecosa else "",
        ])

    nombre_archivo = "control_pecosas.xlsx"
    ruta_salida = os.path.join(tempfile.gettempdir(), nombre_archivo)
    libro.save(ruta_salida)

    return FileResponse(
        ruta_salida, filename=nombre_archivo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
