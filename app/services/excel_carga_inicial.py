"""
Lee la hoja "Hoja1" de los reportes de impresión que ya generaste antes
(histórico). Esa hoja no tiene un encabezado fijo en la fila 1 — trae
primero el texto "EXPEDIENTE: ####; ####" en alguna fila, y más abajo
la fila real de encabezados (Código Patrimonial, Código QR, etc.).
Esta función detecta ambas cosas sin asumir posiciones fijas, porque
cada archivo puede tener columnas ocultas o en distinto orden.
"""
import re
import pandas as pd

COLUMNAS_BUSCADAS = {
    "codigo_patrimonial": ["código patrimonial", "codigo patrimonial"],
    "codigo_qr": ["código qr", "codigo qr"],
    "ruta_qr": ["ruta qr", "url"],
    "bien": ["bien", "descripcion", "descripción"],
    "establecimiento": ["establecimiento"],
    "marca": ["marca"],
    "modelo": ["modelo"],
    "nro_serie": ["nr. serie", "nro serie", "nro. serie", "numero de serie"],
    "pecosa": ["pecosa", "numero pecosa", "número pecosa"],
}


def _buscar_columna(nombres_columnas: list[str], candidatos: list[str]) -> str | None:
    for nombre in nombres_columnas:
        normalizado = str(nombre).strip().lower()
        if normalizado in candidatos:
            return nombre
    for nombre in nombres_columnas:
        normalizado = str(nombre).strip().lower()
        for candidato in candidatos:
            if candidato in normalizado:
                return nombre
    return None


def leer_reporte_impresion_historico(ruta_archivo: str) -> tuple[str, pd.DataFrame]:
    """Devuelve (texto_expediente, dataframe_con_columnas_normalizadas)."""
    crudo = pd.read_excel(ruta_archivo, sheet_name="Hoja1", header=None)

    texto_expediente = ""
    fila_encabezado = None
    for idx, fila in crudo.iterrows():
        valores = [str(v) for v in fila if pd.notna(v)]
        texto_fila = " ".join(valores)
        if not texto_expediente and "expediente" in texto_fila.lower():
            texto_expediente = texto_fila
        if any("patrimonial" in v.lower() for v in valores):
            fila_encabezado = idx
            break

    if fila_encabezado is None:
        raise ValueError(
            "No encontré la fila de encabezados (con 'Código Patrimonial') en la hoja 'Hoja1'."
        )

    encabezados = [str(v) for v in crudo.iloc[fila_encabezado]]
    datos = crudo.iloc[fila_encabezado + 1:].copy()
    datos.columns = encabezados
    datos = datos.dropna(how="all")

    columnas_encontradas = {}
    for clave, candidatos in COLUMNAS_BUSCADAS.items():
        columnas_encontradas[clave] = _buscar_columna(list(datos.columns), candidatos)

    faltantes = [k for k, v in columnas_encontradas.items() if v is None and k in ("codigo_patrimonial", "bien", "pecosa")]
    if faltantes:
        columnas_disponibles = ", ".join(str(c) for c in datos.columns)
        raise ValueError(
            f"No encontré columna(s) esencial(es) {faltantes} en 'Hoja1'. "
            f"Columnas disponibles: {columnas_disponibles}"
        )

    resultado = pd.DataFrame()
    for clave, columna_real in columnas_encontradas.items():
        resultado[clave] = datos[columna_real] if columna_real else None

    return texto_expediente, resultado


def numeros_de_expediente(texto: str) -> str:
    """Extrae todos los números del texto 'EXPEDIENTE: 47630; 40596' y
    los devuelve combinados como '47630;40596' (para usarlos como un
    único N° de expediente combinado cuando el reporte trae varios)."""
    numeros = re.findall(r"\d+", texto)
    return ";".join(numeros) if numeros else "SIN-EXPEDIENTE"
