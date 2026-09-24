"""Ficha A4 de un bien del Maestro Patrimonial."""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.maestro_patrimonial import ETIQUETAS_CAMPOS


AZUL = colors.HexColor("#1F4E78")
AZUL_CLARO = colors.HexColor("#DCEAF5")
GRIS_CLARO = colors.HexColor("#F3F4F6")
GRIS_TEXTO = colors.HexColor("#4B5563")
BORDE = colors.HexColor("#7A8793")
ANCHO_UTIL = A4[0] - (24 * mm)


def _texto(valor) -> str:
    if valor is None:
        return "-"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    return texto or "-"


def _moneda(valor) -> str:
    if valor is None or valor == "":
        return "-"
    try:
        return f"S/ {Decimal(str(valor)):,.2f}"
    except Exception:
        return _texto(valor)


def _parrafo(valor, estilo):
    return Paragraph(escape(_texto(valor)), estilo)


def _estilos():
    base = getSampleStyleSheet()
    return {
        "institucion": ParagraphStyle(
            "Institucion", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8.2, leading=10, textColor=AZUL,
        ),
        "meta": ParagraphStyle(
            "Meta", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.5, leading=9, alignment=TA_RIGHT, textColor=GRIS_TEXTO,
        ),
        "titulo": ParagraphStyle(
            "Titulo", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=15, leading=18, alignment=TA_CENTER, textColor=colors.black,
            spaceAfter=5 * mm,
        ),
        "seccion": ParagraphStyle(
            "Seccion", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=9, leading=11, alignment=TA_CENTER, textColor=colors.white,
        ),
        "etiqueta": ParagraphStyle(
            "Etiqueta", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=7.4, leading=9, textColor=colors.HexColor("#243447"),
        ),
        "valor": ParagraphStyle(
            "Valor", parent=base["Normal"], fontName="Helvetica",
            fontSize=8, leading=9.5, textColor=colors.black,
        ),
        "valor_centrado": ParagraphStyle(
            "ValorCentrado", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8.5, leading=10, alignment=TA_CENTER,
        ),
        "subtitulo": ParagraphStyle(
            "Subtitulo", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=9.5, leading=12, textColor=AZUL, spaceBefore=2 * mm,
            spaceAfter=2 * mm,
        ),
        "pequeno": ParagraphStyle(
            "Pequeno", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.2, leading=8.5, textColor=GRIS_TEXTO,
        ),
        "evento": ParagraphStyle(
            "Evento", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.8, leading=9.5, textColor=colors.black,
        ),
    }


def _titulo_seccion(titulo: str, estilos):
    tabla = Table(
        [[Paragraph(escape(titulo), estilos["seccion"])]],
        colWidths=[ANCHO_UTIL],
    )
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), AZUL),
        ("BOX", (0, 0), (-1, -1), 0.7, AZUL),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tabla


def _tabla_campos(titulo: str, campos: list[tuple[str, object]], estilos, columnas=2):
    elementos = [_titulo_seccion(titulo, estilos)]
    filas = []
    if columnas == 1:
        for etiqueta, valor in campos:
            filas.append([
                _parrafo(etiqueta, estilos["etiqueta"]),
                _parrafo(valor, estilos["valor"]),
            ])
        anchos = [39 * mm, ANCHO_UTIL - (39 * mm)]
    else:
        for indice in range(0, len(campos), 2):
            pares = campos[indice:indice + 2]
            fila = []
            for etiqueta, valor in pares:
                fila.extend([
                    _parrafo(etiqueta, estilos["etiqueta"]),
                    _parrafo(valor, estilos["valor"]),
                ])
            if len(pares) == 1:
                fila.extend(["", ""])
            filas.append(fila)
        anchos = [30 * mm, 63 * mm, 30 * mm, 63 * mm]

    tabla = Table(filas, colWidths=anchos, hAlign="LEFT")
    estilo = [
        ("GRID", (0, 0), (-1, -1), 0.45, BORDE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if columnas == 1:
        estilo.append(("BACKGROUND", (0, 0), (0, -1), AZUL_CLARO))
    else:
        estilo.extend([
            ("BACKGROUND", (0, 0), (0, -1), AZUL_CLARO),
            ("BACKGROUND", (2, 0), (2, -1), AZUL_CLARO),
        ])
    tabla.setStyle(TableStyle(estilo))
    elementos.extend([tabla, Spacer(1, 2.5 * mm)])
    return elementos


def _ruta_qr_valida(altas, impresiones) -> str | None:
    candidatos = [
        getattr(registro.get("bien"), "ruta_qr", None)
        for registro in altas
    ]
    candidatos.extend(getattr(item, "ruta_qr", None) for item in impresiones)
    for candidato in candidatos:
        texto = str(candidato or "").strip()
        partes = urlsplit(texto)
        if partes.scheme.lower() in ("http", "https") and partes.netloc:
            return texto
    return None


def _dibujo_qr(ruta: str, tamano=27 * mm):
    widget = QrCodeWidget(
        ruta, barLevel="M", barBorder=4, barWidth=tamano, barHeight=tamano,
    )
    dibujo = Drawing(tamano, tamano)
    dibujo.add(widget)
    return dibujo


def _identificacion(bien, ruta_qr, estilos):
    qr = _dibujo_qr(ruta_qr) if ruta_qr else Paragraph(
        "QR gráfico<br/>no disponible", estilos["pequeno"]
    )
    filas = [
        [
            _parrafo("Código patrimonial", estilos["etiqueta"]),
            _parrafo(bien.codigo_patrimonial, estilos["valor"]),
            qr,
        ],
        [
            _parrafo("Código QR", estilos["etiqueta"]),
            _parrafo(bien.codigo_qr, estilos["valor"]),
            "",
        ],
        [
            _parrafo("Descripción", estilos["etiqueta"]),
            _parrafo(bien.descripcion, estilos["valor"]),
            "",
        ],
        [
            _parrafo("Estado de conservación", estilos["etiqueta"]),
            _parrafo(bien.estado_conservacion, estilos["valor"]),
            "",
        ],
    ]
    tabla = Table(filas, colWidths=[38 * mm, 116 * mm, 32 * mm])
    tabla.setStyle(TableStyle([
        ("GRID", (0, 0), (1, -1), 0.45, BORDE),
        ("BOX", (2, 0), (2, -1), 0.45, BORDE),
        ("SPAN", (2, 0), (2, -1)),
        ("BACKGROUND", (0, 0), (0, -1), AZUL_CLARO),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [_titulo_seccion("IDENTIFICACIÓN DEL BIEN", estilos), tabla, Spacer(1, 2.5 * mm)]


def _tabla_registros(titulo: str, registros: list[list[tuple[str, object]]], estilos):
    elementos = [_titulo_seccion(titulo, estilos)]
    if not registros:
        tabla = Table([[_parrafo("-", estilos["valor_centrado"])]], colWidths=[ANCHO_UTIL])
        tabla.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.45, BORDE),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elementos.extend([tabla, Spacer(1, 2.5 * mm)])
        return elementos

    filas = []
    estilos_tabla = [
        ("GRID", (0, 0), (-1, -1), 0.45, BORDE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    numero_fila = 0
    for indice_registro, campos in enumerate(registros, start=1):
        filas.append([
            Paragraph(f"Registro {indice_registro}", estilos["etiqueta"]), "", "", ""
        ])
        estilos_tabla.extend([
            ("SPAN", (0, numero_fila), (-1, numero_fila)),
            ("BACKGROUND", (0, numero_fila), (-1, numero_fila), GRIS_CLARO),
        ])
        numero_fila += 1
        for indice in range(0, len(campos), 2):
            pares = campos[indice:indice + 2]
            fila = []
            for etiqueta, valor in pares:
                fila.extend([
                    _parrafo(etiqueta, estilos["etiqueta"]),
                    _parrafo(valor, estilos["valor"]),
                ])
            if len(pares) == 1:
                fila.extend(["", ""])
            filas.append(fila)
            numero_fila += 1
    tabla = Table(filas, colWidths=[30 * mm, 63 * mm, 30 * mm, 63 * mm], repeatRows=0)
    tabla.setStyle(TableStyle(estilos_tabla))
    elementos.extend([tabla, Spacer(1, 2.5 * mm)])
    return elementos


def _eventos_trazabilidad(altas, impresiones, versiones):
    eventos = []

    def agregar(fecha, tipo, titulo, detalle):
        if fecha:
            fecha_orden = (
                fecha if isinstance(fecha, datetime)
                else datetime.combine(fecha, datetime.min.time())
            )
            eventos.append((fecha_orden, tipo, titulo, detalle))

    for version in versiones:
        if version.carga_id is not None or version.origen.casefold() == "importación":
            continue
        agregar(
            version.creado_en,
            "Corrección manual",
            version.origen,
            f"{len(version.cambios)} campo(s) modificados por {version.usuario}.",
        )
    for registro in altas:
        alta = registro["bien"]
        pecosa = registro["pecosa"]
        referencia = f"Pecosa {_texto(pecosa.numero) if pecosa else '-'}"
        agregar(alta.fecha_alta, "Altas", "Alta registrada en SIGA", referencia)
        if pecosa:
            agregar(pecosa.fecha_recepcion, "Altas", "Pecosa recibida", referencia)
            agregar(pecosa.fecha_firma, "Altas", "Pecosa firmada", referencia)
    for item in impresiones:
        inventario = getattr(item, "inventario", None)
        referencia = getattr(inventario, "nombre", None) or f"Inventario #{item.inventario_id}"
        agregar(
            item.importado_en, "Control Impresión",
            "Incluido en Control Impresión", referencia,
        )
        agregar(item.sticker_generado_en, "Control Impresión", "Sticker generado", referencia)
        agregar(item.impreso_en, "Control Impresión", "Impresión confirmada", referencia)
    return sorted(eventos, key=lambda evento: evento[0], reverse=True)


def _trazabilidad(altas, impresiones, versiones, estilos):
    eventos = _eventos_trazabilidad(altas, impresiones, versiones)
    manuales = [
        version for version in versiones
        if version.carga_id is None and version.origen.casefold() != "importación"
    ]
    if not eventos and not manuales:
        return []

    elementos = [PageBreak(), Paragraph("TRAZABILIDAD DEL BIEN", estilos["titulo"])]
    elementos.append(_titulo_seccion("LÍNEA DE TIEMPO", estilos))
    if eventos:
        filas = [[
            _parrafo("Fecha", estilos["etiqueta"]),
            _parrafo("Origen", estilos["etiqueta"]),
            _parrafo("Evento", estilos["etiqueta"]),
            _parrafo("Detalle", estilos["etiqueta"]),
        ]]
        for fecha, tipo, titulo, detalle in eventos:
            filas.append([
                _parrafo(fecha, estilos["evento"]),
                _parrafo(tipo, estilos["evento"]),
                _parrafo(titulo, estilos["evento"]),
                _parrafo(detalle, estilos["evento"]),
            ])
        tabla = Table(
            filas, colWidths=[29 * mm, 33 * mm, 52 * mm, 72 * mm], repeatRows=1,
        )
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL_CLARO),
            ("GRID", (0, 0), (-1, -1), 0.45, BORDE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elementos.extend([tabla, Spacer(1, 3 * mm)])
    else:
        elementos.extend([_parrafo("-", estilos["valor_centrado"]), Spacer(1, 3 * mm)])

    elementos.append(_titulo_seccion("HISTORIAL DE CAMBIOS MANUALES", estilos))
    if not manuales:
        elementos.append(_parrafo("-", estilos["valor_centrado"]))
        return elementos

    for version in manuales:
        encabezado = (
            f"{_texto(version.origen)} - {_texto(version.creado_en)} - "
            f"Usuario: {_texto(version.usuario)}"
        )
        filas = [[
            _parrafo("Campo", estilos["etiqueta"]),
            _parrafo("Anterior", estilos["etiqueta"]),
            _parrafo("Nuevo", estilos["etiqueta"]),
        ]]
        for cambio in version.cambios:
            filas.append([
                _parrafo(ETIQUETAS_CAMPOS.get(cambio.campo, cambio.campo), estilos["evento"]),
                _parrafo(cambio.valor_anterior, estilos["evento"]),
                _parrafo(cambio.valor_nuevo, estilos["evento"]),
            ])
        if len(filas) == 1:
            filas.append([
                _parrafo("-", estilos["evento"]),
                _parrafo("-", estilos["evento"]),
                _parrafo("-", estilos["evento"]),
            ])
        tabla = Table(
            filas, colWidths=[48 * mm, 69 * mm, 69 * mm], repeatRows=1,
        )
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), GRIS_CLARO),
            ("GRID", (0, 0), (-1, -1), 0.45, BORDE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elementos.extend([
            Paragraph(escape(encabezado), estilos["subtitulo"]),
            tabla,
            Spacer(1, 2.5 * mm),
        ])
    return elementos


def generar_ficha_activo_pdf(
    bien,
    altas,
    impresiones,
    versiones,
    inconsistencias_qr=None,
    qr_repetido_maestro=None,
    conflictos=None,
    destino=None,
):
    """Genera la ficha A4 del activo sin metadatos técnicos de las cargas."""
    estilos = _estilos()
    salida = io.BytesIO() if destino is None else destino
    ahora = datetime.now(ZoneInfo("America/Lima"))
    documento = SimpleDocTemplate(
        salida,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=14 * mm,
        title=f"Ficha del activo fijo {bien.codigo_patrimonial}",
        author="SIGA a One Vision",
        subject="Maestro Patrimonial",
    )

    def encabezado_pie(canvas_pdf, doc):
        canvas_pdf.saveState()
        canvas_pdf.setTitle(f"Ficha del activo fijo {bien.codigo_patrimonial}")
        canvas_pdf.setAuthor("SIGA a One Vision")
        canvas_pdf.setStrokeColor(AZUL)
        canvas_pdf.setLineWidth(0.6)
        canvas_pdf.line(12 * mm, 10 * mm, A4[0] - (12 * mm), 10 * mm)
        canvas_pdf.setFont("Helvetica", 7)
        canvas_pdf.setFillColor(GRIS_TEXTO)
        canvas_pdf.drawString(12 * mm, 6.2 * mm, "Generado desde Maestro Patrimonial")
        canvas_pdf.drawRightString(
            A4[0] - (12 * mm), 6.2 * mm, f"Página {doc.page}"
        )
        canvas_pdf.restoreState()

    cabecera = Table([[
        Paragraph(
            "GOBIERNO REGIONAL DE CAJAMARCA<br/>"
            "DIRECCIÓN REGIONAL DE SALUD CAJAMARCA<br/>"
            "OFICINA DE CONTROL PATRIMONIAL",
            estilos["institucion"],
        ),
        Paragraph(
            f"Fecha: {ahora.strftime('%d/%m/%Y')}<br/>"
            f"Hora: {ahora.strftime('%H:%M:%S')}",
            estilos["meta"],
        ),
    ]], colWidths=[130 * mm, 56 * mm])
    cabecera.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    historia = [
        cabecera,
        Paragraph("DATOS DEL ACTIVO FIJO", estilos["titulo"]),
    ]
    ruta_qr = _ruta_qr_valida(altas, impresiones)
    historia.extend(_identificacion(bien, ruta_qr, estilos))
    historia.extend(_tabla_campos("ASIGNACIÓN Y UBICACIÓN", [
        ("Dependencia", bien.nombre_dependencia),
        ("Usuario", bien.usuario),
        ("Ubicación física", bien.ubicacion_fisica),
    ], estilos))
    historia.extend(_tabla_campos("ESPECIFICACIONES TÉCNICAS", [
        ("Marca", bien.marca),
        ("Modelo", bien.modelo),
        ("Número de serie", bien.numero_serie),
        ("Medidas", bien.medidas),
        ("Color", bien.color),
        ("Características", bien.caracteristicas),
    ], estilos))
    historia.extend(_tabla_campos("INGRESO Y VALORES", [
        ("Fecha de compra", bien.fecha_compra),
        ("Valor de compra", _moneda(bien.valor_compra)),
        ("Fecha de alta", bien.fecha_alta),
        ("Valor inicial", _moneda(bien.valor_inicial)),
        ("Valor neto", _moneda(bien.valor_neto)),
        ("Número de orden", bien.numero_orden),
        ("Número de documento", bien.numero_documento),
        ("Fecha NEA", bien.fecha_nea),
    ], estilos))
    historia.extend(_tabla_campos("OBSERVACIONES", [
        ("Observaciones", bien.observaciones),
    ], estilos, columnas=1))

    registros_altas = []
    for registro in altas:
        alta = registro["bien"]
        pecosa = registro["pecosa"]
        registros_altas.append([
            ("Lote", f"#{alta.lote_id}" if alta.lote_id else None),
            ("Pecosa", pecosa.numero if pecosa else None),
            ("Expediente de alta", registro["expediente_alta"]),
            ("Expediente de firma", registro["expediente_firma"]),
            ("Firmante", registro["firmante_nombre"]),
            ("DNI", registro["firmante_dni"]),
            ("Fecha de recepción", pecosa.fecha_recepcion if pecosa else None),
            ("Fecha de firma", pecosa.fecha_firma if pecosa else None),
        ])
    historia.extend(_tabla_registros("RELACIÓN CON ALTAS", registros_altas, estilos))

    registros_impresion = []
    for item in impresiones:
        inventario = getattr(item, "inventario", None)
        registros_impresion.append([
            ("Inventario", getattr(inventario, "nombre", None)),
            ("Año", getattr(inventario, "anio", None)),
            ("Estado", item.estado_impresion),
            ("Código QR", item.codigo_qr),
            ("Red", item.red),
            ("Establecimiento", item.establecimiento),
            ("Área", item.area),
            ("Sticker generado", item.sticker_generado_en),
            ("Impreso", item.impreso_en),
        ])
    historia.extend(_tabla_registros(
        "RELACIÓN CON CONTROL IMPRESIÓN", registros_impresion, estilos
    ))

    alertas = []
    for texto in inconsistencias_qr or []:
        alertas.append(f"Inconsistencia de QR: {texto}")
    for otro in qr_repetido_maestro or []:
        alertas.append(
            f"QR repetido en Maestro Patrimonial con el bien {otro.codigo_patrimonial}."
        )
    for conflicto in conflictos or []:
        if conflicto.estado == "Pendiente":
            alerta = ETIQUETAS_CAMPOS.get(conflicto.campo, conflicto.campo)
            alertas.append(f"Conflicto pendiente en {alerta}.")
    if alertas:
        historia.extend(_tabla_campos(
            "ALERTAS PENDIENTES",
            [("Alerta", alerta) for alerta in alertas],
            estilos,
            columnas=1,
        ))

    historia.extend(_trazabilidad(altas, impresiones, versiones, estilos))
    documento.build(
        historia,
        onFirstPage=encabezado_pie,
        onLaterPages=encabezado_pie,
    )
    if destino is None:
        return salida.getvalue()
    return destino
