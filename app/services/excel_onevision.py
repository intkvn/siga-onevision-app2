"""
Dos cosas:
1) Generar el archivo .xls exacto que pide el Formato de Importación
   de One Visión (15 columnas), a partir de los BienAlta ya normalizados.
2) Leer el reporte que se descarga DESPUÉS de cargar a One Visión
   (con Código QR y Ruta QR), corrigiendo el bug del código patrimonial
   (llega con el primer carácter vacío) para poder cruzarlo.
"""
import xlwt
import pandas as pd
from app.config import ESTADOS

ENCABEZADOS = [
    "AÑO", "Ejecutora", "IPRESS", "DNI", "Codigo Patrimonial", "Descripcion",
    "Fecha de Alta", "Modelo", "Marca", "Estado", "Nro. Serie",
    "Observaciones", "Color", "Observacion Analista", "Caracteristicas",
]


def generar_formato_importacion(bienes: list, anio: str, ejecutora: str, ruta_salida: str):
    """
    'bienes' es una lista de objetos BienAlta ya con persona y centro_costo
    asignados (el cruce ya resuelto, sin pendientes).
    Escribe el archivo .xls en 'ruta_salida'.
    """
    libro = xlwt.Workbook(encoding="utf-8")
    hoja = libro.add_sheet("Worksheet")

    for col, titulo in enumerate(ENCABEZADOS):
        hoja.write(0, col, titulo)

    fila = 1
    for bien in bienes:
        numero_pecosa = bien.pecosa.numero if bien.pecosa else ""
        hoja.write(fila, 0, anio)
        hoja.write(fila, 1, ejecutora)
        hoja.write(fila, 2, bien.centro_costo.ipress if bien.centro_costo else "")
        hoja.write(fila, 3, bien.persona.dni if bien.persona else "")
        hoja.write(fila, 4, bien.codigo_patrimonial)
        hoja.write(fila, 5, bien.descripcion)
        hoja.write(fila, 6, bien.fecha_alta.strftime("%Y-%m-%d") if bien.fecha_alta else "")
        hoja.write(fila, 7, bien.modelo or "")
        hoja.write(fila, 8, bien.marca or "")
        hoja.write(fila, 9, bien.estado_conservacion or "")
        hoja.write(fila, 10, bien.nro_serie or "")
        hoja.write(fila, 11, numero_pecosa)
        hoja.write(fila, 12, "")  # Color - no se usa actualmente
        hoja.write(fila, 13, "")  # Observacion Analista - no se usa actualmente
        hoja.write(fila, 14, "")  # Caracteristicas - no se usa actualmente
        fila += 1

    libro.save(ruta_salida)
    return ruta_salida


def corregir_codigo_patrimonial(valor) -> str:
    """El reporte de One Visión trae el código patrimonial con un
    carácter vacío al inicio. Nos quedamos con los últimos 12 dígitos,
    que son el código real."""
    texto = str(valor).strip()
    solo_digitos = "".join(ch for ch in texto if ch.isdigit())
    return solo_digitos[-12:] if len(solo_digitos) >= 12 else solo_digitos


def leer_reporte_qr_onevision(ruta_archivo: str) -> pd.DataFrame:
    """Lee el reporte total de One Visión (con Código QR y Ruta QR) y
    agrega una columna con el código patrimonial ya corregido, lista
    para cruzar contra bienes_alta.codigo_patrimonial."""
    df = pd.read_excel(ruta_archivo)
    columna_codigo = None
    for candidata in ["Código Patrimonial", "Codigo Patrimonial", "codigo_patrimonial"]:
        if candidata in df.columns:
            columna_codigo = candidata
            break
    if columna_codigo is None:
        raise ValueError("No se encontró la columna de Código Patrimonial en el reporte de One Visión.")

    df["codigo_patrimonial_corregido"] = df[columna_codigo].apply(corregir_codigo_patrimonial)
    return df
