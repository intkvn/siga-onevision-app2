"""Lectura del reporte patrimonial SIGA usado para verificar pecosas."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd


COLUMNAS_NECESARIAS = ["codigo_patrimonial", "nro_pecosa", "fecha_alta"]


def texto_identificador(valor) -> str:
    """Convierte identificadores de Excel a texto sin el sufijo '.0'."""
    if valor is None or pd.isna(valor):
        return ""
    texto = str(valor).strip()
    if texto.endswith(".0") and texto[:-2].isdigit():
        return texto[:-2]
    return texto


def extraer_anio_fecha_alta(valor) -> str:
    """Obtiene el año de fecha_alta sin depender del formato mostrado por Excel."""
    texto = texto_identificador(valor)
    coincidencia = re.search(r"(?:19|20)\d{2}", texto)
    return coincidencia.group() if coincidencia else ""


def leer_reporte_verificacion(ruta_archivo: str) -> pd.DataFrame:
    """Lee un reporte SIGA PATRI con código patrimonial, pecosa y fecha de alta."""
    extension = os.path.splitext(ruta_archivo)[1].lower()
    parametros = {"dtype": str}
    if extension == ".xls":
        parametros["engine"] = "xlrd"

    try:
        df = pd.read_excel(ruta_archivo, **parametros)
    except Exception as error:
        df = _leer_xls_exportado_por_siga(ruta_archivo, extension, error)
    df.columns = [str(columna).strip().lower() for columna in df.columns]
    faltantes = [columna for columna in COLUMNAS_NECESARIAS if columna not in df.columns]
    if faltantes:
        raise ValueError(
            "El reporte debe incluir las columnas: código patrimonial, número de pecosa "
            f"y fecha de alta. Faltan: {', '.join(faltantes)}."
        )

    resultado = pd.DataFrame({
        "codigo_patrimonial": df["codigo_patrimonial"].apply(texto_identificador),
        "nro_pecosa": df["nro_pecosa"].apply(texto_identificador),
        "anio_siga": df["fecha_alta"].apply(extraer_anio_fecha_alta),
    })
    resultado = resultado[resultado["codigo_patrimonial"] != ""].copy()

    repetidos = resultado.loc[
        resultado["codigo_patrimonial"].duplicated(keep=False), "codigo_patrimonial"
    ].unique().tolist()
    if repetidos:
        muestra = ", ".join(repetidos[:5])
        raise ValueError(
            "El reporte tiene códigos patrimoniales repetidos y no permite una validación "
            f"segura. Corrige el reporte y vuelve a cargarlo. Ejemplos: {muestra}."
        )

    return resultado


def _leer_xls_exportado_por_siga(ruta_archivo: str, extension: str, error_original: Exception) -> pd.DataFrame:
    """Convierte exportaciones .xls de SIGA que no cumplen el formato esperado por xlrd."""
    if extension != ".xls" or shutil.which("soffice") is None:
        raise ValueError(
            "No se pudo leer el archivo Excel. Ábrelo en Excel y guárdalo como .xlsx antes de cargarlo."
        ) from error_original

    with tempfile.TemporaryDirectory() as directorio:
        resultado = subprocess.run(
            ["soffice", "--headless", "--convert-to", "xlsx", "--outdir", directorio, ruta_archivo],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        archivos = list(Path(directorio).glob("*.xlsx"))
        if resultado.returncode != 0 or not archivos:
            raise ValueError(
                "No se pudo convertir el archivo exportado por SIGA. Ábrelo en Excel y guárdalo como .xlsx antes de cargarlo."
            ) from error_original
        return pd.read_excel(archivos[0], dtype=str)
