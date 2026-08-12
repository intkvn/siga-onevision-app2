"""
Lee el reporte "Relación de Pecosas" que se descarga de SIGA. Trae una
fila por cada línea de ítem de cada pecosa (una pecosa puede tener
varias líneas), con la cantidad aprobada de cada línea. Sumando
cant_aprobada por nro_pecosa se obtiene el total de bienes que esa
pecosa debería tener.
"""
import pandas as pd

COLUMNAS_NECESARIAS = [
    "ano_eje", "nombre_item", "nombre_depend", "precio_unit",
    "motivo_pedido", "nro_pecosa", "fecha_pecosa", "clasificador",
    "cant_aprobada",
]


def leer_relacion_pecosas(ruta_archivo: str) -> pd.DataFrame:
    df = pd.read_excel(ruta_archivo)
    faltantes = [c for c in COLUMNAS_NECESARIAS if c not in df.columns]
    if faltantes:
        columnas_disponibles = ", ".join(str(c) for c in df.columns)
        raise ValueError(
            f"Al archivo le faltan estas columnas: {faltantes}. "
            f"Columnas disponibles: {columnas_disponibles}"
        )
    return df
