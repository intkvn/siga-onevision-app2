"""
Lee el reporte "Consolidado de Lotes de Impresión QR" (formato plano:
una fila por bien, con sus propias columnas de pecosa, expediente y
lote ya resueltas por el usuario). Reemplaza al enfoque anterior que
detectaba encabezados dentro de la hoja "Hoja1" de cada reporte
individual — ya no hace falta, porque este reporte consolidado ya
trae todo explícito.
"""
import pandas as pd

COLUMNAS_BUSCADAS = {
    "codigo_patrimonial": ["código patrimonial", "codigo patrimonial"],
    "codigo_qr": ["código qr", "codigo qr"],
    "bien": ["bien", "descripcion", "descripción"],
    "establecimiento": ["establecimiento"],
    "marca": ["marca"],
    "modelo": ["modelo"],
    "nro_serie": ["nr. serie", "nro serie", "nro. serie", "numero de serie"],
    "pecosa": ["pecosa", "numero pecosa", "número pecosa", "observacion", "observación", "observaciones"],
    "expediente": ["expediente", "numero expediente", "número expediente", "nro expediente"],
    "lote": ["lote", "numero lote", "número lote", "nro lote"],
}

COLUMNAS_ESENCIALES = ["codigo_patrimonial", "bien", "pecosa", "expediente", "lote"]


def _buscar_columna(nombres_columnas: list[str], candidatos: list[str]) -> str | None:
    for nombre in nombres_columnas:
        if str(nombre).strip().lower() in candidatos:
            return nombre
    for nombre in nombres_columnas:
        normalizado = str(nombre).strip().lower()
        for candidato in candidatos:
            if candidato in normalizado:
                return nombre
    return None


def leer_consolidado(ruta_archivo: str) -> pd.DataFrame:
    """Lee el Excel consolidado y devuelve un DataFrame con columnas
    normalizadas (codigo_patrimonial, codigo_qr, bien, establecimiento,
    marca, modelo, nro_serie, pecosa, expediente, lote)."""
    df = pd.read_excel(ruta_archivo)

    columnas_encontradas = {
        clave: _buscar_columna(list(df.columns), candidatos)
        for clave, candidatos in COLUMNAS_BUSCADAS.items()
    }

    faltantes = [k for k in COLUMNAS_ESENCIALES if columnas_encontradas.get(k) is None]
    if faltantes:
        columnas_disponibles = ", ".join(str(c) for c in df.columns)
        raise ValueError(
            f"No encontré columna(s) esencial(es) {faltantes} en el archivo. "
            f"Columnas disponibles: {columnas_disponibles}"
        )

    resultado = pd.DataFrame()
    for clave, columna_real in columnas_encontradas.items():
        resultado[clave] = df[columna_real] if columna_real else None
    return resultado
