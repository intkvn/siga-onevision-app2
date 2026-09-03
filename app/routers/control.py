import os
import tempfile
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from openpyxl import Workbook

from app.database import get_db
from app.models import (
    RelacionPecosaItem, Pecosa, BienAlta, CorreccionAsignacionBien,
    ObservacionControlPecosa,
)
from app.auth import requiere_login
from app.services.excel_relacion_pecosas import leer_relacion_pecosas

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ESTADO_PENDIENTE_ALMACEN = "Pendiente envío almacén"
ESTADO_PARCIAL = "Ingresada parcial en SIGA"
ESTADO_EXCESO = "Inconsistencia: bienes de más"
ESTADO_FALTA_FIRMA = "Ingresado a SIGA y OVC (falta firma)"
ESTADO_COMPLETA = "Firmada/Completa"
ESTADO_OBSERVADA = "Observada"
CAUSALES_OBSERVACION = [
    "No corresponde a activo fijo",
    "Transferencia a otra RIS/unidad ejecutora",
    "Otra",
]


def _calcular_control(db: Session) -> list[dict]:
    """Arma el control por año y N° de pecosa, en columnas separadas."""
    items = db.query(RelacionPecosaItem).all()
    por_pecosa = defaultdict(list)
    for it in items:
        clave = (str(it.ano_eje or "").strip(), it.nro_pecosa)
        por_pecosa[clave].append(it)

    pecosas_db = {p.numero: p for p in db.query(Pecosa).all()}
    observaciones = {
        (observacion.ano_eje, observacion.nro_pecosa): observacion
        for observacion in db.query(ObservacionControlPecosa).filter(
            ObservacionControlPecosa.activa == 1
        ).all()
    }

    filas = []
    for (ano_eje, nro_pecosa), lineas in por_pecosa.items():
        cantidad_esperada = sum(l.cant_aprobada or 0 for l in lineas)
        pecosa = pecosas_db.get(nro_pecosa)
        cantidad_ingresada = 0
        lotes = []
        if pecosa:
            bienes_pecosa = db.query(BienAlta).filter(BienAlta.pecosa_id == pecosa.id).all()
            cantidad_ingresada = len(bienes_pecosa)
            lotes = sorted({bien.lote_id for bien in bienes_pecosa if bien.lote_id is not None})

        observacion = observaciones.get((ano_eje, nro_pecosa))
        if observacion:
            estado = ESTADO_OBSERVADA
        elif pecosa is None:
            estado = ESTADO_PENDIENTE_ALMACEN
        elif cantidad_ingresada > cantidad_esperada:
            estado = ESTADO_EXCESO
        elif cantidad_ingresada < cantidad_esperada:
            estado = ESTADO_PARCIAL
        elif pecosa.estado != "Firmada":
            estado = ESTADO_FALTA_FIRMA
        else:
            estado = ESTADO_COMPLETA

        primera = lineas[0]
        filas.append({
            "nro_pecosa": nro_pecosa,
            "ano_eje": ano_eje,
            "nombre_depend": primera.nombre_depend,
            "fecha_pecosa": primera.fecha_pecosa,
            "lotes": lotes,
            "motivo_pedido": primera.motivo_pedido,
            "cantidad_esperada": cantidad_esperada,
            "cantidad_ingresada": cantidad_ingresada,
            "estado": estado,
            "firmante": pecosa.firmante if pecosa else None,
            "fecha_firma": pecosa.fecha_firma if pecosa else None,
            "expediente_alta": pecosa.expediente.numero if pecosa and pecosa.expediente else None,
            "expediente_firma": pecosa.expediente_firma if pecosa else None,
            "lineas": lineas,
            "observacion": observacion,
        })

    def _numero_para_orden(nro_pecosa: str) -> int:
        return int(nro_pecosa) if nro_pecosa.isdigit() else -1

    filas.sort(
        key=lambda f: (f["ano_eje"], _numero_para_orden(f["nro_pecosa"])),
        reverse=True,
    )
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
    pecosas_db = {p.numero: p for p in db.query(Pecosa).all()}
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
            "pecosas_db": pecosas_db,
            "estados": [
                ESTADO_PENDIENTE_ALMACEN, ESTADO_PARCIAL, ESTADO_EXCESO,
                ESTADO_FALTA_FIRMA, ESTADO_COMPLETA, ESTADO_OBSERVADA,
            ],
            "causales_observacion": CAUSALES_OBSERVACION,
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
    extension = os.path.splitext(archivo.filename or "")[1].lower()
    if extension not in {".xls", ".xlsx"}:
        return RedirectResponse(
            url="/control?error=Selecciona un archivo Excel de SIGA con extensión .xls o .xlsx",
            status_code=303,
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
        tmp.write(await archivo.read())
        ruta_temporal = tmp.name

    try:
        df = leer_relacion_pecosas(ruta_temporal)
    except (ImportError, ValueError) as e:
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


def _clave_control(valor: str) -> tuple[str, str] | None:
    """Convierte el valor oculto 'año|pecosa' en dos campos independientes."""
    if "|" not in valor:
        return None
    anio, numero = (parte.strip() for parte in valor.split("|", 1))
    return (anio, numero) if anio and numero else None


@router.post("/control/observar")
def observar_pecosas(
    claves: list[str] = Form(...),
    causal: str = Form(...),
    sustento: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    sustento = sustento.strip()
    if causal not in CAUSALES_OBSERVACION or not sustento:
        return RedirectResponse(
            url="/control?error=Selecciona+una+causal+y+escribe+el+sustento+de+la+observaci%C3%B3n",
            status_code=303,
        )

    pendientes = {
        (fila["ano_eje"], fila["nro_pecosa"]): fila
        for fila in _calcular_control(db)
        if fila["estado"] == ESTADO_PENDIENTE_ALMACEN
    }
    seleccionadas = {_clave_control(valor) for valor in claves}
    seleccionadas.discard(None)
    validas = seleccionadas.intersection(pendientes)
    if not validas:
        return RedirectResponse(
            url="/control?error=Selecciona+al+menos+una+pecosa+pendiente+para+observar",
            status_code=303,
        )

    existentes = {
        (fila.ano_eje, fila.nro_pecosa): fila
        for fila in db.query(ObservacionControlPecosa).filter(
            ObservacionControlPecosa.ano_eje.in_([clave[0] for clave in validas]),
            ObservacionControlPecosa.nro_pecosa.in_([clave[1] for clave in validas]),
        ).all()
    }
    for anio, numero in validas:
        registro = existentes.get((anio, numero))
        if registro:
            registro.causal = causal
            registro.sustento = sustento
            registro.activa = 1
            registro.observada_en = datetime.utcnow()
            registro.restituida_en = None
        else:
            db.add(ObservacionControlPecosa(
                ano_eje=anio, nro_pecosa=numero, causal=causal, sustento=sustento,
            ))
    db.commit()
    return RedirectResponse(
        url=f"/control?info=Se+observaron+{len(validas)}+pecosa%28s%29",
        status_code=303,
    )


@router.post("/control/restituir-observacion")
def restituir_observacion(
    ano_eje: str = Form(...),
    nro_pecosa: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    registro = db.query(ObservacionControlPecosa).filter(
        ObservacionControlPecosa.ano_eje == ano_eje.strip(),
        ObservacionControlPecosa.nro_pecosa == nro_pecosa.strip(),
        ObservacionControlPecosa.activa == 1,
    ).first()
    if registro is None:
        return RedirectResponse(url="/control?error=No+se+encontr%C3%B3+la+observaci%C3%B3n+activa", status_code=303)
    registro.activa = 0
    registro.restituida_en = datetime.utcnow()
    db.commit()
    return RedirectResponse(
        url=f"/control?info=La+pecosa+{registro.nro_pecosa}+volvi%C3%B3+a+Pendiente+env%C3%ADo+almac%C3%A9n",
        status_code=303,
    )


def _cantidad_esperada(db: Session, numero_pecosa: str) -> int:
    return sum(
        item.cant_aprobada or 0
        for item in db.query(RelacionPecosaItem).filter(
            RelacionPecosaItem.nro_pecosa == numero_pecosa
        ).all()
    )


def _mover_bien_a_pecosa(
    db: Session, bien: BienAlta, pecosa_destino: Pecosa, motivo: str
) -> CorreccionAsignacionBien:
    """Traslada un bien conservando sus demás datos y registrando el cambio."""
    pecosa_origen = bien.pecosa
    if pecosa_origen is None:
        raise ValueError("El bien no tiene una pecosa de origen.")
    if pecosa_origen.id == pecosa_destino.id:
        raise ValueError("La pecosa de destino debe ser diferente de la pecosa de origen.")

    correccion = CorreccionAsignacionBien(
        bien_id=bien.id,
        pecosa_origen_id=pecosa_origen.id,
        pecosa_destino_id=pecosa_destino.id,
        motivo=motivo.strip(),
    )
    bien.pecosa_id = pecosa_destino.id
    _sincronizar_pecosa_corregida(bien, pecosa_destino)
    db.add(correccion)
    return correccion


def _sincronizar_pecosa_corregida(bien: BienAlta, pecosa_destino: Pecosa) -> None:
    """Mantiene el estado y el lote de una pecosa que recibe un bien ya procesado.

    El bien conserva su lote. La pecosa de destino se incorpora a ese mismo
    lote para que su expediente figure en el historial y no vuelva a aparecer
    como pendiente de normalización.
    """
    if bien.codigo_qr and pecosa_destino.estado in ("Recibida", "Normalizada"):
        pecosa_destino.estado = "StickerGenerado"
    elif bien.lote_id and pecosa_destino.estado == "Recibida":
        pecosa_destino.estado = "Normalizada"

    lote = bien.lote
    if lote is None:
        return
    pecosas_lote = [numero for numero in (lote.pecosas_solicitadas or "").split(",") if numero]
    if pecosa_destino.numero not in pecosas_lote:
        pecosas_lote.append(pecosa_destino.numero)
        lote.pecosas_solicitadas = ",".join(pecosas_lote)


@router.get("/control/pecosa/{pecosa_id}/corregir", response_class=HTMLResponse)
def formulario_corregir_asignacion(
    pecosa_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    pecosa = db.query(Pecosa).get(pecosa_id)
    if pecosa is None:
        return RedirectResponse(url="/control?error=Pecosa+no+encontrada", status_code=303)

    esperada = _cantidad_esperada(db, pecosa.numero)
    bienes = db.query(BienAlta).filter(BienAlta.pecosa_id == pecosa.id).order_by(BienAlta.id).all()
    if len(bienes) <= esperada:
        return RedirectResponse(
            url="/control?error=Esta+pecosa+ya+no+tiene+bienes+de+m%C3%A1s+por+corregir",
            status_code=303,
        )

    historial = db.query(CorreccionAsignacionBien).filter(
        CorreccionAsignacionBien.pecosa_origen_id == pecosa.id
    ).order_by(CorreccionAsignacionBien.creado_en.desc()).all()
    return templates.TemplateResponse(
        "control_corregir_pecosa.html",
        {
            "request": request,
            "pecosa": pecosa,
            "bienes": bienes,
            "cantidad_esperada": esperada,
            "historial": historial,
        },
    )


@router.post("/control/bien/{bien_id}/reasignar-pecosa")
def reasignar_bien_a_pecosa(
    bien_id: int,
    numero_pecosa_destino: str = Form(...),
    motivo: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_login),
):
    bien = db.query(BienAlta).get(bien_id)
    if bien is None or bien.pecosa is None:
        return RedirectResponse(url="/control?error=Bien+no+encontrado", status_code=303)

    pecosa_origen = bien.pecosa
    esperada = _cantidad_esperada(db, pecosa_origen.numero)
    ingresada = db.query(BienAlta).filter(BienAlta.pecosa_id == pecosa_origen.id).count()
    if ingresada <= esperada:
        return RedirectResponse(
            url=f"/control?error=La+pecosa+{pecosa_origen.numero}+ya+no+tiene+un+exceso+que+corregir",
            status_code=303,
        )

    destino_numero = numero_pecosa_destino.strip()
    if not destino_numero or not motivo.strip():
        return RedirectResponse(
            url=f"/control/pecosa/{pecosa_origen.id}/corregir?error=Indica+la+pecosa+de+destino+y+el+motivo",
            status_code=303,
        )
    pecosa_destino = db.query(Pecosa).filter(Pecosa.numero == destino_numero).first()
    if pecosa_destino is None:
        return RedirectResponse(
            url=f"/control/pecosa/{pecosa_origen.id}/corregir?error=La+pecosa+{destino_numero}+no+est%C3%A1+registrada.+Reg%C3%ADstrala+primero+en+Pecosas",
            status_code=303,
        )

    try:
        _mover_bien_a_pecosa(db, bien, pecosa_destino, motivo)
    except ValueError as error:
        return RedirectResponse(
            url=f"/control/pecosa/{pecosa_origen.id}/corregir?error={error}", status_code=303
        )

    db.commit()
    return RedirectResponse(
        url=(
            f"/control?info=Se+movió+el+bien+{bien.codigo_patrimonial}+de+la+pecosa+"
            f"{pecosa_origen.numero}+a+la+pecosa+{pecosa_destino.numero}"
        ),
        status_code=303,
    )


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
        "Nro Expediente Alta", "Nro Expediente Firma", "Estado", "Causal", "Observación",
    ])
    for f in filas_control:
        hoja1.append([
            f["ano_eje"], f["nro_pecosa"], f["fecha_pecosa"], f["nombre_depend"], f["motivo_pedido"],
            f["lineas"][0].clasificador if f["lineas"] else "", f["cantidad_esperada"], f["cantidad_ingresada"],
            f["firmante"] or "", f["expediente_alta"] or "", f["expediente_firma"] or "", f["estado"],
            f["observacion"].causal if f["observacion"] else "",
            f["observacion"].sustento if f["observacion"] else "",
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
