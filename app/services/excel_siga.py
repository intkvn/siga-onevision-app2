"""
Lee el reporte de "Altas Institucionales" que se descarga de SIGA MP
y se queda solo con las filas de las pecosas que nos interesan.

Punto clave (confirmado con tus archivos): SIGA no tiene un campo
dedicado para el número de pecosa — lo guarda en la columna
"observaciones". Por eso el primer paso siempre es filtrar por ahí.
"""
import pandas as pd

COLUMNAS_NECESARIAS = [
    "ano_eje", "sec_ejec", "codigo_patrimonial", "descripcion",
    "fecha_movimto", "modelo", "estado_conserv", "nro_serie",
    "observaciones", "nombre_depend", "nombre_completo",
]


def leer_reporte_siga(ruta_archivo: str) -> pd.DataFrame:
    """Lee el Excel del reporte de altas tal como se descarga de SIGA."""
    df = pd.read_excel(ruta_archivo)

    # La columna "nombre.2" es la Marca (SIGA repite el nombre de columna
    # "nombre" varias veces; pandas las renombra nombre, nombre.1, nombre.2...)
    if "nombre.2" in df.columns:
        df = df.rename(columns={"nombre.2": "marca"})
    else:
        df["marca"] = None

    faltantes = [c for c in COLUMNAS_NECESARIAS if c not in df.columns]
    if faltantes:
        raise ValueError(
            f"El archivo no tiene las columnas esperadas de SIGA: {faltantes}. "
            "Verifica que sea el reporte de Altas Institucionales sin modificar."
        )

    return df


def filtrar_por_pecosas(df: pd.DataFrame, numeros_pecosa: list[str]) -> pd.DataFrame:
    """Se queda solo con las filas cuya columna 'observaciones' (= N° de pecosa)
    esté en la lista de pecosas que se están procesando en este lote."""
    numeros_set = {str(n).strip() for n in numeros_pecosa}

    # 'observaciones' puede venir como número o texto según el Excel — normalizamos a texto
    obs_como_texto = df["observaciones"].apply(
        lambda v: str(int(v)) if pd.notna(v) and float(v).is_integer() else str(v).strip()
        if pd.notna(v) else ""
    )
    return df[obs_como_texto.isin(numeros_set)].copy()
