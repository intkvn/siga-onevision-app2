import io
import math
import re
from urllib.parse import urlsplit

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ENCABEZADO_ETIQUETA = (
    "GOBIERNO REGIONAL DE CAJAMARCA",
    "DIRECCION REGIONAL DE SALUD CAJAMARCA",
    "OFICINA DE CONTROL PATRIMONIAL",
)

NOMBRE_PERFIL_PREDETERMINADO = "Argox iX4-250 203 dpi"
PUNTOS_POR_MM = mm
PUNTOS_POR_PULGADA = 72
PUNTOS_IMPRESORA_POR_MM = 8
BORDE_QR_MODULOS = 4
MAXIMO_QR_MM = 27.0
MINIMO_PUNTOS_POR_MODULO = 3
MARGEN_SUPERIOR_QR_MM = 6.2
SEPARACION_CODIGO_QR_MM = 0.8
INICIO_BLOQUES_DESDE_QR_MM = 2.2
MARGEN_INFERIOR_BLOQUES_MM = 4.6
SEPARACION_BLOQUES_MM = 0.8


def texto_identificador(valor) -> str:
    if valor is None:
        return ""
    return str(valor).strip()


def texto_etiqueta(valor) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def razon_exclusion_bien(bien) -> str | None:
    ruta = "" if bien.ruta_qr is None else str(bien.ruta_qr)
    if not ruta:
        return "Sin Ruta QR"
    if ruta != ruta.strip():
        return "Ruta QR con espacios al inicio o al final"
    if any(ord(caracter) < 32 for caracter in ruta):
        return "Ruta QR con caracteres de control"

    partes = urlsplit(ruta)
    if partes.scheme.lower() not in ("http", "https") or not partes.netloc:
        return "Ruta QR no válida (se requiere http o https)"
    if not texto_identificador(bien.codigo_qr):
        return "Sin código QR"

    configuracion_qr = _configuracion_qr(ruta)
    if configuracion_qr is None:
        return "Ruta QR demasiado extensa para imprimirse con legibilidad"

    patrimonio = texto_identificador(bien.codigo_patrimonial)
    codigo_visible = (
        f"{texto_identificador(bien.codigo_qr)}-{patrimonio}"
        if patrimonio else texto_identificador(bien.codigo_qr)
    )
    ancho_codigo = stringWidth(codigo_visible, "Helvetica-Bold", 7.0)
    ancho_disponible = 35.1 * mm
    if ancho_codigo and ancho_disponible / ancho_codigo < 0.55:
        return "Código visible demasiado extenso para la etiqueta"

    establecimiento = texto_etiqueta(
        bien.centro_costo.nombre_depend if bien.centro_costo else ""
    )
    qr_y = (50.8 - MARGEN_SUPERIOR_QR_MM - MAXIMO_QR_MM) * mm
    alto_bloques = (
        qr_y
        - (INICIO_BLOQUES_DESDE_QR_MM * mm)
        - (MARGEN_INFERIOR_BLOQUES_MM * mm)
    )
    if _ajustar_bloques_inferiores(
        texto_etiqueta(bien.descripcion),
        establecimiento,
        35.1 * mm,
        alto_bloques,
    ) is None:
        return "Descripción y establecimiento demasiado extensos para la etiqueta"
    return None


def clasificar_bienes_impresion(bienes) -> tuple[list, list[dict]]:
    imprimibles = []
    excluidos = []
    for bien in bienes:
        razon = razon_exclusion_bien(bien)
        if razon:
            excluidos.append({"bien": bien, "razon": razon})
        else:
            imprimibles.append(bien)
    return imprimibles, excluidos


def generar_pdf_etiquetas(bienes, perfil, destino=None):
    bienes = list(bienes)
    if not bienes:
        raise ValueError("No hay bienes válidos para generar el PDF.")

    for bien in bienes:
        razon = razon_exclusion_bien(bien)
        if razon:
            raise ValueError(
                f"El bien {texto_identificador(bien.codigo_patrimonial) or texto_identificador(bien.codigo_qr)} "
                f"no se puede imprimir: {razon}."
            )

    buffer_propio = destino is None
    salida = io.BytesIO() if buffer_propio else destino
    # El controlador Argox en orientacion Horizontal expone al PDF el material
    # girado: el avance de 38.1 mm es el ancho logico y los 105.1 mm del rollo
    # son el alto logico. Por eso las dos etiquetas deben apilarse en el eje Y.
    # Si se dibujan lado a lado en una pagina de 105.1 x 38.1 mm, el controlador
    # recorta la segunda posicion y solo imprime los bienes impares.
    ancho_pagina = (
        perfil.alto_etiqueta_mm + perfil.avance_adicional_mm
    ) * mm
    alto_pagina = perfil.ancho_pagina_mm * mm
    pdf = canvas.Canvas(
        salida,
        # ReportLab intercambia MediaBox al declarar /Rotate 90. Se entrega
        # primero la medida fisica horizontal para que el PDF resultante
        # conserve internamente 38.1 x 105.1 mm y se muestre en horizontal.
        pagesize=(alto_pagina, ancho_pagina),
        pageCompression=1,
        invariant=1,
    )
    # BarTender trabaja con una pagina logica vertical de 38.1 x 105.1 mm y
    # la entrega girada al controlador. Declarar el giro en el propio PDF hace
    # que Chrome vea una pagina fisica horizontal completa, sin recortar una
    # de las dos posiciones del rollo.
    pdf.setPageRotation(90)
    pdf.setTitle("Etiquetas patrimoniales")
    pdf.setAuthor("SIGA a One Vision")

    posiciones_y = (
        perfil.ancho_pagina_mm
        - perfil.margen_izquierdo_mm
        - (2 * perfil.ancho_etiqueta_mm)
        - perfil.separacion_central_mm,
        perfil.ancho_pagina_mm
        - perfil.margen_izquierdo_mm
        - perfil.ancho_etiqueta_mm,
    )

    for indice in range(0, len(bienes), 2):
        pareja = bienes[indice:indice + 2]
        for posicion, bien in enumerate(pareja):
            _dibujar_etiqueta_logica(
                pdf,
                bien,
                perfil,
                posiciones_y[posicion],
            )
        pdf.showPage()

    pdf.save()
    if buffer_propio:
        return salida.getvalue()
    return destino


def numero_paginas_para_bienes(cantidad: int) -> int:
    return math.ceil(cantidad / 2)


def _dibujar_etiqueta_logica(pdf, bien, perfil, posicion_y_mm: float):
    ancho_logico = perfil.alto_etiqueta_mm * mm
    alto_logico = perfil.ancho_etiqueta_mm * mm
    # Tras el giro del controlador, el eje Y logico corresponde al ajuste
    # horizontal del material y el eje X al ajuste vertical.
    posicion_x = perfil.desplazamiento_y_mm * mm
    posicion_y = (posicion_y_mm + perfil.desplazamiento_x_mm) * mm

    pdf.saveState()
    if perfil.rotacion_contenido == 0:
        pdf.translate(posicion_x, posicion_y)
    elif perfil.rotacion_contenido == 180:
        pdf.translate(posicion_x + ancho_logico, posicion_y + alto_logico)
        pdf.rotate(180)
    else:
        pdf.restoreState()
        raise ValueError("La rotación del perfil debe ser 0 o 180 grados.")

    _dibujar_contenido_vertical(
        pdf,
        bien,
        ancho=ancho_logico,
        alto=alto_logico,
        perfil=perfil,
    )
    pdf.restoreState()


def _dibujar_contenido_vertical(pdf, bien, ancho, alto, perfil):
    margen_x = 1.5 * mm
    ancho_util = ancho - (2 * margen_x)

    encabezado_superior = alto - 1.5 * mm
    tamano_encabezado = 5.2
    interlineado_encabezado = 5.4
    for indice, linea in enumerate(ENCABEZADO_ETIQUETA):
        _dibujar_centrado_escalado(
            pdf,
            linea,
            "Helvetica-Bold",
            tamano_encabezado,
            margen_x,
            encabezado_superior - tamano_encabezado - (indice * interlineado_encabezado),
            ancho_util,
            escala_minima=0.72,
        )

    ruta = str(bien.ruta_qr)
    configuracion_qr = _configuracion_qr(ruta)
    if configuracion_qr is None:
        raise ValueError("La Ruta QR no cabe con el tamaño mínimo de módulo.")
    tamano_qr, _ = configuracion_qr
    qr_superior = alto - MARGEN_SUPERIOR_QR_MM * mm
    qr_x = (ancho - tamano_qr) / 2
    qr_y = qr_superior - tamano_qr
    _dibujar_qr(pdf, ruta, qr_x, qr_y, tamano_qr)

    patrimonio = texto_identificador(bien.codigo_patrimonial)
    codigo_visible = (
        f"{texto_identificador(bien.codigo_qr)}-{patrimonio}"
        if patrimonio else texto_identificador(bien.codigo_qr)
    )
    _dibujar_centrado_escalado(
        pdf,
        codigo_visible,
        "Helvetica-Bold",
        7.0,
        margen_x,
        qr_y - SEPARACION_CODIGO_QR_MM * mm,
        ancho_util,
        escala_minima=0.55,
    )

    descripcion = texto_etiqueta(bien.descripcion)
    establecimiento = texto_etiqueta(
        bien.centro_costo.nombre_depend if bien.centro_costo else ""
    )
    _dibujar_bloques_inferiores(
        pdf,
        descripcion,
        establecimiento,
        x=margen_x,
        y_superior=qr_y - INICIO_BLOQUES_DESDE_QR_MM * mm,
        ancho=ancho_util,
        y_inferior=MARGEN_INFERIOR_BLOQUES_MM * mm,
    )

    _dibujar_pie_inventario(pdf, ancho, perfil)


def _dibujar_qr(pdf, valor: str, x: float, y: float, tamano: float):
    widget = QrCodeWidget(
        valor,
        barLevel="M",
        barBorder=BORDE_QR_MODULOS,
        barWidth=tamano,
        barHeight=tamano,
    )
    dibujo = Drawing(tamano, tamano)
    dibujo.add(widget)
    renderPDF.draw(dibujo, pdf, x, y)


def _configuracion_qr(valor: str):
    try:
        widget = QrCodeWidget(
            valor,
            barLevel="M",
            barBorder=BORDE_QR_MODULOS,
        )
        modulos_totales = widget.qr.moduleCount + (2 * BORDE_QR_MODULOS)
    except (TypeError, ValueError, OverflowError):
        return None

    puntos_disponibles = int(MAXIMO_QR_MM * PUNTOS_IMPRESORA_POR_MM)
    puntos_por_modulo = puntos_disponibles // modulos_totales
    if puntos_por_modulo < MINIMO_PUNTOS_POR_MODULO:
        return None
    tamano_mm = (
        modulos_totales * puntos_por_modulo / PUNTOS_IMPRESORA_POR_MM
    )
    return tamano_mm * mm, puntos_por_modulo


def _dibujar_centrado_escalado(
    pdf, texto, fuente, tamano, x, y, ancho, escala_minima,
):
    ancho_natural = stringWidth(texto, fuente, tamano)
    escala = min(1.0, ancho / ancho_natural) if ancho_natural else 1.0
    if escala < escala_minima:
        raise ValueError(f"El texto no cabe completo en la etiqueta: {texto}")
    ancho_final = ancho_natural * escala
    objeto = pdf.beginText()
    objeto.setTextOrigin(x + ((ancho - ancho_final) / 2), y)
    objeto.setFont(fuente, tamano)
    objeto.setHorizScale(escala * 100)
    objeto.textLine(texto)
    pdf.drawText(objeto)


def _dibujar_bloque_centrado(
    pdf, texto, fuente, tamano_maximo, tamano_minimo,
    x, y_superior, ancho, alto, maximo_lineas,
):
    if not texto:
        return
    ajuste = _ajustar_lineas(
        texto, fuente, tamano_maximo, tamano_minimo,
        ancho, alto, maximo_lineas,
    )
    if ajuste is None:
        raise ValueError(f"El texto no cabe completo en la etiqueta: {texto}")
    lineas, tamano, interlineado = ajuste
    y = y_superior - tamano
    for linea in lineas:
        pdf.setFont(fuente, tamano)
        pdf.drawCentredString(x + (ancho / 2), y, linea)
        y -= interlineado


def _dibujar_bloques_inferiores(
    pdf, descripcion, establecimiento, x, y_superior, ancho, y_inferior,
):
    ajuste = _ajustar_bloques_inferiores(
        descripcion,
        establecimiento,
        ancho,
        y_superior - y_inferior,
    )
    if ajuste is None:
        raise ValueError(
            "La descripción y el establecimiento no caben completos en la etiqueta."
        )

    descripcion_ajustada, establecimiento_ajustado, separacion = ajuste
    y = y_superior
    bloques = (descripcion_ajustada, establecimiento_ajustado)
    for indice, (lineas, tamano, interlineado) in enumerate(bloques):
        if not lineas:
            continue
        y -= tamano
        pdf.setFont("Helvetica-Bold", tamano)
        for linea in lineas:
            pdf.drawCentredString(x + (ancho / 2), y, linea)
            y -= interlineado
        if indice == 0 and establecimiento_ajustado[0]:
            y -= separacion


def _ajustar_bloques_inferiores(descripcion, establecimiento, ancho, alto):
    candidatos = []
    tamanos_descripcion = _secuencia_tamanos(6.0, 4.2)
    tamanos_establecimiento = _secuencia_tamanos(5.4, 4.0)
    for tamano_descripcion in tamanos_descripcion:
        lineas_descripcion = (
            _envolver_texto(
                descripcion, "Helvetica-Bold", tamano_descripcion, ancho,
            )
            if descripcion else []
        )
        if len(lineas_descripcion) > 3:
            continue
        interlineado_descripcion = tamano_descripcion * 1.08

        for tamano_establecimiento in tamanos_establecimiento:
            lineas_establecimiento = (
                _envolver_texto(
                    establecimiento,
                    "Helvetica-Bold",
                    tamano_establecimiento,
                    ancho,
                )
                if establecimiento else []
            )
            if len(lineas_establecimiento) > 4:
                continue
            interlineado_establecimiento = tamano_establecimiento * 1.08
            separacion = (
                SEPARACION_BLOQUES_MM * mm
                if lineas_descripcion and lineas_establecimiento else 0
            )
            alto_total = (
                len(lineas_descripcion) * interlineado_descripcion
                + separacion
                + len(lineas_establecimiento) * interlineado_establecimiento
            )
            if alto_total <= alto:
                candidatos.append((
                    min(tamano_descripcion, tamano_establecimiento),
                    tamano_descripcion + tamano_establecimiento,
                    (
                        lineas_descripcion,
                        tamano_descripcion,
                        interlineado_descripcion,
                    ),
                    (
                        lineas_establecimiento,
                        tamano_establecimiento,
                        interlineado_establecimiento,
                    ),
                    separacion,
                ))

    if not candidatos:
        return None
    mejor = max(candidatos, key=lambda candidato: (candidato[0], candidato[1]))
    return mejor[2], mejor[3], mejor[4]


def _secuencia_tamanos(maximo, minimo):
    tamanos = []
    actual = maximo
    while actual >= minimo - 0.001:
        tamanos.append(actual)
        actual = round(actual - 0.2, 2)
    return tamanos


def _ajustar_lineas(
    texto, fuente, tamano_maximo, tamano_minimo,
    ancho, alto, maximo_lineas,
):
    tamano = tamano_maximo
    while tamano >= tamano_minimo - 0.001:
        lineas = _envolver_texto(texto, fuente, tamano, ancho)
        interlineado = tamano * 1.08
        if (
            len(lineas) <= maximo_lineas
            and len(lineas) * interlineado <= alto
        ):
            return lineas, tamano, interlineado
        tamano = round(tamano - 0.2, 2)
    return None


def _envolver_texto(texto, fuente, tamano, ancho):
    palabras = texto.split()
    lineas = []
    actual = ""
    for palabra in palabras:
        partes = _dividir_palabra(palabra, fuente, tamano, ancho)
        for parte in partes:
            candidata = f"{actual} {parte}".strip()
            if actual and stringWidth(candidata, fuente, tamano) > ancho:
                lineas.append(actual)
                actual = parte
            else:
                actual = candidata
    if actual:
        lineas.append(actual)
    return lineas


def _dividir_palabra(palabra, fuente, tamano, ancho):
    if stringWidth(palabra, fuente, tamano) <= ancho:
        return [palabra]
    partes = []
    actual = ""
    for caracter in palabra:
        candidata = actual + caracter
        if actual and stringWidth(candidata, fuente, tamano) > ancho:
            partes.append(actual)
            actual = caracter
        else:
            actual = candidata
    if actual:
        partes.append(actual)
    return partes


def _dibujar_pie_inventario(pdf, ancho, perfil):
    fuente = "Helvetica-Bold"
    tamano = 4.6
    y = 1.6 * mm
    margen = 1.5 * mm
    pdf.setFont(fuente, tamano)
    pdf.drawString(margen, y, "DIRESA")

    lado_casilla = 2.0 * mm
    separacion = 0.7 * mm
    texto_1 = f"INV. {perfil.anio_1}"
    texto_2 = str(perfil.anio_2)
    ancho_1 = stringWidth(texto_1, fuente, tamano)
    ancho_2 = stringWidth(texto_2, fuente, tamano)
    ancho_grupo = (
        ancho_1 + separacion + lado_casilla + separacion
        + ancho_2 + separacion + lado_casilla
    )
    x = ancho - margen - ancho_grupo
    pdf.drawString(x, y, texto_1)
    x += ancho_1 + separacion
    _dibujar_casilla(pdf, x, y - 0.5 * mm, lado_casilla, perfil.anio_marcado == perfil.anio_1)
    x += lado_casilla + separacion
    pdf.drawString(x, y, texto_2)
    x += ancho_2 + separacion
    _dibujar_casilla(pdf, x, y - 0.5 * mm, lado_casilla, perfil.anio_marcado == perfil.anio_2)


def _dibujar_casilla(pdf, x, y, lado, marcada):
    pdf.setLineWidth(0.55)
    pdf.rect(x, y, lado, lado, stroke=1, fill=0)
    if marcada:
        margen = 0.35 * mm
        pdf.line(x + margen, y + margen, x + lado - margen, y + lado - margen)
        pdf.line(x + margen, y + lado - margen, x + lado - margen, y + margen)
