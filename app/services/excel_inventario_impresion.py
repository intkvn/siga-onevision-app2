"""Lectura y actualización del reporte general de impresión de One Vision."""
from datetime import datetime
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.models import BienAlta, BienInventarioImpresion, InventarioImpresion


COLUMNAS = {
    "codigo_patrimonial": ("codigo patrimonial",),
    "codigo_qr": ("codigo qr",),
    "ruta_qr": ("ruta qr", "ruta", "url"),
    "descripcion": ("bien", "descripcion"),
    "establecimiento": ("establecimiento",),
    "red": ("red",),
    "area": ("area",),
    "marca": ("marca",),
    "modelo": ("modelo",),
    "color": ("color",),
    "nro_serie": ("nr serie", "nro serie", "numero serie"),
}
REQUERIDAS = (
    "codigo_patrimonial", "codigo_qr", "ruta_qr", "descripcion",
    "establecimiento", "red", "area",
)
TAMANO_LOTE_BD = 1000


def _normalizar_encabezado(valor) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9]+", " ", texto.casefold())
    return " ".join(texto.split())


def _texto_excel(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return " ".join(str(valor).strip().split())


def normalizar_codigo_patrimonial(valor) -> str:
    return _texto_excel(valor)


def _indices_columnas(encabezados) -> dict[str, int]:
    normalizados = [_normalizar_encabezado(valor) for valor in encabezados]
    indices = {}
    for clave, candidatos in COLUMNAS.items():
        for indice, encabezado in enumerate(normalizados):
            if encabezado in candidatos:
                indices[clave] = indice
                break
    faltantes = [clave for clave in REQUERIDAS if clave not in indices]
    if faltantes:
        raise ValueError(
            "El reporte no contiene las columnas requeridas: "
            + ", ".join(faltantes)
        )
    return indices


def _motivo_bloqueo(codigo_qr: str, ruta_qr: str) -> str | None:
    if not codigo_qr:
        return "Sin Código QR"
    if not ruta_qr:
        return "Sin Ruta QR"
    partes = urlsplit(ruta_qr)
    if partes.scheme.lower() not in ("http", "https") or not partes.netloc:
        return "Ruta QR no válida"
    return None


def iterar_reporte_inventario(ruta_archivo: str):
    """Itera el Excel en modo lectura para no cargar el libro completo."""
    libro = load_workbook(ruta_archivo, read_only=True, data_only=True)
    try:
        hoja = libro.active
        filas = hoja.iter_rows(values_only=True)
        encabezados = next(filas, None)
        if encabezados is None:
            raise ValueError("El reporte está vacío.")
        indices = _indices_columnas(encabezados)

        for numero_fila, fila in enumerate(filas, start=2):
            def valor(clave):
                indice = indices.get(clave)
                return _texto_excel(fila[indice]) if indice is not None else ""

            codigo = normalizar_codigo_patrimonial(valor("codigo_patrimonial"))
            if not codigo:
                yield numero_fila, None
                continue
            codigo_qr = valor("codigo_qr")
            ruta_qr = valor("ruta_qr")
            motivo = _motivo_bloqueo(codigo_qr, ruta_qr)
            yield numero_fila, {
                "codigo_patrimonial": codigo,
                "codigo_qr": codigo_qr or None,
                "ruta_qr": ruta_qr or None,
                "descripcion": valor("descripcion"),
                "establecimiento": valor("establecimiento") or None,
                "red": valor("red") or None,
                "area": valor("area") or None,
                "marca": valor("marca") or None,
                "modelo": valor("modelo") or None,
                "color": valor("color") or None,
                "nro_serie": valor("nro_serie") or None,
                "imprimible": 0 if motivo else 1,
                "motivo_bloqueo": motivo,
            }
    finally:
        libro.close()


def importar_reporte_inventario(
    db: Session,
    ruta_archivo: str,
    nombre_archivo: str,
    anio: str = "2026",
    unidad_ejecutora: str = "DIRESA",
) -> dict:
    """Actualiza el inventario anual sin borrar lotes ni impresiones previas."""
    registros = []
    codigos_vistos = set()
    duplicados = 0
    omitidos = 0
    for _, registro in iterar_reporte_inventario(ruta_archivo):
        if registro is None:
            omitidos += 1
            continue
        codigo = registro["codigo_patrimonial"]
        if codigo in codigos_vistos:
            duplicados += 1
            continue
        codigos_vistos.add(codigo)
        registros.append(registro)

    if not registros:
        raise ValueError("El reporte no contiene bienes con código patrimonial.")

    inventario = (
        db.query(InventarioImpresion)
        .filter(
            InventarioImpresion.anio == str(anio),
            InventarioImpresion.unidad_ejecutora == unidad_ejecutora,
        )
        .first()
    )
    if inventario is None:
        inventario = InventarioImpresion(
            nombre=f"Inventario UE {unidad_ejecutora} {anio}",
            anio=str(anio),
            unidad_ejecutora=unidad_ejecutora,
        )
        db.add(inventario)
        db.flush()

    existentes = dict(
        db.query(
            BienInventarioImpresion.codigo_patrimonial,
            BienInventarioImpresion.id,
        )
        .filter(BienInventarioImpresion.inventario_id == inventario.id)
        .all()
    )
    estados_existentes = {
        codigo: (estado, generado_en)
        for codigo, estado, generado_en in db.query(
            BienInventarioImpresion.codigo_patrimonial,
            BienInventarioImpresion.estado_impresion,
            BienInventarioImpresion.sticker_generado_en,
        )
        .filter(BienInventarioImpresion.inventario_id == inventario.id)
        .all()
    }

    altas_por_codigo: dict[str, list[int]] = {}
    for alta_id, codigo in db.query(BienAlta.id, BienAlta.codigo_patrimonial).all():
        normalizado = normalizar_codigo_patrimonial(codigo)
        if normalizado:
            altas_por_codigo.setdefault(normalizado, []).append(alta_id)

    ahora = datetime.utcnow()
    db.query(BienInventarioImpresion).filter(
        BienInventarioImpresion.inventario_id == inventario.id
    ).update({BienInventarioImpresion.activo: 0}, synchronize_session=False)

    nuevos = []
    actualizaciones = []
    vinculados = 0
    ambiguos = 0
    for registro in registros:
        coincidencias = altas_por_codigo.get(registro["codigo_patrimonial"], [])
        if len(coincidencias) == 1:
            registro["bien_alta_id"] = coincidencias[0]
            registro["relacion_alta"] = "Vinculado"
            vinculados += 1
        elif len(coincidencias) > 1:
            registro["bien_alta_id"] = None
            registro["relacion_alta"] = "Ambiguo"
            ambiguos += 1
        else:
            registro["bien_alta_id"] = None
            registro["relacion_alta"] = "Sin alta"

        registro.update({
            "inventario_id": inventario.id,
            "activo": 1,
            "actualizado_en": ahora,
        })
        id_existente = existentes.get(registro["codigo_patrimonial"])
        if id_existente:
            estado_anterior, generado_en = estados_existentes.get(
                registro["codigo_patrimonial"], ("Pendiente", None)
            )
            if estado_anterior != "Impreso":
                if not registro["imprimible"]:
                    registro["estado_impresion"] = "Bloqueado"
                elif estado_anterior == "Bloqueado":
                    registro["estado_impresion"] = (
                        "Sticker generado" if generado_en else "Pendiente"
                    )
            actualizaciones.append({"id": id_existente, **registro})
        else:
            nuevos.append({
                "importado_en": ahora,
                "estado_impresion": (
                    "Pendiente" if registro["imprimible"] else "Bloqueado"
                ),
                **registro,
            })

    for inicio in range(0, len(actualizaciones), TAMANO_LOTE_BD):
        db.bulk_update_mappings(
            BienInventarioImpresion,
            actualizaciones[inicio:inicio + TAMANO_LOTE_BD],
        )
    for inicio in range(0, len(nuevos), TAMANO_LOTE_BD):
        db.bulk_insert_mappings(
            BienInventarioImpresion,
            nuevos[inicio:inicio + TAMANO_LOTE_BD],
        )

    inventario.archivo_ultimo = Path(nombre_archivo).name
    inventario.total_registros = len(registros)
    inventario.actualizado_en = ahora
    db.commit()
    return {
        "inventario_id": inventario.id,
        "total": len(registros),
        "nuevos": len(nuevos),
        "actualizados": len(actualizaciones),
        "duplicados": duplicados,
        "omitidos": omitidos,
        "vinculados": vinculados,
        "ambiguos": ambiguos,
        "inactivos": max(0, len(existentes) - len(actualizaciones)),
    }
